"""Helpers for CG-preconditioned atomistic/NAMD workflows.

These utilities deliberately preserve NADOC topology.  In particular, the
mrDNA coarse preconditioning workflow is flagged as valid only for designs with
no crossover ``extra_bases`` unless the caller explicitly overrides the guard.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Mapping

from backend.core.atomistic import (
    AtomisticModel,
    build_atomistic_model,
    crossover_geometry_diagnostics,
)
from backend.core.models import Design
from backend.core.namd_helpers import _complete_psf_from_stub, _render_namd_conf
from backend.core.pdb_export import (
    export_basepair_map_json,
    export_basepair_map_tsv,
    export_design_maps_json,
    export_dry_implicit_restraints,
    export_identity_json,
    export_identity_tsv,
    export_pdb,
    export_psf,
    export_stacking_map_json,
    export_stacking_map_tsv,
)


WORKFLOW_FLAG_NO_CROSSOVER_EXTRABASES_ONLY = "no_crossover_extrabases_only"


def crossover_extrabase_records(design: Design) -> list[dict]:
    """Return crossover records that explicitly contain extra bases."""
    records: list[dict] = []
    for xo in design.crossovers:
        if xo.extra_bases:
            records.append(
                {
                    "crossover_id": xo.id,
                    "extra_bases": xo.extra_bases,
                    "extra_base_count": len(xo.extra_bases),
                    "half_a": {
                        "helix_id": xo.half_a.helix_id,
                        "bp_index": xo.half_a.index,
                        "direction": xo.half_a.strand.value,
                    },
                    "half_b": {
                        "helix_id": xo.half_b.helix_id,
                        "bp_index": xo.half_b.index,
                        "direction": xo.half_b.strand.value,
                    },
                }
            )
    return records


def assert_no_crossover_extrabases(design: Design) -> None:
    """Raise if a design has crossover extra bases.

    The current mrDNA-coarse preconditioning test workflow is intentionally
    scoped to direct-crossover designs.  Designs with explicit linker bases need
    a separate validation path because those bases are part of the intended
    topology and must be represented consistently in mrDNA and atomistic maps.
    """
    records = crossover_extrabase_records(design)
    if not records:
        return
    ids = ", ".join(
        f"{row['crossover_id']}({row['extra_base_count']})" for row in records
    )
    raise ValueError(
        "mrDNA coarse preconditioning is flagged for designs with no crossover "
        f"extra bases only; found explicit crossover extra bases at: {ids}"
    )


def build_precondition_report(
    design: Design,
    *,
    source: str,
    override: Mapping[tuple[str, int, str], object],
    model: AtomisticModel,
    allow_crossover_extrabases: bool = False,
    notes: str = "",
) -> dict:
    """Build a JSON-serializable report for a CG-preconditioned atomistic model."""
    extrabase_records = crossover_extrabase_records(design)
    if extrabase_records and not allow_crossover_extrabases:
        assert_no_crossover_extrabases(design)

    n_expected_keys = sum(
        abs(domain.end_bp - domain.start_bp) + 1
        for strand in design.strands
        for domain in strand.domains
    )
    before = crossover_geometry_diagnostics(design)
    return {
        "schema": "nadoc.md_precondition_report.v1",
        "workflow_flag": WORKFLOW_FLAG_NO_CROSSOVER_EXTRABASES_ONLY,
        "workflow_scope": {
            "requires_no_crossover_extrabases": not allow_crossover_extrabases,
            "allow_crossover_extrabases": allow_crossover_extrabases,
            "crossover_extrabase_count": len(extrabase_records),
            "crossover_extrabases": extrabase_records,
        },
        "source": source,
        "notes": notes,
        "design": {
            "name": design.metadata.name,
            "helices": len(design.helices),
            "strands": len(design.strands),
            "crossovers": len(design.crossovers),
        },
        "override": {
            "entries": len(override),
            "expected_domain_nucleotides": n_expected_keys,
            "coverage_fraction": (len(override) / n_expected_keys)
            if n_expected_keys
            else 0.0,
        },
        "atomistic_model": {
            "atoms": len(model.atoms),
            "bonds": len(model.bonds),
            "nucleotides": len({(a.chain_id, a.seq_num) for a in model.atoms}),
        },
        "crossover_geometry_before_atomistic_rebuild": before,
    }


def write_preconditioned_namd_inputs(
    design: Design,
    model: AtomisticModel,
    out_dir: Path,
    *,
    name: str,
    report: dict,
    copy_forcefield: bool = True,
) -> dict[str, str]:
    """Write PDB/PSF/maps/restraints/config files for a preconditioned NAMD test."""
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_name = (name or design.metadata.name or "design").replace(" ", "_")

    pdb_text = export_pdb(design, model=model)
    psf_stub = export_psf(design, model=model)
    psf_complete = _complete_psf_from_stub(psf_stub)
    restraints = export_dry_implicit_restraints(design, model=model)

    files: dict[str, str] = {}

    def _write(rel: str, text: str) -> None:
        path = out_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        files[rel] = str(path)

    _write(f"{safe_name}.pdb", pdb_text)
    _write(f"{safe_name}.psf", psf_complete)
    _write(f"{safe_name}.stub.psf", psf_stub)
    _write(f"{safe_name}.identity.json", export_identity_json(design, model=model))
    _write(f"{safe_name}.identity.tsv", export_identity_tsv(design, model=model))
    _write(
        f"{safe_name}.design_maps.json", export_design_maps_json(design, model=model)
    )
    _write(f"{safe_name}.basepairs.json", export_basepair_map_json(design, model=model))
    _write(f"{safe_name}.basepairs.tsv", export_basepair_map_tsv(design, model=model))
    _write(f"{safe_name}.stacking.json", export_stacking_map_json(design, model=model))
    _write(f"{safe_name}.stacking.tsv", export_stacking_map_tsv(design, model=model))
    _write("namd_gbis_smoke.conf", _render_namd_conf(safe_name))
    _write(
        "precondition_report.json", json.dumps(report, indent=2, sort_keys=False) + "\n"
    )

    for rel, text in restraints.items():
        _write(f"restraints/{rel}", text)

    if copy_forcefield:
        ff_src = Path(__file__).parent.parent / "data" / "forcefield"
        ff_dst = out_dir / "forcefield"
        ff_dst.mkdir(parents=True, exist_ok=True)
        for filename in (
            "top_all36_na.rtf",
            "par_all36_na.prm",
            "toppar_water_ions_cufix.str",
        ):
            src = ff_src / filename
            if src.exists():
                shutil.copy2(src, ff_dst / filename)
                files[f"forcefield/{filename}"] = str(ff_dst / filename)

    return files


def build_model_from_override(
    design: Design,
    override: Mapping[tuple[str, int, str], object],
) -> AtomisticModel:
    """Small named wrapper for scripts using CG-derived position overrides."""
    return build_atomistic_model(design, nuc_pos_override=dict(override))
