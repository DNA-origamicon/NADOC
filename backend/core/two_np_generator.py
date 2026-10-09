"""Bounded solid-bundle planning for the temporary two-gold-particle generator.

No state or HTTP dependencies. Candidates use the ordinary lattice builder and
scaffold router. The section score is a geometric bending proxy, not a predicted
RMSF. Wireframe generation is deliberately outside this feature's scope.
"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
import math
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.lattice import honeycomb_position, make_bundle_design, square_position
from backend.core.models import Design, LatticeType
from backend.core.seamed_router import auto_scaffold_seamed


class GeneratorSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    roll_deg: float = Field(default=0.0, ge=-180, le=180)
    duplex_bp: int = Field(default=18, ge=12, le=60)
    extend_rod: bool = True
    connections_per_particle: int = Field(default=1, ge=1, le=3, strict=True)
    mechanics: Literal[
        "legacy", "beam", "variable", "robust", "fem-linear", "fem-nonlinear", "oxdna"
    ] = "legacy"
    shape: Literal["auto", "platform", "curved-rod"] = "auto"
    particle_order: list[str] | None = None
    pathing: Literal["colocalized", "interior", "exterior"] = "colocalized"


def compatible_particle_handle(design, particle_id, *, exclude=()):
    """The same deterministic handle choice for planning and construction."""
    for conjugation in design.nanoparticle_conjugations:
        if conjugation.nanoparticle_id != particle_id:
            continue
        for record in conjugation.surface_strands:
            strand = design.find_strand(record.strand_id)
            if (
                strand
                and strand.id not in exclude
                and strand.sequence
                and 12 <= len(strand.sequence) <= 60
                and set(strand.sequence.upper()) <= set("ACGT")
                and len(strand.domains) == 1
                and record.overhang_id
                and strand.domains[0].helix_id == record.helix_id
                and abs(strand.domains[0].end_bp - strand.domains[0].start_bp) + 1
                == len(strand.sequence)
            ):
                return conjugation, record, strand
    return None


@dataclass
class RodCandidate:
    design: Design
    summary: dict


def gold_particles(design: Design, counts=(2, 3, 4)):
    particles = [p for p in design.nanoparticles if p.kind == "gold_nanosphere"]
    if len(particles) not in counts:
        raise ValueError(
            f"Generate design requires {'exactly two' if counts == (2,) else 'two, three, or four'} gold nanoparticles; found {len(particles)}."
        )
    if any(p.coating or p.biotin_dna for p in particles):
        raise ValueError(
            "This first generator supports thiol-DNA gold particles. Streptavidin/biotin coatings need a different attachment model."
        )
    centers = np.array([p.pose.to_array()[:3, 3] for p in particles])
    if not np.isfinite(centers).all():
        raise ValueError("Nanoparticle centers must be finite.")
    distances = np.linalg.norm(centers[:, None] - centers[None, :], axis=-1)
    for i in range(len(particles)):
        for j in range(i):
            if (
                distances[i, j]
                <= (particles[i].diameter_nm + particles[j].diameter_nm) / 2
            ):
                raise ValueError(
                    "Gold cores overlap or touch. Separate their centers before generating."
                )
    distance = float(distances.max())
    return particles, centers, distance


def gold_pair(design: Design):
    return gold_particles(design, (2,))


def pair_frame(centers: np.ndarray, roll_deg: float = 0) -> np.ndarray:
    """Right-handed world frame: local Z follows the centers; +Y faces cargo.

    Use the least-parallel Cartesian axis for a deterministic, pole-safe roll.
    The explicit roll setting resolves the remaining geometric freedom.
    """
    z = centers[1] - centers[0]
    z = z / np.linalg.norm(z)
    reference = np.eye(3)[int(np.argmin(np.abs(z)))]
    y = reference - np.dot(reference, z) * z
    y /= np.linalg.norm(y)
    x = np.cross(y, z)
    angle = math.radians(roll_deg)
    rolled_y = math.cos(angle) * y + math.sin(angle) * x
    return np.column_stack((np.cross(rolled_y, z), rolled_y, z))


def _section(cells, lattice, label):
    pos = honeycomb_position if lattice == LatticeType.HONEYCOMB else square_position
    xy = np.array([pos(*cell) for cell in cells])
    centered = xy - xy.mean(axis=0)
    # Equal helix areas; include each helix's own circular second moment (r=1 nm).
    weakest = float(np.linalg.eigvalsh(centered.T @ centered)[0] + len(cells) / 4)
    width = float(np.ptp(xy[:, 0]) + 2)
    height = float(np.ptp(xy[:, 1]) + 2)
    return {
        "cells": [list(c) for c in sorted(cells)],
        "section": label,
        "helix_count": len(cells),
        "width_nm": width,
        "height_nm": height,
        "section_score": weakest,
    }


@lru_cache(maxsize=2)
def cross_sections(lattice: LatticeType) -> tuple[dict, ...]:
    if lattice == LatticeType.SQUARE:
        # Complete rectangles only, with both dimensions represented. An even
        # cell count permits a single continuous scaffold in this routing family.
        return tuple(
            _section(
                [(r, c) for r in range(rows) for c in range(cols)],
                lattice,
                f"{rows} × {cols}",
            )
            for rows in range(2, 10)
            for cols in range(rows, 13)
            if rows * cols <= 96 and rows * cols % 2 == 0 and cols <= 3 * rows
        )

    # Filled radial shells about a honeycomb face. Reject dangling outer helices
    # before routing; complete surviving shells have sixfold rotational symmetry.
    ring = [(0, 1), (1, 1), (1, 2), (1, 3), (0, 3), (0, 2)]
    center = np.mean([honeycomb_position(*p) for p in ring], axis=0)
    shells = defaultdict(list)
    for row in range(-9, 11):
        for col in range(-9, 12):
            radius = round(
                float(np.linalg.norm(np.array(honeycomb_position(row, col)) - center)),
                6,
            )
            shells[radius].append((row, col))
    sections, cells = [], []
    for _, shell in sorted(shells.items()):
        cells += shell
        if len(cells) > 96:
            break
        points = np.array([honeycomb_position(*p) for p in cells])
        distances = np.linalg.norm(points[:, None] - points[None, :], axis=-1)
        if np.min(np.sum(np.isclose(distances, 2.25), axis=1)) >= 2:
            sections.append(_section(cells, lattice, f"{len(cells)}-helix radial"))
    # Established 18HB footprint: threefold rotational symmetry. It fills the
    # useful gap between 6HB and 24HB without trimming an arbitrary outer row.
    eighteen = [
        (1, 3),
        (0, 3),
        (0, 2),
        (0, 1),
        (1, 1),
        (1, 2),
        (2, 2),
        (2, 1),
        (3, 1),
        (3, 2),
        (3, 3),
        (2, 3),
        (2, 4),
        (2, 5),
        (2, 6),
        (1, 6),
        (1, 5),
        (1, 4),
    ]
    # Complete fused honeycomb faces fill the 6→18 gap. These have twofold
    # rotational symmetry and no dangling helices; no partial face is trimmed.
    for count, cols in ((10, 5), (14, 7)):
        sections.append(
            _section(
                [(r, c) for r in range(2) for c in range(1, cols + 1)],
                lattice,
                f"{count}-helix double-layer",
            )
        )
    sections.append(_section(eighteen, lattice, "18-helix radial"))
    return tuple(sections)


def scaffold_nt(design: Design) -> int:
    return sum(
        abs(d.end_bp - d.start_bp) + 1
        for s in design.scaffolds()
        if not s.is_reference
        for d in s.domains
    )


@lru_cache(maxsize=24)
def _routed(lattice: LatticeType, cells: tuple, length_bp: int) -> Design:
    seed = make_bundle_design(
        list(cells), length_bp, name="Generated two-NP rod", lattice_type=lattice
    )
    routed, result = auto_scaffold_seamed(seed)
    if (
        not result.valid
        or len([s for s in routed.scaffolds() if not s.is_reference]) != 1
    ):
        raise ValueError("This cross-section could not be routed as one scaffold.")
    return routed


def plan_rods(source: Design, settings: GeneratorSettings) -> tuple[RodCandidate, dict]:
    """Compare actually routed candidates under both scaffold budgets."""
    particles, centers, distance = gold_pair(source)
    lattice = source.lattice_type
    if lattice not in (LatticeType.HONEYCOMB, LatticeType.SQUARE):
        raise ValueError("This generator supports honeycomb and square lattices.")
    period = 21 if lattice == LatticeType.HONEYCOMB else 32
    # One period beyond each target leaves room for phase-compatible staple roots.
    minimum_bp = math.ceil(distance / BDNA_RISE_PER_BP) + 2 * period
    minimum_bp = math.ceil(minimum_bp / period) * period
    minimum_nm = minimum_bp * BDNA_RISE_PER_BP
    sections = sorted(
        cross_sections(lattice),
        key=lambda s: (s["section_score"], s["helix_count"]),
        reverse=True,
    )
    best = {}
    for size, name in ((7249, "M13mp18"), (8064, "p8064")):
        for section in sections:
            count = section["helix_count"]
            if count * minimum_bp > size:
                continue
            if max(section["width_nm"], section["height_nm"]) > minimum_nm / 2:
                continue
            cells = tuple(tuple(p) for p in section["cells"])
            try:
                routed = _routed(lattice, cells, minimum_bp)
            except ValueError:
                continue
            used = scaffold_nt(routed)
            if used > size:
                continue
            length = minimum_bp
            if settings.extend_rod:
                # Routing depends on crossover phase. Keep that phase fixed and
                # extend by complete periods, then verify the actual routed count.
                extra = (size - used) // (count * period)
                for periods in range(extra, 0, -1):
                    try:
                        extended = _routed(
                            lattice, cells, minimum_bp + periods * period
                        )
                    except ValueError:
                        continue
                    if scaffold_nt(extended) <= size:
                        routed = extended
                        length = minimum_bp + periods * period
                        used = scaffold_nt(routed)
                        break
            if used > size:
                continue
            axial_points = [
                point.z
                for helix in routed.helices
                for point in (helix.axis_start, helix.axis_end)
            ]
            actual_length_nm = max(axial_points) - min(axial_points)
            summary = {
                **section,
                "scaffold_name": name,
                "scaffold_size": size,
                "scaffold_used_nt": used,
                "unused_scaffold_nt": size - used,
                "nominal_length_bp": length,
                "length_bp": max(h.bp_start + h.length_bp for h in routed.helices)
                - min(h.bp_start for h in routed.helices),
                "length_nm": actual_length_nm,
            }
            best[size] = RodCandidate(routed, summary)
            break
    if not best:
        raise ValueError(
            "Neither 7249 nor 8064 can route a supported complete rod cross-section across this separation with attachment margins. The nanoparticle centers were not moved."
        )
    chosen = best.get(7249) or best[8064]
    upgrade = best.get(8064)
    if upgrade and (
        7249 not in best
        or (
            upgrade.summary["helix_count"] > chosen.summary["helix_count"]
            and upgrade.summary["section_score"]
            > chosen.summary["section_score"] + 1e-8
        )
    ):
        chosen = upgrade
    reason = (
        "8064 enables a thicker complete cross-section."
        if chosen.summary["scaffold_size"] == 8064 and 7249 in best
        else "7249 is sufficient; 8064 does not improve the complete cross-section."
        if chosen.summary["scaffold_size"] == 7249
        else "Only 8064 fits a supported routed cross-section."
    )
    report = {
        "lattice_type": lattice.value,
        "particle_ids": [p.id for p in particles],
        "centers_nm": centers.tolist(),
        "center_distance_nm": distance,
        "selected": chosen.summary,
        "alternatives": [
            best[n].summary if n in best else {"scaffold_size": n, "feasible": False}
            for n in (7249, 8064)
        ],
        "reason": reason,
        "settings": settings.model_dump(),
        "axis": pair_frame(centers, settings.roll_deg)[:, 2].tolist(),
        "side_normal": pair_frame(centers, settings.roll_deg)[:, 1].tolist(),
        "qualification": "Geometric layout; stiffness and RMSF have not been simulated.",
    }
    # Cached builds are immutable templates. Callers always receive their own copy.
    return RodCandidate(
        chosen.design.model_copy(deep=True), deepcopy(chosen.summary)
    ), deepcopy(report)
