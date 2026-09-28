# Start here

## What Interception does

Interception is an inference router. It catches a supported model call from an AI/agent project,
stores the exact request durably, routes that request through the configured ChatGPT Work transport,
validates the RETURN, and releases the original caller.

It does **not** plan projects, manage goals, schedule project work, or replace upstream systems such
as Panoptes.

## Start on Windows

1. Extract the Interception ZIP to a local folder.
2. Double-click **Start-Interception.cmd**.
   The launcher selects clean 64-bit CPython 3.13 or 3.11 and prepares the repository-local
   `.venv` without changing global Python/Conda/CUDA/NVIDIA state.
3. On the first launch only, choose the AI/agent project whose inference calls Interception should
   service. Interception remembers that local target in the user's Windows profile.
4. Selection is the start command. Interception automatically installs/assesses the target, verifies
   the configured private GitHub mailbox transport, starts the local OpenAI-compatible endpoint, and
   starts the GitHub request/return watcher. There is no separate configure/start sequence.
5. On later launches, if the remembered target still exists, Interception reopens it and starts the
   runtime automatically.
6. Point the target's supported inference client at the generated local endpoint once, or use an
   explicit target adapter. After that, inference requests are intended to flow without manual
   copy/paste or per-request UI work.

## GitHub → ChatGPT Work transport

The preferred cloud transport is GitHub-only:

```text
target inference call
      ↓
Interception local SQLite + CATCH
      ↓
private GitHub request branch / permanent PR
      ↓ PR commit update
ChatGPT Work
      ↓
private GitHub return branch
      ↓
Interception validates RETURN
      ↓
original caller resumes
```

Request and response traffic use separate GitHub branches so a Work RETURN commit does not wake the
same Work trigger again.

Current temporary private transport:

- repository: `zhenrez/chat-docs-versions-histories`
- request branch: `interception-mailbox`
- permanent request PR: **#2**
- return branch: `interception-returns`

The transport repository is temporary infrastructure. A dedicated private Interception mailbox repo
is the cleaner long-term destination.

The desktop launcher owns the normal local runtime path. Selecting a target automatically verifies
the configured GitHub transport and starts both the local API bridge and relay watcher. The target is
remembered for subsequent launches, so normal use is launch-and-run rather than an operator checklist.
The lower-level `relay-configure` / `relay-watch` commands remain available only for headless
recovery and maintenance.

## Diagnostics

The **Diagnostics** tab contains the bundled Prompt Evolver proof. It is only a transport fixture:

1. Click **Run intercepted-call proof**.
2. Copy the waiting inference request.
3. Fulfill it through ChatGPT/Work or a manual RETURN during diagnosis.
4. Paste/import the RETURN.
5. The waiting upstream caller must resume.

A successful proof establishes CATCH → inference → validated RETURN → caller continuation. It does
not establish universal framework compatibility.

## Compatibility boundary

The OpenAI Chat Completions path is implemented. Static assessment can detect several framework and
provider candidates, but native Anthropic Messages, OpenAI Responses, Gemini-native calls and other
protocols require explicit adapters and target-specific proof.

"Any arbitrary AI project" is the compatibility target, not a blanket current claim.

## Verification for maintainers

```sh
python -m pip install -e '.[dev]'
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m interception proof /path/to/project
```

The proof command waits for a real RETURN. It never self-answers.
