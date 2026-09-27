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
EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
    ".txt",
    ".sh",
    ".bash",
    ".ps1",
    ".cmd",
    ".bat",
}
CODE_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".sh", ".bash", ".ps1", ".cmd", ".bat"}
CALL_PATTERNS = {
    "openai_chat": r"(?:^|\.)chat\.completions\.create$|^litellm\.a?completion$",
    "native_protocol": r"(?:^|\.)(?:responses|messages)\.create$|(?:^|\.)generate_content$|(?:^|\.)generateContent$",
}
BOUNDARY_PATTERNS = {
    "openai_chat": r"/chat/completions\b|\.chat\.completions\.create\s*\(",
    "native_protocol": r"/v1/(?:messages|responses|embeddings)\b|\.(?:responses|messages)\.create\s*\(|\.generateContent\s*\(|:generateContent\b",
    "agent_cli": r"(?:^|[\s\"'/(])(?:claude\s+(?:-p|--print)|codex\s+exec|codeagent-wrapper\b)",
}
SIGNALS = {
    "openai": r"\bopenai\b|\bOpenAI\b|\bAsyncOpenAI\b|OPENAI_BASE_URL",
    "anthropic": r"\banthropic\b|\bAnthropic\b",
    "groq": r"\bgroq(?:-sdk)?\b|\bGroq\b",
    "google_genai": r"@google/genai|\bgoogle\.genai\b|\bgenai\.Client\b",
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
            # Boundary evidence is separate from provider mentions. A dependency
            # or prose string cannot establish that this project performs inference.
            if path.suffix in CODE_EXTENSIONS and path.suffix != ".py":
                for line_no, line in enumerate(text.splitlines(), 1):
                    if line.lstrip().startswith(("#", "//", "*", "REM ")):
                        continue
                    for boundary, pattern in BOUNDARY_PATTERNS.items():
                        if re.search(pattern, line):
                            calls.append(
                                {
                                    "file": relative,
                                    "line": line_no,
                                    "mechanism": boundary,
                                    "boundary": boundary,
                                    "status": "TEXT_BOUNDARY_CANDIDATE",
                                }
                            )
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
                litellm_aliases = set()
                parents = {
                    child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)
                }
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module == "litellm":
                        litellm_aliases.update(
                            alias.asname or alias.name
                            for alias in node.names
                            if alias.name in {"completion", "acompletion"}
                        )
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        function = ast.unparse(node.func)
                        if len(function) <= 160 and re.fullmatch(r"[A-Za-z_][\w.]*", function):
                            for boundary, pattern in CALL_PATTERNS.items():
                                if re.search(pattern, function) or (
                                    boundary == "openai_chat" and function in litellm_aliases
                                ):
                                    calls.append(
                                        {
                                            "file": relative,
                                            "line": node.lineno,
                                            "mechanism": function,
                                            "boundary": boundary,
                                            "status": "AST_CALL_CANDIDATE",
                                        }
                                    )
                    # Inspect argument/assignment strings for raw HTTP endpoints;
                    # exclude standalone strings (including docstrings).
                    if (
                        isinstance(node, ast.Constant)
                        and isinstance(node.value, str)
                        and not isinstance(parents.get(node), ast.Expr)
                    ):
                        for boundary, pattern in BOUNDARY_PATTERNS.items():
                            if re.search(pattern, node.value):
                                calls.append(
                                    {
                                        "file": relative,
                                        "line": node.lineno,
                                        "mechanism": boundary,
                                        "boundary": boundary,
                                        "status": "AST_STRING_CANDIDATE",
                                    }
                                )
        if truncated:
            break
    detected = {item["signal"] for item in evidence}
    # Exclude tests/examples from the recommendation while preserving their evidence.
    boundaries = set()
    for call in calls:
        parts = Path(call["file"]).parts
        call["scope"] = (
            "TEST_OR_EXAMPLE"
            if (
                any(part in {"tests", "test", "examples", "docs", "fixtures"} for part in parts)
                or Path(call["file"]).name.startswith("test_")
            )
            else "SOURCE_CANDIDATE"
        )
        if call["scope"] == "SOURCE_CANDIDATE":
            boundaries.add(call["boundary"])
    recommendation = "no_inference_boundary_detected"
    if len(boundaries) > 1:
        recommendation = "mixed_boundaries_require_route_selection"
    elif "openai_chat" in boundaries:
        recommendation = "openai_compatible_proxy_candidate"
    elif "native_protocol" in boundaries:
        recommendation = "protocol_adapter_required"
    elif "agent_cli" in boundaries:
        recommendation = "cli_adapter_required"
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
        "assessment_version": 2,
        "project": str(root),
        "files_scanned": files,
        "scan_complete_within_scope": not truncated,
        "scope": "UTF-8 source/config; excludes secrets, hidden folders, dependencies, large files; heuristic evidence only",
        "frameworks": sorted(
            detected & {"litellm", "langchain", "langgraph", "crewai", "autogen", "llamaindex"}
        ),
        "providers": sorted(detected & {"openai", "anthropic", "groq", "google_genai"}),
        "evidence": evidence,
        "call_sites": calls,
        "skipped": skipped,
        "recommended_interception": recommendation,
        "inference_boundaries": sorted(boundaries),
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
