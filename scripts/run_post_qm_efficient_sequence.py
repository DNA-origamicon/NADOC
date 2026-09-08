#!/usr/bin/env python3
"""Resume the efficient TT-CPD study sequence after all fixed-geometry QM completes.

All generated scientific artifacts live under the caller-supplied Archive root.  The
script is idempotent: passed KIMMDY outputs are reused, while the shortlist and pilot
plan are rebuilt atomically from their hash-audited inputs.  It never promotes candidate
parameters, mutates a NADOC design, or substitutes reactant thymine for a product.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.kimmdy_analysis import (  # noqa: E402
    analyze_kimmdy_trajectory,
    write_kimmdy_outputs,
)
from backend.core.models import Design  # noqa: E402
from backend.core.photoproduct_registry import (  # noqa: E402
    photoproduct_capabilities,
)
from experiments.exp60_extra_vs_native_photoproducts.run import (  # noqa: E402
    _pair_class,
    _resolve_cases,
    _near_insert_keys,
)

PRODUCTS = (
    "tt-cpd-cis-syn",
    "tt-cpd-cis-syn-ii",
    "tt-cpd-trans-syn-i",
    "tt-cpd-trans-syn-ii",
    "tt-cpd-cis-anti-i",
    "tt-cpd-cis-anti-ii",
    "tt-cpd-trans-anti-i",
    "tt-cpd-trans-anti-ii",
)
CONFORMERS = ("001", "002", "003", "004")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": _sha256(path)}


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n")
    temporary.replace(path)


def _under_storage(path: Path, storage_root: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(storage_root.resolve())
    except ValueError as exc:
        raise ValueError(f"generated path is outside Archive storage: {resolved}") from exc
    return resolved


def validate_qm_completion(queue_report: Path, qm_root: Path) -> dict[str, Any]:
    """Require the queue receipt and every product/conformer batch receipt."""
    if not queue_report.is_file():
        raise RuntimeError(f"QM queue completion report is absent: {queue_report}")
    queue = json.loads(queue_report.read_text())
    if queue.get("status") != "passed":
        raise RuntimeError("QM queue report is not a passed fixed-geometry queue receipt")

    if queue.get("schema") == "nadoc.photoproduct-all-form-response-completion.v1":
        records = queue.get("batches") or []
        expected = {
            (product, f"conformer-{conformer}")
            for product in PRODUCTS
            for conformer in CONFORMERS
        }
        observed = {
            (record.get("product_id"), record.get("conformer_id"))
            for record in records
        }
        if (
            queue.get("simulation_ready") is not False
            or queue.get("gate_effect") != "none"
            or queue.get("product_count") != len(PRODUCTS)
            or queue.get("conformer_count") != len(expected)
            or queue.get("task_count") != 211 * len(expected)
            or len(records) != len(expected)
            or observed != expected
        ):
            raise RuntimeError("all-form QM completion receipt is incomplete or malformed")
        reports = []
        for record in records:
            source = record.get("batch_report") or {}
            path = Path(str(source.get("path") or "")).resolve()
            try:
                path.relative_to(qm_root.resolve())
            except ValueError as exc:
                raise RuntimeError(f"QM batch receipt escapes the selected root: {path}") from exc
            if not path.is_file() or _sha256(path) != source.get("sha256"):
                raise RuntimeError(f"QM batch receipt is absent or hash-mismatched: {path}")
            payload = json.loads(path.read_text())
            if (
                payload.get("schema")
                != "nadoc.photoproduct-local-fixed-hessian-batch.v1"
                or payload.get("status") != "passed"
                or payload.get("simulation_ready") is not False
                or payload.get("gate_effect") != "none"
                or payload.get("product_id") != record.get("product_id")
                or payload.get("conformer_id") != record.get("conformer_id")
                or payload.get("task_count") != record.get("task_count")
            ):
                raise RuntimeError(
                    f"QM batch receipt is not passed or has stale identity: {path}"
                )
            reports.append(_source(path))
        return {
            "queue_report": _source(queue_report),
            "batch_count": len(reports),
            "batches": reports,
        }

    if queue.get("schema") != "nadoc.photoproduct-local-response-queue.v1":
        raise RuntimeError("QM queue report has an unsupported schema")

    reports = []
    for product in PRODUCTS:
        for conformer in CONFORMERS:
            path = qm_root / product / f"conformer-{conformer}" / "local-batch-report-v1.json"
            # The canonical campaign predates the remaining-isomer v1 filenames.
            if product == "tt-cpd-cis-syn" and not path.is_file():
                path = path.with_name("local-batch-report-v2.json")
            if not path.is_file():
                raise RuntimeError(f"missing QM batch receipt: {path}")
            payload = json.loads(path.read_text())
            if (
                payload.get("schema") != "nadoc.photoproduct-local-fixed-hessian-batch.v1"
                or payload.get("status") != "passed"
                or payload.get("product_id") != product
                or payload.get("conformer_id") != f"conformer-{conformer}"
            ):
                raise RuntimeError(f"QM batch receipt is not passed or has stale identity: {path}")
            reports.append(_source(path))
    return {
        "queue_report": _source(queue_report),
        "batch_count": len(reports),
        "batches": reports,
    }


def _analysis_passed(path: Path, job_id: str) -> bool:
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    return (
        payload.get("schema") == "nadoc.kimmdy-analysis.v1"
        and payload.get("pair_mode") == "all-tt"
        and payload.get("pair_scope") == "all"
        and payload.get("post_qm_sequence", {}).get("job_id") == job_id
        and payload.get("screen", {}).get("truncated") is False
    )


def run_all_pair_analysis(output_root: Path, max_frames: int) -> list[dict[str, Any]]:
    """Step 2: analyse all T-T pairs, retaining both strand relationships."""
    records = []
    for case in _resolve_cases():
        out = output_root / "all_pair_analysis" / case["job_id"]
        summary = out / "summary.json"
        reused = _analysis_passed(summary, case["job_id"])
        if not reused:
            design = Design.model_validate_json(case["design"].read_text())
            report, series = analyze_kimmdy_trajectory(
                case["topology"],
                case["dcds"],
                design,
                pair_mode="all-tt",
                pair_scope="all",
                screen_cutoff_ang=6.0,
                max_candidates=100_000,
                max_frames=max_frames,
                rate_model="periodic",
            )
            if report.get("screen", {}).get("truncated"):
                raise RuntimeError(f"all-pair candidate screen truncated for {case['job_id']}")
            report["post_qm_sequence"] = {
                "job_id": case["job_id"],
                "family": case["family"],
                "arrangement": case["arrangement"],
                "lineage_id": case["lineage_id"],
                "design": str(case["design"].resolve()),
                "design_source": case["design_source"],
            }
            write_kimmdy_outputs(report, series, out)
        records.append({
            "job_id": case["job_id"],
            "summary": _source(summary),
            "reused": reused,
        })
    return records


def stable_base_key(identity: dict[str, Any]) -> str:
    kind = identity.get("kind")
    if kind == "crossover_insert":
        return f"__xb__:{identity['crossover_id']}:{int(identity['extra_base_k'])}"
    if kind != "base":
        raise ValueError(f"unsupported KIMMDY design identity kind: {kind!r}")
    key = f"{identity['helix_id']}:{int(identity['bp_index'])}:{str(identity['direction']).upper()}"
    copy = int(identity.get("copy_k", 0) or 0)
    return f"{key}:{copy}" if copy else key


def _priority_class(pair: dict[str, Any], near: set[tuple[str, int, str]]) -> str:
    relationship = "intrastrand" if pair.get("same_strand") else "interstrand"
    return f"{relationship}:{_pair_class(pair, near)}"


def build_shortlist(analysis_records: list[dict[str, Any]], output_root: Path) -> dict[str, Any]:
    """Step 3: rank stable-identity sites without calling propensity a yield."""
    near_by_family = _near_insert_keys()
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    all_rows = []
    for record in analysis_records:
        summary_path = Path(record["summary"]["path"])
        report = json.loads(summary_path.read_text())
        context = report["post_qm_sequence"]
        near = near_by_family[context["family"]]
        for pair in report["pairs"]:
            if pair.get("screen_min_midpoint_ang") is None:
                continue
            try:
                base_keys = [
                    stable_base_key(pair[side]["design_identity"])
                    for side in ("site_a", "site_b")
                ]
            except (KeyError, TypeError, ValueError):
                continue
            row = {
                "job_id": context["job_id"],
                "family": context["family"],
                "arrangement": context["arrangement"],
                "lineage_id": context["lineage_id"],
                "priority_class": _priority_class(pair, near),
                "base_keys": base_keys,
                "intended_weld": bool(pair.get("intended_weld")),
                "mean_geometric_propensity": float(pair["periodic_propensity_mean"]),
                "reactive_corner_pct": float(pair["pct_reactive_corner"]),
                "minimum_midpoint_distance_nm": float(pair["d_mid_min_nm"]),
                "representative_frame": pair["representative_max_propensity"],
            }
            all_rows.append(row)
            key = (row["family"], row["arrangement"], row["priority_class"])
            grouped.setdefault(key, []).append(row)

    representatives = []
    for key, rows in sorted(grouped.items()):
        rows.sort(
            key=lambda row: (
                -row["mean_geometric_propensity"],
                -row["reactive_corner_pct"],
                tuple(row["base_keys"]),
            )
        )
        representatives.append({**rows[0], "available_pair_count": len(rows)})

    # The causal pilot focuses on the only family with matched 0x/1x/2x trajectories.
    primary = [
        row for row in representatives
        if row["family"] == "24hb"
        and row["arrangement"] in {"1-1", "2-2"}
        and (
            row["priority_class"] == "interstrand:designed_extra_extra"
            or row["priority_class"].startswith("intrastrand:")
            and ("extra_extra" in row["priority_class"] or "extra_native" in row["priority_class"])
        )
    ]
    payload = {
        "schema": "nadoc.tt-cpd-efficient-shortlist.v1",
        "status": "passed_geometric_shortlist_not_yield_prediction",
        "created_at": _now(),
        "analysis_only": True,
        "interpretation": (
            "Ranks reactant-state geometric opportunity. It does not infer absolute yield, "
            "stability, or a TT-CPD stereoisomer."
        ),
        "analysis_sources": [record["summary"] for record in analysis_records],
        "representatives": representatives,
        "primary_pilot_sites": primary,
        "all_screened_pair_count": len(all_rows),
    }
    output = output_root / "priority_shortlist.json"
    _write_json_atomic(output, payload)
    return payload


def build_pilot_plan(shortlist: dict[str, Any], output_root: Path, registry: Path) -> dict[str, Any]:
    """Step 4: preregister the small pilot matrix and expose its hard launch gates."""
    capabilities = photoproduct_capabilities(registry)
    ready = [row for row in capabilities["products"] if row["simulation_ready"]]
    sites = shortlist["primary_pilot_sites"]
    arms = []
    for arrangement in ("0-0", "1-1", "2-2"):
        arms.append({
            "family": "24hb",
            "arrangement": arrangement,
            "state": "reactant",
            "replicas": 3,
            "duration_ns_per_replica": 20,
            "timestep_fs": 2.0,
        })
    for site in sites:
        arms.append({
            "family": "24hb",
            "arrangement": site["arrangement"],
            "state": "product",
            "site_class": site["priority_class"],
            "base_keys": site["base_keys"],
            "stereoisomer": None,
            "replicas": 3,
            "duration_ns_per_replica": 20,
            "timestep_fs": 2.0,
        })
    blockers = []
    if not sites:
        blockers.append("no screened 24hb interstrand/intrastrand extra-base pilot sites")
    if not ready:
        blockers.append("no TT-CPD stereoisomer has released, hash-verified simulation assets")
    blockers.append(
        "isomer-resolved accessibility must assign a supported stereoisomer to each product arm"
    )
    payload = {
        "schema": "nadoc.tt-cpd-efficient-pilot-plan.v1",
        "status": "blocked_fail_closed" if blockers else "ready_to_package",
        "created_at": _now(),
        "automatic_trajectory_conversion": False,
        "protocol": {
            "pilot_duration_ns": 20,
            "replicas": 3,
            "ordinary_mass_timestep_fs": 2.0,
            "extension_rule": "extend selected arms toward 250 ns only after pilot discrimination",
        },
        "arms": arms,
        "ready_products": [row["id"] for row in ready],
        "blockers": blockers,
        "launch_effect": "none",
    }
    _write_json_atomic(output_root / "pilot_plan.json", payload)
    return payload


def run(args: argparse.Namespace) -> dict[str, Any]:
    storage = args.storage_root.resolve()
    output_root = _under_storage(args.output_root, storage)
    qm_root = _under_storage(args.qm_root, storage)
    queue_report = _under_storage(args.queue_report, storage)
    completion = validate_qm_completion(queue_report, qm_root)
    analyses = run_all_pair_analysis(output_root, args.max_frames)
    shortlist = build_shortlist(analyses, output_root)
    pilot = build_pilot_plan(shortlist, output_root, args.registry)
    report = {
        "schema": "nadoc.tt-cpd-efficient-post-qm-sequence.v1",
        "status": "waiting_at_scientific_gate" if pilot["blockers"] else "ready_to_package_pilots",
        "updated_at": _now(),
        "storage_root": str(storage),
        "qm_completion": completion,
        "steps": {
            "2_all_pair_analysis": {"status": "passed", "jobs": analyses},
            "3_priority_shortlist": {
                "status": shortlist["status"],
                "artifact": _source(output_root / "priority_shortlist.json"),
            },
            "4_targeted_pilots": {
                "status": pilot["status"],
                "artifact": _source(output_root / "pilot_plan.json"),
                "blockers": pilot["blockers"],
            },
        },
    }
    _write_json_atomic(output_root / "post_qm_sequence_status.json", report)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-root", type=Path, required=True)
    parser.add_argument("--qm-root", type=Path, required=True)
    parser.add_argument("--queue-report", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--max-frames", type=int, default=500)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.max_frames < 1:
        raise ValueError("--max-frames must be positive")
    print(json.dumps(run(args), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
