"""Bounded static evidence collection; never execute or rewrite the target project."""

import ast
import json
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
    ".ipynb",
    ".go",
    ".cs",
    ".sh",
    ".ps1",
}
SOURCE_LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".cs": "csharp",
    ".sh": "shell",
    ".ps1": "powershell",
}
SIGNALS = {
    "openai": r"\bopenai\b|\bOpenAI\b|\bAsyncOpenAI\b|OPENAI_BASE_URL",
    "anthropic": r"\banthropic\b|\bAnthropic\b",
    "gemini": r"\bgoogle\.genai\b|\bgenai\.Client\b|\bChatGoogleGenerativeAI\b",
    "litellm": r"\blitellm\b",
    "langchain": r"\blangchain(?:_[a-z]+)?\b",
    "langgraph": r"\blanggraph\b",
    "crewai": r"\bcrewai\b",
    "autogen": r"\bautogen(?:_agentchat|_core|_ext)?\b",
    "llamaindex": r"\bllama_index\b|\bllamaindex\b",
    "http_client": r"\b(?:requests|httpx|aiohttp|fetch|HttpClient|http\.NewRequest)\b",
    "checkpoint_candidate": r"\b(?:checkpointer|checkpoint|SqliteSaver|MemorySaver|interrupt)\b",
    "streaming_candidate": r"\bstream\s*[:=]\s*(?:True|true)",
    "timeout_candidate": r"\b(?:timeout|request_timeout|max_retries|retry)\b",
    "endpoint_configuration": r"\b(?:base_url|baseURL|OPENAI_BASE_URL|api_base)\b",
    "unsupported_protocol": r"\.responses\.create\b|/v1/(?:responses|messages|embeddings)",
}
PROVIDER_SIGNALS = {"openai", "anthropic", "gemini"}
FRAMEWORK_SIGNALS = {"litellm", "langchain", "langgraph", "crewai", "autogen", "llamaindex"}
MCP_SERVER_PATTERN = re.compile(r"@modelcontextprotocol/sdk/server|\bMcpServer\b")
HOST_RUNTIME_MARKERS = {
    ".claude": "claude_code",
    ".codex": "codex",
    ".cursor": "cursor",
    ".gemini": "gemini_cli",
    ".kiro": "kiro",
}
HOST_CLI_NAMES = {
    "claude": "claude_code",
    "codex": "codex",
    "gemini": "gemini_cli",
}
NON_RUNTIME_PARTS = {"test", "tests", "fixture", "fixtures"}
DURABLE_JOB_PATTERNS = {
    "PERSISTENT_STORE": re.compile(r"\b(?:sqlite3|sqlite|StorageEngine)\b", re.IGNORECASE),
    "ENQUEUE": re.compile(r"\b(?:enqueue_task|enqueue|queue\.insert)\s*\("),
    "CLAIM": re.compile(r"\b(?:dequeue_task|dequeue_batch|claim_task)\s*\("),
    "COMPLETE": re.compile(r"\b(?:complete_task|mark_done|ack_task)\s*\("),
    "FAIL": re.compile(r"\b(?:fail_task|mark_error|nack_task)\s*\("),
}
DURABLE_JOB_REQUIRED = frozenset(DURABLE_JOB_PATTERNS)
LINEAGE_PATTERNS = {
    "agent": re.compile(r"\bagent_id\b"),
    "environment": re.compile(r"\b(?:environment_id|env_id)\b"),
    "parent_request": re.compile(r"\bparent_request_id\b"),
    "root_request": re.compile(r"\broot_request_id\b"),
    "run": re.compile(r"\brun_id\b"),
    "session": re.compile(r"\bsession_id\b"),
    "workspace": re.compile(r"\bworkspace_id\b"),
}


def _is_runtime_path(relative):
    path = Path(relative)
    parts = {part.lower() for part in path.parts[:-1]}
    name = path.name.lower()
    return not (parts & NON_RUNTIME_PARTS or name.startswith("test_") or name.endswith("_test.py"))


def _source_language(path):
    return SOURCE_LANGUAGE_BY_SUFFIX.get(path.suffix.lower())


def _host_cli_candidates(text, *, direct_shell=False):
    found = set()
    process_launch = re.search(
        r"\b(?:subprocess\.(?:run|Popen)|spawn|execFile|exec)\s*\(",
        text,
    )
    for executable, runtime in HOST_CLI_NAMES.items():
        quoted = re.search(rf"[\"']{re.escape(executable)}[\"']", text)
        shell_command = direct_shell and re.search(
            rf"(?m)^\s*(?:&\s*)?{re.escape(executable)}(?:\s|$)",
            text,
        )
        if (process_launch and quoted) or shell_command:
            found.add(runtime)
    return found


def _runtime_protocol_surfaces(text, runtime_signals):
    surfaces = set()
    if "langchain" in runtime_signals and re.search(r"\.a?invoke\s*\(", text):
        surfaces.add("LANGCHAIN_MODEL")
    if re.search(r"/api/(?:generate|chat)\b", text) and re.search(
        r"\b(?:httpx|requests|aiohttp|fetch)\b",
        text,
    ):
        surfaces.add("OLLAMA_NATIVE")
    if re.search(r"/v1/chat/completions\b", text):
        surfaces.add("OPENAI_CHAT_COMPLETIONS")
    if re.search(r"/v1/messages\b", text):
        surfaces.add("ANTHROPIC_MESSAGES_UNSUPPORTED")
    if "gemini" in runtime_signals and re.search(r"\.generate_content\s*\(", text):
        surfaces.add("GEMINI_GENERATE_CONTENT")
    return surfaces


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
            elif root == "google":
                signals.add("gemini")
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
        "gemini": r"\b(?:google\.genai|genai\.Client|ChatGoogleGenerativeAI)\b",
        "litellm": r"""(?:from\s+['"]litellm['"]|require\(\s*['"]litellm['"]\s*\))""",
        "langchain": r"\blangchain(?:_[a-z]+)?\b",
    }
    for signal, pattern in import_patterns.items():
        if re.search(pattern, text):
            signals.add(signal)
    return signals


def _protocol_for_call(function, runtime_signals):
    if "chat.completions.create" in function:
        return "OPENAI_CHAT_COMPLETIONS"
    if "responses.create" in function:
        return "OPENAI_RESPONSES_UNSUPPORTED"
    if "messages.create" in function:
        return "ANTHROPIC_MESSAGES_UNSUPPORTED"
    if "gemini" in runtime_signals and "generate_content" in function:
        return "GEMINI_GENERATE_CONTENT"
    if "completion" in function:
        return "COMPLETION_CALL_UNRESOLVED"
    return None


def _surface_owner(protocol):
    if protocol == "MCP_SERVER":
        return "EXTERNAL_CLIENT_CANDIDATE"
    if protocol == "LANGCHAIN_MODEL":
        return "FRAMEWORK_CANDIDATE"
    if protocol == "HOST_CLI_SUBPROCESS":
        return "HOST_RUNTIME_CANDIDATE"
    return "PROJECT"


def _surface_adapter(protocol):
    mapping = {
        "OPENAI_CHAT_COMPLETIONS": "openai_compatible_proxy_candidate",
        "OLLAMA_NATIVE": "ollama_native_adapter_candidate",
        "LANGCHAIN_MODEL": "framework_adapter_candidate",
        "MCP_SERVER": "mcp_host_adapter_candidate",
        "HOST_CLI_SUBPROCESS": "host_runtime_adapter_candidate",
        "GEMINI_GENERATE_CONTENT": "gemini_native_adapter_candidate",
        "ANTHROPIC_MESSAGES_UNSUPPORTED": "anthropic_native_adapter_candidate",
        "OPENAI_RESPONSES_UNSUPPORTED": "openai_responses_adapter_candidate",
    }
    return mapping.get(protocol, "explicit_sdk_adapter")


def _surface_continuations(protocol):
    if protocol == "HOST_CLI_SUBPROCESS":
        return {"HOST_RUNTIME_RESUME"}
    if protocol == "MCP_SERVER":
        return set()
    return {"SYNCHRONOUS_HOLD"}


def _add_surface(surface_map, protocol, evidence):
    owner = _surface_owner(protocol)
    key = (owner, protocol)
    surface = surface_map.setdefault(
        key,
        {
            "owner": owner,
            "invocation_protocol": protocol,
            "recommended_interception": _surface_adapter(protocol),
            "evidence": [],
            "continuation_candidates": set(_surface_continuations(protocol)),
            "lineage_fields": set(),
        },
    )
    if evidence not in surface["evidence"]:
        surface["evidence"].append(evidence)


def _record_text_evidence(
    *,
    text,
    relative,
    runtime_path,
    evidence,
    runtime_detected,
    durable_evidence,
    lineage_by_file,
    cell=None,
):
    for line_no, line in enumerate(text.splitlines(), 1):
        for signal, pattern in SIGNALS.items():
            if re.search(pattern, line):
                item = {
                    "signal": signal,
                    "file": relative,
                    "line": line_no,
                    "status": "STATIC_CANDIDATE",
                    "provenance": "TEXTUAL_REFERENCE"
                    if runtime_path
                    else "NON_RUNTIME_REFERENCE",
                }
                if cell is not None:
                    item["cell"] = cell
                evidence.append(item)
                if runtime_path:
                    runtime_detected.add(signal)
        if not runtime_path:
            continue
        for signal, pattern in DURABLE_JOB_PATTERNS.items():
            if pattern.search(line):
                item = {"signal": signal, "file": relative, "line": line_no}
                if cell is not None:
                    item["cell"] = cell
                durable_evidence.setdefault(signal, []).append(item)
        for field, pattern in LINEAGE_PATTERNS.items():
            if pattern.search(line):
                lineage_by_file.setdefault(relative, set()).add(field)


def _scan_python_calls(text, relative, runtime_path, surface_map, calls, *, cell=None):
    if not runtime_path:
        return set()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    runtime_signals = _python_runtime_signals(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = ast.unparse(node.func)
        if len(function) > 160 or not re.fullmatch(r"[A-Za-z_][\w.]*", function):
            continue
        protocol = _protocol_for_call(function, runtime_signals)
        if protocol is None:
            continue
        call = {
            "file": relative,
            "line": node.lineno,
            "mechanism": function,
            "status": "AST_CALL_CANDIDATE",
            "provenance": "EXECUTABLE_RUNTIME_CALL",
        }
        if cell is not None:
            call["cell"] = cell
        calls.append(call)
        _add_surface(surface_map, protocol, dict(call))
    return runtime_signals


def _scan_runtime_surfaces(
    *,
    path,
    text,
    relative,
    runtime_path,
    runtime_signals,
    surface_map,
    protocol_surfaces,
    host_runtimes,
    cell=None,
):
    if not runtime_path:
        return
    generic = _runtime_protocol_surfaces(text, runtime_signals)
    for protocol in generic:
        protocol_surfaces.add(protocol)
        item = {
            "file": relative,
            "line": 1,
            "status": "STATIC_CANDIDATE",
            "provenance": "EXECUTABLE_RUNTIME_REFERENCE",
        }
        if cell is not None:
            item["cell"] = cell
        _add_surface(surface_map, protocol, item)
    direct_shell = path.suffix.lower() in {".sh", ".ps1"}
    host_hits = _host_cli_candidates(text, direct_shell=direct_shell)
    if host_hits:
        host_runtimes.update(host_hits)
        protocol_surfaces.add("HOST_CLI_SUBPROCESS")
        item = {
            "file": relative,
            "line": 1,
            "status": "STATIC_CANDIDATE",
            "provenance": "HOST_PROCESS_INVOCATION",
            "host_runtimes": sorted(host_hits),
        }
        if cell is not None:
            item["cell"] = cell
        _add_surface(surface_map, "HOST_CLI_SUBPROCESS", item)
    if MCP_SERVER_PATTERN.search(text):
        protocol_surfaces.add("MCP_SERVER")
        item = {
            "file": relative,
            "line": 1,
            "status": "STATIC_CANDIDATE",
            "provenance": "PROTOCOL_SERVER_REFERENCE",
        }
        if cell is not None:
            item["cell"] = cell
        _add_surface(surface_map, "MCP_SERVER", item)


def _legacy_summary(surfaces, host_runtimes):
    if not surfaces:
        if host_runtimes:
            return (
                "HOST_RUNTIME_CANDIDATE",
                "NOT_DETECTED",
                "host_runtime_adapter_candidate",
            )
        return "UNKNOWN", "NOT_DETECTED", "explicit_sdk_adapter"

    owners = {surface["owner"] for surface in surfaces}
    protocols = {surface["invocation_protocol"] for surface in surfaces}
    owner = next(iter(owners)) if len(owners) == 1 else "MULTIPLE"
    protocol = next(iter(protocols)) if len(protocols) == 1 else "MULTIPLE"
    if len(surfaces) == 1:
        recommended = surfaces[0]["recommended_interception"]
    else:
        recommended = "multiple_adapters_required"
    return owner, protocol, recommended


def assess(project):
    root = Path(project).resolve()
    if not root.is_dir():
        raise ValueError("Project must be an existing directory")
    evidence, calls, skipped = [], [], []
    runtime_signals = set()
    runtime_detected = set()
    source_languages = set()
    surface_map = {}
    durable_evidence = {}
    lineage_by_file = {}
    files = 0
    total = 0
    truncated = False
    host_runtimes = {
        runtime for marker, runtime in HOST_RUNTIME_MARKERS.items() if (root / marker).exists()
    }
    protocol_surfaces = set()

    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(
            d
            for d in dirs
            if d not in SKIP and not d.startswith(".") and not (Path(directory) / d).is_symlink()
        )
        for name in sorted(names):
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            suffix = path.suffix.lower()
            if path.is_symlink() or name.startswith(".") or suffix not in EXTENSIONS:
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
            runtime_path = _is_runtime_path(relative)
            language = _source_language(path)
            if language:
                source_languages.add(language)

            if suffix == ".ipynb":
                try:
                    notebook = json.loads(text)
                except (TypeError, ValueError):
                    skipped.append({"file": relative, "reason": "Notebook JSON parse failed"})
                    continue
                code_cells = [
                    cell
                    for cell in notebook.get("cells", [])
                    if isinstance(cell, dict) and cell.get("cell_type") == "code"
                ]
                if code_cells:
                    source_languages.add("jupyter_python")
                for cell_number, cell in enumerate(notebook.get("cells", []), 1):
                    if not isinstance(cell, dict) or cell.get("cell_type") != "code":
                        continue
                    source = cell.get("source", "")
                    cell_text = "".join(source) if isinstance(source, list) else str(source)
                    _record_text_evidence(
                        text=cell_text,
                        relative=relative,
                        runtime_path=runtime_path,
                        evidence=evidence,
                        runtime_detected=runtime_detected,
                        durable_evidence=durable_evidence,
                        lineage_by_file=lineage_by_file,
                        cell=cell_number,
                    )
                    python_signals = _scan_python_calls(
                        cell_text,
                        relative,
                        runtime_path,
                        surface_map,
                        calls,
                        cell=cell_number,
                    )
                    if python_signals is None:
                        skipped.append(
                            {
                                "file": relative,
                                "reason": f"Python parse failed in notebook cell {cell_number}",
                            }
                        )
                        python_signals = set()
                    runtime_signals.update(python_signals)
                    source_signals = _source_runtime_signals(path, cell_text) if runtime_path else set()
                    runtime_signals.update(source_signals)
                    _scan_runtime_surfaces(
                        path=path,
                        text=cell_text,
                        relative=relative,
                        runtime_path=runtime_path,
                        runtime_signals=python_signals | source_signals,
                        surface_map=surface_map,
                        protocol_surfaces=protocol_surfaces,
                        host_runtimes=host_runtimes,
                        cell=cell_number,
                    )
                continue

            _record_text_evidence(
                text=text,
                relative=relative,
                runtime_path=runtime_path,
                evidence=evidence,
                runtime_detected=runtime_detected,
                durable_evidence=durable_evidence,
                lineage_by_file=lineage_by_file,
            )
            source_signals = _source_runtime_signals(path, text) if runtime_path else set()
            runtime_signals.update(source_signals)

            python_signals = set()
            if suffix == ".py":
                python_signals = _scan_python_calls(
                    text,
                    relative,
                    runtime_path,
                    surface_map,
                    calls,
                )
                if python_signals is None:
                    skipped.append({"file": relative, "reason": "Python parse failed"})
                    python_signals = set()
                runtime_signals.update(python_signals)

            _scan_runtime_surfaces(
                path=path,
                text=text,
                relative=relative,
                runtime_path=runtime_path,
                runtime_signals=source_signals | python_signals,
                surface_map=surface_map,
                protocol_surfaces=protocol_surfaces,
                host_runtimes=host_runtimes,
            )
        if truncated:
            break

    durable_signals = set(durable_evidence)
    durable_established = DURABLE_JOB_REQUIRED <= durable_signals
    durable_files = {
        item["file"]
        for signal in DURABLE_JOB_REQUIRED
        for item in durable_evidence.get(signal, [])
    }
    lineage_candidates = set().union(*lineage_by_file.values()) if lineage_by_file else set()

    surfaces = []
    for _, surface in sorted(surface_map.items(), key=lambda item: item[0]):
        evidence_files = {item["file"] for item in surface["evidence"]}
        if durable_established and evidence_files & durable_files:
            surface["continuation_candidates"].add("DURABLE_JOB_RESUME")
        for file_name in evidence_files:
            surface["lineage_fields"].update(lineage_by_file.get(file_name, set()))
        surface["continuation_candidates"] = sorted(surface["continuation_candidates"])
        surface["lineage_fields"] = sorted(surface["lineage_fields"])
        surface["evidence"] = sorted(
            surface["evidence"],
            key=lambda item: (item["file"], item.get("cell", 0), item.get("line", 0)),
        )
        surfaces.append(surface)

    boundary_owner, protocol, recommended = _legacy_summary(surfaces, host_runtimes)

    continuation_candidates = set()
    for surface in surfaces:
        continuation_candidates.update(surface["continuation_candidates"])
    if "checkpoint_candidate" in runtime_detected:
        continuation_candidates.update({"COOPERATIVE_REENTRY", "WORKFLOW_REENTRY"})
    if host_runtimes:
        continuation_candidates.add("HOST_RUNTIME_RESUME")
    if durable_established:
        continuation_candidates.add("DURABLE_JOB_RESUME")

    blockers = [
        "Static assessment cannot prove runtime routing, complete context, inference-boundary ownership, or restart safety.",
        "Continuation strategy is unverified until the target's blocking, checkpoint, workflow, host-resume, durable-job, or process-lifecycle behavior is exercised.",
        "Agent-level deadlines/retries must allow the selected human-length wait or resume strategy.",
    ]
    unsupported = {
        surface["invocation_protocol"]
        for surface in surfaces
        if surface["invocation_protocol"]
        in {"OPENAI_RESPONSES_UNSUPPORTED", "ANTHROPIC_MESSAGES_UNSUPPORTED"}
    }
    if unsupported:
        blockers.append(
            "Detected native inference protocols need protocol adapters before interception can be claimed."
        )
    elif "anthropic" in runtime_signals or "unsupported_protocol" in runtime_detected:
        blockers.append(
            "Native Anthropic, Responses, embeddings and multimodal calls need protocol adapters; V1 rejects them."
        )
    if truncated:
        blockers.append("Scan budget reached; assessment is incomplete.")

    result = {
        "assessment_version": 3,
        "project": str(root),
        "files_scanned": files,
        "scan_complete_within_scope": not truncated,
        "scope": (
            "Bounded UTF-8 source/config plus Jupyter code cells; excludes secrets, hidden "
            "folders, dependencies and large files; heuristic evidence only"
        ),
        "source_languages": sorted(source_languages),
        "frameworks": sorted(runtime_signals & FRAMEWORK_SIGNALS),
        "providers": sorted(runtime_signals & PROVIDER_SIGNALS),
        "textual_references": sorted(
            {item["signal"] for item in evidence} & (PROVIDER_SIGNALS | FRAMEWORK_SIGNALS)
        ),
        "host_runtime_candidates": sorted(host_runtimes),
        "protocol_surfaces": sorted(protocol_surfaces),
        "inference_surfaces": surfaces,
        "inference_boundary_owner": boundary_owner,
        "direct_inference_protocol": protocol,
        "evidence": evidence,
        "call_sites": calls,
        "skipped": skipped,
        "recommended_interception": recommended,
        "durable_job_resume": {
            "status": "STATIC_CANDIDATE" if durable_established else "NOT_ESTABLISHED",
            "signals": sorted(durable_signals),
            "evidence": [
                item
                for signal in sorted(durable_evidence)
                for item in durable_evidence[signal]
            ],
        },
        "lineage_candidates": sorted(lineage_candidates),
        "checkpoint_support": (
            "UNVERIFIED" if "checkpoint_candidate" in runtime_detected else "NOT_DETECTED"
        ),
        "streaming_detected": (
            "STATIC_CANDIDATE" if "streaming_candidate" in runtime_detected else "NOT_DETECTED"
        ),
        "automatic_installation": "CONFIGURATION_ONLY; source code not modified",
        "continuation_strategy": "UNVERIFIED",
        "continuation_candidates": sorted(continuation_candidates),
        "hold_mode": "UNVERIFIED; choose only after target-specific continuation proof",
        "required_changes": blockers,
    }
    home = root / ".inference_bridge"
    if home.is_symlink():
        raise ValueError("Bridge directory must not be a symlink")
    write_json(home / "assessment.json", result)
    return result
