# Interception Road UI Driver

## Trigger contract

Run only for new Gmail messages from `think.tattoo.viz@gmail.com` whose subject begins exactly:

`Interception Road:`

The triggering email body is the owner's current instruction.

## Fixed scope

Repository: `zhenrez/Interception`
Branch: `sandbox/ui-scope-correction`

Before every run, read:
1. `INTERCEPTION_PRODUCT_AUTHORITY.md`
2. current branch head
3. relevant current implementation/tests

Never modify any other branch or repository. Never merge, deploy, publish, spend money, expose secrets, or alter the owner's desktop/local installation.

## Mission

Correct the Interception product/UI so it serves only its frozen mission: intercept inference calls, preserve the inference transaction, route it through the user's ChatGPT subscription execution path, validate the response, and return it to the original caller.

The Goal / Guidelines / Constraints / Done-means project-management surface is out of scope and must be removed/replaced by target/inference-routing controls. Preserve the proven bridge, ledger, CATCH/RETURN, assessor, adapters, continuation, relay, and bootstrap unless a concrete defect requires a bounded fix.

## Required run sequence

1. Read the Gmail request fully.
2. Re-read `INTERCEPTION_PRODUCT_AUTHORITY.md`.
3. Inspect exact branch head and relevant code/tests.
4. Choose the smallest bounded change satisfying the email without scope expansion.
5. Implement only on `sandbox/ui-scope-correction`.
6. Run relevant verification; do not claim unobserved local/Windows behavior.
7. Commit verified changes to that branch.
8. Reply to the triggering Gmail message with: exact commit SHA, what changed, verification performed/results, blockers, and next safe increment.
9. If blocked, do not guess or switch branches/projects; reply with the concrete blocker.

## Safety / isolation

- Desktop operational branch `feat/operational-inference` is read-only for comparison.
- Phone sandbox `sandbox/phone-only-cloud` is unrelated.
- Gmail sandbox `sandbox/gmail-wakeup-temp` is unrelated.
- Mailbox PRs #2 and #3 are unrelated to this UI-development lane.
- Do not reintroduce project goal-management into Interception.
