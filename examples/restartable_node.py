"""Explicitly restart-safe node for `interception run-node`.

The supervisor re-enters this entire file after a RETURN or restart. Keep effects
idempotent and use a stable run/step key. Do not catch InferencePending here.
"""

import os
from pathlib import Path

from interception import Bridge
from interception.files import atomic_write

project = Path(os.environ["INTERCEPTION_PROJECT"])
run_id = os.environ["INTERCEPTION_RUN_ID"]
bridge = Bridge(project)
answer = bridge.require(
    {
        "model": "manual",
        "messages": [
            {"role": "user", "content": "Write a three-step plan for a community garden."}
        ],
    },
    key=f"{run_id}:garden-plan",
    checkpoint={"run_id": run_id, "node": "garden-plan", "topic": "community garden"},
    metadata={"caller": {"workflow": run_id, "step": "garden-plan"}},
)
atomic_write(project / "garden-plan.txt", answer["content"])
print("Node resumed and wrote garden-plan.txt")
