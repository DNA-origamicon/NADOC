"""
CG-to-atomistic bridge: read a relaxed oxDNA configuration and produce
an AtomisticModel with CG-informed backbone positions instead of ideal
B-DNA geometry.

The key improvement over ideal B-DNA: oxDNA relaxation resolves
crossover terminal atom clashes (O5'/O1P pairs at ~0.05 nm in the
ideal model), so the GROMACS EM starts from a near-equilibrium
structure and converges in ~1000 steps instead of ~12000.

Pipeline
--------
1. Export oxDNA package from the current design.
2. Run oxDNA relaxation (``oxDNA input.txt`` → ``last_conf.dat``).
3. Call ``build_atomistic_model_from_cg(design, last_conf.dat)``.
4. Pass the returned AtomisticModel to ``build_gromacs_package``.

The base orientations are kept from ideal B-DNA geometry; only backbone
positions are updated with CG coordinates.  GROMACS EM fine-tunes
everything from this improved starting point.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from backend.core.models import Design
from backend.core.atomistic import AtomisticModel, build_atomistic_model
from backend.physics.oxdna_interface import read_configuration


def build_atomistic_model_from_cg(
    design: Design,
    conf_path: str | Path,
) -> AtomisticModel:
    """
    Build an all-atom model using backbone positions from a relaxed oxDNA
    configuration rather than ideal B-DNA geometry.

    Parameters
    ----------
    design    : Design — must match the topology used to generate the conf.
    conf_path : Path to a relaxed oxDNA .dat file (e.g. ``last_conf.dat``).

    Returns
    -------
    AtomisticModel identical to ``build_atomistic_model(design)`` except
    that each nucleotide's backbone position is taken from the CG conf.
    """
    nuc_pos_override: dict[tuple[str, int, str], np.ndarray] = read_configuration(
        conf_path, design
    )
    return build_atomistic_model(design, nuc_pos_override=nuc_pos_override)
