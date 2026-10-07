"""Run a native placement check with persistent failure evidence and review gate."""
import argparse
import json
import shlex
import subprocess
import sys

from .store import check_review_gate, record_failure


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-id", required=True)
    parser.add_argument("--source-file", action="append", default=[])
    parser.add_argument("--directory")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("A test command is required after --")
    try:
        result = subprocess.run(command, capture_output=True, text=True, errors="replace")
        stdout, stderr, returncode = result.stdout, result.stderr, result.returncode
    except OSError as error:
        stdout, stderr, returncode = "", str(error), 127
    print(stdout, end="")
    print(stderr, end="", file=sys.stderr)
    try:
        if returncode not in (0, 77):
            payload = {"test_id": args.test_id, "phase": "native-command",
                "exception": f"Native placement command exited with status {returncode}",
                "evidence": {"command": command, "returncode": returncode,
                             "stdout": stdout, "stderr": stderr},
                "reproduce_command": shlex.join(command)}
            if args.source_file:
                payload["source_files"] = args.source_file
            report = record_failure(payload, args.directory)
            print(f"NATIVE FULL PLACEMENT: REVIEW REQUIRED — {report['html']}", file=sys.stderr)
        pending = check_review_gate(args.directory)
        if pending:
            print("NATIVE FULL PLACEMENT: REVIEW REQUIRED", file=sys.stderr)
            print(json.dumps(pending, indent=2), file=sys.stderr)
            return 2
    except Exception as error:
        print(f"Native placement review gate failed closed: {error}", file=sys.stderr)
        return 2
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
