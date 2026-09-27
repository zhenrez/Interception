"""Opt-in tests against pinned, unmodified upstream source, using real local HTTP.

INTERCEPTION_UPSTREAM_ROOT=/path/to/compatibility-repos pytest tests/integration -v
No upstream application startup scripts or remote model endpoints are executed.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

import pytest

from interception import Bridge
from interception.files import write_json
from interception.server import BridgeServer

ROOT = os.environ.get("INTERCEPTION_UPSTREAM_ROOT")
pytestmark = pytest.mark.skipif(
    not ROOT, reason="Set INTERCEPTION_UPSTREAM_ROOT for upstream tests"
)
PINS = {
    "AI-Zelos__zelos": "ebb2ed4252a92fa463cf8491c88ffc5032455df0",
    "open-jarvis__OpenJarvis": "e86c582bbe9672db7a8ba574326140cb4ce29655",
}


@pytest.fixture(autouse=True)
def local_connections_only(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.setenv("no_proxy", "*")
    original = socket.socket.connect

    def connect(sock, address):
        if not isinstance(address, tuple) or address[0] not in ("127.0.0.1", "::1"):
            raise AssertionError(f"Upstream test attempted non-loopback connection: {address}")
        return original(sock, address)

    monkeypatch.setattr(socket.socket, "connect", connect)


def checkout(name):
    path = Path(ROOT) / name
    sha = subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()
    assert sha == PINS[name], "Upstream revision changed; review and repin explicitly"
    assert not subprocess.check_output(["git", "-C", str(path), "diff", "HEAD", "--"], text=True)
    return path


@pytest.fixture(scope="module")
def zelos():
    source = checkout("AI-Zelos__zelos") / "zelos/planner.py"
    spec = importlib.util.spec_from_file_location("upstream_zelos_planner", source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def jarvis():
    sys.path.insert(0, str(checkout("open-jarvis__OpenJarvis") / "src"))
    from openjarvis.core.types import Message, Role
    from openjarvis.engine.openai_compat_engines import OpenAICompatEngine

    return OpenAICompatEngine, Message, Role


@contextmanager
def running(bridge):
    # No auth here also permits the intentionally unsupported native Anthropic
    # request to reach routing validation. Server is bound only to loopback.
    with BridgeServer(bridge, port=0, poll=0.01) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            worker.join(timeout=2)


def pending(bridge):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        rows = bridge.requests()
        if rows:
            return rows[-1]["id"]
        time.sleep(0.01)
    raise AssertionError("No inference reached the mailbox")


def return_file(bridge, rid, response):
    # Exercise the actual RETURN directory watcher, not direct ledger acceptance.
    write_json(
        bridge.returns / f"req_{rid}.json",
        {
            "request_id": rid,
            "status": "COMPLETED",
            "response": response,
        },
    )


def test_zelos_planner_catch_hold_return_parse(zelos, tmp_path):
    bridge = Bridge(tmp_path)
    with ThreadPoolExecutor() as pool, running(bridge) as host:
        planner = zelos.LLMPlanner(
            {
                "provider": "openai",
                "model": "manual",
                "api_key": "local-only",
                "base_url": host + "/v1",
                "max_retries": 0,
            }
        )
        future = pool.submit(planner.plan, "Build a small calculator", goal_id="test-goal")
        rid = pending(bridge)
        packet = json.loads((bridge.catch / f"req_{rid}.json").read_text())
        assert "Build a small calculator" in json.dumps(packet["original_request"])
        assert packet["original_request"]["messages"][0]["content"] == planner.system_prompt
        # A malformed answer must leave the real upstream call suspended.
        return_file(bridge, rid, {"role": "user", "content": "invalid role"})
        time.sleep(0.1)
        assert bridge.get(rid)["state"] == "WAITING_FOR_INFERENCE"
        assert not future.done()
        plan = {
            "tasks": [
                {
                    "task_id": "t1",
                    "description": "Implement calculator operations",
                    "required_capability": "code-generation.python",
                    "dependencies": [],
                }
            ],
            "dependencies": [],
        }
        return_file(bridge, rid, {"role": "assistant", "content": json.dumps(plan)})
        result = future.result(timeout=5)
        assert result.goal_id == "test-goal"
        assert result.tasks[0].task_id == "t1"
        assert result.tasks[0].required_capability == "code-generation.python"
        assert bridge.get(rid)["state"] == "COMPLETED"


def test_zelos_native_anthropic_is_not_compatible(zelos, tmp_path):
    bridge = Bridge(tmp_path)
    with running(bridge) as host:
        provider = zelos.AnthropicProvider("manual", "local-only", base_url=host + "/v1")
        with pytest.raises(RuntimeError, match="404"):
            provider.chat([{"role": "user", "content": "Hello"}])
    assert bridge.requests() == []


@pytest.mark.parametrize("tool_call", [False, True])
def test_openjarvis_generate(jarvis, tmp_path, tool_call):
    Engine, Message, Role = jarvis
    bridge = Bridge(tmp_path)
    with ThreadPoolExecutor() as pool, running(bridge) as host:
        engine = Engine(host=host, api_key="local-only", timeout=None)
        try:
            kwargs = (
                {
                    "tools": [
                        {
                            "type": "function",
                            "function": {
                                "name": "echo",
                                "parameters": {
                                    "type": "object",
                                    "properties": {"text": {"type": "string"}},
                                    "required": ["text"],
                                },
                            },
                        }
                    ]
                }
                if tool_call
                else {}
            )
            future = pool.submit(
                engine.generate,
                [Message(role=Role.USER, content="Hello")],
                model="manual",
                **kwargs,
            )
            rid = pending(bridge)
            assert not future.done()
            response = {"role": "assistant", "content": "Hello back"}
            if tool_call:
                response = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "echo", "arguments": '{"text":"hello"}'},
                        }
                    ],
                }
            return_file(bridge, rid, response)
            result = future.result(timeout=5)
            if tool_call:
                assert result["tool_calls"][0]["name"] == "echo"
                assert json.loads(result["tool_calls"][0]["arguments"]) == {"text": "hello"}
            else:
                assert result["content"] == "Hello back"
        finally:
            engine.close()


def test_openjarvis_async_stream(jarvis, tmp_path):
    Engine, Message, Role = jarvis
    bridge = Bridge(tmp_path)
    with running(bridge) as host:

        async def exercise():
            engine = Engine(host=host, api_key="local-only", timeout=None)
            try:

                async def collect():
                    return [
                        part
                        async for part in engine.stream(
                            [Message(role=Role.USER, content="Hello")], model="manual"
                        )
                    ]

                task = asyncio.create_task(collect())
                rid = await asyncio.to_thread(pending, bridge)
                await asyncio.sleep(0.1)
                assert not task.done()
                return_file(bridge, rid, {"role": "assistant", "content": "stream resumed"})
                assert "".join(await asyncio.wait_for(task, 5)) == "stream resumed"
            finally:
                client = getattr(engine, "_async_client", None)
                if client is not None:
                    await client.aclose()
                engine.close()

        asyncio.run(exercise())


def test_openjarvis_caller_timeout_preserves_request_but_not_workflow(jarvis, tmp_path):
    from openjarvis.engine._base import EngineConnectionError

    Engine, Message, Role = jarvis
    bridge = Bridge(tmp_path)
    with running(bridge) as host:
        engine = Engine(host=host, api_key="local-only", timeout=0.1)
        try:
            with pytest.raises(EngineConnectionError):
                engine.generate(
                    [Message(role=Role.USER, content="Wait for a human")], model="manual"
                )
            rid = pending(bridge)
        finally:
            engine.close()
    restored = Bridge(tmp_path)
    assert restored.get(rid)["state"] == "WAITING_FOR_INFERENCE"
    restored.write_return(rid, {"role": "assistant", "content": "answer after timeout"})
    assert restored.get(rid)["response"]["content"] == "answer after timeout"
    # The caller raised. Persistence alone does NOT restore its workflow.
