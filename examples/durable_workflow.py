"""Run again after a return, even in a new process. No API key needed.

    python examples/durable_workflow.py /path/to/project

The stable key identifies one workflow node. Supply a NEW run ID for new work.
"""

import argparse
from pathlib import Path

from interception import Bridge, InferencePending
from interception.files import atomic_write


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    parser.add_argument("--run-id", default="example-001")
    args = parser.parse_args()
    bridge = Bridge(args.project)
    key = f"{args.run_id}:outline"
    # All continuation inputs are JSON and persisted with the request.
    checkpoint = {"run_id": args.run_id, "node": "outline", "topic": "a small community garden"}
    try:
        answer = bridge.require(
            {
                "model": "manual",
                "messages": [
                    {
                        "role": "user",
                        "content": f"Write a three-step plan for {checkpoint['topic']}.",
                    }
                ],
            },
            key=key,
            checkpoint=checkpoint,
            metadata={"caller": {"workflow": "garden", "step": "outline"}},
        )
    except InferencePending as pending:
        print(
            f"Safely suspended: {pending.request_id}. Export the batch, return the answer, then rerun."
        )
        return
    # Idempotent output; do not blindly replay external side effects.
    atomic_write(Path(args.project) / "garden-plan.txt", answer["content"])
    print("Resumed successfully. Wrote garden-plan.txt")


if __name__ == "__main__":
    main()
