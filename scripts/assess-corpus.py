"""Assess local, pinned checkouts without installing or executing upstream code."""

import argparse
import json
from pathlib import Path
import subprocess

from interception.assess import assess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Directory containing owner__repository checkouts")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = Path(__file__).resolve().parents[1] / "docs/compatibility/corpus.json"
    results = []
    for item in json.loads(manifest.read_text()):
        path = args.root / item["repository"].replace("/", "__")
        sha = subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"], text=True
        ).strip()
        if sha != item["sha"]:
            raise ValueError(f"Revision differs from corpus pin: {item['repository']}")
        result = assess(path)
        results.append(
            {
                **item,
                **{
                    key: result[key]
                    for key in (
                        "assessment_version",
                        "files_scanned",
                        "scan_complete_within_scope",
                        "recommended_interception",
                        "inference_boundaries",
                        "checkpoint_support",
                        "providers",
                        "frameworks",
                        "skipped",
                    )
                },
                "boundary_candidate_count": len(result["call_sites"]),
            }
        )
        print(item["repository"], result["recommended_interception"], flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()
