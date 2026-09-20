"""Load a native part or assembly into a named NADOC backend document, without a browser.

Examples:
  python3 scripts/nadoc_load.py --api http://127.0.0.1:8020 --doc benchmark-a --file VoltronCoreArmV2.nadoc
  python3 scripts/nadoc_load.py --api http://127.0.0.1:8020 --doc benchmark-a --source /path/to/design.nadoc

--file uses the backend workspace. --source imports a local file's bytes, leaving
that source untouched. Assembly references must resolve in the backend workspace.
This prepares backend state; visual performance still requires a rendering browser.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


def load(api: str, doc: str, path: str, *, source: bool = False) -> dict:
    base = urlparse(api)
    if base.scheme != "http" or base.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Use the local backend's http://localhost or loopback URL")
    if not doc.strip() or doc == "__default__":
        raise ValueError("Choose an explicit document ID; the shared default is not a test document")
    suffix = Path(path).suffix.lower()
    if suffix not in {".nadoc", ".nass"}:
        raise ValueError("Native loading supports .nadoc parts and .nass assemblies")

    def request(method: str, route: str, body: dict | None = None) -> dict:
        req = Request(api.rstrip("/") + "/api" + route,
                      data=json.dumps(body).encode() if body is not None else None,
                      headers={"Content-Type": "application/json", "X-NADOC-Doc": doc}, method=method)
        with urlopen(req, timeout=240) as response:
            return json.load(response)

    if source:
        content = Path(path).expanduser().read_text()
        json.loads(content)  # fail before contacting the backend on malformed input
    elif suffix == ".nass":
        content = request("GET", "/library/content?path=" + quote(path, safe=""))["content"]
    if suffix == ".nass":
        result = request("POST", "/assembly/import", {"content": content})
        document = result.get("assembly") or {}
    elif source:
        result = request("POST", "/design/import", {"content": content})
        document = result.get("design") or {}
    else:
        result = request("POST", "/library/open-part", {"path": path, "name": Path(path).stem})
        document = result.get("design") or {}
    if not document.get("id"):
        raise ValueError("The backend did not return a loaded document")
    return {"doc": doc, "kind": "assembly" if suffix == ".nass" else "part",
            "id": document["id"], "name": document.get("metadata", {}).get("name", document.get("name")),
            "path": path, "source_import": source, "scope": "Backend document loaded; no rendering or simulation performed"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--doc", required=True)
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument("--file", help="Backend workspace-relative native path")
    sources.add_argument("--source", help="Local native file to import without changing the source")
    args = parser.parse_args()
    try:
        print(json.dumps(load(args.api, args.doc, args.source or args.file, source=bool(args.source)), indent=2))
    except HTTPError as error:
        print(f"Backend HTTP {error.code}: {error.read().decode()[:2000]}", file=sys.stderr)
        sys.exit(1)
    except (OSError, ValueError, KeyError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
