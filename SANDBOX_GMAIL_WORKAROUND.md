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


## Exact local setup

Prerequisites:
- Interception installed for the target project.
- GitHub CLI installed and authenticated with `gh auth login`.
- A private GitHub repository with an open PR whose head branch is in that same private repository.
- A Gmail App Password for the sender account; keep it out of files.

Configure the GitHub relay:

```powershell
.venv\Scripts\python.exe -m interception relay-configure "C:\path\to\project" OWNER/PRIVATE-MAILBOX-REPO PR_NUMBER
```

Configure the temporary Gmail sandbox:

```powershell
.venv\Scripts\python.exe -m interception.sandbox configure "C:\path\to\project" SENDER@gmail.com RECIPIENT@gmail.com
```

Set the Gmail App Password only for the current PowerShell window:

```powershell
$env:INTERCEPTION_SMTP_PASSWORD = "YOUR_16_CHARACTER_APP_PASSWORD"
```

Generate the ChatGPT Work Gmail-trigger specification:

```powershell
.venv\Scripts\python.exe -m interception.sandbox work-spec "C:\path\to\project"
```

In ChatGPT Work, create a Gmail event-triggered task using the configured sender, subject beginning
with `Interception inference ready:`, and the generated prompt.

Run one live wake test:

```powershell
.venv\Scripts\python.exe -m interception.sandbox notify "C:\path\to\project"
```

Then keep the temporary relay/wake loop running while local agents are active:

```powershell
.venv\Scripts\python.exe -m interception.sandbox watch "C:\path\to\project" --interval 30
```

Disable immediately:

```powershell
.venv\Scripts\python.exe -m interception.sandbox disable "C:\path\to\project"
```

The Gmail message contains no inference payload or repository URL. It only wakes the Work task;
the Work task reads the authoritative request from the private GitHub mailbox and writes RETURN there.
