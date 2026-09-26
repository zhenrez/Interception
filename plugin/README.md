# GitHub-only ChatGPT Work transport

Interception uses GitHub as the only MVP cloud transport. No Gmail, SMTP, Slack, public webhook,
or inbound server is required.

## Runtime loop

1. A target agent makes a supported inference call.
2. Interception commits the exact request/checkpoint locally before remote publication.
3. The local relay publishes immutable CATCH packets plus a manifest to the private
   **request branch** behind one permanent draft PR.
4. A PR commit-update event wakes one global ChatGPT Work task.
5. Work reads the exact request and writes its RETURN only to the private **return branch**.
6. Because the return branch is not the PR head, a RETURN commit does not wake Work again.
7. The local relay reads the return branch, validates the envelope against the original request,
   records it in SQLite, and releases the original caller.

## Current temporary mailbox

- private repository: `zhenrez/chat-docs-versions-histories`
- request branch: `interception-mailbox`
- permanent draft request PR: **#2**
- return branch: `interception-returns`
- namespace: `mailboxes/<mailbox-id>/`

The document-history repository is temporary infrastructure. A dedicated private Interception
mailbox repository is the cleaner long-term destination; changing repositories must not change the
transport contract.

## Local configuration

The local machine needs GitHub CLI authenticated to the mailbox repository.

```bash
interception relay-configure /path/to/project zhenrez/chat-docs-versions-histories 2 \
  --return-branch interception-returns

interception relay-automation /path/to/project
interception relay-watch /path/to/project
```

The project-local relay configuration stores only routing metadata. SQLite remains authoritative for
the request lifecycle.

## Global Work trigger

Create one event-triggered ChatGPT Work task:

- connector: GitHub
- repository: `zhenrez/chat-docs-versions-histories`
- pull request: **#2**
- trigger on PR commit updates
- comments/reviews are not required

Use the exact transport procedure in the private request branch's
`INTERCEPTION_WORK_DRIVER.md`.

One Work task services all mailbox namespaces. Do not create a task per target project.

## Remote layout

Request branch:

```text
mailboxes/<mailbox-id>/
  manifest.json
  CATCH/
    req_<request-id>.json
```

Return branch:

```text
mailboxes/<mailbox-id>/
  RETURN/
    req_<request-id>.json
```

The manifest contains the exact request ID, request path, return path, and SHA-256 of the CATCH
packet. Work verifies the hash before inference. Existing RETURNs are immutable and skipped.

## Security and correctness boundaries

- The remote repository must be private.
- The request PR must remain open and its head branch must remain the configured request branch.
- The return branch must exist and be separately verified.
- CATCH packets are immutable.
- RETURNs cannot choose executable commands; returned tool calls are handed back to the original
  agent and remain subject to that agent's tool policy.
- Invalid/mismatched RETURNs never release a waiting caller.
- Oversized packets stay local with a diagnostic rather than being truncated.
- Git history retains published inference packets; private-repo access remains an important boundary.
- Network loss does not discard the locally durable request.
- Interception is transport/inference only. It does not perform project planning or modify target
  repositories.

## Completion boundary

Code-level relay behavior is tested on Linux/Windows CI. Full operational acceptance still requires
one observed live round trip:

```text
target call
→ local CATCH
→ request-branch PR commit
→ Work trigger
→ return-branch RETURN
→ local relay import
→ original caller resumes
```

Do not claim that end-to-end path until each step is actually observed.
