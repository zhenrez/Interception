"""Small explicit adapters: no source rewriting and no global SDK monkeypatches."""

from pathlib import Path
import sys
import types
import uuid


def connect_prompt_evolver(client, bridge, *, run_id=None, stop=None):
    """Explicit opt-in on ONE LLMClient instance; never alter a class or provider SDK.

    The live caller blocks; no process-restart replay is claimed. Upstream helpers
    such as complete_json and judge_score continue to call this instance's complete.
    """
    if getattr(client, "_interception_connected", False):
        raise ValueError("This client is already connected")
    response_type = getattr(sys.modules[type(client).__module__], "LLMResponse")
    run_id = run_id or uuid.uuid4().hex

    def complete(self, user, system=None, temperature=None, max_tokens=None, model=None):
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        request = {
            "model": model or self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": max_tokens or self.max_tokens,
        }
        request_id = bridge.submit(
            request,
            metadata={
                "caller": {
                    "agent": "prompt-evolver",
                    "run": run_id,
                    "operation": "complete",
                    "continuation": "LIVE_BLOCKING",
                }
            },
        )
        self._interception_request_id = request_id
        answer = bridge.wait(request_id, stop=stop)
        return response_type(text=answer["content"], model="manual/unspecified", usage={})

    client.complete = types.MethodType(complete, client)
    client._interception_connected = True
    return client


def openai_client(*, port=8742, token="manual-local", asynchronous=False):
    """OpenAI SDK configured for human-length waits; caller deadlines still apply."""
    from openai import AsyncOpenAI, OpenAI
    import httpx

    cls = AsyncOpenAI if asynchronous else OpenAI
    transport = httpx.AsyncClient if asynchronous else httpx.Client
    return cls(
        base_url=f"http://127.0.0.1:{port}/v1",
        api_key=token,
        timeout=None,
        max_retries=0,
        http_client=transport(timeout=None, trust_env=False),
    )


def file_context(project, paths, *, max_bytes=1024 * 1024):
    """Explicitly selected UTF-8 context only; no implicit whole-repo/secret upload."""
    root = Path(project).resolve()
    files = []
    remaining = max_bytes
    for name in paths:
        path = (root / name).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Context files must stay inside the project")
        if path.name.startswith(".env") or any(
            term in path.name.lower() for term in ("secret", "credential")
        ):
            raise ValueError("Secret-bearing context files are excluded")
        with path.open("rb") as stream:
            raw = stream.read(remaining + 1)
        if len(raw) > remaining:
            raise ValueError("Selected context exceeds size budget; narrow the file selection")
        remaining -= len(raw)
        files.append({"path": path.relative_to(root).as_posix(), "content": raw.decode("utf-8")})
    return {
        "working_directory": str(root),
        "relevant_files": files,
        "status": "EXPLICITLY_SUPPLIED",
    }
