import json

import pytest

from interception import Bridge
from interception.sandbox.gmail_wakeup import configure, disable, notify


class StubRelay:
    def __init__(self, bridge, manifest):
        self.bridge = bridge
        self.config = {"prefix": "mailboxes/project-123", "branch": "mailbox"}
        self._manifest = manifest

    def read(self, path, branch):
        assert path == "mailboxes/project-123/manifest.json"
        assert branch == "mailbox"
        return json.dumps(self._manifest)


def test_gmail_sandbox_is_explicitly_enabled_and_removable(tmp_path):
    bridge = Bridge(tmp_path)
    configure(bridge, "sender@example.com", "recipient@example.com")
    assert (bridge.home / "ENABLE_TEMP_GMAIL_SANDBOX").is_file()
    disable(bridge)
    assert not (bridge.home / "ENABLE_TEMP_GMAIL_SANDBOX").exists()


def test_gmail_sandbox_fails_closed_when_disabled(tmp_path):
    bridge = Bridge(tmp_path)
    relay = StubRelay(bridge, {"requests": [{"request_id": "secret-request-id"}]})
    sent = []

    with pytest.raises(ValueError, match="disabled"):
        notify(relay, send=lambda message, cfg: sent.append((message, cfg)))

    assert sent == []


def test_gmail_wake_contains_no_inference_payload_or_repository_url_and_deduplicates(tmp_path):
    bridge = Bridge(tmp_path)
    configure(bridge, "sender@example.com", "recipient@example.com")
    relay = StubRelay(
        bridge,
        {
            "requests": [
                {
                    "request_id": "secret-request-id",
                    "path": "mailboxes/project-123/CATCH/req_secret-request-id.json",
                    "sha256": "deadbeef",
                }
            ]
        },
    )
    sent = []

    assert notify(relay, send=lambda message, cfg: sent.append((message, cfg))) is True
    assert len(sent) == 1
    message, cfg = sent[0]
    body = message.get_content()

    assert message["From"] == "sender@example.com"
    assert message["To"] == "recipient@example.com"
    assert message["Subject"].startswith("Interception inference ready: project-123 ")
    assert "1 inference request(s) are waiting" in body
    assert "secret-request-id" not in str(message)
    assert "deadbeef" not in str(message)
    assert "github.com" not in str(message).lower()
    assert "CATCH" not in str(message)
    assert cfg["temporary"] is True

    assert notify(relay, send=lambda message, cfg: sent.append((message, cfg))) is False
    assert len(sent) == 1
