"""Local OpenAI Chat Completions subset and durable submit/status HTTP API."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import logging
import select
import socket
import threading
import time
from urllib.parse import urlsplit

from .bridge import MAX_BYTES, IdempotencyConflict
from .files import loads

LOG = logging.getLogger(__name__)


def completion(record):
    response = record["response"]
    return {
        "id": "chatcmpl-" + record["id"],
        "object": "chat.completion",
        "created": int(record["created"]),
        "model": record["packet"]["original_request"]["model"],
        "choices": [
            {
                "index": 0,
                "message": response,
                "finish_reason": "tool_calls" if response.get("tool_calls") else "stop",
            }
        ],
    }


class BridgeServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, bridge, port=8742, token=None, poll=0.25):
        self.bridge = bridge
        self.token = token
        self.poll = poll
        self.stop_event = threading.Event()
        self.slots = threading.BoundedSemaphore(64)
        super().__init__(("127.0.0.1", port), Handler)
        self.watcher = threading.Thread(target=self.watch, daemon=True)
        self.watcher.start()

    def watch(self):
        while not self.stop_event.is_set():
            try:
                self.bridge.ingest()
            except Exception:
                LOG.exception("Mailbox watcher failed; request ledger retained")
            self.stop_event.wait(self.poll)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def server_close(self):
        self.stop_event.set()
        super().server_close()
        self.watcher.join(timeout=2)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(15)  # Bounds header/body reads and dead socket writes.

    def log_message(self, *_):
        pass  # No prompts, headers, tokens or request content in HTTP logs.

    def authorized(self):
        if self.headers.get("Origin"):
            self.error(403, "Browser-origin requests are disabled")
            return False
        host = self.headers.get("Host", "").split(":")[0]
        if host not in {"127.0.0.1", "localhost"}:
            self.error(403, "Invalid local Host")
            return False
        token = self.server.token
        if token and not hmac.compare_digest(
            self.headers.get("Authorization", ""), "Bearer " + token
        ):
            self.error(401, "Local bridge token required")
            return False
        return True

    def send_json(self, status, data):
        raw = json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(raw)
        self.close_connection = True

    def error(self, status, message):
        self.send_json(
            status, {"error": {"message": message, "type": "bridge_error", "code": str(status)}}
        )

    def do_GET(self):
        try:
            if not self.authorized():
                return
            path = urlsplit(self.path).path
            if path == "/health":
                self.send_json(
                    200, {"status": "ok", "provider": "manual", "protocol": "chat.completions"}
                )
            elif path == "/v1/models":
                self.send_json(
                    200,
                    {
                        "object": "list",
                        "data": [
                            {"id": "manual", "object": "model", "created": 0, "owned_by": "local"}
                        ],
                    },
                )
            elif path.startswith("/bridge/requests/"):
                record = self.server.bridge.get(path.rsplit("/", 1)[-1])
                self.send_json(
                    200,
                    {
                        "request_id": record["id"],
                        "state": record["state"],
                        "response": record["response"],
                        "checkpoint": record["packet"]["checkpoint"],
                    },
                )
            else:
                self.error(
                    404, "Unsupported endpoint; use /v1/chat/completions or /bridge/requests"
                )
        except KeyError:
            self.error(404, "Unknown request")
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            return

    def read_body(self):
        if self.headers.get("Transfer-Encoding"):
            raise ValueError("Chunked request bodies are not supported")
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1:
            raise ValueError("One Content-Length header is required")
        size = int(lengths[0])
        if size < 1 or size > MAX_BYTES:
            raise ValueError("Request body must be between 1 byte and 8 MiB")
        raw = self.rfile.read(size)
        if len(raw) != size:
            raise ValueError("Incomplete request body")
        return loads(raw.decode("utf-8"))

    def do_POST(self):
        streaming = False
        try:
            if not self.authorized():
                return
            path = urlsplit(self.path).path
            if path not in {"/v1/chat/completions", "/bridge/requests"}:
                self.error(404, "Unsupported endpoint; V1 supports Chat Completions only")
                return
            body = self.read_body()
            if not isinstance(body, dict):
                raise ValueError("Request body must be an object")
            key = self.headers.get("Idempotency-Key") or self.headers.get(
                "X-Stainless-Idempotency-Key"
            )
            if path == "/bridge/requests":
                request_id = self.server.bridge.submit(
                    body.get("request"),
                    key=key or body.get("key"),
                    metadata=body.get("metadata"),
                    checkpoint=body.get("checkpoint"),
                )
                record = self.server.bridge.get(request_id)
                self.send_json(
                    202 if record["response"] is None else 200,
                    {
                        "request_id": request_id,
                        "state": record["state"],
                        "status_url": f"/bridge/requests/{request_id}",
                    },
                )
                return
            metadata = body.pop("bridge_context", None)
            request_id = self.server.bridge.submit(body, key=key, metadata=metadata)
            if body.get("stream", False):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.send_header("X-Request-ID", request_id)
                self.end_headers()
                streaming = True
                self.close_connection = True
                # SSE comments keep idle sockets alive without inventing answer tokens.
                heartbeat = 0.0
                while not self.server.stop_event.is_set():
                    result = self.server.bridge.result(request_id)
                    if result is not None:
                        self.stream_result(self.server.bridge.get(request_id))
                        return
                    if time.monotonic() - heartbeat >= 2:
                        self.wfile.write(b": waiting for manual inference\n\n")
                        self.wfile.flush()
                        heartbeat = time.monotonic()
                    self.server.stop_event.wait(self.server.poll)
                return
            while not self.server.stop_event.is_set():
                if self.server.bridge.result(request_id) is not None:
                    self.send_json(200, completion(self.server.bridge.get(request_id)))
                    return
                readable, _, _ = select.select([self.connection], [], [], 0)
                if readable and not self.connection.recv(1, socket.MSG_PEEK):
                    return  # Release the worker; keep the durable request.
                self.server.stop_event.wait(self.server.poll)
        except IdempotencyConflict as exc:
            self.error(409, str(exc))
        except (BrokenPipeError, ConnectionResetError, socket.timeout, InterruptedError):
            return  # Durable request remains available after disconnection/restart.
        except (ValueError, TypeError, KeyError) as exc:
            if not streaming:
                self.error(400, str(exc))
        except Exception:
            LOG.exception("Request failed; ledger retained")
            if not streaming:
                self.error(400, "Request or schema validation failed")

    def stream_result(self, record):
        base = completion(record)
        base["object"] = "chat.completion.chunk"
        message = dict(record["response"])
        if "tool_calls" in message:
            message["tool_calls"] = [
                dict(call, index=i) for i, call in enumerate(message["tool_calls"])
            ]
        for delta, finish in ((message, None), ({}, base["choices"][0]["finish_reason"])):
            chunk = dict(base, choices=[{"index": 0, "delta": delta, "finish_reason": finish}])
            self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
