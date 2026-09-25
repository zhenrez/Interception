# Interception — Phone-Only Cloud Sandbox

This branch is a disposable experiment created directly from `main`. It is intentionally independent
of every desktop Interception implementation branch.

## Mission

Allow the owner to submit useful work from a phone while the Windows machine is unreachable.

```
phone Gmail request
      ↓
ChatGPT Work event trigger
      ↓
durable request record in private GitHub mailbox
      ↓
Work executes the bounded request using connected cloud tools
      ↓
durable result record
      ↓
Gmail reply to phone
```

## Absolute isolation

This sandbox MUST NOT:

- read or write a desktop project's `.inference_bridge/`;
- import or execute desktop Interception Python;
- depend on a local `.venv`, Windows process, TeamViewer, SMTP helper, or local relay;
- touch `feat/operational-inference`, `sandbox/gmail-wakeup-temp`, or their state;
- use desktop mailbox PR #2;
- merge into `main` or any desktop branch unless the owner explicitly requests it later.

Failure of this sandbox must have zero effect on desktop Interception.

## Private mailbox

Repository: `zhenrez/chat-docs-versions-histories`
Branch: `interception-phone-mailbox`
Draft PR: **#3 — keep open**
Namespace: `phone_interception/`

## How the owner uses it

From the phone, send an email from the connected Gmail account to that same account:

**Subject:** `Interception Phone: <short task name>`

**Body:** State the task naturally. Include the target repository/project/link when the task acts on
a specific project. Constraints and "done means" are optional; Work must establish observable
acceptance criteria when they are missing.

Example:

```
Subject: Interception Phone: inspect Interception phone sandbox

Check zhenrez/Interception branch sandbox/phone-only-cloud.
Find the first concrete defect or missing verification in the phone-only path.
Fix one bounded increment, verify it, commit only to that sandbox branch, and email me the result.
Do not merge or touch desktop branches.
```

See `WORK_TASK_PROMPT.md` for the Work task instructions.
