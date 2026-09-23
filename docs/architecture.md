# V1 implementation checkpoint

## Authority and delta

Authority: the user's design brief and instruction to build in `zhenrez/Interception`.
Initial repository: `4fb2cbc6684e7961203c68e29326a0a9ed88d20d`, containing README and Apache license only.
The chosen implementation preserves the A+B design: local protocol adapter plus explicit durable
workflow adapter. It does not claim the proxy can persist a third-party agent's stack.

## Boundaries and acceptance evidence

- Every accepted submission commits original request, supplied metadata and JSON checkpoint in one
  SQLite transaction before CATCH publication. Crash recovery reconstructs missing/modified CATCH.
- SQLite WAL and synchronous FULL are used. Durability assumes an intact local filesystem and OS
  honoring fsync; there is no off-machine disaster recovery.
- Logical identity is an optional stable key plus input fingerprint. Changed content under the same
  key conflicts. Unkeyed identical requests are not conflated.
- RETURN filename and envelope IDs must agree. Response role, content, tool names/arguments and JSON
  schemas are checked. Invalid files remain inspectable with diagnostics; corrected content retries.
- A completed response is immutable. Duplicate equivalent answers are idempotent. Agent delivery can
  happen more than once after a retry; exactly-once external side effects belong to the workflow.
- Projection reconciliation takes a SQLite write lock so independent processes cannot publish stale
  CATCH state over a newer completion. File publication uses replace and fsync.
- Polling is used deliberately for portable Windows behavior. It does not depend on a fragile file
  event edge and therefore sees RETURN files already present after reboot.
- HTTP request bodies are bounded to 8 MiB, header/body reads are time-bounded, and concurrent HTTP
  workers are limited to 64. The inference wait has no server deadline. Disconnected nonstream clients
  release their worker; their durable requests remain. Caller/framework deadlines are outside control.
- Runtime metadata is supplied via bridge_context or Python metadata, not reconstructed by a model.
  The prompt is deterministic, includes original messages and schema/tools, and never drops context
  silently to meet an unknown ChatGPT context limit. Batch size remains user/account-dependent.
- Static assessment is bounded to 10,000 source/config files and 32 MiB; files over 512 KiB, hidden
  directories, dependencies and secret-named files are excluded. Truncation/skips are reported.
- `require()` commits before throwing InferencePending. The workflow must restore/re-enter its node.
- `run-node` persists the registered script/hash and node state. It unwinds the node on suspension,
  waits, and re-enters after a validated answer. The node contract requires safe replay. On reboot the
  supervisor must be started again. RETURN data never chooses an executable or shell command.

## Explicit exclusions

Universal adaptation is impossible to establish from static source inspection alone. Native
Anthropic, Responses, multimodal inputs, remote schema references, n>1, legacy function protocol,
OS network interception, and transparent arbitrary stack checkpointing are excluded from V1.
Framework-specific retries, graph checkpoint stores and side-effect replay must be evaluated with a
real target project before claiming support. Windows GUI interaction needs a real desktop smoke test.

## Next extension: notification relay

The user's follow-up requests a separate ChatGPT plugin branch using an already integrated service.
Confirmed in this session: GitHub is connected; Work's GitHub webhook schema supports PR opening and
opt-in PR commit updates. This supplies a supported wake-up mechanism, not a promise of unlimited,
instant or approval-free inference. The code repository is public; live inference payloads require
an explicitly selected private mailbox. Core local durability must not depend on network delivery.
