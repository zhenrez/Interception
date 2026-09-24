import base64
import copy
import json
from urllib.parse import unquote

import pytest

from interception import Bridge
from interception.github_relay import GitHubError, GitHubRelay, automation_spec, configure

REQUEST = {"model": "manual", "messages": [{"role": "user", "content": "private context"}]}


class FakeGitHub:
    def __init__(self):
        self.private = True
        self.files = {}
        self.head = "initial-head"
        self.writes = []
        self.trees = {}
        self.commits = {}
        self.fail_update = False
        self.prefix = "repos/user/private-mailbox"

    def __call__(self, method, endpoint, body=None):
        if method != "GET":
            self.writes.append((method, endpoint, copy.deepcopy(body)))
        suffix = endpoint.removeprefix(self.prefix)
        if method == "GET" and not suffix:
            return {"private": self.private}
        if method == "GET" and suffix == "/pulls/7":
            return {
                "state": "open",
                "head": {
                    "ref": "mailbox",
                    "sha": self.head,
                    "repo": {"full_name": "user/private-mailbox"},
                },
            }
        if method == "GET" and suffix.startswith("/contents/"):
            path = unquote(suffix[len("/contents/") :].split("?ref=")[0])
            if path not in self.files:
                raise GitHubError(404, "missing")
            data = self.files[path].encode()
            return {
                "encoding": "base64",
                "size": len(data),
                "content": base64.b64encode(data).decode(),
            }
        if method == "GET" and suffix.startswith("/git/commits/"):
            return {"tree": {"sha": "base-tree"}}
        if method == "POST" and suffix == "/git/trees":
            sha = f"tree-{len(self.trees)}"
            self.trees[sha] = body["tree"]
            return {"sha": sha}
        if method == "POST" and suffix == "/git/commits":
            sha = f"commit-{len(self.commits)}"
            self.commits[sha] = body
            return {"sha": sha}
        if method == "PATCH" and suffix == "/git/refs/heads/mailbox":
            assert body["force"] is False
            if self.fail_update:
                self.fail_update = False
                raise GitHubError(409, "simulated concurrent branch update")
            commit = self.commits[body["sha"]]
            for entry in self.trees[commit["tree"]]:
                self.files[entry["path"]] = entry["content"]
            self.head = body["sha"]
            return {}
        raise AssertionError((method, endpoint, body))


def relay(tmp_path):
    api = FakeGitHub()
    config = configure(tmp_path, "user/private-mailbox", 7, api=api)
    return GitHubRelay(tmp_path, api=api), api, config


def test_public_repo_refused_before_payload_writes(tmp_path):
    api = FakeGitHub()
    api.private = False
    Bridge(tmp_path).submit(REQUEST)
    with pytest.raises(ValueError, match="private"):
        configure(tmp_path, "user/private-mailbox", 7, api=api)
    assert api.writes == []


def test_batched_publish_idempotency_and_validated_return(tmp_path):
    worker, api, config = relay(tmp_path)
    first = worker.bridge.submit(REQUEST)
    second = worker.bridge.submit(dict(REQUEST, model="other"))
    result = worker.sync()
    assert result["published_files"] == 3
    assert sum(method == "PATCH" for method, _, _ in api.writes) == 1
    writes = len(api.writes)
    assert worker.sync()["published_files"] == 0
    assert len(api.writes) == writes
    prefix = config["prefix"]
    api.files[f"{prefix}/RETURN/req_{first}.json"] = json.dumps(
        {
            "request_id": first,
            "status": "COMPLETED",
            "response": {"role": "assistant", "content": "done"},
        }
    )
    result = worker.sync()
    assert result["imported"] == [first]
    assert worker.bridge.result(first)["content"] == "done"
    assert worker.bridge.result(second) is None
    assert (worker.bridge.returns / f"req_{first}.json").is_file()
    manifest = json.loads(api.files[f"{prefix}/manifest.json"])
    assert [item["request_id"] for item in manifest["requests"]] == [second]


def test_recheck_privacy_and_remote_mutation(tmp_path):
    worker, api, config = relay(tmp_path)
    rid = worker.bridge.submit(REQUEST)
    worker.sync()
    api.private = False
    writes = len(api.writes)
    with pytest.raises(ValueError, match="private"):
        worker.sync()
    assert len(api.writes) == writes
    api.private = True
    api.files[f"{config['prefix']}/CATCH/req_{rid}.json"] = "tampered"
    with pytest.raises(ValueError, match="differs"):
        worker.sync()


def test_remote_invalid_return_keeps_request_pending(tmp_path):
    worker, api, config = relay(tmp_path)
    rid = worker.bridge.submit(REQUEST)
    worker.sync()
    api.files[f"{config['prefix']}/RETURN/req_{rid}.json"] = '{"request_id":"wrong"}'
    outcome = worker.sync()
    assert outcome["errors"][0]["request_id"] == rid
    assert worker.bridge.result(rid) is None


def test_failed_remote_commit_retry_keeps_local_request(tmp_path):
    worker, api, _ = relay(tmp_path)
    rid = worker.bridge.submit(REQUEST)
    api.fail_update = True
    with pytest.raises(GitHubError):
        worker.sync()
    assert worker.bridge.get(rid)["state"] == "WAITING_FOR_INFERENCE"
    assert not api.files
    assert worker.sync()["published_files"] == 2
    assert worker.sync()["published_files"] == 0


def test_automation_exact_pr_scope_and_no_schedule(tmp_path):
    _, _, config = relay(tmp_path)
    spec = automation_spec(config)
    assert "schedule" not in spec and "timing_mode" not in spec
    params = spec["triggers"][0]["params"]
    assert params["repository"] == "user/private-mailbox"
    assert params["pull_request_number"] == 7
    assert params["enable_commit_updates"] is True
    assert params["enable_comments"] is False
    assert "response-only commits must not create loops" in spec["prompt"]
