"""An SDK caller waiting normally on the bridge. Start `serve` first."""

import argparse
from interception.adapters import openai_client
from interception.bridge import Bridge
from interception.cli import load_config

parser = argparse.ArgumentParser()
parser.add_argument("project")
args = parser.parse_args()
settings = load_config(Bridge(args.project))
with openai_client(port=settings["port"], token=settings["token"]) as client:
    answer = client.chat.completions.create(
        model="manual",
        messages=[
            {"role": "user", "content": "Give me one useful next step for organizing my project."}
        ],
        extra_headers={"Idempotency-Key": "example-openai-run-001:plan"},
        extra_body={"bridge_context": {"caller": {"agent": "example", "step": "plan"}}},
    )
    print(answer.choices[0].message.content)
