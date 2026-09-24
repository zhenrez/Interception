"""SQLite-backed request lifecycle; mailbox files are recoverable projections."""

from contextlib import contextmanager
import hashlib
from pathlib import Path
import sqlite3
import threading
import time
import uuid

from .contracts import ContractError, check_request, validate_return
from .files import atomic_write, dumps, loads, write_json
from .packet import make_packet, markdown_packet

MAX_BYTES = 8 * 1024 * 1024


class InferencePending(Exception):
    """Cooperative suspension: the caller must exit/yield and re-enter its blocked node."""

    def __init__(self, request_id):
        self.request_id = request_id
        super().__init__(f"WAITING_FOR_INFERENCE: {request_id}")


class IdempotencyConflict(ValueError):
    pass


class Bridge:
    def __init__(self, project):
        self.root = Path(project).resolve()
        if not self.root.is_dir():
            raise ValueError("Project must be an existing directory")
        self.home = self.root / ".inference_bridge"
        self.catch = self.home / "CATCH"
        self.returns = self.home / "RETURN"
        self._lock = threading.RLock()
        for path in (self.home, self.catch, self.returns):
            if path.is_symlink():
                raise ValueError("Mailbox directories must not be symlinks")
            path.mkdir(exist_ok=True, mode=0o700)
        self.db = self.home / "state.sqlite"
        if self.db.is_symlink():
            raise ValueError("Ledger must not be a symlink")
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValueError(f"Unsupported ledger version: {version}")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS requests (
                    id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE,
                    fingerprint TEXT NOT NULL, packet TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('WAITING_FOR_INFERENCE','COMPLETED')),
                    response TEXT, created REAL NOT NULL, completed REAL
                );
                CREATE TABLE IF NOT EXISTS returns_seen (
                    name TEXT PRIMARY KEY, digest TEXT NOT NULL,
                    outcome TEXT NOT NULL, detail TEXT NOT NULL
                );
                PRAGMA user_version=1;
            """)
        self.reconcile()

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.db, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def submit(self, request, *, key=None, metadata=None, checkpoint=None):
        check_request(request)
        if key is not None and (not isinstance(key, str) or not key or len(key) > 512):
            raise ValueError("Idempotency key must be a nonempty string of at most 512 characters")
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")
        canonical = dumps({"request": request, "metadata": metadata, "checkpoint": checkpoint})
        if len(canonical.encode("utf-8")) > MAX_BYTES:
            raise ValueError("Request/context exceeds 8 MiB; supply smaller relevant context")
        fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
        with self._lock, self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = (
                db.execute("SELECT * FROM requests WHERE idempotency_key=?", (key,)).fetchone()
                if key
                else None
            )
            if prior:
                if prior["fingerprint"] != fingerprint:
                    raise IdempotencyConflict(
                        "Idempotency key already belongs to a different request/context/checkpoint"
                    )
                request_id = prior["id"]
            else:
                request_id = uuid.uuid4().hex
                packet = make_packet(self.root, request_id, request, metadata, checkpoint)
                db.execute(
                    "INSERT INTO requests VALUES (?,?,?,?,?,NULL,?,NULL)",
                    (
                        request_id,
                        key,
                        fingerprint,
                        dumps(packet),
                        "WAITING_FOR_INFERENCE",
                        time.time(),
                    ),
                )
        # Commit before publishing: a crash between these is repaired on restart.
        self.reconcile()
        return request_id

    def get(self, request_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown request: {request_id}")
        result = dict(row)
        result["packet"] = loads(result["packet"])
        result["response"] = loads(result["response"]) if result["response"] else None
        return result

    def requests(self):
        with self.connection() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT id,state,created,completed FROM requests ORDER BY created,id"
                )
            ]

    def reconcile(self):
        with self._lock, self.connection() as db:
            # Serialize projections across separate Bridge instances/processes too.
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT id,state,packet FROM requests ORDER BY created,id").fetchall()
            pending = []
            for row in rows:
                path = self.catch / f"req_{row['id']}.json"
                if row["state"] == "WAITING_FOR_INFERENCE":
                    packet = loads(row["packet"])
                    # Rewrite only missing/changed projections; DB is the authority.
                    if (
                        path.is_symlink()
                        or not path.exists()
                        or path.read_bytes() != (dumps(packet) + "\n").encode("utf-8")
                    ):
                        atomic_write(path, dumps(packet) + "\n")
                    pending.append(packet)
                else:
                    path.unlink(missing_ok=True)
            manifest = [
                "# Pending inference requests",
                "",
                f"{len(pending)} WAITING REQUESTS",
                "",
                "Fulfill each attached request independently. Dependency independence is not inferred.",
                "Write one matching RETURN JSON per request. Do not execute requested tools here.",
                "",
            ]
            for packet in pending:
                manifest.append(
                    f"- [{packet['request_id']}](req_{packet['request_id']}.json) — {self.root.name}"
                )
            atomic_write(self.catch / "INFERENCE_BATCH.md", "\n".join(manifest) + "\n")

    def export_batch(self, output=None):
        """A self-contained attachment, not just links to unavailable local files."""
        with self.connection() as db:
            packets = [
                loads(row[0])
                for row in db.execute(
                    "SELECT packet FROM requests WHERE state='WAITING_FOR_INFERENCE' ORDER BY created,id"
                )
            ]
        text = "# Interception inference batch\n\nReturn one JSON file per request ID.\n\n"
        text += "\n\n---\n\n".join(markdown_packet(packet) for packet in packets)
        path = Path(output) if output else self.catch / "INFERENCE_BATCH_FULL.md"
        atomic_write(path, text)
        return path

    def accept(self, returned):
        if not isinstance(returned, dict) or not isinstance(returned.get("request_id"), str):
            raise ContractError("RETURN requires a string request_id")
        request_id = returned["request_id"]
        with self._lock, self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
            if row is None:
                raise ContractError("Unknown RETURN request_id")
            response = validate_return(loads(row["packet"]), returned)
            encoded = dumps(response)
            if row["state"] == "COMPLETED":
                if encoded != row["response"]:
                    raise ContractError(
                        "Completed response is immutable; conflicting return rejected"
                    )
            else:
                db.execute(
                    "UPDATE requests SET state='COMPLETED',response=?,completed=? WHERE id=?",
                    (encoded, time.time(), request_id),
                )
        self.reconcile()
        return request_id

    def ingest(self):
        """Partial/invalid files never wake callers; corrected files are reconsidered."""
        outcomes = []
        for path in sorted(self.returns.glob("*.json")):
            digest = None
            try:
                if path.is_symlink() or not path.is_file():
                    raise ValueError("RETURN must be a regular, non-symlink file")
                with path.open("rb") as stream:
                    raw = stream.read(MAX_BYTES + 1)
                digest = hashlib.sha256(raw).hexdigest()
                with self.connection() as db:
                    previous = db.execute(
                        "SELECT digest FROM returns_seen WHERE name=?", (path.name,)
                    ).fetchone()
                if previous and previous[0] == digest:
                    continue
                if len(raw) > MAX_BYTES:
                    raise ValueError("RETURN exceeds 8 MiB")
                returned = loads(raw.decode("utf-8-sig"))
                if (
                    not isinstance(returned, dict)
                    or path.name != f"req_{returned.get('request_id')}.json"
                ):
                    raise ContractError("Filename must match req_<request_id>.json")
                self.accept(returned)
                outcome, detail = "ACCEPTED", "Validated and recorded"
            except (ValueError, KeyError, OSError, UnicodeError, TypeError) as exc:
                outcome, detail = "REJECTED", str(exc)
            except Exception as exc:
                # Schema validators have their own exception hierarchy. Do not log payload values.
                from jsonschema.exceptions import ValidationError, SchemaError
                from referencing.exceptions import Unresolvable

                if not isinstance(exc, (ValidationError, SchemaError, Unresolvable)):
                    raise
                outcome, detail = "REJECTED", "Response does not satisfy the JSON Schema"
            with self.connection() as db:
                db.execute(
                    "INSERT OR REPLACE INTO returns_seen VALUES (?,?,?,?)",
                    (path.name, digest or "unreadable", outcome, detail[:1000]),
                )
            outcomes.append({"file": path.name, "outcome": outcome, "detail": detail})
        return outcomes

    def diagnostics(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute("SELECT name,outcome,detail FROM returns_seen")]

    def result(self, request_id):
        return self.get(request_id)["response"]

    def wait(self, request_id, *, poll=0.25, stop=None):
        """No inference deadline. Process lifetime is still the caller's responsibility."""
        while stop is None or not stop.is_set():
            self.ingest()
            result = self.result(request_id)
            if result is not None:
                return result
            if stop is not None:
                stop.wait(poll)
            else:
                time.sleep(poll)
        raise InterruptedError("Bridge stopped; request remains durable")

    def complete(self, request, *, key=None, metadata=None):
        return self.wait(self.submit(request, key=key, metadata=metadata))

    async def acomplete(self, request, *, key=None, metadata=None):
        import asyncio

        request_id = await asyncio.to_thread(self.submit, request, key=key, metadata=metadata)
        while True:
            await asyncio.to_thread(self.ingest)
            result = await asyncio.to_thread(self.result, request_id)
            if result is not None:
                return result
            await asyncio.sleep(0.25)

    def require(self, request, *, key, checkpoint, metadata=None):
        """Persist request + checkpoint atomically, then cooperatively suspend.

        Re-enter the same node with the same key/input after restart. This does NOT
        serialize a Python stack or automatically rerun arbitrary side effects.
        """
        request_id = self.submit(request, key=key, checkpoint=checkpoint, metadata=metadata)
        self.ingest()
        result = self.result(request_id)
        if result is None:
            raise InferencePending(request_id)
        return result

    def write_return(self, request_id, response):
        returned = {"request_id": request_id, "status": "COMPLETED", "response": response}
        validate_return(self.get(request_id)["packet"], returned)
        write_json(self.returns / f"req_{request_id}.json", returned)
        # Propagate acceptance failures to the importer, including immutable conflicts.
        self.accept(returned)
        return request_id
