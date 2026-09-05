"""Carry a prepared job's physical restraints across production transitions."""

import json
from pathlib import Path

from backend.core.md_protocols import retarget_anchor_pdb


def harmonic_anchor_k(manifest: dict) -> float | None:
    anchors = manifest.get("anchors") or {}
    if anchors.get("mechanism") == "harmonic_positional":
        return float(anchors["force_constant_kcal_mol_A2"])
    # Production children record the same mechanism using a descriptive string.
    if str(anchors.get("mechanism", "")).startswith("harmonic restraints"):
        return float(anchors["k_kcal_mol_a2"])
    return None


def production_anchor_file(
    package: Path, marker: str | None
) -> tuple[str | None, float | None]:
    """Copy selection/targets, replacing binary marker weights with stored k values.

    Same-job production keeps the physical anchor targets. Replica production uses
    its existing equilibrated-coordinate retargeting instead.
    """
    manifest = json.loads((package / "manifest.json").read_text())
    k = harmonic_anchor_k(manifest)
    if marker is None or k is None:
        return marker, None
    graphene = manifest.get("graphene_nanopore") or {}
    target = "restraints_production_anchors.pdb"
    retarget_anchor_pdb(
        package / marker,
        package / target,
        k=k,
        graphene_k=(manifest.get("anchors") or {}).get("graphene_k_kcal_mol_a2")
        or graphene.get("restraint_k_kcal_mol_A2"),
    )
    return target, k
