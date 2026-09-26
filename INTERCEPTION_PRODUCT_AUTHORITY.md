# INTERCEPTION PRODUCT AUTHORITY — UI CORRECTION SANDBOX

## Frozen mission

Interception has one job:

> Intercept inference calls that would normally require a paid model API, durably route the exact inference request through the user's ChatGPT subscription execution path, validate the generated response, and return that response to the waiting caller so the original workflow can continue.

Interception is an inference proxy/transport and continuation layer. It is not a project planner, prompt scheduler, project manager, or goal executor.

## Architectural boundary

Upstream systems such as Panoptes, CrewAI, MetaGPT, agent teams, compilers, debate frameworks, ARIADNE, Archotraz, ARTTOO, or any future project decide what work to perform and when they need inference.

Interception receives the inference transaction and must preserve its semantics:
- original messages/instructions;
- system/developer context supplied by the caller;
- requested output format / schema;
- tools/function-call contract;
- caller/run/checkpoint metadata when supplied;
- idempotency identity;
- response correlation and validation.

Interception then routes the request to an available ChatGPT subscription execution surface and returns the validated answer to the original caller.

## UI authority

The desktop UI must center on TARGET + INFERENCE ROUTING, not project goals.

Appropriate controls include:
- target project name;
- local project folder;
- GitHub repository;
- detected inference surface/framework/provider/protocol;
- recommended/selected adapter;
- bridge endpoint/status;
- mailbox/relay/Work trigger status;
- waiting/completed/invalid request counts;
- test intercepted call;
- pending request inspection;
- adapter instructions;
- reassess target;
- start/stop bridge.

The following current UI concepts are OUT OF SCOPE and must be removed from the Interception product surface:
- Goal
- Guidelines
- Constraints
- Done means
- Save goal
- Copy goal + working procedure for chat
- project execution handoff/procedure

Those belong to upstream orchestration systems such as Panoptes.

Prompt Evolver may remain only as a diagnostic/proof fixture demonstrating a real upstream inference call can be intercepted, held, answered, and resumed. It must not define the product.

## Preserve

Do not rewrite or weaken the proven bridge core while correcting the UI:
- SQLite authoritative request ledger;
- CATCH / RETURN projections;
- OpenAI Chat Completions-compatible local endpoint;
- request/response validation;
- stable idempotency behavior;
- caller/checkpoint preservation;
- cooperative continuation / restart-safe node support;
- bounded assessor;
- private GitHub relay / ChatGPT Work transport;
- Windows bootstrap hardening.

## Universal-adapter truth

"Any arbitrary AI project" is the target, not a current blanket compatibility claim. Adapter coverage must be explicit and evidence-based. Unsupported protocols require adapters rather than silent approximation.

## Sandbox rule

All UI correction work must stay on branch `sandbox/ui-scope-correction`.
Do not merge, deploy, or alter `feat/operational-inference` or any desktop installation without explicit owner authorization.
