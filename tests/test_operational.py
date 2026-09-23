from concurrent.futures import ThreadPoolExecutor
import importlib.util
from pathlib import Path
import sys
import threading
import time
import subprocess

import pytest

from interception import Bridge
from interception import adapters, files


def test_atomic_publication_survives_transient_windows_sharing_violation(tmp_path, monkeypatch):
    original = files.os.replace
    attempts = []

    def busy_once(source, target):
        attempts.append(target)
        if len(attempts) == 1:
            raise PermissionError("Windows sharing violation")
        original(source, target)

    monkeypatch.setattr(files.os, "replace", busy_once)
    files.write_json(tmp_path / "state.json", {"state": "ready"})
    assert files.loads((tmp_path / "state.json").read_text()) == {"state": "ready"}
    assert len(attempts) == 2


def test_state_reader_retries_permission_error_without_hiding_corrupt_json(tmp_path, monkeypatch):
    assert hasattr(files, "read_json"), "Node-state reads need bounded sharing-violation retry"
    path = tmp_path / "state.json"
    files.write_json(path, {"state": "ready"})
    original = Path.read_text
    attempts = []

    def busy_once(self, *args, **kwargs):
        attempts.append(self)
        if len(attempts) == 1:
            raise PermissionError("Windows sharing violation")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", busy_once)
    assert files.read_json(path) == {"state": "ready"}
    path.write_text("{invalid")
    with pytest.raises(ValueError):
        files.read_json(path)


def load_target():
    path = Path(__file__).parents[1] / "interception" / "_vendor" / "prompt_evolver_llm.py"
    assert path.is_file(), "Bundle the pinned real Prompt Evolver inference wrapper"
    spec = importlib.util.spec_from_file_location("proof_prompt_evolver_llm", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def wait_request(bridge):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        rows = bridge.requests()
        if rows:
            return rows[0]["id"]
        time.sleep(0.01)
    pytest.fail("No CATCH appeared")


def test_real_prompt_evolver_judge_holds_then_resumes_without_provider(tmp_path):
    assert hasattr(adapters, "connect_prompt_evolver"), "Missing explicit instance adapter"
    target = load_target()
    client = target.LLMClient(model="ollama/requested", timeout=1)
    bridge = Bridge(tmp_path)
    stop = threading.Event()
    adapters.connect_prompt_evolver(client, bridge, run_id="proof", stop=stop)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.judge_score, "Reply 4 for this fixture")
        try:
            rid = wait_request(bridge)
            assert not future.done()
            packet = bridge.get(rid)["packet"]
            assert packet["original_request"]["model"] == "ollama/requested"
            assert packet["original_request"]["temperature"] == 0.0
            assert packet["original_request"]["max_tokens"] == 16
            bridge.write_return(rid, {"role": "assistant", "content": "4"})
            assert future.result(timeout=3) == 4
        finally:
            stop.set()


def test_adapter_preserves_overrides_and_reports_manual_model(tmp_path):
    assert hasattr(adapters, "connect_prompt_evolver"), "Missing explicit instance adapter"
    target = load_target()
    client = target.LLMClient()
    bridge = Bridge(tmp_path)
    stop = threading.Event()
    adapters.connect_prompt_evolver(client, bridge, run_id="override", stop=stop)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            client.complete,
            "user",
            system="system",
            model="requested/other",
            temperature=0.0,
            max_tokens=42,
        )
        try:
            rid = wait_request(bridge)
            request = bridge.get(rid)["packet"]["original_request"]
            assert request == {
                "model": "requested/other",
                "temperature": 0.0,
                "max_tokens": 42,
                "messages": [
                    {"role": "system", "content": "system"},
                    {"role": "user", "content": "user"},
                ],
            }
            bridge.write_return(rid, {"role": "assistant", "content": "answer"})
            result = future.result(timeout=3)
            assert isinstance(result, target.LLMResponse)
            assert result.text == "answer" and result.usage == {}
            assert result.model == "manual/unspecified"
        finally:
            stop.set()


def test_project_brief_is_isolated_versioned_and_rejects_stale_edits(tmp_path):
    from interception import brief

    left, right = tmp_path / "left", tmp_path / "right"
    left.mkdir()
    right.mkdir()
    a, b = Bridge(left), Bridge(right)
    first = brief.save(
        a,
        goal="Finish project A",
        guidelines="Reuse existing code",
        constraints="No paid APIs",
        done_when="Behavior test passes",
        expected_revision=0,
    )
    assert first["revision"] == 1
    assert brief.load(b) is None
    second = brief.save(
        a,
        goal="Finish revised A",
        guidelines="Reuse existing code",
        constraints="No paid APIs",
        done_when="Behavior test passes",
        expected_revision=1,
    )
    with pytest.raises(ValueError, match="changed"):
        brief.save(a, goal="Stale", expected_revision=1)
    assert brief.load(a) == second
    handoff = brief.handoff(a)
    assert "Finish revised A" in handoff and "No paid APIs" in handoff
    assert str(left) in handoff and str(right) not in handoff
    assert "acceptance" in handoff.lower()


def test_bundled_cli_target_waits_for_real_return_and_records_proof(tmp_path):
    process = subprocess.Popen(
        [sys.executable, "-m", "interception", "proof", str(tmp_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        bridge = Bridge(tmp_path)
        deadline = time.monotonic() + 5
        while not bridge.requests() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert process.poll() is None, "Bundled proof command must hold for inference"
        rid = wait_request(bridge)
        bridge.write_return(rid, {"role": "assistant", "content": "4"})
        output, error = process.communicate(timeout=5)
        assert process.returncode == 0, error
        assert "RESUMED" in output
        proofs = list((bridge.home / "proofs").glob("*.json"))
        assert len(proofs) == 1
        receipt = files.read_json(proofs[0])
        assert receipt["request_id"] == rid and receipt["score"] == 4
        assert receipt["transport"] == "local CATCH/RETURN"
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate()


def test_answer_from_other_project_cannot_release_waiter(tmp_path):
    from interception.contracts import ContractError

    left, right = tmp_path / "left", tmp_path / "right"
    left.mkdir()
    right.mkdir()
    a, b = Bridge(left), Bridge(right)
    request = {"model": "manual", "messages": [{"role": "user", "content": "hello"}]}
    rid = a.submit(request)
    with pytest.raises(ContractError, match="Unknown"):
        b.accept(
            {
                "request_id": rid,
                "status": "COMPLETED",
                "response": {"role": "assistant", "content": "wrong project"},
            }
        )
    assert a.result(rid) is None
