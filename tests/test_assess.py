import json

import pytest

from interception.adapters import file_context
from interception.assess import assess
from interception.cli import install


def test_assessment_evidence_not_false_certainty(tmp_path):
    source = 'from openai import OpenAI\nclient = OpenAI()\nclient.chat.completions.create(model="x", messages=[])\n# checkpoint\n'
    (tmp_path / "agent.py").write_text(source)
    (tmp_path / ".env").write_text('OPENAI_API_KEY="DO-NOT-READ"')
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "ignored.js").write_text("anthropic")
    result = assess(tmp_path)
    assert result["providers"] == ["openai"]
    assert result["checkpoint_support"] == "UNVERIFIED"
    assert result["call_sites"][0]["line"] == 3
    assert "DO-NOT-READ" not in json.dumps(result)
    assert (tmp_path / "agent.py").read_text() == source


def test_install_idempotent_and_no_source_rewrite(tmp_path):
    (tmp_path / "agent.py").write_text("print('hi')")
    install(tmp_path)
    first = (tmp_path / ".inference_bridge" / "bridge.toml").read_text()
    install(tmp_path)
    assert (tmp_path / ".inference_bridge" / "bridge.toml").read_text() == first
    assert (tmp_path / "agent.py").read_text() == "print('hi')"


def test_context_boundaries(tmp_path):
    (tmp_path / "agent.py").write_text("hello")
    assert file_context(tmp_path, ["agent.py"])["relevant_files"][0]["content"] == "hello"
    with pytest.raises(ValueError):
        file_context(tmp_path, ["../escape"])
    with pytest.raises(ValueError):
        file_context(tmp_path, [".env"])
    with pytest.raises(ValueError):
        file_context(tmp_path, ["agent.py"], max_bytes=2)
