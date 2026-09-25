# Phone Mailbox Record Contract

All records are JSON and live only on the private `interception-phone-mailbox` branch.

## Request

```json
{
  "schema_version": 1,
  "gmail_message_id": "GMAIL_MESSAGE_ID",
  "received_at": "ISO-8601",
  "subject": "Interception Phone: ...",
  "body": "owner request",
  "targets": [],
  "constraints": [],
  "state": "ACCEPTED"
}
```

## Result

```json
{
  "schema_version": 1,
  "gmail_message_id": "GMAIL_MESSAGE_ID",
  "status": "COMPLETED",
  "summary": "...",
  "actions_taken": [],
  "evidence": [],
  "changed_resources": [],
  "blockers": [],
  "next_step": null
}
```

Status is one of `COMPLETED`, `BLOCKED`, or `FAILED`.

## Delivery

```json
{
  "schema_version": 1,
  "gmail_message_id": "GMAIL_MESSAGE_ID",
  "delivered_at": "ISO-8601",
  "result_path": "phone_interception/results/GMAIL_MESSAGE_ID.json"
}
```

Existing request, result, and delivery records are immutable. A delivery record means the Gmail
response was actually sent.
