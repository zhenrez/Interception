"""Compatibility entry point: python inference_bridge.py <command> <project>."""

from interception.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
