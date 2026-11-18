"""Total DNA strand molarity and periodic simulation volume (not salt molarity).

Counts DNA strands in the exported topology, not nucleotides or assemblies.
Only the physical configuration's box header changes; coordinates never scale.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from backend.core.constants import OXDNA_LENGTH_UNIT

AVOGADRO = 6.02214076e23


def box_edge_nm(strands: int, concentration_um: float) -> float:
    if strands < 1 or not math.isfinite(concentration_um) or concentration_um <= 0:
        raise ValueError("DNA concentration must be finite and positive, with at least one DNA strand.")
    edge = (strands * 1e30 / (AVOGADRO * concentration_um)) ** (1 / 3)
    if not math.isfinite(edge):
        raise ValueError("DNA concentration produces a nonfinite simulation box.")
    return edge


def configuration_box(directory: Path, concentration_um=None, *, configuration_path=None):
    """Validate and return proposed bytes plus resolved, persistable conditions."""
    with (configuration_path or directory / "conf.dat").open() as stream:
        lines = stream.readlines() if concentration_um is not None else [stream.readline() for _ in range(3)]
    topology = (directory / "topology.top").read_text().splitlines()
    strands = {row.split()[0] for row in topology[1:] if len(row.split()) >= 4
               and int(row.split()[0]) > 0 and row.split()[1] in {"A", "C", "G", "T", "N"}}
    box = np.array([float(v) for v in lines[1].split("=", 1)[1].split()]) * OXDNA_LENGTH_UNIT
    if len(box) != 3 or not np.all(np.isfinite(box)) or np.any(box <= 0):
        raise ValueError("The source configuration has an invalid simulation box.")
    if concentration_um is not None:
        edge = box_edge_nm(len(strands), float(concentration_um))
        positions = np.array([[float(v) for v in row.split()[:3]] for row in lines[3:] if row.strip()]) * OXDNA_LENGTH_UNIT
        # Keep a 3 nm empty gap between a bounding envelope and its images.
        # Reject instead of wrapping/repositioning particles or stretching bonds.
        extents = np.ptp(positions, axis=0)
        if not np.all(np.isfinite(positions)):
            raise ValueError("The starting configuration contains nonfinite coordinates.")
        if np.any(extents + 3.0 > box) and not np.allclose(box, edge):
            raise ValueError("The starting configuration spans the periodic box boundary. "
                             "Keep its inherited box; changing concentration could break periodic contacts.")
        minimum = float(extents.max()) + 3.0
        if edge < minimum:
            maximum = len(strands) * 1e30 / (AVOGADRO * minimum ** 3)
            raise ValueError(f"DNA concentration needs a {edge:.3f} nm box, but this starting configuration "
                             f"needs at least {minimum:.3f} nm including a 3 nm image gap. "
                             f"Use at most {maximum:.6g} µM total DNA strands or keep the inherited box.")
        box[:] = edge
        units = edge / OXDNA_LENGTH_UNIT
        lines[1] = f"b = {units:.15g} {units:.15g} {units:.15g}\n"
    concentration = len(strands) * 1e30 / (AVOGADRO * float(np.prod(box)))
    return ''.join(lines), dict(convention="total_dna_strands", dna_strands=len(strands),
                               concentration_uM=concentration, box_nm=box.tolist())


def apply_concentration(directory, config, concentration_um=None):
    text, conditions = configuration_box(Path(directory), concentration_um)
    if concentration_um is not None:
        path = Path(directory) / 'conf.dat'
        temporary = path.with_suffix('.concentration.tmp')
        temporary.write_text(text)
        temporary.replace(path)
    config['dna_concentration_uM'] = concentration_um
    config['box_conditions'] = conditions
    return conditions


def apply_job_concentration(job, directory, value=None):
    """API adapter with actionable validation errors; preserves all saved inputs on error."""
    from fastapi import HTTPException
    try:
        return apply_concentration(directory, job.run_config, value)
    except FileNotFoundError as exc:
        if value is None:
            return None  # Historical settings-only records need not have physical inputs.
        raise HTTPException(422, "The job has no physical inputs for changing DNA concentration.") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def validate_source_concentration(directory, configuration, value):
    """Reject invalid continuation requests before allocating a child job directory."""
    if value is None:
        return
    from fastapi import HTTPException
    try:
        configuration_box(directory, value, configuration_path=configuration)
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc
