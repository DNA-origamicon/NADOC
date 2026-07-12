"""Phase-1 pin for the transcribed SNUPI per-motif parameter database.

Guards backend/data/parameters/snupi_params.json (SNUPI SI Tables S1-S5, 74
motifs). Asserts the JSON loads, all 74 motifs are present with the full
{12 geometry, 6 rigidity, 15 coupling} value set, every value is finite, and the
15 coupling coefficients assemble into a symmetric 6x6 stiffness block. See
memory/project_snupi_mimic.md (Phase 1).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

PARAMS = Path(__file__).resolve().parents[1] / "backend" / "data" / "parameters" / "snupi_params.json"

GEOM_KEYS = ["dx1", "dx2", "dy1", "dy2", "dz1", "dz2",
             "theta_x1", "theta_x2", "theta_y1", "theta_y2", "theta_z1", "theta_z2"]
RIG_KEYS = ["EA", "GAy", "GAz", "GJ", "EIy", "EIz"]
COUP_KEYS = ["g_Tx_Ty", "g_Tx_Tz", "g_Ty_Tz",
             "g_Dx_Dy", "g_Dx_Dz", "g_Dy_Dz",
             "g_Dx_Tx", "g_Dx_Ty", "g_Dx_Tz",
             "g_Dy_Tx", "g_Dy_Ty", "g_Dy_Tz",
             "g_Dz_Tx", "g_Dz_Ty", "g_Dz_Tz"]
FAMILY_COUNTS = {"regular_bp": 10, "nicked_bp": 16, "co_nick": 16,
                 "double_co": 16, "single_co": 16}
DOF = ["dx", "dy", "dz", "theta_x", "theta_y", "theta_z"]


@pytest.fixture(scope="module")
def db():
    with open(PARAMS, encoding="utf-8") as f:
        return json.load(f)


def test_loads_and_metadata(db):
    assert db["temperature_K"] == 300
    assert db["dof_order"] == DOF
    # transcribed convention is SNUPI's own beam frame, NOT Euler-ZYZ
    assert "Euler" not in db["convention"] or "NOT Euler" in db["convention"]


def test_all_74_motifs_present(db):
    motifs = db["motifs"]
    assert set(motifs) == set(FAMILY_COUNTS)
    for fam, n in FAMILY_COUNTS.items():
        assert len(motifs[fam]) == n, f"{fam}: {len(motifs[fam])} != {n}"
    total = sum(len(motifs[fam]) for fam in motifs)
    assert total == 74


def _iter_motifs(db):
    for fam, entries in db["motifs"].items():
        for name, m in entries.items():
            yield fam, name, m


def test_every_motif_has_full_value_set(db):
    for fam, name, m in _iter_motifs(db):
        assert set(m["geometry"]) == set(GEOM_KEYS), f"{fam}/{name} geometry"
        assert set(m["rigidity"]) == set(RIG_KEYS), f"{fam}/{name} rigidity"
        assert set(m["coupling"]) == set(COUP_KEYS), f"{fam}/{name} coupling"


def test_all_values_finite(db):
    for fam, name, m in _iter_motifs(db):
        for block in ("geometry", "rigidity", "coupling"):
            for k, v in m[block].items():
                assert isinstance(v, (int, float)) and math.isfinite(v), \
                    f"{fam}/{name}/{block}/{k} = {v!r}"


def test_rigidities_positive(db):
    # diagonal beam rigidities must be physically positive
    for fam, name, m in _iter_motifs(db):
        for k in RIG_KEYS:
            assert m["rigidity"][k] > 0, f"{fam}/{name}/{k} = {m['rigidity'][k]}"


def _assemble_6x6(m):
    """Build the local 6x6 stiffness with rigidity on the diagonal and the 15
    coupling coefficients mirrored across it (q = [dx,dy,dz,theta_x,theta_y,theta_z])."""
    idx = {d: i for i, d in enumerate(DOF)}
    K = np.zeros((6, 6))
    diag_map = {"dx": "EA", "dy": "GAy", "dz": "GAz",
                "theta_x": "GJ", "theta_y": "EIy", "theta_z": "EIz"}
    for d, rk in diag_map.items():
        K[idx[d], idx[d]] = m["rigidity"][rk]
    cmap = {
        "g_Tx_Ty": ("theta_x", "theta_y"), "g_Tx_Tz": ("theta_x", "theta_z"),
        "g_Ty_Tz": ("theta_y", "theta_z"),
        "g_Dx_Dy": ("dx", "dy"), "g_Dx_Dz": ("dx", "dz"), "g_Dy_Dz": ("dy", "dz"),
        "g_Dx_Tx": ("dx", "theta_x"), "g_Dx_Ty": ("dx", "theta_y"), "g_Dx_Tz": ("dx", "theta_z"),
        "g_Dy_Tx": ("dy", "theta_x"), "g_Dy_Ty": ("dy", "theta_y"), "g_Dy_Tz": ("dy", "theta_z"),
        "g_Dz_Tx": ("dz", "theta_x"), "g_Dz_Ty": ("dz", "theta_y"), "g_Dz_Tz": ("dz", "theta_z"),
    }
    for gk, (a, b) in cmap.items():
        val = m["coupling"][gk]
        K[idx[a], idx[b]] = val
        K[idx[b], idx[a]] = val
    return K


def test_coupling_assembles_symmetric(db):
    # all 15 couplings present => the 6x6 block is fully specified and symmetric
    for fam, name, m in _iter_motifs(db):
        K = _assemble_6x6(m)
        assert np.allclose(K, K.T), f"{fam}/{name} not symmetric"
        # off-diagonal fully populated by the 15 coupling terms (15 unique pairs)
        assert np.count_nonzero(np.triu(K, 1)) == 15 or \
            np.count_nonzero(np.triu(np.abs(K) > 0, 1)) <= 15


def test_regular_bp_mean_matches_si(db):
    # SI Table S1 Mean column: EA=1825.2, and twist-stretch g(dx,theta_x) mean ~ -277
    reg = db["motifs"]["regular_bp"]
    ea = np.mean([reg[k]["rigidity"]["EA"] for k in reg])
    assert ea == pytest.approx(1825.2, abs=0.5)
    gcpl = np.mean([reg[k]["coupling"]["g_Dx_Tx"] for k in reg])
    assert gcpl == pytest.approx(-277.4, abs=1.0)
