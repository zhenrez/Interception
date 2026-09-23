"""Small explicit adapters: no source rewriting and no global SDK monkeypatches."""

from pathlib import Path


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
