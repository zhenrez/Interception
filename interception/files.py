"""Atomic mailbox publication. SQLite remains authoritative."""

import json
import os
from pathlib import Path
import tempfile
import time


def sharing_retry(operation):
    """Bounded retry for transient Windows reader/replace sharing violations."""
    for attempt in range(6):
        try:
            return operation()
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.02 * (2**attempt))


def read_json(path):
    return loads(sharing_retry(lambda: Path(path).read_text(encoding="utf-8")))


def dumps(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)


def loads(text):
    def invalid(value):
        raise ValueError(f"Non-JSON numeric constant: {value}")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(text, parse_constant=invalid, object_pairs_hook=unique)


def atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        sharing_retry(lambda: os.replace(temp, path))
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def write_json(path, value):
    atomic_write(
        Path(path), json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    )
