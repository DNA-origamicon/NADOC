"""Per-cluster display styling — `color` + `opacity` on ClusterRigidTransform.

Both are display-only (Physical layer) metadata: they never touch topology or
geometry. What these tests actually guard is the PATCH whitelist. `PatchClusterBody`
drops any key it doesn't declare and still answers 200 OK, so a missing field means
"everything works, nothing persists, no error anywhere" — the exact silent failure
this file exists to catch.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.api.routes import _demo_design
from backend.core.models import (
    ClusterRigidTransform,
    Design,
    Direction,
    Domain,
    Helix,
    LatticeType,
    Strand,
    StrandType,
    Vec3,
)


@pytest.fixture(autouse=True)
def _reset():
    design_state.set_design(_demo_design())
    yield
    design_state.set_design(_demo_design())


@pytest.fixture
def client():
    return TestClient(app)


def _seed() -> Design:
    """One helix at HC (0,0) in cluster 'cA'. A Δ=(0,+2) paste lands adjacent."""
    h = Helix(
        id="h_XY_0_0",
        axis_start=Vec3(x=0, y=0, z=0),
        axis_end=Vec3(x=0, y=0, z=100 * 0.34),
        length_bp=100,
        grid_pos=(0, 0),
    )
    s = Strand(
        id="s0",
        domains=[
            Domain(helix_id=h.id, start_bp=0, end_bp=99, direction=Direction.FORWARD)
        ],
        strand_type=StrandType.STAPLE,
    )
    return Design(
        lattice_type=LatticeType.HONEYCOMB,
        helices=[h],
        strands=[s],
        cluster_transforms=[
            ClusterRigidTransform(id="cA", name="Cluster A", helix_ids=[h.id])
        ],
    )


def _cluster(resp, cluster_id="cA") -> dict:
    return next(
        c for c in resp.json()["design"]["cluster_transforms"] if c["id"] == cluster_id
    )


# ── defaults ──────────────────────────────────────────────────────────────────


def test_unstyled_cluster_defaults_to_no_color_and_full_opacity():
    ct = ClusterRigidTransform(name="c", helix_ids=["h0"])
    assert ct.color is None
    assert ct.opacity == 1.0


def test_old_designs_load_without_the_display_fields():
    """models.py declares no model_config, so pydantic v2 `extra='ignore'` +
    defaults means a pre-2026-08 .nadoc round-trips with no migration."""
    ct = ClusterRigidTransform.model_validate(
        {"id": "cA", "name": "Cluster A", "helix_ids": ["h0"]}
    )
    assert ct.color is None
    assert ct.opacity == 1.0


# ── PATCH whitelist ───────────────────────────────────────────────────────────


def test_patch_persists_color_and_opacity(client):
    design_state.set_design(_seed())
    r = client.patch(
        "/api/design/cluster/cA", json={"color": "#ff8800", "opacity": 0.4}
    )
    assert r.status_code == 200, r.text
    c = _cluster(r)
    assert c["color"] == "#ff8800"
    assert c["opacity"] == pytest.approx(0.4)


def test_patch_leaves_the_pose_alone(client):
    """Styling is not a pose edit — translation/rotation/pivot must not move."""
    design_state.set_design(_seed())
    before = _cluster(
        client.patch("/api/design/cluster/cA", json={"translation": [1.0, 2.0, 3.0]})
    )
    r = client.patch("/api/design/cluster/cA", json={"color": "#123456"})
    after = _cluster(r)
    assert after["translation"] == before["translation"]
    assert after["rotation"] == before["rotation"]
    assert after["pivot"] == before["pivot"]


def test_empty_color_clears_back_to_the_auto_palette(client):
    """`None` already means "not supplied" in a PATCH body, so "" is the clear
    sentinel — this is what the sidebar's Reset button sends."""
    design_state.set_design(_seed())
    client.patch("/api/design/cluster/cA", json={"color": "#ff8800", "opacity": 0.4})
    r = client.patch("/api/design/cluster/cA", json={"color": ""})
    assert r.status_code == 200, r.text
    c = _cluster(r)
    assert c["color"] is None
    assert c["opacity"] == pytest.approx(0.4), (
        "clearing the color must not reset opacity"
    )


def test_omitting_a_field_leaves_it_untouched(client):
    design_state.set_design(_seed())
    client.patch("/api/design/cluster/cA", json={"color": "#ff8800", "opacity": 0.4})
    r = client.patch("/api/design/cluster/cA", json={"name": "Renamed"})
    c = _cluster(r)
    assert c["name"] == "Renamed"
    assert c["color"] == "#ff8800"
    assert c["opacity"] == pytest.approx(0.4)


@pytest.mark.parametrize(
    "bad", ["notahex", "#fff", "red", "ff8800", "#gg0000", "#ff88000"]
)
def test_malformed_color_is_rejected(client, bad):
    design_state.set_design(_seed())
    r = client.patch("/api/design/cluster/cA", json={"color": bad})
    assert r.status_code == 400, r.text


def test_uppercase_hex_is_accepted(client):
    design_state.set_design(_seed())
    r = client.patch("/api/design/cluster/cA", json={"color": "#FF8800"})
    assert r.status_code == 200, r.text
    assert _cluster(r)["color"] == "#FF8800"


@pytest.mark.parametrize(
    "sent,expect", [(5, 1.0), (-2, 0.0), (0, 0.0), (1, 1.0), (0.35, 0.35)]
)
def test_opacity_is_clamped(client, sent, expect):
    design_state.set_design(_seed())
    r = client.patch("/api/design/cluster/cA", json={"opacity": sent})
    assert r.status_code == 200, r.text
    assert _cluster(r)["opacity"] == pytest.approx(expect)


def test_patch_without_commit_does_not_push_undo(client):
    """Recoloring is cosmetic: Ctrl+Z must undo the last STRUCTURAL op, not the
    swatch. The sidebar sends the no-commit form for exactly this reason.

    So one undo after seed-then-style must rewind PAST the styling to whatever
    preceded the seed — cluster 'cA' disappears entirely. If the styling patch had
    pushed a checkpoint, undo would instead land on the seed with cA unstyled.
    """
    design_state.set_design(_seed())
    r = client.patch("/api/design/cluster/cA", json={"color": "#ff8800"})
    assert r.status_code == 200, r.text
    assert _cluster(r)["color"] == "#ff8800"

    client.post("/api/design/undo")
    ids = {c.id for c in design_state.get_or_404().cluster_transforms}
    assert "cA" not in ids, "the cosmetic patch pushed its own undo checkpoint"


# ── survival across copy + serialization ──────────────────────────────────────


def test_paste_carries_the_display_fields_to_the_copy(client):
    """cluster_copy builds copies with model_copy, so unlisted fields ride along.
    Pins that, since an explicit-construction refactor would drop them silently."""
    design_state.set_design(_seed())
    client.patch("/api/design/cluster/cA", json={"color": "#ff8800", "opacity": 0.4})
    r = client.post(
        "/api/design/cluster-paste",
        json={"cluster_ids": ["cA"], "delta_row": 0, "delta_col": 2},
    )
    assert r.status_code == 200, r.text
    cts = {c["id"]: c for c in r.json()["design"]["cluster_transforms"]}
    new = next(c for cid, c in cts.items() if cid != "cA")
    assert new["color"] == "#ff8800"
    assert new["opacity"] == pytest.approx(0.4)
    assert new["id"] != "cA"


def test_display_fields_survive_a_design_round_trip(client):
    """.nadoc save/load goes through to_dict/model_validate. Guards against a
    future _design_response prune dropping them off the wire."""
    design_state.set_design(_seed())
    client.patch("/api/design/cluster/cA", json={"color": "#ff8800", "opacity": 0.4})
    design = design_state.get_or_404()
    reloaded = Design.model_validate(design.to_dict())
    ct = next(c for c in reloaded.cluster_transforms if c.id == "cA")
    assert ct.color == "#ff8800"
    assert ct.opacity == pytest.approx(0.4)


# ── Provenance: which clusters the app made by itself ─────────────────────────
# COLOUR resolution ranks a hand-made cluster above an auto one. Auto clusters routinely
# blanket every helix (an imported design gets a "Scaffold Cluster" AND a "Geometry
# Cluster" covering all of them), so without provenance an auto cluster could silently
# win the colour on a nucleotide the user had deliberately clustered.


def test_user_created_clusters_are_not_auto(client):
    """POST /design/cluster is the only manual path — it must leave auto_created False."""
    design_state.set_design(_seed())
    r = client.post(
        "/api/design/cluster", json={"name": "My bar", "helix_ids": ["h_XY_0_0"]}
    )
    assert r.status_code == 200, r.text
    made = next(
        c for c in r.json()["design"]["cluster_transforms"] if c["name"] == "My bar"
    )
    assert made["auto_created"] is False


def test_every_autodetect_creation_site_marks_itself_auto():
    """Cross-list pin: cluster_autodetect is the main producer of "premade" clusters, and
    a site that forgets the flag silently outranks the user's own clusters. Source-text,
    because the alternative is running four different autodetect passes."""
    import re
    from pathlib import Path

    src = Path("backend/core/cluster_autodetect.py").read_text()
    sites = [m.start() for m in re.finditer(r"ClusterRigidTransform\(", src)]
    assert sites, "no creation sites found — did the module move?"
    for pos in sites:
        # The call spans a few lines; look at the balanced-ish window after it.
        window = src[pos : pos + 400]
        assert "auto_created=True" in window, (
            f"cluster_autodetect creation site at offset {pos} does not set auto_created"
        )


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"name": "Scaffold Cluster 1"}, True),
        ({"name": "Geometry Cluster 2"}, True),
        ({"name": "Cluster 1", "is_default": True}, True),
        ({"name": "Duplex 1", "overhang_duplex_driver_id": "oh1"}, True),
        # The load-bearing limit: cluster_autodetect also emits a plain "Cluster N", so the
        # name cannot separate it from a user-created one. Guessing auto here would demote
        # real user clusters, so the inference deliberately does not.
        ({"name": "Cluster 3"}, False),
        ({"name": "My bar"}, False),
    ],
)
def test_legacy_designs_backfill_provenance_on_load(payload, expected):
    """A design saved before auto_created existed infers it once, on load, so the
    inference is persisted on the next save rather than re-guessed forever."""
    ct = ClusterRigidTransform.model_validate({**payload, "helix_ids": ["h0"]})
    assert ct.auto_created is expected


def test_an_explicit_flag_always_beats_the_name_inference():
    ct = ClusterRigidTransform.model_validate(
        {"name": "Scaffold Cluster 1", "helix_ids": ["h0"], "auto_created": False}
    )
    assert ct.auto_created is False


def test_provenance_survives_paste(client):
    """cluster_copy uses model_copy, so a pasted cluster keeps the provenance of the one
    it came from — a copy of a user cluster must not silently become auto."""
    design_state.set_design(_seed())
    r = client.post(
        "/api/design/cluster-paste",
        json={"cluster_ids": ["cA"], "delta_row": 0, "delta_col": 2},
    )
    assert r.status_code == 200, r.text
    cts = {c["id"]: c for c in r.json()["design"]["cluster_transforms"]}
    new = next(c for cid, c in cts.items() if cid != "cA")
    assert new["auto_created"] == cts["cA"]["auto_created"]
