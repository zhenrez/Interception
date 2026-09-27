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


def test_mentions_and_completion_helpers_do_not_establish_inference(tmp_path):
    (tmp_path / "helpers.py").write_text(
        'MODEL_LABEL = "openai"\ncompletion_evidence_resolver()\nplan_completion_receipt()\ncompletion()\n'
    )
    result = assess(tmp_path)
    assert result["call_sites"] == []
    assert result["recommended_interception"] == "no_inference_boundary_detected"


@pytest.mark.parametrize(
    "name,source,expected",
    [
        ("auto-loop.sh", 'claude -p "$prompt"\n', "cli_adapter_required"),
        ("driver.ps1", 'codex exec "do task"\n', "cli_adapter_required"),
        (
            "provider.ts",
            'groq.chat.completions.create({model: "manual"});',
            "openai_compatible_proxy_candidate",
        ),
        (
            "provider.py",
            'urlopen(Request(f"{base}/chat/completions", data=body))',
            "openai_compatible_proxy_candidate",
        ),
        (
            "provider.ts",
            'ai.models.generateContent({model: "gemini"});',
            "protocol_adapter_required",
        ),
        (
            "provider.py",
            'from litellm import completion as generate\ngenerate(model="x")',
            "openai_compatible_proxy_candidate",
        ),
    ],
)
def test_boundaries_across_runtime_types(tmp_path, name, source, expected):
    (tmp_path / name).write_text(source)
    result = assess(tmp_path)
    assert result["files_scanned"] == 1
    assert result["recommended_interception"] == expected


def test_example_provider_does_not_classify_project_as_proxy_compatible(tmp_path):
    (tmp_path / "examples").mkdir()
    (tmp_path / "examples/client.py").write_text("client.chat.completions.create()")
    result = assess(tmp_path)
    assert result["call_sites"][0]["scope"] == "TEST_OR_EXAMPLE"
    assert result["recommended_interception"] == "no_inference_boundary_detected"


def test_application_message_routes_are_not_native_model_protocols(tmp_path):
    (tmp_path / "chat.ts").write_text('fetch("/api/messages");\n')
    assert assess(tmp_path)["call_sites"] == []


def test_mixed_routes_require_explicit_selection(tmp_path):
    (tmp_path / "provider.py").write_text(
        "client.chat.completions.create()\nclient.responses.create()\n"
    )
    assert (
        assess(tmp_path)["recommended_interception"] == "mixed_boundaries_require_route_selection"
    )
