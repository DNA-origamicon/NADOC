#!/usr/bin/env python3
"""Evaluate whether mrDNA preconditioning improves NAMD starting geometry.

The metric here is deliberately practical: build the raw NADOC atomistic model,
build the mrDNA-preconditioned atomistic model from an mrDNA PSF/DCD pair, and
compare covalent bond-length outliers.  A model that still contains extreme
covalent stretches is not ready for an unrestrained NAMD launch, regardless of
how visually plausible the coarse relaxation looks.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from backend.core.atomistic import AtomisticModel, build_atomistic_model
from backend.core.md_precondition import (
    WORKFLOW_FLAG_NO_CROSSOVER_EXTRABASES_ONLY,
    assert_no_crossover_extrabases,
    build_model_from_override,
    crossover_extrabase_records,
)
from backend.core.models import Design
from backend.core.mrdna_bridge import nuc_pos_override_from_mrdna_coarse


def _load_design(path: Path) -> Design:
    return Design.model_validate(json.loads(path.read_text()))


def _atom_label(model: AtomisticModel, idx: int) -> str:
    atom = model.atoms[idx]
    return (
        f"{idx + 1}:{atom.chain_id}:{atom.seq_num}:{atom.residue}:{atom.name}:"
        f"{atom.helix_id}:{atom.bp_index}:{atom.direction}"
    )


def _bond_stats(model: AtomisticModel, *, top_n: int = 20) -> dict:
    rows: list[tuple[float, int, int]] = []
    for i, j in model.bonds:
        ai = model.atoms[i]
        aj = model.atoms[j]
        dx = ai.x - aj.x
        dy = ai.y - aj.y
        dz = ai.z - aj.z
        rows.append((math.sqrt(dx * dx + dy * dy + dz * dz), i, j))
    rows.sort(reverse=True, key=lambda row: row[0])
    lengths = [row[0] for row in rows]

    def count_over(threshold: float) -> int:
        return sum(1 for value in lengths if value > threshold)

    def quantile(q: float) -> float:
        if not lengths:
            return 0.0
        idx = min(len(lengths) - 1, max(0, int(round(q * (len(lengths) - 1)))))
        return sorted(lengths)[idx]

    return {
        "atoms": len(model.atoms),
        "bonds": len(model.bonds),
        "length_nm": {
            "min": min(lengths) if lengths else 0.0,
            "mean": statistics.fmean(lengths) if lengths else 0.0,
            "p95": quantile(0.95),
            "p99": quantile(0.99),
            "p999": quantile(0.999),
            "max": max(lengths) if lengths else 0.0,
        },
        "outlier_counts": {
            "gt_0p20_nm": count_over(0.20),
            "gt_0p25_nm": count_over(0.25),
            "gt_0p30_nm": count_over(0.30),
            "gt_0p50_nm": count_over(0.50),
            "gt_1p00_nm": count_over(1.00),
        },
        "top_outliers": [
            {
                "length_nm": value,
                "atom_i": _atom_label(model, i),
                "atom_j": _atom_label(model, j),
            }
            for value, i, j in rows[:top_n]
        ],
    }


def _ratio(after: float, before: float) -> float | None:
    if before == 0:
        return None
    return after / before


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--design", type=Path, required=True)
    ap.add_argument("--psf", type=Path, required=True, help="mrDNA coarse PSF")
    ap.add_argument("--dcd", type=Path, required=True, help="mrDNA coarse DCD")
    ap.add_argument("--out-json", type=Path, required=True)
    ap.add_argument("--frame", type=int, default=-1)
    ap.add_argument("--sigma-nt", type=float, default=1.0)
    ap.add_argument("--allow-crossover-extrabases", action="store_true")
    args = ap.parse_args()

    design = _load_design(args.design)
    extrabases = crossover_extrabase_records(design)
    if extrabases and not args.allow_crossover_extrabases:
        assert_no_crossover_extrabases(design)

    raw_model = build_atomistic_model(design)
    raw_stats = _bond_stats(raw_model)

    override = nuc_pos_override_from_mrdna_coarse(
        design,
        str(args.psf),
        str(args.dcd),
        frame=args.frame,
        sigma_nt=args.sigma_nt,
    )
    pre_model = build_model_from_override(design, override)
    pre_stats = _bond_stats(pre_model)

    before_outliers = raw_stats["outlier_counts"]
    after_outliers = pre_stats["outlier_counts"]
    report = {
        "schema": "nadoc.mrdna_preconditioning_evaluation.v1",
        "workflow_flag": WORKFLOW_FLAG_NO_CROSSOVER_EXTRABASES_ONLY,
        "design": {
            "path": str(args.design),
            "name": design.metadata.name,
            "helices": len(design.helices),
            "strands": len(design.strands),
            "crossovers": len(design.crossovers),
            "crossover_extrabase_count": len(extrabases),
        },
        "mrdna_source": {
            "psf": str(args.psf),
            "dcd": str(args.dcd),
            "frame": args.frame,
            "sigma_nt": args.sigma_nt,
            "override_entries": len(override),
        },
        "raw_atomistic": raw_stats,
        "mrdna_preconditioned": pre_stats,
        "improvement": {
            "max_bond_length_ratio": _ratio(
                pre_stats["length_nm"]["max"],
                raw_stats["length_nm"]["max"],
            ),
            "gt_0p25_nm_count_ratio": _ratio(
                after_outliers["gt_0p25_nm"],
                before_outliers["gt_0p25_nm"],
            ),
            "gt_0p30_nm_count_ratio": _ratio(
                after_outliers["gt_0p30_nm"],
                before_outliers["gt_0p30_nm"],
            ),
            "gt_0p50_nm_count_ratio": _ratio(
                after_outliers["gt_0p50_nm"],
                before_outliers["gt_0p50_nm"],
            ),
        },
        "decision": {
            "namd_ready_by_bond_geometry": (
                pre_stats["outlier_counts"]["gt_0p30_nm"] == 0
                and pre_stats["length_nm"]["max"] < 0.30
            ),
            "note": (
                "This is a covalent-geometry gate only. Passing it would justify "
                "a NAMD minimization/warmup test; failing it means mrDNA has not "
                "solved the atomistic starting-geometry problem yet."
            ),
        },
    }

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({
        "out_json": str(args.out_json),
        "override_entries": len(override),
        "raw_max_bond_nm": raw_stats["length_nm"]["max"],
        "preconditioned_max_bond_nm": pre_stats["length_nm"]["max"],
        "raw_gt_0p30_nm": before_outliers["gt_0p30_nm"],
        "preconditioned_gt_0p30_nm": after_outliers["gt_0p30_nm"],
        "namd_ready_by_bond_geometry": report["decision"]["namd_ready_by_bond_geometry"],
    }, indent=2))


if __name__ == "__main__":
    main()
