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


def test_documentation_reference_does_not_imply_proxy_compatibility(tmp_path):
    (tmp_path / "adapter.py").write_text(
        '"""Projects config to Codex. See https://developers.openai.com/codex/subagents.\n'
        'Maps aliases to OpenAI model IDs.\n"""\n'
        'MODEL_ALIASES = {"high": "gpt-example"}\n',
        encoding="utf-8",
    )
    result = assess(tmp_path)
    assert result["recommended_interception"] != "openai_compatible_proxy_candidate"
    assert result["inference_boundary_owner"] == "UNKNOWN"
    assert result["continuation_strategy"] == "UNVERIFIED"


def test_real_chat_completions_call_is_proxy_candidate_but_resume_stays_unverified(tmp_path):
    (tmp_path / "agent.py").write_text(
        "from openai import OpenAI\n"
        'client = OpenAI(base_url="http://provider")\n'
        'answer = client.chat.completions.create(model="x", messages=[])\n',
        encoding="utf-8",
    )
    result = assess(tmp_path)
    assert result["recommended_interception"] == "openai_compatible_proxy_candidate"
    assert result["inference_boundary_owner"] == "PROJECT"
    assert result["direct_inference_protocol"] == "OPENAI_CHAT_COMPLETIONS"
    assert result["continuation_strategy"] == "UNVERIFIED"
    assert "SYNCHRONOUS_HOLD" in result["continuation_candidates"]


def test_host_runtime_marker_is_candidate_not_proof(tmp_path):
    (tmp_path / ".codex").mkdir()
    (tmp_path / "project.py").write_text("print('no model call')\n", encoding="utf-8")
    result = assess(tmp_path)
    assert result["inference_boundary_owner"] == "HOST_RUNTIME_CANDIDATE"
    assert result["recommended_interception"] == "host_runtime_adapter_candidate"
    assert result["continuation_strategy"] == "UNVERIFIED"
    assert result["continuation_candidates"] == ["HOST_RUNTIME_RESUME"]


def test_mcp_tool_server_marks_external_client_boundary(tmp_path):
    (tmp_path / "server.ts").write_text(
        'import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";\n'
        'const server = new McpServer({ name: "skills", version: "1" });\n'
        'server.tool("think", "Return a protocol", {}, async () => ({\n'
        '  content: [{ type: "text", text: "Execute this protocol" }]\n'
        '}));\n',
        encoding="utf-8",
    )
    result = assess(tmp_path)
    assert result["inference_boundary_owner"] == "EXTERNAL_CLIENT_CANDIDATE"
    assert result["protocol_surfaces"] == ["MCP_SERVER"]
    assert result["recommended_interception"] == "mcp_host_adapter_candidate"
    assert result["continuation_strategy"] == "UNVERIFIED"
