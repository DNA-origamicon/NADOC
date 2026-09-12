"""Experimental neutral PEG-like bead–spring surface, DNA2PEG v1.

DNA retains oxDNA2. PEG has harmonic CM bonds and WCA PEG/PEG and PEG/DNA
CM sterics. Statistical segments are not chemical repeat units. No dipoles,
hydration, ion binding, or interparticle charge interactions are implied.
"""
from __future__ import annotations

import math
import os
from pathlib import Path

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from backend.core.constants import NM_TO_OXDNA

PEG_BTYPE = 500


class PegParameters(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    segments: int = Field(8, ge=2, le=64)
    bondLengthNm: float = Field(0.7, ge=0.3, le=1.5)
    beadDiameterNm: float = Field(0.5, ge=0.2, le=1.0)
    terminalChargeE: float = Field(0.0, ge=-2.0, le=2.0)

    def engine_parameters(self) -> dict:
        return {
            "peg_bond_length": self.bondLengthNm * NM_TO_OXDNA,
            "peg_bond_k": 100.0,
            "peg_sigma": self.beadDiameterNm * NM_TO_OXDNA,
            # Isotropic DNA CM proxy of diameter 1 nm for the mixed WCA pair.
            "peg_dna_sigma": (self.beadDiameterNm + 1.0) * 0.5 * NM_TO_OXDNA,
            "peg_epsilon": 0.1,
        }


def is_peg(spec) -> bool:
    return isinstance(spec, dict) and spec.get("material") == "PEG" and spec.get("enabled", True)


def find_peg_oxdna() -> str | None:
    explicit = os.environ.get("NADOC_PEG_OXDNA_BIN")
    path = Path(explicit) if explicit else Path.home() / ".local/share/nadoc/engines/oxdna-peg/current/bin/oxDNA"
    return str(path) if path.is_file() and os.access(path, os.X_OK) else None


def configure_peg_stages(stages, spec):
    if not is_peg(spec):
        return
    params = PegParameters.model_validate(spec)
    for stage in stages:
        if stage.parfile:
            raise ValueError("PEG with protein hybrids is not supported in this milestone")
        stage.interaction = "DNA2PEG"
        stage.peg_parameters = params.engine_parameters()
        stage.dt = min(stage.dt, 0.001)


def build_peg_strands(spec, *, origami_cm_oxdna, n_particles_origami, n_strands_origami, surface):
    from backend.physics.oxdna_surface_strands import CaptureBuild, placement_points_nm, plane_basis, strand_count, _conf_line

    params = PegParameters.model_validate(spec.peg)
    out = CaptureBuild()
    if strand_count(spec.shape, spec.size_nm, spec.density_per_um2) * (params.segments + 1) > 100_000:
        raise ValueError("PEG milestone supports at most 100,000 surface beads")
    points = placement_points_nm(spec.shape, spec.size_nm, spec.seed,
        density_per_um2=spec.density_per_um2, offset_x_nm=spec.offset_x_nm,
        offset_y_nm=spec.offset_y_nm)
    if len(points) * (params.segments + 1) > 100_000:
        raise ValueError("PEG milestone supports at most 100,000 surface beads")
    cm = np.asarray(origami_cm_oxdna, dtype=float).reshape((-1, 3))
    if not len(cm):
        raise ValueError("This surface workflow requires a DNA probe/design")
    normal, u, v = plane_basis(surface["dir"])
    from backend.physics.oxdna_surface_geometry import resolved_wall
    from backend.core.surface_transforms import surface_frame
    resolved = resolved_wall(surface, cm)
    wall = -resolved["position"]
    if surface.get("tangent_u") is not None:
        frame = surface_frame(resolved)
        u, v = np.asarray(frame.tangent_u), frame.tangent_v
    centroid = cm.mean(axis=0)
    origin = centroid + (wall - centroid @ normal) * normal
    length = params.segments + 1
    for chain, (x, y) in enumerate(points):
        anchor = origin + NM_TO_OXDNA * (x * u + y * v)
        start = n_particles_origami + chain * length
        for j in range(length):
            pos = anchor + j * params.bondLengthNm * NM_TO_OXDNA * normal
            out.topology_rows.append((n_strands_origami + chain + 1, str(PEG_BTYPE),
                start + j + 1 if j < length - 1 else -1, start + j - 1 if j else -1))
            out.conf_lines.append(_conf_line(pos, u, normal))
            out.max_extent_oxdna = max(out.max_extent_oxdna, float(np.abs(pos).max()))
            nearest = float(np.linalg.norm(cm - pos, axis=1).min()) / NM_TO_OXDNA
            out.min_dist_to_origami_nm = min(out.min_dist_to_origami_nm or math.inf, nearest)
        out.trap_anchors.append((start, anchor.tolist()))
    out.n_strands = len(points)
    out.n_beads = len(out.conf_lines)
    # WCA is steep. Refuse an overlapped seed rather than submit a doomed run.
    cutoff_nm = (params.beadDiameterNm + 1.0) * 0.5 * 2 ** (1 / 6)
    if out.min_dist_to_origami_nm is not None and out.min_dist_to_origami_nm < cutoff_nm:
        raise ValueError("PEG seed overlaps the DNA probe; increase surface clearance or change patch offsets/seed")
    return out


def peg_terminal_field_text(spec, field) -> str:
    """Only the optional terminal group receives qE; neutral beads never do.

    A physical field is required to interpret an elementary charge. Legacy force
    per nucleotide mode remains DNA-only. Screening is not in this milestone.
    """
    if not is_peg(spec) or not field or "field_V_per_m" not in field:
        return ""
    from backend.physics.oxdna_interface import electric_force_pn, pn_to_oxdna_force
    charge = PegParameters.model_validate(spec).terminalChargeE
    magnitude = pn_to_oxdna_force(electric_force_pn(field["field_V_per_m"], charge))
    if not magnitude:
        return ""
    direction = np.asarray(field.get("dir", [0, 1, 0]), dtype=float)
    direction /= np.linalg.norm(direction)
    vector = ",".join(f"{v:.9g}" for v in direction)
    return "\n".join(
        "{\ntype = string\n" + f"particle = {int(i)}\nF0 = {magnitude:.12g}\nrate = 0\ndir = {vector}\n}}\n"
        for i in (spec.get("built") or {}).get("terminal_particles", [])
    )
