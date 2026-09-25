import argparse
import json
import os
import sys
import time

from ..bridge import Bridge
from ..github_relay import GitHubRelay, automation_spec
from .gmail_wakeup import configure, disable, notify


def _work_spec(relay):
    spec = automation_spec(relay.config)
    return {
        "trigger": {
            "connector": "gmail",
            "condition": {
                "sender": "Use the configured Gmail sender address",
                "subject_starts_with": "Interception inference ready:",
            },
        },
        "prompt": spec["prompt"],
        "note": (
            "Create this as a Gmail event-triggered ChatGPT Work task. "
            "The Gmail message is wake-only; GitHub remains the authoritative mailbox."
        ),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Temporary Gmail wake-up sandbox")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("configure")
    p.add_argument("project")
    p.add_argument("sender")
    p.add_argument("recipient")

    p = sub.add_parser("disable")
    p.add_argument("project")

    p = sub.add_parser("notify")
    p.add_argument("project")

    p = sub.add_parser("watch")
    p.add_argument("project")
    p.add_argument("--interval", type=int, default=30)

    p = sub.add_parser("work-spec")
    p.add_argument("project")

    args = parser.parse_args(argv)

    try:
        if args.command == "configure":
            print(json.dumps(configure(Bridge(args.project), args.sender, args.recipient), indent=2))
            return 0
        if args.command == "disable":
            disable(Bridge(args.project))
            print("Temporary Gmail sandbox disabled.")
            return 0

        relay = GitHubRelay(args.project)

        if args.command == "work-spec":
            print(json.dumps(_work_spec(relay), indent=2))
            return 0

        if args.command == "notify":
            result = relay.sync()
            sent = notify(relay)
            print(json.dumps({"relay": result, "email_sent": sent}, indent=2))
            return 0

        if args.interval < 10:
            raise ValueError("Interval must be at least 10 seconds")

        while True:
            try:
                result = relay.sync()
                sent = notify(relay)
                print(json.dumps({"relay": result, "email_sent": sent}), flush=True)
            except Exception as exc:
                print(f"Gmail sandbox delayed: {exc}", file=sys.stderr, flush=True)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("Stopped. Pending requests are retained.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Gmail sandbox: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
