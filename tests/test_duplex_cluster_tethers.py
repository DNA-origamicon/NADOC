"""P3 [[overhang-duplex-cluster]] — the free-until-taut drag tethers for a duplex cluster.
Each applied connection is one backbone bond: MOVING end = the duplex connecting bead c (rides
the cluster, on the duplex helix), FIXED end = the overhang's embedded-staple ROOT bead P (on the
parent part). These feed the gizmo's ssDNA taut projector, so the derivation must name real beads
that resolve in the geometry, with the moving beads on the duplex helix and the fixed beads off it."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from backend.api.crud import _geometry_for_design
from backend.core.models import Design
from backend.core.duplex_cluster import (
    materialize_duplex_cluster, duplex_cluster_for, duplex_cluster_tethers,
)
from backend.core.direct_relax import _DEFAULT_TARGET_NM

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "relax_2x2_binding.nadoc"
# Untracked fixture with no headless builder yet (design-automation AF-FIXTURES) — skip cleanly
# where it's absent (a fresh checkout / the other computer) instead of erroring.
pytestmark = pytest.mark.skipif(
    not _FIXTURE.exists(),
    reason="relax_2x2_binding.nadoc missing (untracked; regen via AF-FIXTURES builder)")


def _load_materialized():
    d = Design.model_validate(json.loads(_FIXTURE.read_text()))
    drv = d.overhang_bindings[0].driver_oh_id
    dvn = d.overhang_bindings[0].driven_oh_id
    d, _ = materialize_duplex_cluster(d, drv)
    return d, drv, dvn


def _bead(nucs, helix_id, bp, direction):
    for n in nucs:
        if n["helix_id"] == helix_id and n["bp_index"] == bp and n["direction"] == direction:
            return np.asarray(n.get("backbone_position") or n.get("base_position"), float)
    return None


def test_monovalent_duplex_yields_two_bond_tethers():
    d, _drv, _dvn = _load_materialized()
    cl = duplex_cluster_for(d, _drv)
    teth = duplex_cluster_tethers(d, cl)
    assert len(teth) == 2                                   # one per applied connection end
    for t in teth:
        assert set(t["moving"]) == {"helix_id", "bp", "direction"}
        assert set(t["fixed"]) == {"helix_id", "bp", "direction"}
        assert t["contour_nm"] == _DEFAULT_TARGET_NM         # one backbone bond
        assert t["moving"]["direction"] in ("FORWARD", "REVERSE")


def test_tether_anchors_resolve_to_real_beads():
    """Every moving/fixed anchor must name a bead that exists in the geometry — otherwise the
    gizmo's resolveWorldPos returns null and the tether is silently dropped."""
    d, _drv, _dvn = _load_materialized()
    cl = duplex_cluster_for(d, _drv)
    nucs = _geometry_for_design(d)
    for t in duplex_cluster_tethers(d, cl):
        m = _bead(nucs, t["moving"]["helix_id"], t["moving"]["bp"], t["moving"]["direction"])
        f = _bead(nucs, t["fixed"]["helix_id"], t["fixed"]["bp"], t["fixed"]["direction"])
        assert m is not None, f"moving anchor {t['moving']} not in geometry"
        assert f is not None, f"fixed anchor {t['fixed']} not in geometry"


def test_moving_anchors_on_duplex_helix_fixed_anchors_off_it():
    """MOVING beads sit on the duplex cluster's helix (so they ride the drag); FIXED beads sit
    on a parent-part helix (so the taut model pulls the duplex to them, not vice-versa)."""
    d, _drv, _dvn = _load_materialized()
    cl = duplex_cluster_for(d, _drv)
    dup_helices = set(cl.helix_ids)
    teth = duplex_cluster_tethers(d, cl)
    assert teth
    for t in teth:
        assert t["moving"]["helix_id"] in dup_helices, t
        assert t["fixed"]["helix_id"] not in dup_helices, t
