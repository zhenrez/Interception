# TEMPORARY Gmail wake-up sandbox

This branch is intentionally disposable. It is **not** part of the Interception MVP.

## Isolation

- Base: `feat/operational-inference` at `f40632b85ea7b5a93813c50a81abf4565e18b298`
- Sandbox branch: `sandbox/gmail-wakeup-temp`
- Gmail code lives only under `interception/sandbox/`.
- Core CLI/relay behavior is unchanged.
- Deleting this branch removes the workaround from the repository history used for normal development.

## Fail-closed activation

The shim will not send anything unless all of these exist locally:

1. `.inference_bridge/ENABLE_TEMP_GMAIL_SANDBOX`
2. `.inference_bridge/github-relay.json`
3. `.inference_bridge/gmail-sandbox.json`
4. `INTERCEPTION_SMTP_PASSWORD`

Email contains only a pending-count + mailbox digest. GitHub remains the authoritative CATCH/RETURN transport.

## Removal

Delete the marker file to disable immediately. When the direct GitHub Work trigger is available, delete this sandbox branch/package. No production branch change is required.
