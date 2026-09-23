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
PROVIDER_SIGNALS = {"openai", "anthropic"}
FRAMEWORK_SIGNALS = {"litellm", "langchain", "langgraph", "crewai", "autogen", "llamaindex"}
HOST_RUNTIME_MARKERS = {
    ".claude": "claude_code",
    ".codex": "codex",
    ".cursor": "cursor",
    ".gemini": "gemini_cli",
    ".kiro": "kiro",
}


def _python_runtime_signals(tree):
    signals = set()
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        for name in names:
            root = name.split(".", 1)[0].lower()
            if root == "openai":
                signals.add("openai")
            elif root == "anthropic":
                signals.add("anthropic")
            elif root == "litellm":
                signals.add("litellm")
            elif root.startswith("langchain"):
                signals.add("langchain")
            elif root == "langgraph":
                signals.add("langgraph")
            elif root == "crewai":
                signals.add("crewai")
            elif root.startswith("autogen"):
                signals.add("autogen")
            elif root == "llama_index":
                signals.add("llamaindex")
    return signals


def _source_runtime_signals(path, text):
    if path.suffix == ".py":
        return set()
    signals = set()
    import_patterns = {
        "openai": r"""(?:from\s+['"]openai['"]|require\(\s*['"]openai['"]\s*\)|\bOPENAI_BASE_URL\b)""",
        "anthropic": r"""(?:from\s+['"]@?anthropic|require\(\s*['"]@?anthropic)""",
        "litellm": r"""(?:from\s+['"]litellm['"]|require\(\s*['"]litellm['"]\s*\))""",
    }
    for signal, pattern in import_patterns.items():
        if re.search(pattern, text):
            signals.add(signal)
    return signals


def _direct_protocol(calls):
    mechanisms = [item["mechanism"] for item in calls]
    if any("chat.completions.create" in item for item in mechanisms):
        return "OPENAI_CHAT_COMPLETIONS"
    if any("responses.create" in item for item in mechanisms):
        return "OPENAI_RESPONSES_UNSUPPORTED"
    if any("messages.create" in item for item in mechanisms):
        return "ANTHROPIC_MESSAGES_UNSUPPORTED"
    if any("completion" in item for item in mechanisms):
        return "COMPLETION_CALL_UNRESOLVED"
    return "NOT_DETECTED"


def assess(project):
    root = Path(project).resolve()
    if not root.is_dir():
        raise ValueError("Project must be an existing directory")
    evidence, calls, skipped = [], [], []
    runtime_signals = set()
    files = 0
    total = 0
    truncated = False
    host_runtimes = sorted(
        runtime for marker, runtime in HOST_RUNTIME_MARKERS.items() if (root / marker).exists()
    )
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
                        evidence.append(
                            {
                                "signal": signal,
                                "file": relative,
                                "line": line_no,
                                "status": "STATIC_CANDIDATE",
                                "provenance": "TEXTUAL_REFERENCE",
                            }
                        )
            runtime_signals.update(_source_runtime_signals(path, text))
            if path.suffix == ".py":
                try:
                    tree = ast.parse(text)
                except SyntaxError:
                    skipped.append({"file": relative, "reason": "Python parse failed"})
                    continue
                runtime_signals.update(_python_runtime_signals(tree))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        function = ast.unparse(node.func)
                        if (
                            len(function) <= 160
                            and re.fullmatch(r"[A-Za-z_][\w.]*", function)
                            and any(
                                token in function
                                for token in ("completion", "responses.create", "messages.create")
                            )
                        ):
                            calls.append(
                                {
                                    "file": relative,
                                    "line": node.lineno,
                                    "mechanism": function,
                                    "status": "AST_CALL_CANDIDATE",
                                    "provenance": "EXECUTABLE_RUNTIME_CALL",
                                }
                            )
        if truncated:
            break
    detected = {item["signal"] for item in evidence}
    protocol = _direct_protocol(calls)
    if protocol != "NOT_DETECTED":
        boundary_owner = "PROJECT"
    elif host_runtimes:
        boundary_owner = "HOST_RUNTIME_CANDIDATE"
    else:
        boundary_owner = "UNKNOWN"

    if protocol == "OPENAI_CHAT_COMPLETIONS":
        recommended = "openai_compatible_proxy_candidate"
    elif boundary_owner == "HOST_RUNTIME_CANDIDATE":
        recommended = "host_runtime_adapter_candidate"
    else:
        recommended = "explicit_sdk_adapter"

    continuation_candidates = []
    if protocol != "NOT_DETECTED":
        continuation_candidates.append("SYNCHRONOUS_HOLD")
    if "checkpoint_candidate" in detected:
        continuation_candidates.extend(["COOPERATIVE_REENTRY", "WORKFLOW_REENTRY"])
    if host_runtimes:
        continuation_candidates.append("HOST_RUNTIME_RESUME")
    continuation_candidates = sorted(set(continuation_candidates))

    blockers = [
        "Static assessment cannot prove runtime routing, complete context, inference-boundary ownership, or restart safety.",
        "Continuation strategy is unverified until the target's blocking, checkpoint, workflow, host-resume, or process-lifecycle behavior is exercised.",
        "Agent-level deadlines/retries must allow the selected human-length wait or resume strategy.",
    ]
    if protocol in {"OPENAI_RESPONSES_UNSUPPORTED", "ANTHROPIC_MESSAGES_UNSUPPORTED"}:
        blockers.append(
            "The detected native inference protocol needs a protocol adapter; V1 rejects it."
        )
    elif "anthropic" in runtime_signals or "unsupported_protocol" in detected:
        blockers.append(
            "Native Anthropic, Responses, embeddings and multimodal calls need protocol adapters; V1 rejects them."
        )
    if truncated:
        blockers.append("Scan budget reached; assessment is incomplete.")
    result = {
        "assessment_version": 2,
        "project": str(root),
        "files_scanned": files,
        "scan_complete_within_scope": not truncated,
        "scope": "UTF-8 source/config; excludes secrets, hidden folders, dependencies, large files; heuristic evidence only",
        "frameworks": sorted(runtime_signals & FRAMEWORK_SIGNALS),
        "providers": sorted(runtime_signals & PROVIDER_SIGNALS),
        "textual_references": sorted(detected & (PROVIDER_SIGNALS | FRAMEWORK_SIGNALS)),
        "host_runtime_candidates": host_runtimes,
        "inference_boundary_owner": boundary_owner,
        "direct_inference_protocol": protocol,
        "evidence": evidence,
        "call_sites": calls,
        "skipped": skipped,
        "recommended_interception": recommended,
        "checkpoint_support": "UNVERIFIED"
        if "checkpoint_candidate" in detected
        else "NOT_DETECTED",
        "streaming_detected": "STATIC_CANDIDATE"
        if "streaming_candidate" in detected
        else "NOT_DETECTED",
        "automatic_installation": "CONFIGURATION_ONLY; source code not modified",
        "continuation_strategy": "UNVERIFIED",
        "continuation_candidates": continuation_candidates,
        "hold_mode": "UNVERIFIED; choose only after target-specific continuation proof",
        "required_changes": blockers,
    }
    home = root / ".inference_bridge"
    if home.is_symlink():
        raise ValueError("Bridge directory must not be a symlink")
    write_json(home / "assessment.json", result)
    return result
