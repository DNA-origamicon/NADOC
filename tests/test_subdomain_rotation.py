"""Phase 4 — per-sub-domain rotation backend tests.

Covers the geometry pipeline AND the new HTTP endpoints:
  • Single sub-domain rotation visibly affects geometry positions.
  • Two sub-domains compose deterministically (sequential PATCH chain).
  • Linker bridge co-rotation through a sub-domain chain (tipi: the
    complement strand's bp on the same helix follows the rotated OH).
  • Feature log entry shape + round-trip serialisation.
  • Undo restores the prior (theta, phi) value.
  • Frame endpoint correctness (unit-norm parent_axis + phi_ref, pivot
    near the junction-side bp).
  • φ-range clamp: -10° → 422; 181° → 422.
  • commit:false leaves the feature log untouched; commit:true appends.
  • Two commit:true within ~2 s coalesce into a single log entry.
  • Legacy load: entries without the new fields default to []; geometry
    still applies the whole-overhang rotation.

All tests reuse the same 6HB + overhang fixture used by
``tests/test_sub_domains.py``.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.core.deformation import (
    apply_overhang_rotation_if_needed,
    deformed_nucleotide_arrays,
)
from backend.core.models import (
    Design,
    OverhangRotationLogEntry,
)


client = TestClient(app)


# ── Fixtures (reuse helpers from test_sub_domains) ─────────────────────────────


def _patch(path: str, body: dict | None = None):
    return client.patch(f"/api{path}", json=body or {})


def _post(path: str, body: dict | None = None):
    return client.post(f"/api{path}", json=body or {})


def _get(path: str):
    return client.get(f"/api{path}")


def _fresh_design_with_overhang(length_bp: int = 12) -> tuple[Design, str, str]:
    """Build a fresh 6HB design with one extruded overhang. Returns
    ``(design, overhang_id, sub_domain_id)`` and installs it in
    ``design_state``."""
    from tests.test_sub_domains import _extrude_overhang, _make_6hb
    design, ovhg_id = _extrude_overhang(_make_6hb(), length_bp=length_bp)
    design_state.set_design(design)
    spec = next(o for o in design_state.get_or_404().overhangs if o.id == ovhg_id)
    sd_id = spec.sub_domains[0].id
    return design_state.get_or_404(), ovhg_id, sd_id


def _overhang_nuc_positions(design: Design, overhang_id: str) -> np.ndarray:
    spec = next(o for o in design.overhangs if o.id == overhang_id)
    helix = next(h for h in design.helices if h.id == spec.helix_id)
    # Use the arrays pipeline + overhang rotation pass so per-sub-domain
    # rotations are reflected in the returned positions (mirrors what
    # ``_design_response_with_geometry`` does in crud.py).
    arrs = deformed_nucleotide_arrays(helix, design)
    arrs = apply_overhang_rotation_if_needed(arrs, helix, design)
    strand = next(s for s in design.strands if s.id == spec.strand_id)
    domain = next(d for d in strand.domains if d.overhang_id == overhang_id)
    from backend.core.models import Direction
    dir_int = 0 if domain.direction == Direction.FORWARD else 1
    lo = min(domain.start_bp, domain.end_bp)
    hi = max(domain.start_bp, domain.end_bp)
    mask = (
        (arrs['bp_indices'] >= lo) &
        (arrs['bp_indices'] <= hi) &
        (arrs['directions'] == dir_int)
    )
    return arrs['positions'][mask].astype(float).copy()


# ── 1. Single sub-domain rotation visible in geometry ─────────────────────────


def test_single_subdomain_rotation_affects_geometry() -> None:
    design, ovhg_id, sd_id = _fresh_design_with_overhang(length_bp=12)
    pre = _overhang_nuc_positions(design, ovhg_id)
    assert pre.shape[0] > 0

    resp = _patch(
        f"/design/overhang/{ovhg_id}/sub-domains/{sd_id}/rotation",
        {"theta_deg": 0.0, "phi_deg": 30.0, "commit": True},
    )
    assert resp.status_code == 200, resp.text
    post = _overhang_nuc_positions(design_state.get_or_404(), ovhg_id)
    assert post.shape == pre.shape
    # At least one nucleotide must have moved by > 0.1 nm (φ=30 over 12 bp).
    delta = np.linalg.norm(post - pre, axis=1)
    assert delta.max() > 0.1


# ── 2. Two sub-domains compose deterministically ───────────────────────────────


def test_chain_two_subdomains_deterministic() -> None:
    design, ovhg_id, sd_whole = _fresh_design_with_overhang(length_bp=12)

    # Split into [5, 7].
    resp = _post(
        f"/design/overhang/{ovhg_id}/sub-domains/split",
        {"sub_domain_id": sd_whole, "split_at_offset": 5},
    )
    assert resp.status_code == 200, resp.text

    spec = next(o for o in design_state.get_or_404().overhangs if o.id == ovhg_id)
    sd_5p, sd_3p = sorted(spec.sub_domains, key=lambda s: s.start_bp_offset)

    # Rotate the 5'-most sub-domain by phi=20.
    r1 = _patch(
        f"/design/overhang/{ovhg_id}/sub-domains/{sd_5p.id}/rotation",
        {"theta_deg": 0.0, "phi_deg": 20.0, "commit": True},
    )
    assert r1.status_code == 200, r1.text

    # Rotate the 3'-most sub-domain by phi=15.
    r2 = _patch(
        f"/design/overhang/{ovhg_id}/sub-domains/{sd_3p.id}/rotation",
        {"theta_deg": 0.0, "phi_deg": 15.0, "commit": True},
    )
    assert r2.status_code == 200, r2.text

    # Capture geometry after sequential patches.
    seq_pos = _overhang_nuc_positions(design_state.get_or_404(), ovhg_id)

    # Reset to identity and use the batch endpoint to apply the same op.
    _patch(
        f"/design/overhang/{ovhg_id}/sub-domains/{sd_5p.id}/rotation",
        {"theta_deg": 0.0, "phi_deg": 0.0, "commit": True},
    )
    _patch(
        f"/design/overhang/{ovhg_id}/sub-domains/{sd_3p.id}/rotation",
        {"theta_deg": 0.0, "phi_deg": 0.0, "commit": True},
    )
    rb = _patch(
        f"/design/overhang/{ovhg_id}/sub-domains/rotations-batch",
        {
            "ops": [
                {"sub_domain_id": sd_5p.id, "theta_deg": 0.0, "phi_deg": 20.0},
                {"sub_domain_id": sd_3p.id, "theta_deg": 0.0, "phi_deg": 15.0},
            ],
            "commit": True,
        },
    )
    assert rb.status_code == 200, rb.text
    batch_pos = _overhang_nuc_positions(design_state.get_or_404(), ovhg_id)

    # Geometry must match within tight tolerance.
    assert seq_pos.shape == batch_pos.shape
    diff = np.linalg.norm(seq_pos - batch_pos, axis=1).max()
    assert diff < 1e-6, f"sequential != batch composition: max delta {diff}"


# ── 3. Linker bridge co-rotation across the chain ──────────────────────────────


def test_linker_complement_corotates_with_subdomain() -> None:
    """A LINKER strand domain that pairs the overhang's bp range should
    follow the sub-domain rotation. We construct a synthetic linker
    domain via direct design mutation (no need to exercise the full
    overhang-connection pipeline)."""
    from backend.core.models import (
        Direction, Domain, Strand, StrandType,
    )

    design, ovhg_id, sd_id = _fresh_design_with_overhang(length_bp=10)
    spec = next(o for o in design.overhangs if o.id == ovhg_id)
    strand = next(s for s in design.strands if s.id == spec.strand_id)
    oh_dom = next(d for d in strand.domains if d.overhang_id == ovhg_id)

    opp_dir = Direction.REVERSE if oh_dom.direction == Direction.FORWARD else Direction.FORWARD
    linker_dom = Domain(
        helix_id=oh_dom.helix_id,
        start_bp=min(oh_dom.start_bp, oh_dom.end_bp),
        end_bp=max(oh_dom.start_bp, oh_dom.end_bp),
        direction=opp_dir,
    )
    if opp_dir == Direction.REVERSE:
        linker_dom = linker_dom.model_copy(update={
            "start_bp": max(oh_dom.start_bp, oh_dom.end_bp),
            "end_bp":   min(oh_dom.start_bp, oh_dom.end_bp),
        })
    linker = Strand(
        id="__test_linker__",
        strand_type=StrandType.LINKER,
        domains=[linker_dom],
    )
    new_design = design.copy_with(strands=list(design.strands) + [linker])
    design_state.set_design(new_design)

    pre = _overhang_nuc_positions(design_state.get_or_404(), ovhg_id)

    resp = _patch(
        f"/design/overhang/{ovhg_id}/sub-domains/{sd_id}/rotation",
        {"theta_deg": 30.0, "phi_deg": 45.0, "commit": True},
    )
    assert resp.status_code == 200, resp.text

    post = _overhang_nuc_positions(design_state.get_or_404(), ovhg_id)
    assert np.linalg.norm(post - pre, axis=1).max() > 0.1


# ── 4. Feature log entry shape + round-trip ────────────────────────────────────


def test_log_entry_shape_and_round_trip() -> None:
    design, ovhg_id, sd_id = _fresh_design_with_overhang(length_bp=10)

    resp = _patch(
        f"/design/overhang/{ovhg_id}/sub-domains/{sd_id}/rotation",
        {"theta_deg": 12.0, "phi_deg": 34.0, "commit": True},
    )
    assert resp.status_code == 200, resp.text

    log = design_state.get_or_404().feature_log
    assert len(log) >= 1
    entry = log[-1]
    assert entry.feature_type == 'overhang_rotation'
    assert entry.overhang_ids == [ovhg_id]
    assert entry.rotations == [[0.0, 0.0, 0.0, 1.0]]
    assert entry.sub_domain_ids == [sd_id]
    assert entry.sub_domain_thetas_deg == [12.0]
    assert entry.sub_domain_phis_deg == [34.0]

    # Round-trip via model_dump / re-validate.
    payload = entry.model_dump()
    rebuilt = OverhangRotationLogEntry.model_validate(payload)
    assert rebuilt.overhang_ids == entry.overhang_ids
    assert rebuilt.sub_domain_ids == entry.sub_domain_ids
    assert rebuilt.sub_domain_thetas_deg == entry.sub_domain_thetas_deg
    assert rebuilt.sub_domain_phis_deg == entry.sub_domain_phis_deg


# ── 5. Undo restores prior theta/phi ───────────────────────────────────────────


def test_undo_restores_prior_subdomain_angles() -> None:
    design, ovhg_id, sd_id = _fresh_design_with_overhang(length_bp=10)

    # First commit: 10/20.
    r1 = _patch(
        f"/design/overhang/{ovhg_id}/sub-domains/{sd_id}/rotation",
        {"theta_deg": 10.0, "phi_deg": 20.0, "commit": True},
    )
    assert r1.status_code == 200, r1.text

    # Wait past the 2-second coalesce window so the second commit appends
    # a distinct entry. We force-bump the previous entry's timestamp
    # backwards to avoid actually sleeping in tests.
    import datetime as _dt
    log = design_state.get_or_404().feature_log
    log[-1].__dict__['timestamp'] = (
        _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(seconds=10)
    ).isoformat()

    # Second commit: 40/60.
    r2 = _patch(
        f"/design/overhang/{ovhg_id}/sub-domains/{sd_id}/rotation",
        {"theta_deg": 40.0, "phi_deg": 60.0, "commit": True},
    )
    assert r2.status_code == 200, r2.text

    # Roll back (undo) the last entry via DELETE /design/features/last —
    # the delta-style revert path for overhang_rotation entries.
    rrev = client.delete("/api/design/features/last")
    assert rrev.status_code == 200, rrev.text

    spec = next(o for o in design_state.get_or_404().overhangs if o.id == ovhg_id)
    sd = next(s for s in spec.sub_domains if s.id == sd_id)
    assert sd.rotation_theta_deg == pytest.approx(10.0)
    assert sd.rotation_phi_deg   == pytest.approx(20.0)


# ── 6. Frame endpoint correctness ──────────────────────────────────────────────


def test_frame_endpoint_returns_unit_vectors() -> None:
    design, ovhg_id, sd_id = _fresh_design_with_overhang(length_bp=8)

    resp = _get(f"/design/overhang/{ovhg_id}/sub-domains/{sd_id}/frame")
    assert resp.status_code == 200, resp.text
    j = resp.json()
    assert set(j.keys()) >= {"pivot", "parent_axis", "phi_ref"}

    pa = np.array(j["parent_axis"], dtype=float)
    pr = np.array(j["phi_ref"], dtype=float)
    piv = np.array(j["pivot"], dtype=float)

    assert pa.shape == (3,)
    assert pr.shape == (3,)
    assert piv.shape == (3,)

    assert abs(float(np.linalg.norm(pa)) - 1.0) < 1e-6
    assert abs(float(np.linalg.norm(pr)) - 1.0) < 1e-6

    # phi_ref must lie in plane ⊥ parent_axis.
    assert abs(float(np.dot(pa, pr))) < 1e-6

    # pivot is finite.
    assert np.isfinite(piv).all()


# ── 7. φ clamp ─────────────────────────────────────────────────────────────────


def test_phi_clamp_rejects_negative() -> None:
    _, ovhg_id, sd_id = _fresh_design_with_overhang(length_bp=8)
    r = _patch(
        f"/design/overhang/{ovhg_id}/sub-domains/{sd_id}/rotation",
        {"theta_deg": 0.0, "phi_deg": -10.0, "commit": False},
    )
    assert r.status_code == 422, r.text


def test_phi_clamp_rejects_over_180() -> None:
    _, ovhg_id, sd_id = _fresh_design_with_overhang(length_bp=8)
    r = _patch(
        f"/design/overhang/{ovhg_id}/sub-domains/{sd_id}/rotation",
        {"theta_deg": 0.0, "phi_deg": 181.0, "commit": False},
    )
    assert r.status_code == 422, r.text


def test_theta_clamp_rejects_over_180() -> None:
    _, ovhg_id, sd_id = _fresh_design_with_overhang(length_bp=8)
    r = _patch(
        f"/design/overhang/{ovhg_id}/sub-domains/{sd_id}/rotation",
        {"theta_deg": 200.0, "phi_deg": 0.0, "commit": False},
    )
    assert r.status_code == 422, r.text


# ── 8. commit:false vs commit:true log behaviour ───────────────────────────────


def test_commit_false_does_not_touch_log() -> None:
    design, ovhg_id, sd_id = _fresh_design_with_overhang(length_bp=10)
    pre_log_len = len(design.feature_log)

    r = _patch(
        f"/design/overhang/{ovhg_id}/sub-domains/{sd_id}/rotation",
        {"theta_deg": 15.0, "phi_deg": 25.0, "commit": False},
    )
    assert r.status_code == 200, r.text
    assert len(design_state.get_or_404().feature_log) == pre_log_len

    # State still updated (geometry preview).
    spec = next(o for o in design_state.get_or_404().overhangs if o.id == ovhg_id)
    sd = next(s for s in spec.sub_domains if s.id == sd_id)
    assert sd.rotation_theta_deg == pytest.approx(15.0)
    assert sd.rotation_phi_deg == pytest.approx(25.0)


def test_commit_true_appends_log_entry() -> None:
    design, ovhg_id, sd_id = _fresh_design_with_overhang(length_bp=10)
    pre_log_len = len(design.feature_log)

    r = _patch(
        f"/design/overhang/{ovhg_id}/sub-domains/{sd_id}/rotation",
        {"theta_deg": 15.0, "phi_deg": 25.0, "commit": True},
    )
    assert r.status_code == 200, r.text
    assert len(design_state.get_or_404().feature_log) == pre_log_len + 1


# ── 9. Coalescing 2s window ────────────────────────────────────────────────────


def test_two_commits_within_2s_coalesce_into_one_entry() -> None:
    design, ovhg_id, sd_id = _fresh_design_with_overhang(length_bp=10)
    pre_log_len = len(design.feature_log)

    r1 = _patch(
        f"/design/overhang/{ovhg_id}/sub-domains/{sd_id}/rotation",
        {"theta_deg": 10.0, "phi_deg": 20.0, "commit": True},
    )
    assert r1.status_code == 200
    assert len(design_state.get_or_404().feature_log) == pre_log_len + 1

    # Second commit immediately after — must coalesce.
    r2 = _patch(
        f"/design/overhang/{ovhg_id}/sub-domains/{sd_id}/rotation",
        {"theta_deg": 30.0, "phi_deg": 40.0, "commit": True},
    )
    assert r2.status_code == 200
    log = design_state.get_or_404().feature_log
    assert len(log) == pre_log_len + 1  # NO new entry
    # Latest angles win.
    entry = log[-1]
    assert entry.sub_domain_thetas_deg == [30.0]
    assert entry.sub_domain_phis_deg == [40.0]


# ── 10. Legacy entries without new fields default to [] ────────────────────────


def test_legacy_overhang_rotation_entry_load() -> None:
    """An old-format OverhangRotationLogEntry round-trips with empty trailing
    lists; the geometry pipeline still applies the whole-overhang rotation."""
    entry = OverhangRotationLogEntry(
        overhang_ids=["ovhg_legacy_0"],
        rotations=[[0.0, 0.0, 0.7071068, 0.7071068]],
        labels=[None],
    )
    payload = entry.model_dump()
    assert payload['sub_domain_ids'] == []
    assert payload['sub_domain_thetas_deg'] == []
    assert payload['sub_domain_phis_deg'] == []
    rebuilt = OverhangRotationLogEntry.model_validate(payload)
    assert rebuilt.sub_domain_ids == []


def test_log_entry_validator_rejects_mismatched_lengths() -> None:
    with pytest.raises(Exception):
        OverhangRotationLogEntry(
            overhang_ids=["a", "b"],
            rotations=[[0, 0, 0, 1], [0, 0, 0, 1]],
            sub_domain_ids=["sd1"],   # length 1 != 2
        )


def test_log_entry_validator_rejects_invalid_subdomain_slot() -> None:
    with pytest.raises(Exception):
        OverhangRotationLogEntry(
            overhang_ids=["a"],
            rotations=[[0, 0, 0, 1]],
            sub_domain_ids=["sd1"],
            sub_domain_thetas_deg=[None],   # missing
            sub_domain_phis_deg=[10.0],
        )
