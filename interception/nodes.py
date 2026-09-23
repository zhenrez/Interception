"""Supervisor for explicitly restart-safe Python nodes, not arbitrary process stacks."""

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import runpy
import sys

from .bridge import Bridge, InferencePending
from .files import loads, write_json


@contextmanager
def node_lock(path):
    """OS lock released on process death, including Windows reboot."""
    with path.open("a+b") as stream:
        stream.seek(0)
        if not stream.read(1):
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ValueError("This node is already supervised") from exc
        else:
            import fcntl

            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ValueError("This node is already supervised") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def supervise(project, run_id, script=None):
    if not isinstance(run_id, str) or not run_id or len(run_id) > 512:
        raise ValueError("Use a nonempty run ID of at most 512 characters")
    bridge = Bridge(project)
    jobs = bridge.home / "nodes"
    if jobs.is_symlink():
        raise ValueError("Node state directory must not be a symlink")
    jobs.mkdir(exist_ok=True)
    key = hashlib.sha256(run_id.encode()).hexdigest()
    state_path = jobs / f"{key}.json"
    with node_lock(jobs / f"{key}.lock"):
        if state_path.exists():
            state = loads(state_path.read_text(encoding="utf-8"))
            if state["run_id"] != run_id or state["project"] != str(bridge.root):
                raise ValueError("Stored node identity does not match")
            path = Path(state["script"])
            if script is not None and Path(script).resolve() != path:
                raise ValueError("Run ID is already registered to a different script")
        else:
            if script is None:
                raise ValueError("Unknown node run ID; register it with run-node first")
            path = Path(script).resolve()
            if path.suffix != ".py" or not path.is_file():
                raise ValueError("Node script must be an existing Python file")
            state = {
                "version": 1,
                "run_id": run_id,
                "project": str(bridge.root),
                "script": str(path),
                "script_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "state": "READY",
                "request_id": None,
            }
            write_json(state_path, state)
        if hashlib.sha256(path.read_bytes()).hexdigest() != state["script_sha256"]:
            raise ValueError(
                "Node script changed since registration; review it and use a new run ID"
            )
        while state["state"] != "COMPLETED":
            if state["state"] == "WAITING_FOR_INFERENCE":
                print(
                    f"Node {run_id} suspended on {state['request_id']}; RETURN will resume it.",
                    flush=True,
                )
                bridge.wait(state["request_id"])
            state["state"] = "RUNNING"
            write_json(state_path, state)
            old_env = {
                name: os.environ.get(name)
                for name in ("INTERCEPTION_PROJECT", "INTERCEPTION_RUN_ID")
            }
            old_argv, old_cwd, old_path = sys.argv[:], Path.cwd(), sys.path[:]
            os.environ["INTERCEPTION_PROJECT"] = str(bridge.root)
            os.environ["INTERCEPTION_RUN_ID"] = run_id
            sys.argv = [str(path)]
            sys.path.insert(0, str(path.parent))
            os.chdir(bridge.root)
            try:
                runpy.run_path(str(path), run_name="__main__")
            except InferencePending as pending:
                bridge.get(pending.request_id)  # Must belong to this project's ledger.
                state.update(state="WAITING_FOR_INFERENCE", request_id=pending.request_id)
            except BaseException:
                state["state"] = "INTERRUPTED"
                write_json(state_path, state)
                raise
            else:
                state["state"] = "COMPLETED"
            finally:
                sys.argv, sys.path = old_argv, old_path
                os.chdir(old_cwd)
                for name, value in old_env.items():
                    if value is None:
                        os.environ.pop(name, None)
                    else:
                        os.environ[name] = value
            write_json(state_path, state)
        return state
