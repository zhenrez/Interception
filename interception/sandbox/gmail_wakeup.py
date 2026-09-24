"""Temporary Gmail wake-up shim isolated from the MVP.

Email carries only a mailbox identifier/count. GitHub remains authoritative.
This module refuses to run unless an explicit marker file exists.
"""

from email.message import EmailMessage
import hashlib
import os
import re
import smtplib
import ssl

from ..files import dumps, loads, write_json

ENABLE_MARKER = "ENABLE_TEMP_GMAIL_SANDBOX"
CONFIG_NAME = "gmail-sandbox.json"
STATE_NAME = "gmail-sandbox-sent.json"


def _address(value):
    if not isinstance(value, str) or not re.fullmatch(r"[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+", value):
        raise ValueError("Use a plain email address")
    return value


def configure(bridge, sender, recipient):
    config = {
        "version": 1,
        "temporary": True,
        "sender": _address(sender),
        "recipient": _address(recipient),
    }
    write_json(bridge.home / CONFIG_NAME, config)
    (bridge.home / ENABLE_MARKER).write_text(
        "TEMPORARY Gmail sandbox enabled. Delete this file to disable immediately.\n",
        encoding="utf-8",
    )
    return config


def disable(bridge):
    marker = bridge.home / ENABLE_MARKER
    if marker.exists():
        marker.unlink()
    return True


def _config(relay):
    if not (relay.bridge.home / ENABLE_MARKER).is_file():
        raise ValueError("Temporary Gmail sandbox is disabled")
    path = relay.bridge.home / CONFIG_NAME
    if not path.is_file():
        raise ValueError("Temporary Gmail sandbox is not configured")
    cfg = loads(path.read_text(encoding="utf-8"))
    if cfg.get("version") != 1 or cfg.get("temporary") is not True:
        raise ValueError("Invalid Gmail sandbox configuration")
    _address(cfg.get("sender"))
    _address(cfg.get("recipient"))
    return cfg


def notify(relay, *, send=None):
    cfg = _config(relay)
    raw = relay.read(f"{relay.config['prefix']}/manifest.json", relay.config["branch"])
    if raw is None:
        return False
    ids = sorted(item["request_id"] for item in loads(raw)["requests"])
    if not ids:
        return False
    digest = hashlib.sha256(dumps(ids).encode()).hexdigest()
    state_path = relay.bridge.home / STATE_NAME
    if state_path.exists() and loads(state_path.read_text()).get("digest") == digest:
        return False

    mailbox_id = relay.config["prefix"].split("/")[-1]
    message = EmailMessage()
    message["From"] = cfg["sender"]
    message["To"] = cfg["recipient"]
    message["Subject"] = f"Interception inference ready: {mailbox_id} {digest}"
    message.set_content(
        f"{len(ids)} inference request(s) are waiting in the configured private GitHub mailbox.\n"
        "No inference payload or repository URL is included in this email.\n"
    )

    if send is None:
        password = os.environ.get("INTERCEPTION_SMTP_PASSWORD")
        if not password:
            raise ValueError("INTERCEPTION_SMTP_PASSWORD is required for the temporary Gmail sandbox")
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=30) as smtp:
            smtp.login(cfg["sender"], password)
            smtp.send_message(message)
    else:
        send(message, cfg)

    write_json(state_path, {"digest": digest, "request_ids": ids})
    return True
