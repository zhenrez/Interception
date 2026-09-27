# Compatibility investigation — 23 upstream repositories

Tested on Linux, Python 3.12.14, on 2026-09-27 UTC. The submitted list had 24 URLs; `alrece/loop-engineering` appeared twice. Revisions are pinned in [corpus.json](corpus.json); these results describe those snapshots, not future revisions.

## What the evidence establishes

The bridge worked with **unmodified upstream provider code from two repositories**. Six integration cases exercised real HTTP over loopback, real CATCH/RETURN files and the bridge watcher. The upstream application launchers, deployment stacks and arbitrary agent workflows were not run. No paid inference endpoint was used. The returned test answers are controlled fixtures, not a live Gmail-triggered ChatGPT run.

| Runtime case | Result | Boundary of the result |
|---|---|---|
| Zelos planner → CATCH → invalid RETURN → valid RETURN → parsed plan | Passed | Full planner method ran; invalid role did not release it. Its provider still has a hardcoded 120-second timeout. |
| Zelos native Anthropic request | Correctly rejected | HTTP 404, no request queued. No native Anthropic adapter is implemented. |
| OpenJarvis text generation | Passed | Real engine returned the mailbox answer with explicit `timeout=None`. |
| OpenJarvis function tool call | Passed | Function name and JSON arguments survived response parsing. Tool execution itself was not tested. |
| OpenJarvis async text streaming | Passed | Caller remained pending until RETURN, then consumed SSE content. |
| OpenJarvis caller deadline expires | Expected failure confirmed | With a 0.1-second client deadline, caller raised; after server shutdown and ledger reopening, its queued request could still be completed. The failed workflow was not automatically restored. |

[Recorded test results](test-results.json): the complete local suite passed **56 tests**, including these six upstream cases and ten new assessment regressions. Core tests also cover subprocess exit/crash recovery and explicitly restart-safe node resumption. Those core tests do not establish restart safety for the upstream applications.

## Repository findings

Every row links to the reviewed source at its exact commit. Only Zelos and OpenJarvis have runtime results in this investigation. All other rows are source inspection. “Candidate” means that routing, deadlines and workflow recovery still need integration work.

| Repository | Reviewed inference boundary | Outcome / required work |
|---|---|---|
| [eugenelim/agent-ready-repo](https://github.com/eugenelim/agent-ready-repo/blob/d7aa82b8d0d0e38e3fdf361265f1f8c1d3cbf6d3/packages/agentbundle/agentbundle/commands/pack_evals.py) | Host coding-agent packs; evaluation runner invokes Claude CLI. | Host/CLI adapter required. Not a standalone OpenAI inference agent. |
| [d4vidc4rson/paralogy-divergent-thinking-tools](https://github.com/d4vidc4rson/paralogy-divergent-thinking-tools/blob/36edefda0e3fe600cfd297a3bc29d74020a56111/mcp-server/src/index.ts) | MCP tools that supply divergent-thinking guidance to a host. | Intercept the host model client; no direct model call found in reviewed server. |
| [nicepkg/auto-company](https://github.com/nicepkg/auto-company/blob/125292073565035455495c8769bca3b27775030d/auto-loop.sh) | Claude Code subprocess with a cycle timeout and kill handling. | CLI lifecycle/checkpoint adapter required; changing an OpenAI URL does not cover this loop. |
| [alrece/loop-engineering](https://github.com/alrece/loop-engineering/blob/cc361d30aa1835b0ddd5d3974459ac95b190e4b0/scripts/loop-adversarial.sh) | External codeagent-wrapper; Codex/Gemini backend orchestration. | Host/CLI adapter required; no standalone HTTP interception point verified. |
| [JSONbored/loopover](https://github.com/JSONbored/loopover/blob/f665d94a751ed5374216117b469fcd7092003b23/src/selfhost/ai.ts) | Configurable Chat Completions fetch, other protocols and agent/CLI routes. | Selected text route is a proxy candidate; 120-second AbortSignal and fallback behavior need adaptation. |
| [Aiden-Vihaan/Nexus-AI-Productivity_Dashboard](https://github.com/Aiden-Vihaan/Nexus-AI-Productivity_Dashboard/blob/175a7236d721b95306127acb55d3a0dd8c54d122/src/Intelligence/AI/AI-provider.ts) | MockAIProvider returns local canned responses. | No real inference exercised by this provider; not a positive compatibility result. |
| [Atri2-code/High-Throughput-Concurrent-Task-Scheduler](https://github.com/Atri2-code/High-Throughput-Concurrent-Task-Scheduler/blob/aec9c1d1d275bb946b9ee8d589a52e2b343b7bf9/scheduler.py) | DAG/task scheduling through ProcessPoolExecutor. | No model inference boundary found. Scheduler behavior does not test this bridge. |
| [AI-Zelos/zelos](https://github.com/AI-Zelos/zelos/blob/ebb2ed4252a92fa463cf8491c88ffc5032455df0/zelos/planner.py) | LLMPlanner → OpenAICompatibleProvider → urllib Chat Completions. | RUNTIME PASS for short-wait planner round trip. Hardcoded 120-second timeout prevents indefinite hold; native Anthropic test correctly rejects. |
| [pragya0129/agentForge](https://github.com/pragya0129/agentForge/blob/5c365c3fecea30862db514a61517a078e95d784d/server/src/services/groq.service.ts) | Groq SDK chat.completions.create. | Protocol candidate; application constructs client without explicit endpoint/timeout. Configure/verify SDK routing before use; not runtime-tested. |
| [JNAbhishek27/LifeOS-AI](https://github.com/JNAbhishek27/LifeOS-AI/blob/cef426ceeb983090b966ac0e65c10bb636fa70b9/server.ts) | Google GenAI models.generateContent. | Native Gemini protocol adapter required. |
| [CCTTOO666/innovation-network](https://github.com/CCTTOO666/innovation-network/blob/c8e9e5af619fccf55b1fcab0376d502276103d96/innov/core/llm.py) | urllib Chat Completions with a hardcoded DeepSeek URL. | Source/SDK adapter required: ask() does not use the parsed configuration base_url and defaults to a 15-second timeout. |
| [robzilla1738/supergoal](https://github.com/robzilla1738/supergoal/blob/ec2f6eb8eb3304a4ed32f1f18948a6c6198fcd67/README.md) | Goal-planning skills/prompts for a host agent. | Intercept the host; no standalone model client found in reviewed source. |
| [dharanisri2107/Researchmind](https://github.com/dharanisri2107/Researchmind/blob/6a1492abb4c1ffc53c35982343eeaad90b1013c1/README.md) | Snapshot contains README and license, without the advertised application source. | No runnable inference implementation available in this snapshot. |
| [AdieLaine/multi-agent-reasoning](https://github.com/AdieLaine/multi-agent-reasoning/blob/4fa5fae1e4ae0fc1d83d44e831e5d3cd5806bda0/reasoning.py) | OpenAI SDK Chat Completions in reasoning stages, with Swarm integration. | Proxy candidate for selected calls; SDK settings, retries and stage checkpoints still require verification. |
| [DeepMyst/Mysti](https://github.com/DeepMyst/Mysti/blob/6d709229b5199f6769fb3cf763e5122dcc43c079/src/providers/localai/LocalAIProvider.ts) | VS Code extension: LocalAI streaming HTTP plus other provider/CLI implementations. | Selected LocalAI text route is a candidate; extension lifecycle and other routes untested. |
| [Rajib1000/strategic-reasoning-engine](https://github.com/Rajib1000/strategic-reasoning-engine/blob/74f31d55b6eecbfec7b0e22afec478f67ff122d0/index.html) | Opaque/obfuscated HTML/JavaScript entrypoint; README claims cannot establish implementation. | Static inspection only. Entrypoint not executed; no compatibility verdict. |
| [elophanto/EloPhanto](https://github.com/elophanto/EloPhanto/blob/f9992ab185e430cf70842e864ca76a6a10df3c43/core/kimi_adapter.py) | Several provider adapters; Kimi adapter uses configurable endpoint and httpx. | Selected compatible route is a candidate; Kimi/ZAI clients have 180-second timeouts. Other protocols and workflow state require adapters. |
| [asilvainnovations/Strat-Planner-Pro](https://github.com/asilvainnovations/Strat-Planner-Pro/blob/ccab13c984648b3c36926e19ce47b57a5f97e3e2/src/components/strategic/StrategyMatrix.tsx) | Frontend invokes Supabase ai-strategy-assistant; reviewed snapshot has migrations but no matching edge-function source. | Inference resides behind the remote function. Frontend proxy settings alone do not intercept that backend. |
| [LilMGenius/polysona](https://github.com/LilMGenius/polysona/blob/ad1f263801eb1e777a5ee89e0a034688bc6bfbd9/server/routes/api.ts) | Host-agent skills plus a persona/content dashboard with deterministic local scoring. | Intercept the host coding agent; dashboard is not evidence of a model provider. |
| [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent/blob/03544a73be9423b903bbfa11c29b252a0b88dce9/agent/chat_completion_helpers.py) | OpenAI-compatible dispatch alongside native Responses/Anthropic/other routes and provider watchdogs. | Selected Chat Completions route is a candidate; watchdogs, retries, tools and restart behavior require a Hermes-specific adapter test. |
| [itsPremkumar/Hermes-Full-Autonomous-Company](https://github.com/itsPremkumar/Hermes-Full-Autonomous-Company/blob/a08c09da9db0d1146202598a147e86a556eb1a4c/autonomy-loop.py) | Company automation around a host Hermes installation; bundled OpenRouter verification shell scripts also issue direct Chat Completions requests. | Core orchestration needs host integration. Verification scripts hardcode OpenRouter with 25/40-second limits; they need separate routing. Side-effecting automation was not launched. |
| [open-jarvis/OpenJarvis](https://github.com/open-jarvis/OpenJarvis/blob/e86c582bbe9672db7a8ba574326140cb4ce29655/src/openjarvis/engine/_openai_compat.py) | OpenAICompatEngine text/tool generation and asynchronous SSE. | RUNTIME PASS for these engine paths with explicit local host and timeout=None. Timeout-negative case preserved request but failed caller; no whole-workflow restart claim. |
| [1mancompany/OneManCompany](https://github.com/1mancompany/OneManCompany/blob/3fde1888941248351e5cfc0b153d9149fda73d81/src/onemancompany/agents/base.py) | LangChain ChatOpenAI/ChatAnthropic factory; custom endpoint, retry and fallback configuration. | Selected ChatOpenAI route is a candidate; 300-second request timeout, retries and OpenRouter fallback need explicit handling. |

## Assessor changes driven by this corpus

The original assessor missed `.sh`/PowerShell launchers and classified arbitrary Python names containing `completion` as model calls. For example, agent-ready-repo's `completion_evidence_resolver` was a false positive. Provider mentions also incorrectly encouraged proxy recommendations for mock or host-agent projects.

Assessment version 2 includes shell files; records exact SDK call candidates and raw endpoint/CLI evidence; recognizes Groq and Google GenAI mentions; separates test/example evidence from source candidates; and reports mixed routes or no detected inference boundary. Provider names alone no longer select a proxy. It does not rewrite upstream source.

This is still bounded heuristic discovery, not exhaustive call-graph analysis. Comments, strings and aliases can produce false positives or omissions; endpoints assembled dynamically, hidden directories, binaries, large files, hosted backends and external wrappers may be missed. `no_inference_boundary_detected` means exactly that, not proof that a project never uses AI. `checkpoint_support` remains unverified. The curated table above adds source review to the machine scan; the two are deliberately not interchangeable.

The bounded scan reached its 32 MiB budget in loopover and hermes-agent, so their automatic assessments are incomplete. Targeted source review supplied the route details above. Other snapshots also contain excluded large or unparseable files, listed in the machine results.

[assessment-results.json](assessment-results.json) records the final scan summary for all pins. Full file/line candidates are regenerated under each checkout's `.inference_bridge/assessment.json`; none of those mailbox directories belongs in public source control.

## Reproduce

Use a Linux Python environment with this repository installed and its development dependencies available. Windows launcher/bootstrap behavior was not tested or changed by this investigation.

Create an external corpus directory containing each pinned checkout as `owner__repository`. Clone only the repositories you want to examine; fetch and check out the exact SHA from `corpus.json`. The assessment runner expects all 23 checkouts. The runtime suite needs only `AI-Zelos__zelos` and `open-jarvis__OpenJarvis`. Do not run the upstream projects' install or startup scripts for these tests.

```bash
python scripts/assess-corpus.py /path/to/compatibility-repos --output /tmp/assessment-results.json
INTERCEPTION_UPSTREAM_ROOT=/path/to/compatibility-repos python -m pytest tests/integration -v
INTERCEPTION_UPSTREAM_ROOT=/path/to/compatibility-repos python -m pytest -q
python -m ruff check .
python -m ruff format --check .
```

Runtime tests verify exact upstream SHAs and a clean tracked worktree, import the real provider modules, and restrict socket connections to loopback. They skip when `INTERCEPTION_UPSTREAM_ROOT` is absent; an ordinary CI pass must not be presented as proof that these upstream integrations ran there. Test dependencies used locally: OpenAI 2.54.0, httpx 0.28.1, jsonschema 4.26.0, pytest 9.1.1. Tests and report were rebased onto the existing plugin branch, preserving its later Windows launcher work.

## What to build next

Start with an explicit restart-safe Zelos planning node or OpenJarvis engine adapter. Give each logical step a durable identity, checkpoint inputs before submission, exit/yield on pending inference, and re-enter the same step after RETURN. Add watchdog/retry configuration and verify tool loops before expanding to Hermes or OneManCompany.

The notification branch can wake a configured ChatGPT Work task, but this investigation did not activate Gmail notifications or prove unattended end-to-end delivery. Notification delivery and the model client's timeout/restart behavior are separate integration requirements.
