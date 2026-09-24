"""Refresh portable CPD geometry illustrations without reloading archived studies."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.core.cpd_preview import attach_isomer_previews  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--snapshot", type=Path, default=ROOT / "frontend/public/cpd-progress.json"
    )
    args = parser.parse_args()
    payload = attach_isomer_previews(json.loads(args.snapshot.read_text()))
    args.snapshot.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"Updated {len(payload['isomers'])} isomer illustrations in {args.snapshot}")


if __name__ == "__main__":
    main()
