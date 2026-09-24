from interception import Bridge
from interception.sandbox.gmail_wakeup import configure, disable


def test_gmail_sandbox_is_explicitly_enabled_and_removable(tmp_path):
    bridge = Bridge(tmp_path)
    configure(bridge, "sender@example.com", "recipient@example.com")
    assert (bridge.home / "ENABLE_TEMP_GMAIL_SANDBOX").is_file()
    disable(bridge)
    assert not (bridge.home / "ENABLE_TEMP_GMAIL_SANDBOX").exists()
