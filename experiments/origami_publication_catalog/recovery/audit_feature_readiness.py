"""Read retained recovery evidence without constructing or writing molecular designs.

Run from the repository root with ``.venv/bin/python -m
experiments.origami_publication_catalog.recovery.audit_feature_readiness``.
This is a readiness inventory, NOT a publication/replay certificate.
"""

import argparse
import ast
import hashlib
import json
from pathlib import Path

from backend.api.part_proof_commands import dependencies
from backend.core.part_dependencies import DependencyIndex


ROOT = Path(__file__).resolve().parents[3]
CASES = ("D007", "D008", "D005", "D006", "D021")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(evidence):
    cases = []
    for ident in CASES:
        report_path = evidence / f"{ident}_report.json"
        trace_path = evidence / f"{ident}_trace.json"
        report = json.loads(report_path.read_text())
        trace = json.loads(trace_path.read_text())
        source = ROOT / "experiments/origami_publication_catalog/assets/sources" / Path(report["source_pdf"]).name
        # Resolve old workstation paths against this checkout.
        saved = ROOT / "workspace/Image_Recovery_First5_20261102" / Path(report["nadoc"]).name
        cases.append({
            "id": ident,
            "source_sha256_matches": sha(source) == report["source_sha256"],
            "report_sha256": sha(report_path),
            "trace_sha256": sha(trace_path),
            "saved_design_exists": saved.is_file(),
            "saved_design_replay": "NOT_RUN: audit does not certify designs",
            "helix_count": len(trace["slice_coordinates"]),
            "strand_paths": len(trace.get("paths", [])),
            "unjoined_fragments": len(trace.get("fragments", [])),
            "insertion_sites": len(trace.get("insertions", [])),
            "insertions_outside_single_site_command_range": [
                entry for entry in trace.get("insertions", []) if entry[2] not in (-1, 0, 1)
            ],
            "assigned_sequences_historical": report.get("assigned_sequences", 0),
            "trace_contains_sequence_map": "seqmap" in trace,
            "publication_status": "AGENT_PROCESS_REQUIRED: native construction and replay not established",
        })

    # Probe dependency contracts only. No executor or model construction is called.
    # In particular, 'known' must NOT be mistaken for parameter validity.
    probes = [
        ("helix-add-at-cell", {"row": 0, "col": 0, "length_bp": 42,
                               "populate_strands": False, "_helix_id": "audit-helix"}),
        ("strand-add", {"_strand_id": "audit-strand", "strand_type": "scaffold",
                        "domains": [{"helix_id": "audit-helix", "start_bp": 0,
                                     "end_bp": 20, "direction": "forward"}]}),
        ("loop-skip-insert", {"helix_id": "audit-helix", "bp_index": 10, "delta": 144}),
        ("strand-sequence", {"strand_id": "audit-strand", "sequence": "A" * 21}),
    ]
    index = DependencyIndex()
    contracts = []
    for position, (kind, inputs) in enumerate(probes):
        contract = dependencies(kind, {"_proof_version": 1, **inputs})
        feature_id = f"probe-{position}"
        index.append(feature_id, contract)
        contracts.append({"kind": kind, "known": contract.known, "barrier": contract.barrier})

    scripts = []
    for name in ("recover_first5.py", "recover_pin_partial.py"):
        path = Path(__file__).with_name(name)
        tree = ast.parse(path.read_text())
        scripts.append({
            "path": str(path.relative_to(ROOT)), "sha256": sha(path),
            "direct_serialization_lines": sorted({node.lineno for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "model_dump_json"}),
            "calls_agent_publish": any(isinstance(node, ast.Call) and
                ((isinstance(node.func, ast.Name) and node.func.id == "publish") or
                 (isinstance(node.func, ast.Attribute) and node.func.attr == "publish"))
                for node in ast.walk(tree)),
        })
    return {"scope": "retained first-five image recovery readiness; no molecular construction",
            "cases": cases, "legacy_scripts": scripts,
            "dependency_probes": contracts, "dependency_index": index.as_dict(),
            "warning": "Known dependency contracts do not certify parameters, source evidence, or replay."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path,
                        default=ROOT / ".development-artifacts/image-recovery-first5-20261102")
    args = parser.parse_args()
    print(json.dumps(audit(args.evidence), indent=2))
