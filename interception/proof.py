"""A real pinned Prompt Evolver judging call through the local inference bridge."""

import uuid

from ._vendor.prompt_evolver_llm import LLMClient
from .adapters import connect_prompt_evolver
from .bridge import Bridge
from .files import write_json


def run(project, *, stop=None):
    bridge = Bridge(project)
    run_id = uuid.uuid4().hex
    client = connect_prompt_evolver(LLMClient(), bridge, run_id=run_id, stop=stop)
    score = client.judge_score(
        "This is a transport proof, not an assessment of project quality. "
        "Return only the integer result of 2 + 2 (a number between 1 and 5)."
    )
    rid = client._interception_request_id
    content = bridge.result(rid)["content"]
    # Upstream judge_score defaults to 3 for malformed text. Never count that as proof.
    if content.strip() != "4" or score != 4:
        raise ValueError(
            "Caller resumed, but the answer did not meet the proof criterion: exactly 4"
        )
    receipt = {
        "status": "RESUMED",
        "run_id": run_id,
        "request_id": rid,
        "score": score,
        "target": "jmoles/prompt-evolver LLMClient.judge_score",
        "target_revision": "6061b34a843b86ef2b1f08bc2f7060c649277e18",
        "transport": "local CATCH/RETURN",
        "external_wakeup_verified": False,
        "full_evolution_verified": False,
    }
    write_json(bridge.home / "proofs" / f"{run_id}.json", receipt)
    return receipt
