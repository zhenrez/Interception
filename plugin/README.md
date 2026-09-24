# ChatGPT plugin branch: event-triggered inference mailbox

This branch reuses the **already connected GitHub plugin** as the ChatGPT-side transport.
It does not require publishing a new custom app or pretending that an MCP notification by itself
starts a model turn. A supported **Work webhook automation** provides the wake-up.

## The loop

1. Local agent submits; Interception commits the request/checkpoint and enters HOLD.
2. Local relay publishes new CATCH packets and a manifest in one commit to a **private mailbox PR**.
3. The PR commit-update event starts the configured ChatGPT Work task.
4. ChatGPT reads pending CATCH packets through GitHub and writes machine-readable RETURN files.
5. Local relay retrieves RETURN, validates it, records it, and the waiting caller/node continues.

ChatGPT is event-triggered. The local relay checks GitHub for answers every 30 seconds by default.
This avoids exposing a server on the user's computer. Network outages retain the local queue.
Actual task delivery/latency is platform-controlled; no instant, unlimited, or approval-free SLA.

## Confirmed platform capability

Verified in this session on 2026-09-23:

- The user's GitHub connector can read `zhenrez/Interception`.
- Work's discovered GitHub webhook schema supports an exact repository and PR number,
  with `enable_commit_updates=true` to include new PR commits.
- OpenAI documents event-triggered tasks in Work for eligible accounts; writes may require approval.
- `zhenrez/Interception` is **public**. It is the source-code repository, not the live payload mailbox.

Sources:
- https://help.openai.com/en/articles/10291617-tasks-in-chatgpt
- The connected account's `automations.discover_webhook_schema(connector_type="github")` result.

## What is implemented and what remains unconfigured

Implemented: private-repository gate, PR identity checks, atomic batched Git commits, stable request
paths, manifest content hashes, no-op sync deduplication, non-forced ref updates, validated local
RETURN ingestion, retry after network/update failure, and generation of a narrowly scoped Work task
configuration. The relay is tested against a simulated GitHub API, not a live private mailbox.

**Not activated:** a private mailbox destination, local GitHub authentication, and the actual Work
automation. No live prompts have been published and no background task has been created.
The relay does not create a private repository or PR itself. Once the destination is selected,
the repository/PR and scoped automation can be set up through authorized GitHub/Work actions.

## Setup contract

Use a private GitHub repository accessible to both the local GitHub CLI and ChatGPT's connector.
Create an open PR from a branch in that same repository (a small mailbox README provides its initial
diff). Keep that PR open as the mailbox event source. No merge is required.

On the computer running the agents, install GitHub CLI and authenticate it (`gh auth login`).
The ChatGPT connector's credentials are not silently copied to the local machine.

```bash
interception relay-configure /path/to/project owner/private-mailbox 7
interception relay-automation /path/to/project
interception relay-watch /path/to/project
```

`7` is the actual mailbox PR number. `relay-automation` prints an exact ready-to-register task
specification. It does not activate it. In Work, first verify read access to the selected private
repo, discover the supported GitHub trigger schema, then register that specification as a webhook
automation **without a schedule**. Keep the full prompt and exact repository/PR filters.

The core `serve` or `run-node` still runs as appropriate. After reboot, restart those processes and
`relay-watch`; the durable local queue and remote request paths allow recovery.

## Data and event behavior

Remote layout:

```text
mailboxes/<project-id>/manifest.json
mailboxes/<project-id>/CATCH/req_<id>.json
mailboxes/<project-id>/RETURN/req_<id>.json
```

The manifest lists pending request IDs, paths, and SHA-256 hashes. Every logical request is immutable.
ChatGPT skips an existing RETURN; its own answer commit can trigger another task, but that task sees
no unanswered work and performs no write. The local manifest cleanup may cause one further no-op
wake-up. Separate tasks for separate mailboxes must retain their own prefix and exact PR scope.

Only configured private repositories are permitted. Packet limits are 900,000 UTF-8 bytes for this
transport; oversized requests stay local with a diagnostic, rather than being truncated. Git history
retains published packets even after future file deletion. Review the destination's access membership
and include only intended inference context; private is an access boundary, not automatic redaction.

Remote answers cannot specify executable commands. They only satisfy a pre-existing local request
and its schema. Returned tool calls are for the original agent's tool policy to handle.

## Remaining integration evidence

Before calling this end-to-end operational: verify one harmless synthetic request through the actual
private repo → Work event → returned JSON → local resume path, including whether write approval is
required for that account. Respect task/account rate limits and unfinished-batch reports. Notifications
can be enabled through ChatGPT's own task notification settings; this branch does not change them.


## MVP trigger decision

The MVP uses the GitHub PR commit-update event directly as the ChatGPT Work wake-up.
No Gmail sender, SMTP credential, app password, email digest state, or secondary notification
transport is required. GitHub is the durable mailbox, event source, and RETURN channel.

The remaining live proof is therefore:

```text
local CATCH
→ private GitHub mailbox PR commit
→ ChatGPT Work trigger
→ GitHub RETURN
→ local relay import
→ waiting caller resumes
```
