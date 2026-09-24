import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from interception import Bridge
from interception.adapters import openai_client
from interception.server import BridgeServer

REQUEST = {"model": "manual", "messages": [{"role": "user", "content": "Hello"}]}


@contextmanager
def running(bridge):
    with BridgeServer(bridge, port=0, token="test-token", poll=0.02) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            yield server
        finally:
            server.shutdown()
            worker.join(timeout=2)


def pending(bridge, count=1):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        rows = bridge.requests()
        if len(rows) >= count:
            return rows[-1]["id"]
        time.sleep(0.01)
    raise AssertionError("Request did not reach mailbox")


def http(server, path, data=None, token="test-token", headers=None):
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.server_port}{path}",
        data=json.dumps(data).encode() if data is not None else None,
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            **(headers or {}),
        },
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        return response.status, json.load(response)


def test_official_sdk_wait_and_resume(tmp_path):
    bridge = Bridge(tmp_path)
    with (
        running(bridge) as server,
        openai_client(port=server.server_port, token="test-token") as client,
        ThreadPoolExecutor() as pool,
    ):
        future = pool.submit(
            client.chat.completions.create,
            **REQUEST,
            extra_headers={"Idempotency-Key": "sdk-run:step"},
        )
        rid = pending(bridge)
        time.sleep(0.1)
        assert not future.done()
        bridge.write_return(rid, {"role": "assistant", "content": "SDK resumed"})
        assert future.result(timeout=5).choices[0].message.content == "SDK resumed"
        replay = client.chat.completions.create(
            **REQUEST, extra_headers={"Idempotency-Key": "sdk-run:step"}
        )
        assert replay.choices[0].message.content == "SDK resumed"
        assert len(bridge.requests()) == 1


def test_official_sdk_streaming_tool_calls(tmp_path):
    bridge = Bridge(tmp_path)
    request = dict(
        REQUEST,
        stream=True,
        tools=[
            {"type": "function", "function": {"name": "echo", "parameters": {"type": "object"}}}
        ],
    )
    with (
        running(bridge) as server,
        openai_client(port=server.server_port, token="test-token") as client,
        ThreadPoolExecutor() as pool,
    ):
        future = pool.submit(lambda: list(client.chat.completions.create(**request)))
        rid = pending(bridge)
        bridge.write_return(
            rid,
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "echo", "arguments": '{"text":"hi"}'},
                    }
                ],
            },
        )
        chunks = future.result(timeout=5)
        assert chunks[0].choices[0].delta.tool_calls[0].function.name == "echo"
        assert chunks[-1].choices[0].finish_reason == "tool_calls"


def test_async_sdk(tmp_path):
    bridge = Bridge(tmp_path)
    with running(bridge) as server:

        async def exercise():
            async with openai_client(
                port=server.server_port, token="test-token", asynchronous=True
            ) as client:
                task = asyncio.create_task(client.chat.completions.create(**REQUEST))
                rid = await asyncio.to_thread(pending, bridge)
                await asyncio.to_thread(
                    bridge.write_return, rid, {"role": "assistant", "content": "async resumed"}
                )
                response = await asyncio.wait_for(task, 5)
                assert response.choices[0].message.content == "async resumed"

        asyncio.run(exercise())


def test_durable_http_submit_status_and_restart(tmp_path):
    bridge = Bridge(tmp_path)
    with running(bridge) as server:
        status, created = http(
            server,
            "/bridge/requests",
            {"request": REQUEST, "key": "http-run:step", "checkpoint": {"node": "step"}},
        )
        assert status == 202
        rid = created["request_id"]
    # Socket and original server are gone. New server recovers durable request.
    with running(Bridge(tmp_path)) as server:
        status, value = http(server, f"/bridge/requests/{rid}")
        assert value["state"] == "WAITING_FOR_INFERENCE"
        assert value["checkpoint"] == {"node": "step"}
        server.bridge.write_return(rid, {"role": "assistant", "content": "restored"})
        _, value = http(server, f"/bridge/requests/{rid}")
        assert value["state"] == "COMPLETED"


def test_rejects_auth_origin_unsupported_and_idempotency_conflict(tmp_path):
    bridge = Bridge(tmp_path)
    with running(bridge) as server:
        for path, body, token, headers, expected in [
            ("/health", None, "wrong", {}, 401),
            ("/health", None, "test-token", {"Origin": "https://untrusted.example"}, 403),
            ("/v1/responses", REQUEST, "test-token", {}, 404),
            ("/v1/chat/completions", dict(REQUEST, n=2), "test-token", {}, 400),
        ]:
            with pytest.raises(urllib.error.HTTPError) as caught:
                http(server, path, body, token, headers)
            assert caught.value.code == expected
        assert bridge.requests() == []
        http(server, "/bridge/requests", {"request": REQUEST, "key": "same"})
        with pytest.raises(urllib.error.HTTPError) as caught:
            http(
                server,
                "/bridge/requests",
                {"request": dict(REQUEST, model="different"), "key": "same"},
            )
        assert caught.value.code == 409


def test_disconnected_client_retains_request_and_releases_worker(tmp_path):
    import socket

    bridge = Bridge(tmp_path)
    with running(bridge) as server:
        sock = socket.create_connection(("127.0.0.1", server.server_port))
        body = json.dumps(REQUEST).encode()
        sock.sendall(
            (
                f"POST /v1/chat/completions HTTP/1.1\r\nHost: 127.0.0.1:{server.server_port}\r\nAuthorization: Bearer test-token\r\nContent-Length: {len(body)}\r\n\r\n"
            ).encode()
            + body
        )
        rid = pending(bridge)
        sock.close()
        deadline = time.monotonic() + 3
        while server.slots._value != 64 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.slots._value == 64
        assert bridge.get(rid)["state"] == "WAITING_FOR_INFERENCE"
