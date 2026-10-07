"""Report/check/explicitly acknowledge native Full placement incidents."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

from .store import ROOT, acknowledge, check_review_gate, record_failure, report_directory


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", help="Overrides NADOC_PLACEMENT_REPORT_DIR")
    commands = parser.add_subparsers(dest="command", required=True)
    record = commands.add_parser("record")
    record.add_argument("--input", default="-", help="JSON input file, or stdin")
    commands.add_parser("check")
    imports = commands.add_parser("apply-reviews")
    imports.add_argument("--from-directory", default=str(ROOT / "tools/native_placement_audit/reviews"))
    review = commands.add_parser("acknowledge")
    review.add_argument("incident_id")
    review.add_argument("--reviewer", required=True)
    review.add_argument("--review", required=True, help="Completed review JSON, see docs/native_placement_review.md")
    review.add_argument("--export-review", help="Export signed-by-name/hash review record for CI's restored ledger")
    args = parser.parse_args(argv)
    try:
        if args.command == "record":
            payload = json.loads(sys.stdin.read() if args.input == "-" else Path(args.input).read_text())
            print(json.dumps(record_failure(payload, args.directory)))
        elif args.command == "acknowledge":
            acknowledge(args.incident_id, reviewer=args.reviewer,
                        review=json.loads(Path(args.review).read_text()), directory=args.directory)
            if args.export_review:
                output = Path(args.export_review)
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes((report_directory(args.directory) / "incidents" / args.incident_id / "review.json").read_bytes())
            print("Explicit review recorded; other unresolved incidents remain gated.")
        elif args.command == "apply-reviews":
            for path in sorted(Path(args.from_directory).glob("*.json")):
                review = json.loads(path.read_text())
                incident_id = review["incident_id"]
                # Never interpret arbitrary manifest paths outside the incident root.
                import re
                if not re.fullmatch(r"[0-9]{8}T[0-9]{6}-[0-9a-f]{12}", incident_id):
                    raise ValueError("Invalid incident ID in review manifest")
                target = report_directory(args.directory) / "incidents" / incident_id
                if not (target / "report.json").exists():
                    continue  # Other CI job/branch owns this incident.
                if hashlib.sha256((target / "report.json").read_bytes()).hexdigest() != review["report_sha256"]:
                    raise ValueError("Review does not match the immutable incident report")
                if not (target / "review.json").exists():
                    acknowledge(incident_id, reviewer=review["reviewer"], review=review["review"], directory=args.directory)
            print("Explicit review manifests applied")
        else:
            pending = check_review_gate(args.directory)
            if pending:
                print("NATIVE FULL PLACEMENT: REVIEW REQUIRED", file=sys.stderr)
                print(json.dumps(pending, indent=2), file=sys.stderr)
                return 2
            print("Native Full placement review gate: clear")
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Native placement review gate failed closed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
