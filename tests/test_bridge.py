from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys

import pytest

from interception import Bridge, InferencePending
from interception.bridge import IdempotencyConflict
from interception.contracts import ContractError
from interception.files import loads, write_json

REQUEST = {"model": "manual", "messages": [{"role": "user", "content": "Hello"}]}


def envelope(request_id, content="hello"):
    return {
        "request_id": request_id,
        "status": "COMPLETED",
        "response": {"role": "assistant", "content": content},
    }


def test_restart_and_missing_catch_recovery(tmp_path):
    bridge = Bridge(tmp_path)
    rid = bridge.submit(REQUEST, key="run:step", checkpoint={"node": "step"})
    (bridge.catch / f"req_{rid}.json").unlink()
    restarted = Bridge(tmp_path)
    assert loads((restarted.catch / f"req_{rid}.json").read_text())["checkpoint"] == {
        "node": "step"
    }
    assert restarted.submit(REQUEST, key="run:step", checkpoint={"node": "step"}) == rid
    write_json(restarted.returns / f"req_{rid}.json", envelope(rid))
    assert restarted.wait(rid) == {"role": "assistant", "content": "hello"}
    assert Bridge(tmp_path).result(rid)["content"] == "hello"
    assert not (restarted.catch / f"req_{rid}.json").exists()


def test_partial_invalid_then_corrected_return(tmp_path):
    bridge = Bridge(tmp_path)
    rid = bridge.submit(REQUEST)
    path = bridge.returns / f"req_{rid}.json"
    path.write_text('{"request_id":')
    assert bridge.ingest()[0]["outcome"] == "REJECTED"
    assert bridge.result(rid) is None
    assert bridge.ingest() == []
    write_json(path, envelope("wrong"))
    assert bridge.ingest()[0]["outcome"] == "REJECTED"
    write_json(path, envelope(rid))
    assert bridge.ingest()[0]["outcome"] == "ACCEPTED"
    assert bridge.result(rid)["content"] == "hello"


def test_completed_immutable_and_duplicate_idempotent(tmp_path):
    bridge = Bridge(tmp_path)
    rid = bridge.submit(REQUEST)
    bridge.accept(envelope(rid))
    bridge.accept(envelope(rid))
    with pytest.raises(ContractError, match="immutable"):
        bridge.accept(envelope(rid, "different"))
    assert bridge.result(rid)["content"] == "hello"


def test_concurrent_stable_key_and_distinct_unkeyed_requests(tmp_path):
    bridge = Bridge(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(lambda _: bridge.submit(REQUEST, key="same-step"), range(16)))
    assert len(set(ids)) == 1
    assert bridge.submit(REQUEST) != bridge.submit(REQUEST)
    with pytest.raises(IdempotencyConflict):
        bridge.submit(dict(REQUEST, model="different"), key="same-step")


def test_cooperative_suspend_resume(tmp_path):
    bridge = Bridge(tmp_path)
    with pytest.raises(InferencePending) as caught:
        bridge.require(REQUEST, key="run:node", checkpoint={"node": "node", "input": [1, 2]})
    rid = caught.value.request_id
    Bridge(tmp_path).write_return(rid, {"role": "assistant", "content": "resumed"})
    assert (
        Bridge(tmp_path).require(
            REQUEST, key="run:node", checkpoint={"node": "node", "input": [1, 2]}
        )["content"]
        == "resumed"
    )


def test_process_exit_and_reentry(tmp_path):
    example = Path(__file__).resolve().parents[1] / "examples" / "durable_workflow.py"
    first = subprocess.run(
        [sys.executable, str(example), str(tmp_path)], capture_output=True, text=True
    )
    assert first.returncode == 0, first.stderr
    assert "Safely suspended" in first.stdout
    bridge = Bridge(tmp_path)
    rid = bridge.requests()[0]["id"]
    write_json(bridge.returns / f"req_{rid}.json", envelope(rid, "1. Plan\n2. Plant\n3. Water"))
    second = subprocess.run(
        [sys.executable, str(example), str(tmp_path)], capture_output=True, text=True
    )
    assert second.returncode == 0, second.stderr
    assert "Resumed successfully" in second.stdout
    assert (tmp_path / "garden-plan.txt").read_text() == "1. Plan\n2. Plant\n3. Water"
    assert len(bridge.requests()) == 1


def test_process_killed_after_ledger_commit_before_publication(tmp_path):
    script = """
import os, sys
from interception import Bridge
b = Bridge(sys.argv[1])
b.reconcile = lambda: os._exit(17)
b.submit({"model":"manual", "messages":[{"role":"user","content":"persist"}]}, key="crash")
"""
    exited = subprocess.run([sys.executable, "-c", script, str(tmp_path)])
    assert exited.returncode == 17
    restarted = Bridge(tmp_path)
    rid = restarted.requests()[0]["id"]
    assert (restarted.catch / f"req_{rid}.json").is_file()
    assert restarted.get(rid)["state"] == "WAITING_FOR_INFERENCE"


def test_schema_and_tool_validation(tmp_path):
    bridge = Bridge(tmp_path)
    schema = {
        "type": "object",
        "required": ["count"],
        "properties": {"count": {"type": "integer", "minimum": 1}},
        "additionalProperties": False,
    }
    rid = bridge.submit(
        dict(
            REQUEST,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "count", "schema": schema},
            },
        )
    )
    write_json(bridge.returns / f"req_{rid}.json", envelope(rid, '{"count":0}'))
    assert bridge.ingest()[0]["outcome"] == "REJECTED"
    assert bridge.result(rid) is None
    write_json(bridge.returns / f"req_{rid}.json", envelope(rid, '{"count":2}'))
    assert bridge.ingest()[0]["outcome"] == "ACCEPTED"
    tool_id = bridge.submit(
        dict(
            REQUEST,
            tools=[{"type": "function", "function": {"name": "count", "parameters": schema}}],
            tool_choice="required",
        )
    )
    with pytest.raises(ContractError, match="requires a tool"):
        bridge.accept(envelope(tool_id))
    tool = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "count", "arguments": '{"count":3}'},
            }
        ],
    }
    bridge.write_return(tool_id, tool)
    assert bridge.result(tool_id) == tool


@pytest.mark.parametrize(
    "field,value",
    [
        ("n", 2),
        ("stream", "yes"),
        (
            "messages",
            [
                {
                    "role": "user",
                    "content": [{"type": "image_url", "image_url": {"url": "https://example.org"}}],
                }
            ],
        ),
        ("tools", [{"type": "web_search"}]),
        ("response_format", {"type": "xml"}),
        (
            "response_format",
            {
                "type": "json_schema",
                "json_schema": {"schema": {"$ref": "https://example.org/schema"}},
            },
        ),
    ],
)
def test_unsupported_requests_not_queued(tmp_path, field, value):
    bridge = Bridge(tmp_path)
    with pytest.raises(ValueError):
        bridge.submit(dict(REQUEST, **{field: value}))
    assert bridge.requests() == []


def test_batch_self_contained_and_original_preserved(tmp_path):
    bridge = Bridge(tmp_path)
    body = dict(
        REQUEST,
        messages=[
            {"role": "system", "content": "System instruction"},
            {"role": "developer", "content": "Developer instruction"},
            *REQUEST["messages"],
        ],
    )
    rid = bridge.submit(
        body, metadata={"context": {"relevant_files": [{"path": "a.py", "content": "x=1"}]}}
    )
    packet = bridge.get(rid)["packet"]
    assert packet["original_request"] == body
    assert packet["caller"] == {"status": "UNKNOWN"}
    batch = bridge.export_batch().read_text()
    assert "System instruction" in batch and "Developer instruction" in batch and "x=1" in batch
    assert rid in batch


def test_nonstandard_json_rejected():
    for text in ('{"x":NaN}', '{"x":1,"x":2}'):
        with pytest.raises(ValueError):
            loads(text)


def test_unknown_return_and_symlink_rejected(tmp_path):
    bridge = Bridge(tmp_path)
    with pytest.raises(ContractError, match="Unknown"):
        bridge.accept(envelope("missing"))
    rid = bridge.submit(REQUEST)
    target = tmp_path / "answer.json"
    write_json(target, envelope(rid))
    try:
        (bridge.returns / f"req_{rid}.json").symlink_to(target)
    except OSError:
        pytest.skip("Symlinks unavailable")
    assert bridge.ingest()[0]["outcome"] == "REJECTED"
    assert bridge.result(rid) is None


def test_malformed_return_does_not_block_other_requests(tmp_path):
    bridge = Bridge(tmp_path)
    tools = [{"type": "function", "function": {"name": "echo", "parameters": {"type": "object"}}}]
    first = bridge.submit(dict(REQUEST, tools=tools))
    second = bridge.submit(REQUEST)
    bad = envelope(first)
    bad["response"]["tool_calls"] = [{"type": "function", "id": "call_1", "function": None}]
    write_json(bridge.returns / f"req_{first}.json", bad)
    write_json(bridge.returns / f"req_{second}.json", envelope(second))
    assert {item["outcome"] for item in bridge.ingest()} == {"ACCEPTED", "REJECTED"}
    assert bridge.result(first) is None
    assert bridge.result(second)["content"] == "hello"


def test_import_conflict_is_reported(tmp_path):
    bridge = Bridge(tmp_path)
    rid = bridge.submit(REQUEST)
    bridge.write_return(rid, {"role": "assistant", "content": "original"})
    with pytest.raises(ContractError, match="immutable"):
        bridge.write_return(rid, {"role": "assistant", "content": "conflict"})
    assert bridge.result(rid)["content"] == "original"


def test_multiple_bridge_instances_share_key(tmp_path):
    bridges = [Bridge(tmp_path) for _ in range(4)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(lambda b: b.submit(REQUEST, key="shared"), bridges))
    assert len(set(ids)) == 1
    assert len(bridges[0].requests()) == 1


def test_repair_non_utf8_catch(tmp_path):
    bridge = Bridge(tmp_path)
    rid = bridge.submit(REQUEST)
    (bridge.catch / f"req_{rid}.json").write_bytes(b"\xff\xfe")
    repaired = Bridge(tmp_path)
    assert loads((repaired.catch / f"req_{rid}.json").read_text())["request_id"] == rid


def test_supervised_node_auto_resumes_and_survives_supervisor_kill(tmp_path):
    import time

    example = Path(__file__).resolve().parents[1] / "examples" / "restartable_node.py"
    command = [
        sys.executable,
        "-m",
        "interception",
        "run-node",
        str(tmp_path),
        "test-run",
        str(example),
    ]
    worker = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 20
        state_paths = []
        while time.monotonic() < deadline:
            state_paths = list((tmp_path / ".inference_bridge" / "nodes").glob("*.json"))
            if (
                state_paths
                and loads(state_paths[0].read_text())["state"] == "WAITING_FOR_INFERENCE"
            ):
                break
            time.sleep(0.02)
        assert state_paths
        state = loads(state_paths[0].read_text())
        assert state["state"] == "WAITING_FOR_INFERENCE"
        worker.kill()
        worker.communicate(timeout=3)
        worker = subprocess.Popen(
            [sys.executable, "-m", "interception", "resume-node", str(tmp_path), "test-run"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        bridge = Bridge(tmp_path)
        bridge.write_return(
            state["request_id"], {"role": "assistant", "content": "Resumed automatically"}
        )
        out, err = worker.communicate(timeout=8)
        assert worker.returncode == 0, err
        assert "COMPLETED" in out
        assert (tmp_path / "garden-plan.txt").read_text() == "Resumed automatically"
        assert len(bridge.requests()) == 1
        assert loads(state_paths[0].read_text())["state"] == "COMPLETED"
    finally:
        if worker.poll() is None:
            worker.kill()
            worker.communicate(timeout=3)
