"""Bounded static evidence collection; never execute or rewrite the target project."""

import ast
import os
from pathlib import Path
import re

from .files import write_json

SKIP = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".inference_bridge",
    "dist",
    "build",
    ".next",
    "vendor",
    ".tox",
}
EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".toml", ".yaml", ".yml", ".txt"}
SIGNALS = {
    "openai": r"\bopenai\b|\bOpenAI\b|\bAsyncOpenAI\b|OPENAI_BASE_URL",
    "anthropic": r"\banthropic\b|\bAnthropic\b",
    "litellm": r"\blitellm\b",
    "langchain": r"\blangchain(?:_[a-z]+)?\b",
    "langgraph": r"\blanggraph\b",
    "crewai": r"\bcrewai\b",
    "autogen": r"\bautogen(?:_agentchat|_core|_ext)?\b",
    "llamaindex": r"\bllama_index\b|\bllamaindex\b",
    "http_client": r"\b(?:requests|httpx|aiohttp|fetch)\b",
    "checkpoint_candidate": r"\b(?:checkpointer|checkpoint|SqliteSaver|MemorySaver|interrupt)\b",
    "streaming_candidate": r"\bstream\s*[:=]\s*(?:True|true)",
    "timeout_candidate": r"\b(?:timeout|request_timeout|max_retries|retry)\b",
    "endpoint_configuration": r"\b(?:base_url|baseURL|OPENAI_BASE_URL|api_base)\b",
    "unsupported_protocol": r"\.responses\.create\b|/v1/(?:responses|messages|embeddings)",
}


def assess(project):
    root = Path(project).resolve()
    if not root.is_dir():
        raise ValueError("Project must be an existing directory")
    evidence, calls, skipped = [], [], []
    files = 0
    total = 0
    truncated = False
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(
            d
            for d in dirs
            if d not in SKIP and not d.startswith(".") and not (Path(directory) / d).is_symlink()
        )
        for name in sorted(names):
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink() or name.startswith(".") or path.suffix not in EXTENSIONS:
                continue
            if any(word in name.lower() for word in ("secret", "credential", "lock")):
                continue
            if files >= 10000 or total >= 32 * 1024 * 1024:
                truncated = True
                break
            try:
                if path.stat().st_size > 512 * 1024:
                    skipped.append({"file": relative, "reason": "over 512 KiB"})
                    continue
                raw = path.read_bytes()
                total += len(raw)
                text = raw.decode("utf-8")
            except (OSError, UnicodeError):
                skipped.append({"file": relative, "reason": "unreadable or non-UTF-8"})
                continue
            files += 1
            for line_no, line in enumerate(text.splitlines(), 1):
                for signal, pattern in SIGNALS.items():
                    if re.search(pattern, line):
                        # No source snippets: configuration can contain credentials.
                        evidence.append(
                            {
                                "signal": signal,
                                "file": relative,
                                "line": line_no,
                                "status": "STATIC_CANDIDATE",
                            }
                        )
            if path.suffix == ".py":
                try:
                    tree = ast.parse(text)
                except SyntaxError:
                    skipped.append({"file": relative, "reason": "Python parse failed"})
                    continue
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        function = ast.unparse(node.func)
                        if (
                            len(function) <= 160
                            and re.fullmatch(r"[A-Za-z_][\w.]*", function)
                            and (
                                any(
                                    token in function
                                    for token in (
                                        "completion",
                                        "responses.create",
                                        "messages.create",
                                    )
                                )
                            )
                        ):
                            calls.append(
                                {
                                    "file": relative,
                                    "line": node.lineno,
                                    "mechanism": function,
                                    "status": "AST_CALL_CANDIDATE",
                                }
                            )
        if truncated:
            break
    detected = {item["signal"] for item in evidence}
    compatible = bool(detected & {"openai", "litellm"})
    blockers = [
        "Static assessment cannot prove runtime routing, complete context, or restart safety.",
        "Agent-level deadlines/retries must allow a human-length wait.",
        "Durable workflow resume requires an explicit checkpoint adapter and stable step keys.",
    ]
    if "anthropic" in detected or "unsupported_protocol" in detected:
        blockers.append(
            "Native Anthropic, Responses, embeddings and multimodal calls need protocol adapters; V1 rejects them."
        )
    if truncated:
        blockers.append("Scan budget reached; assessment is incomplete.")
    result = {
        "assessment_version": 1,
        "project": str(root),
        "files_scanned": files,
        "scan_complete_within_scope": not truncated,
        "scope": "UTF-8 source/config; excludes secrets, hidden folders, dependencies, large files; heuristic evidence only",
        "frameworks": sorted(
            detected & {"litellm", "langchain", "langgraph", "crewai", "autogen", "llamaindex"}
        ),
        "providers": sorted(detected & {"openai", "anthropic"}),
        "evidence": evidence,
        "call_sites": calls,
        "skipped": skipped,
        "recommended_interception": "openai_compatible_proxy_candidate"
        if compatible
        else "explicit_sdk_adapter",
        "checkpoint_support": "UNVERIFIED"
        if "checkpoint_candidate" in detected
        else "NOT_DETECTED",
        "streaming_detected": "STATIC_CANDIDATE"
        if "streaming_candidate" in detected
        else "NOT_DETECTED",
        "automatic_installation": "CONFIGURATION_ONLY; source code not modified",
        "hold_mode": "SYNCHRONOUS_HOLD_CANDIDATE; DURABLE_SUSPEND requires adapter",
        "required_changes": blockers,
    }
    home = root / ".inference_bridge"
    if home.is_symlink():
        raise ValueError("Bridge directory must not be a symlink")
    write_json(home / "assessment.json", result)
    return result
