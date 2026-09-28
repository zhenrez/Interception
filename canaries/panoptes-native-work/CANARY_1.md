# Panoptes native Work propagation — Canary 1

Status: ARMED, NOT TRIGGERED.

This canary tests only the native GitHub PR commit-update -> ChatGPT Work -> verified GitHub result path.
It must not run Panoptes control logic, target-project implementation, GEPA/Forge work, browser automation, or Appium.

## Frozen source

- Panoptes repository: `AlkaiDynamics/Panoptes`
- Expected `main` SHA: `5a48edd7296789922f927420cdf634d97a141b7e`
- Trigger repository: `zhenrez/Interception`
- Trigger PR head: `canary/panoptes-work-trigger`
- Result branch: `canary/panoptes-work-results`
- Trigger event path: `canaries/panoptes-native-work/events/generation-0001.json`
- Result path: `canaries/panoptes-native-work/results/<event_id>.json`

The trigger and result branches MUST remain different. Work MUST NOT write to the monitored PR head.

## Event identity

The event envelope is:

```json
{
  "schema_version": "panoptes.work-event/v1",
  "account": "zhenrez",
  "project": "Panoptes-canary",
  "generation": 1,
  "source_checkpoint": "5a48edd7296789922f927420cdf634d97a141b7e",
  "previous_result": null,
  "chain_budget": 1,
  "event_id": "5e2cbf342dd4206522da2e5f32d62c5fab350f152e61d86c1c6d2bd070c534e4"
}
```

`event_id` is SHA-256 of the UTF-8 canonical JSON formed from every field above except `event_id`, with keys sorted and separators `,` and `:` and no insignificant whitespace.

Canonical preimage:

```json
{"account":"zhenrez","chain_budget":1,"generation":1,"previous_result":null,"project":"Panoptes-canary","schema_version":"panoptes.work-event/v1","source_checkpoint":"5a48edd7296789922f927420cdf634d97a141b7e"}
```

## Required Work behavior

For one invocation only:

1. Read the generation envelope from the current monitored PR head.
2. Recompute `event_id`; fail closed if it does not match.
3. Check the result branch for `canaries/panoptes-native-work/results/<event_id>.json`.
   If it already exists, perform no writes and finish as an idempotent no-op.
4. Read current `AlkaiDynamics/Panoptes` `main` and verify it equals `source_checkpoint`.
5. Do not change Panoptes, Interception main, the trigger branch, ARTTOO, Archotraz, or any target project.
6. Write at most one result artifact to `canary/panoptes-work-results`.
7. Because `chain_budget == 1`, do not create or schedule generation 2 and do not update the trigger PR head.
8. Re-read the result branch and verify the result commit/file exists before reporting success.

## Result envelope

The one result file must contain at least:

```json
{
  "schema_version": "panoptes.work-result/v1",
  "event_id": "<exact event_id>",
  "generation": 1,
  "source_checkpoint": "<exact source_checkpoint>",
  "observed_panoptes_main": "<SHA actually read>",
  "status": "verified",
  "trigger_repository": "zhenrez/Interception",
  "trigger_branch": "canary/panoptes-work-trigger",
  "result_branch": "canary/panoptes-work-results",
  "chain_budget_remaining": 0
}
```

If the source SHA, event identity, repository access, or result write cannot be verified, use `status: "blocked"` and record the blocker; do not continue the chain.

## PASS gate

Canary 1 passes only when GitHub shows all of the following:

- the exact generation-0001 event commit exists on the monitored PR head;
- a native GitHub PR commit-update invoked Work;
- Work read Panoptes at the expected SHA;
- exactly one result for the immutable `event_id` exists on the separate result branch;
- Work re-read GitHub and verified that result;
- no generation 2 event was emitted;
- no write occurred to the trigger branch from Work.

Until an exact-PR native Work trigger is registered for this PR, DO NOT commit `generation-0001.json`.
