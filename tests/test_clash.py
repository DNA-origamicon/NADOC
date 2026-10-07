"""Design-layer steric-clash detector (backend/core/clash.py).

Calibration pins: clean bundles report zero clashes; the mitred-corner fixture
reports its folded A↔B seam clashes.  See clash.py's module docstring.
"""

from pathlib import Path

import numpy as np
import pytest

from backend.core.clash import (
    DEFAULT_CLASH_THRESHOLD_NM,
    DEFAULT_DESIGNED_MARGIN_NM,
    clash_report,
)
from backend.core.models import Design
from tests.conftest import make_6hb_design, make_18hb_design

pytestmark = pytest.mark.native_placement

_CORNER = Path(__file__).resolve().parent / "fixtures" / "corner_miter_test.nadoc"
_26HB = Path(__file__).resolve().parents[1] / "Examples" / "26hb_platform_v3.nadoc"


def _load(path: Path) -> Design:
    return Design.from_json(path.read_text(encoding="utf-8"))


# ── Clean designs → zero clashes ──────────────────────────────────────────────


def test_clean_6hb_reports_no_clashes():
    assert clash_report(make_6hb_design()).count == 0


def test_clean_18hb_reports_no_clashes():
    assert clash_report(make_18hb_design()).count == 0


@pytest.mark.skipif(not _26HB.exists(), reason="26hb_platform_v3 example missing")
def test_clean_26hb_platform_reports_no_clashes():
    # Un-folded multi-bundle platform — tight lattice packing everywhere, but no
    # pose, so nothing should be flagged.
    assert clash_report(_load(_26HB)).count == 0


# ── Folded corner → seam clashes ──────────────────────────────────────────────


@pytest.mark.skipif(not _CORNER.exists(), reason="corner_miter_test fixture missing")
def test_corner_miter_reports_seam_clashes():
    from backend.core.design_geometry import _geometry_for_design

    design = _load(_CORNER)
    report = clash_report(design)

    # The two arms fold together at the mitred corner → real backbone overlaps.
    assert report.count > 0
    # Independently enumerate distances between the actual exported native DNA
    # beads. A count calibrated against radius1 construction points included
    # phantom/incorrectly positioned beads and cannot be a molecular oracle.
    # Keep both calibrated distance thresholds unchanged and require every
    # expected pair's identity, not just a minimum number of collisions.
    posed = _geometry_for_design(design)
    straight = _geometry_for_design(design.model_copy(update={"deformations": [], "cluster_transforms": []}))
    key = lambda n: (n["helix_id"], n["bp_index"], n["direction"], n.get("copy_k", 0))
    straight_by_key = {key(n): n["backbone_position"] for n in straight}
    positions = np.asarray([n["backbone_position"] for n in posed])
    rest = np.asarray([straight_by_key[key(n)] for n in posed])
    distances = np.linalg.norm(positions[:, None]-positions[None, :], axis=2)
    rest_distances = np.linalg.norm(rest[:, None]-rest[None, :], axis=2)
    selected = np.argwhere(np.triu((distances < DEFAULT_CLASH_THRESHOLD_NM) &
                                  (rest_distances > DEFAULT_DESIGNED_MARGIN_NM), k=1))
    expected = {frozenset((key(posed[i])[:3], key(posed[j])[:3])) for i, j in selected}
    actual = {frozenset(((p.a.helix_id, p.a.bp_index, p.a.direction),
                         (p.b.helix_id, p.b.bp_index, p.b.direction))) for p in report.pairs}
    assert report.count == len(selected)
    assert actual == expected

    # Every flagged pair is a genuine sub-0.65 nm overlap, nearest first.
    dists = [p.distance_nm for p in report.pairs]
    assert dists == sorted(dists)
    assert all(d < DEFAULT_CLASH_THRESHOLD_NM for d in dists)
    assert min(dists) < 0.4  # reference min ≈ 0.28 nm

    # Clashes are between the two arms (A = cols 0..5, B = cols 9..14), never
    # within one arm (that would be designed lattice packing, excluded).
    def _col(helix_id: str) -> int:
        return int(helix_id.rsplit("_", 1)[-1])

    for p in report.pairs:
        ca, cb = _col(p.a.helix_id), _col(p.b.helix_id)
        lo, hi = sorted((ca, cb))
        assert lo <= 5 and hi >= 9, f"expected cross-arm pair, got cols {ca},{cb}"


@pytest.mark.skipif(not _CORNER.exists(), reason="corner_miter_test fixture missing")
def test_corner_report_serialises():
    report = clash_report(_load(_CORNER))
    d = report.to_dict()
    assert d["count"] == report.count
    assert d["threshold_nm"] == DEFAULT_CLASH_THRESHOLD_NM
    assert d["designed_margin_nm"] == DEFAULT_DESIGNED_MARGIN_NM
    first = d["clashes"][0]
    assert set(first) == {"a", "b", "distance_nm"}
    assert set(first["a"]) == {"helix_id", "bp_index", "direction", "position"}
    assert len(first["a"]["position"]) == 3


@pytest.mark.skipif(not _CORNER.exists(), reason="corner_miter_test fixture missing")
def test_tighter_margin_still_excludes_designed_packing():
    # Lattice packing sits ≤ ~0.5 nm straight; a 1.0 nm margin must still exclude
    # it (clean arms) while keeping the ~20 nm-straight fold clashes.
    report = clash_report(_load(_CORNER), designed_margin_nm=1.0)
    assert report.count > 0
    assert clash_report(make_6hb_design(), designed_margin_nm=1.0).count == 0
