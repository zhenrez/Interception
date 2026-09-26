# Interception

**Let an agent wait for a ChatGPT answer without losing its inference request.**

Interception captures supported inference requests, turns them into self-contained prompts,
and holds the caller until a matching, validated answer arrives. No provider API key is required.
The core makes no inference API calls.

## Start on Windows

1. Download this repository (GitHub **Code → Download ZIP**) and extract it to a local drive.
2. Double-click **Start-Interception.cmd**. The hardened bootstrap selects a clean 64-bit
   python.org-style CPython 3.13 or 3.11, creates/reuses the repository-local `.venv`, prefers the
   bundled offline wheelhouse, and otherwise uses explicit PyPI without changing global
   Python/Conda/CUDA/NVIDIA state.
3. Click **Choose target project** and select the AI/agent project whose inference calls you want
   Interception to service.
4. Review **Target & routing**, then start the local OpenAI-compatible endpoint from **Inference**.
5. Point the target's supported inference client at the generated local connection settings, or use
   an explicit adapter.
6. The preferred cloud path is private GitHub → ChatGPT Work → separate GitHub RETURN branch.
   See [START_HERE.md](START_HERE.md) and [plugin/README.md](plugin/README.md).

See [START_HERE.md](START_HERE.md) for the exact procedure and current completion boundary.
The bundled proof does not require Ollama, LiteLLM, a provider API key, or a separate target download.
It includes the pinned upstream inference wrapper and its real `judge_score` method, not the full
evolutionary engine. Keep the window open while the caller waits.

**Connecting a real agent is a separate step:** installation assesses the project and creates
connection settings at `.inference_bridge/connection.json`. It does not rewrite unfamiliar
source code. Set the agent's OpenAI Chat Completions client to those settings, or use the Python
adapter below. A project with an unsupported protocol or workflow deadline needs an adapter.

The desktop launcher requires official 64-bit CPython 3.13 or 3.11 with Tcl/Tk. The CLI works
without a GUI. The launcher will replace only this repository's incompatible `.venv`; it never
changes global Python, Conda, CUDA or NVIDIA installations. Failures are written to
`artifacts/launcher-failure.txt`. For a setup-only check, run
`Start-Interception.cmd -VerifyOnly`. GitHub relay authentication remains a separate explicit setup step; the launcher does not make it a prerequisite for core/local operation.

## What works

- Target-focused desktop control panel for inference-surface assessment and routing.
- Explicit per-instance Prompt Evolver `LLMClient.complete` adapter retained only as a bundled live
  transport diagnostic.
- Static project assessment v3: explicit `inference_surfaces[]` for multiple simultaneous
  project/framework/host/external-client boundaries; Python AST evidence, Jupyter code-cell
  inspection, and bounded Python/JS/TS/Go/C#/shell/PowerShell source discovery. Findings are
  candidates, not runtime proofs.
- Local OpenAI **Chat Completions** endpoint; text, JSON answers, JSON Schema, function tool calls,
  synchronous and asynchronous callers, and SSE streaming with waiting heartbeats.
- Lossless original request plus supplied agent identity, context, task, checkpoint and output contract.
- SQLite request/checkpoint commits, atomic mailbox files, crash recovery and stable-key deduplication.
- Invalid, partial, mismatched and conflicting returns cannot release a waiting request.
- A Python cooperative suspend/resume adapter and an automatic supervisor for **explicitly restart-safe nodes**.
- Static durable-job detection requires persistent-store + enqueue + claim + complete + fail evidence
  before `DURABLE_JOB_RESUME` is surfaced; lineage candidates such as run/session/parent/root request,
  agent, workspace and environment IDs are preserved for target-specific validation.
- Compact pending manifest and a self-contained batch attachment containing all pending packets.
- Local desktop control panel and CLI. No accounts, hosted service, or paid inference dependency.

## The two mailboxes

```text
<your project>/.inference_bridge/
  CATCH/req_<id>.json
  CATCH/INFERENCE_BATCH.md
  RETURN/req_<id>.json
  state.sqlite
  assessment.json
  bridge.toml
  connection.json
```

SQLite is authoritative; CATCH files are recoverable projections. Completed requests leave the
pending CATCH list. RETURN files remain for inspection; accepted responses are immutable in SQLite.
An exported batch is a snapshot and should be regenerated when pending work changes.

**Do not commit `.inference_bridge/` to a public repository.** It contains prompts, supplied
context, checkpoints and a local access token. Add it to the target project's `.gitignore` if needed.
The assessor skips secret-named files and environment files, but prompts themselves can contain
secrets; this is not a general-purpose redaction system. No project files are uploaded automatically.

## Install and use from a terminal

Python 3.11 or later:

```bash
python -m pip install -e .
python inference_bridge.py assess /path/to/project
python inference_bridge.py install /path/to/project
python inference_bridge.py serve /path/to/project
```

In another terminal:

```bash
interception status /path/to/project
interception batch /path/to/project
interception import-return /path/to/project /path/to/downloaded-answer.json
```

`submit PROJECT request.json --key RUN:STEP` queues a Chat Completions request.
`resume PROJECT REQUEST_ID` waits for and prints its response; it does **not** resurrect an
arbitrary process. `watch PROJECT` ingests returns without running the HTTP server.

## Connect an OpenAI SDK agent

Install the optional SDK helper into the environment that runs your agent:

```bash
python -m pip install -e '.[openai]'
```

```python
from interception import Bridge
from interception.adapters import openai_client
from interception.cli import load_config

settings = load_config(Bridge("/path/to/project"))
with openai_client(port=settings["port"], token=settings["token"]) as client:
    answer = client.chat.completions.create(
        model="manual",
        messages=[{"role": "user", "content": "Review this plan..."}],
        extra_headers={"Idempotency-Key": "unique-workflow-run:review-step"},
        extra_body={
            "bridge_context": {
                "caller": {"agent": "reviewer", "workflow": "planning", "step": "review"},
                "task": {"objective": "Review this plan", "constraints": []},
            }
        },
    )
    print(answer.choices[0].message.content)
```

The helper disables SDK inference timeouts and automatic retries. Use `asynchronous=True` for
`AsyncOpenAI`. Framework-level deadlines still need adjustment. For an existing SDK client,
set `base_url`, local `api_key`, `timeout=None`, and `max_retries=0` explicitly.
A stable idempotency key identifies **one logical inference step**, including its exact input,
context and checkpoint. Reuse it only to retry that step. Identical unkeyed calls are separate
requests. Changing a keyed request is rejected instead of silently substituting a cached answer.

## Durable workflow suspension

```python
from interception import Bridge, InferencePending

bridge = Bridge("/path/to/project")
try:
    answer = bridge.require(
        {"model": "manual", "messages": [{"role": "user", "content": "Review this plan..."}]},
        key="run-42:review",
        checkpoint={"run_id": "run-42", "node": "review", "plan": "..."},
    )
except InferencePending as pending:
    # Exit/yield successfully. Re-enter this node with the same inputs/key later.
    print(pending.request_id)
```

For automatic re-entry after RETURN, use the supervisor with a node deliberately written to be
restart-safe (like `examples/restartable_node.py`):

```bash
interception run-node /path/to/project garden-run-001 examples/restartable_node.py
# After a reboot or killed supervisor, restart this registered node:
interception resume-node /path/to/project garden-run-001
```

The node throws `InferencePending`, its Python stack unwinds, and the small supervisor waits.
RETURN makes it re-enter the node; the completed inference is replayed from the ledger.
After a supervisor restart, a waiting node remains suspended until its answer exists.
A completed node does not run again. An OS lock prevents concurrent supervisors for the same run.
The registered script hash must still match; imported dependencies are not fingerprinted.

**This is cooperative re-entry, not arbitrary process serialization.** All pre-inference work
must be restart-safe, and external side effects need their own idempotency/checkpoint mechanism.
The supervisor does not install a Windows startup service. Restart it after reboot. A crash during
a node's side effect can cause that node to re-enter; exactly-once external effects are not promised.
Never wrap an arbitrary agent script in `run-node` and assume it is safe to replay.

Other languages can use `POST /bridge/requests` with `request`, `key`, `metadata`, and `checkpoint`.
It returns immediately with a durable ID and status URL. Poll `GET /bridge/requests/<id>` and restore
the application's own continuation when `state` is `COMPLETED`. Both require the local bearer token.

## RETURN format

```json
{
  "request_id": "EXACT_ID_FROM_CATCH",
  "status": "COMPLETED",
  "response": {"role": "assistant", "content": "The answer"}
}
```

Save as `RETURN/req_<id>.json`, preferably through the importer. Structured JSON belongs inside
`response.content` as a JSON-escaped string. Function calls use standard assistant `tool_calls`
with unique IDs and JSON-encoded arguments. The original agent executes those tools, not the bridge.

## Honest compatibility boundaries

| Capability | V1 behavior |
|---|---|
| OpenAI Chat Completions text/function tools | Implemented; official Python SDK tested |
| JSON Schema | Draft 2020-12, local references; remote schema fetches prohibited |
| Streaming | Wait heartbeats, then validated answer chunks; no fabricated intermediate tokens |
| Model identity/sampling/token usage | Original parameters preserved; manual ChatGPT is not the requested model; no invented usage |
| Prompt Evolver | Explicit instance adapter; bundled judging hold/return proof; full evolutionary run not yet proven |
| LangChain/CrewAI/LiteLLM/etc. | Static detection and configurable OpenAI path candidates; general framework integration not proven |
| Anthropic native/Responses/embeddings/audio/images | Unsupported; rejected, requires protocol adapters |
| HTTP connection across reboot | Cannot survive; request and response persist; reattach using stable keys or status API |
| Full context/caller identity | Captures request plus explicitly supplied metadata/files; cannot infer hidden process memory |
| Any arbitrary project, seamless adaptation | Not established; assessment identifies intervention points, not universal correctness |
| ChatGPT watching Windows folders | Not available from an ordinary remote chat; use batch transfer or a separately configured relay |
| Cloud transport | Private GitHub request PR → ChatGPT Work → separate private RETURN branch |

No network interception, TLS interception, hidden paid-provider fallback, or global SDK monkeypatching.
The server binds to loopback only and rejects browser Origin requests. This is a trusted local-user
bridge, not a multi-tenant network service. Keep SQLite on a local disk; do not run concurrent copies
through a cloud-synced/network drive.

## Development and verification

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
```

Tests exercise real OpenAI SDK round trips, streaming tools, async callers, interrupted publication,
process death/re-entry, malformed returns, contract enforcement, concurrency, connection loss,
assessment boundaries and node supervision. See [architecture](docs/architecture.md).

Apache-2.0 licensed.

## GitHub / ChatGPT notification extension

This branch adds an optional event-triggered relay through the existing GitHub plugin.
A private mailbox PR update can wake a Work task; its returned JSON resumes the local caller.
See [plugin setup and verified boundaries](plugin/README.md). The implementation is prepared,
but a live private mailbox and Work automation have not been activated.
