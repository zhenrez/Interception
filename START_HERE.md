# Start here

## Work from a simple goal

1. Extract the ZIP to a local folder. Double-click **Start-Interception.cmd**.
   The existing launcher selects CPython 3.13 or 3.11 and prepares `.venv` for you.
   First setup needs internet access for Python packages; no paid inference service is required.
2. Click **Choose project folder**. Select the actual project you want improved.
3. Enter your goal in your own words. Add guidelines and constraints if you have them.
   **Done means** is optional: the assistant must establish observable acceptance criteria.
4. Click **Copy goal + working procedure for chat**. Paste into your project chat with its
   repository connected or files attached. Keep this window open while copying/pasting.
5. The assistant follows the included procedure: recover current authority → establish scope
   and acceptance → choose bounded work → execute → verify → checkpoint → continue.

You do not need to supply implementation vocabulary or a perfect prompt. Missing decisions
should be retrieved first; only material unresolved choices should come back to you.
Your brief is revisioned in this project's SQLite ledger. It is not an instruction to merge,
publish, spend money, or override an earlier hold. The assistant must reconcile those boundaries.

## Prove the inference connection

1. Open the **Inference** tab and click **Run bundled Prompt Evolver test**.
2. Click **Copy waiting requests for ChatGPT**, then paste into chat.
3. ChatGPT returns a JSON envelope. Copy the whole envelope, including `request_id`.
4. Click **Paste RETURN JSON from clipboard**.
5. The waiting upstream judging method returns. The panel displays **RESUMED** and stores
   a receipt under `.inference_bridge/proofs/` in the selected project.

The test deliberately asks a tiny arithmetic question so a successful run proves transport
and same-process continuation, without implying project quality or full evolutionary optimization.
You can use **Save request batch as a file** and **Import RETURN files** instead of clipboard.
Malformed or other-project envelopes are rejected. Failed proof answers require a new test.

Keep the test window open while waiting. Closing it retains the request but loses that live
Python caller. Restarting the proof starts a new logical call. Existing explicitly restart-safe
nodes have a separate durable re-entry mechanism; arbitrary process restoration is not promised.

## What this delivery finishes

- Reconciles the existing core/assessor and relay/launcher branches in one review branch.
- Supplies a bundled real target, explicit adapter, project briefs and chat handoff.
- Provides a Windows launcher using the existing clean-Python conventions.
- Exercises local CATCH → manual answer → validated RETURN → the same waiting caller resumes.

## What still needs connection

Automatic remote wake-up requires a selected private GitHub mailbox, local GitHub authentication
and an enabled Work trigger. Gmail is an optional wake-up route requiring separate mail credentials.
Those account-specific connections are not configured by the ZIP. Never put live inference packets
in the public Interception source repository. Setup remains in `plugin/README.md`.

Chat currently performs project work. This desktop does not automatically edit arbitrary projects,
schedule recurring work or guarantee completion from a goal. Panoptes remains a separate planning
and continuation project. Its scheduler/executor and GEPA adoption are not implemented by this patch.
Do not count an answered inference call as a finished project or an independently accepted integration.

## Adapter for the full Prompt Evolver checkout

In the Python process that creates the project's `LLMClient`, explicitly opt in immediately after
constructing that client, before handing it to mutation/evaluation/validation components:

```python
from interception import Bridge
from interception.adapters import connect_prompt_evolver

# llm is the project's existing LLMClient instance.
connect_prompt_evolver(llm, Bridge(project_folder), run_id=run_id)
```

Only that instance changes. Its inherited `complete_json` and `judge_score` continue using
`complete`; there is no global provider patch or paid fallback. Requested model/settings are
preserved in CATCH. The returned `LLMResponse.model` is `manual/unspecified` and usage is empty.
Workflow-level deadlines and process lifetime remain the host application's responsibility.

## Verification for maintainers

```sh
python -m pip install -e '.[dev]'
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m interception proof /path/to/project
```

The last command waits for an actual RETURN. It never self-answers.
