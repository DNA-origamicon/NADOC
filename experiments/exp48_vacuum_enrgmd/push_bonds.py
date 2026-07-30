#!/usr/bin/env python3
"""Shim — the push-bond rule now lives in ``backend/core/namd_push_bonds.py``.

exp48 proved the rule out; it is production code now (the vacuum ENRG-MD pre-stage of
the Aksimentiev protocol), so there is exactly one implementation and this module just
re-exports it.  The self-test that used to live here is ``tests/test_namd_push_bonds.py``.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.core.namd_push_bonds import (  # noqa: E402,F401
    CROSSOVER_EXCLUSION_NT,
    PUSH_K,
    PUSH_R0_ANG,
    PushBondResult,
    atom_resolver,
    interhelical_push_bonds,
    qualifying_positions,
    watson_crick_pairs,
)
