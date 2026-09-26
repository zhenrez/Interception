import argparse
import json
from pathlib import Path
import secrets
import sys
import time
import tomllib

from .assess import assess
from .bridge import Bridge
from .files import atomic_write, loads, write_json
from .server import BridgeServer


def install(project, port=8742):
    assessment = assess(project)
    bridge = Bridge(project)
    config = bridge.home / "bridge.toml"
    if not config.exists():
        atomic_write(config, f'version = 1\nport = {port}\ntoken = "{secrets.token_urlsafe(32)}"\n')
    settings = load_config(bridge)
    write_json(
        bridge.home / "connection.json",
        {
            "base_url": f"http://127.0.0.1:{settings['port']}/v1",
            "api_key": settings["token"],
            "timeout": None,
            "max_retries": 0,
            "note": "Local-only token. Apply to the project's inference client; no provider API key needed.",
        },
    )
    return assessment


def load_config(bridge):
    path = bridge.home / "bridge.toml"
    if not path.exists():
        raise ValueError("Run install first (or open the desktop launcher)")
    config = tomllib.loads(path.read_text(encoding="utf-8"))
    if (
        config.get("version") != 1
        or not isinstance(config.get("token"), str)
        or len(config["token"]) < 16
    ):
        raise ValueError("Invalid bridge.toml version/token")
    if type(config.get("port")) is not int or not 1 <= config["port"] <= 65535:
        raise ValueError("Invalid bridge.toml port")
    return config


def import_return(bridge, source):
    path = Path(source)
    with path.open("rb") as stream:
        raw = stream.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("RETURN exceeds 8 MiB")
    returned = loads(raw.decode("utf-8-sig"))
    if not isinstance(returned, dict):
        raise ValueError("RETURN must be an object")
    # Validate original envelope before canonical publication.
    from .contracts import validate_return

    request_id = returned.get("request_id")
    if not isinstance(request_id, str):
        raise ValueError("RETURN requires a request_id")
    validate_return(bridge.get(request_id)["packet"], returned)
    return bridge.write_return(request_id, returned["response"])


def main(argv=None):
    parser = argparse.ArgumentParser(description="Interception — durable manual inference bridge")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("relay-configure", "relay-sync", "relay-watch", "relay-automation"):
        command = sub.add_parser(name)
        command.add_argument("project")
        if name == "relay-configure":
            command.add_argument("repository")
            command.add_argument("pr_number", type=int)
            command.add_argument("--return-branch", default="interception-returns")
        if name == "relay-watch":
            command.add_argument("--interval", type=int, default=30)
    for name in ("run-node", "resume-node"):
        command = sub.add_parser(name)
        command.add_argument("project")
        command.add_argument("run_id")
        if name == "run-node":
            command.add_argument("script")
    for name in (
        "assess",
        "install",
        "serve",
        "status",
        "watch",
        "batch",
        "resume",
        "submit",
        "import-return",
        "desktop",
        "demo",
        "proof",
    ):
        command = sub.add_parser(name)
        command.add_argument("project", nargs="?" if name == "desktop" else None, default=None)
        if name in {"install", "serve"}:
            command.add_argument("--port", type=int, default=None)
        if name == "batch":
            command.add_argument("--output")
        if name == "resume":
            command.add_argument("request_id")
        if name == "submit":
            command.add_argument("request_file")
            command.add_argument("--key")
        if name == "import-return":
            command.add_argument("file")
    args = parser.parse_args(argv)
    try:
        if args.command.startswith("relay-"):
            from .github_relay import GitHubRelay, automation_spec, configure

            if args.command == "relay-configure":
                print(
                    json.dumps(
                        configure(
                            args.project,
                            args.repository,
                            args.pr_number,
                            return_branch=args.return_branch,
                        ),
                        indent=2,
                    )
                )
            else:
                relay = GitHubRelay(args.project)
                if args.command == "relay-sync":
                    print(json.dumps(relay.sync(), indent=2))
                elif args.command == "relay-watch":
                    relay.watch(args.interval)
                else:
                    print(json.dumps(automation_spec(relay.config), indent=2))
            return 0
        if args.command in {"run-node", "resume-node"}:
            from .nodes import supervise

            state = supervise(args.project, args.run_id, getattr(args, "script", None))
            print(f"Node {state['run_id']}: {state['state']}")
            return 0
        if args.command == "desktop":
            from .desktop import launch

            launch(args.project)
            return 0
        if args.command == "assess":
            print(json.dumps(assess(args.project), indent=2))
            return 0
        if args.command == "install":
            result = install(args.project, args.port or 8742)
            print(
                f"Installed mailbox and configuration. Route candidate: {result['recommended_interception']}."
            )
            print("Source unchanged. Connection settings: .inference_bridge/connection.json")
            return 0
        bridge = Bridge(args.project)
        if args.command == "proof":
            from .proof import run

            print(
                "Prompt Evolver is waiting. Export CATCH, obtain RETURN, then import it.",
                flush=True,
            )
            print(json.dumps(run(args.project), indent=2))
        elif args.command == "serve":
            settings = load_config(bridge)
            with BridgeServer(
                bridge, port=args.port or settings["port"], token=settings["token"]
            ) as server:
                print(
                    f"Interception listening at http://127.0.0.1:{server.server_port}/v1",
                    flush=True,
                )
                print(f"Waiting for RETURN files in {bridge.returns}", flush=True)
                try:
                    server.serve_forever()
                except KeyboardInterrupt:
                    pass
        elif args.command == "status":
            bridge.ingest()
            print(
                json.dumps(
                    {"requests": bridge.requests(), "returns": bridge.diagnostics()}, indent=2
                )
            )
        elif args.command == "watch":
            while True:
                for outcome in bridge.ingest():
                    print(json.dumps(outcome), flush=True)
                time.sleep(0.5)
        elif args.command == "batch":
            bridge.ingest()
            print(bridge.export_batch(args.output))
        elif args.command == "resume":
            print(json.dumps(bridge.wait(args.request_id), ensure_ascii=False, indent=2))
        elif args.command == "submit":
            path = Path(args.request_file)
            if path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("Request exceeds 8 MiB")
            print(bridge.submit(loads(path.read_text(encoding="utf-8")), key=args.key))
        elif args.command == "import-return":
            print(import_return(bridge, args.file))
        elif args.command == "demo":
            print(
                bridge.submit(
                    {
                        "model": "manual",
                        "messages": [
                            {
                                "role": "user",
                                "content": "Reply with one short sentence confirming that the manual inference mailbox works.",
                            }
                        ],
                    },
                    metadata={
                        "caller": {"agent": "mailbox_demo", "workflow": "demo", "step": "greeting"}
                    },
                )
            )
            print(bridge.export_batch())
        return 0
    except KeyboardInterrupt:
        print("Stopped. Pending requests are retained.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Interception: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
