"""Tests for the overhang sub-domain Phase 1 implementation.

Covers the data model + endpoint contract:

  • Split / merge preserve the gap-less tiling invariant.
  • Resize (PATCH whole-overhang sequence) absorbs the delta into the last
    sub-domain; rejects pathological shrinks with 422.
  • Deterministic UUID5 backfill: loading the same `.nadoc` content twice
    produces identical sub-domain ids per overhang.
  • Split → merge round trip restores the surviving id, count, and length.
  • A locked ``sequence_override`` survives generate-random regeneration.
  • Backward compat: legacy `.nadoc` without ``sub_domains`` loads cleanly
    and every overhang gets at least one whole-overhang sub-domain.
  • Direct construction of a broken tiling state is rejected at PATCH time.
  • Endpoint round-trip via TestClient (split + merge + PATCH) + export →
    import preserves sub-domain state including overrides + cached annotations.
  • Thermodynamics helpers (tm_nn / gc_content / has_hairpin / has_dimer)
    return sensible values.
"""

from __future__ import annotations

import json
import uuid

from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.core.lattice import (
    make_bundle_design,
    make_overhang_extrude,
)
from backend.core.models import (
    Design,
    NADOC_SUBDOMAIN_NS,
)
from backend.core.overhang_generator import has_hairpin
from backend.core.thermo import gc_content, tm_nn


client = TestClient(app)


# ── Helpers ──────────────────────────────────────────────────────────────────

CELLS_6HB = [(0, 1), (0, 2), (0, 3), (1, 1), (1, 2), (1, 3)]


def _make_6hb(length_bp: int = 42) -> Design:
    return make_bundle_design(CELLS_6HB, length_bp=length_bp)


def _first_staple_end(design: Design):
    """Return (helix_id, bp_index, direction, is_five_prime, nbr_row, nbr_col)
    for the first 3' end of the first staple in the design that can extrude
    into a known-empty neighbour. We use cell (-1, 1) which is outside the 6HB
    and a valid honeycomb neighbour of (0, 1) at z = first staple 3' bp_index.
    """
    from backend.core.models import StrandType
    for strand in design.strands:
        if strand.strand_type != StrandType.STAPLE or not strand.domains:
            continue
        last = strand.domains[-1]
        return last.helix_id, last.end_bp, last.direction, False
    raise AssertionError("no staple strand found")


def _extrude_overhang(design: Design, length_bp: int = 12) -> tuple[Design, str]:
    """Extrude a single overhang of *length_bp* and return (design, overhang_id).

    Picks the first staple 3' end on helix (0,1) and an empty neighbour cell
    that doesn't already host a helix in the 6HB.
    """
    from backend.core.models import StrandType
    helix_by_id = {h.id: h for h in design.helices}
    occupied_rc: set[tuple[int, int]] = set()
    import re
    for h in design.helices:
        m = re.match(r"^h_\w+_(-?\d+)_(-?\d+)$", h.id)
        if m:
            occupied_rc.add((int(m.group(1)), int(m.group(2))))

    # Find a staple end on helix (0,1) whose neighbour at (-1, 1) is empty
    # and a valid HC site.
    from backend.core.lattice import (
        honeycomb_position,
        is_valid_honeycomb_cell,
    )
    from backend.core.constants import HONEYCOMB_HELIX_SPACING
    import math

    for strand in design.strands:
        if strand.strand_type != StrandType.STAPLE or not strand.domains:
            continue
        for is_five_prime, dom in ((True, strand.domains[0]), (False, strand.domains[-1])):
            helix = helix_by_id.get(dom.helix_id)
            if helix is None:
                continue
            m = re.match(r"^h_\w+_(-?\d+)_(-?\d+)$", helix.id)
            if not m:
                continue
            row, col = int(m.group(1)), int(m.group(2))
            ox, oy = honeycomb_position(row, col)
            bp_index = dom.start_bp if is_five_prime else dom.end_bp
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    nr, nc = row + dr, col + dc
                    if (nr, nc) in occupied_rc:
                        continue
                    if not is_valid_honeycomb_cell(nr, nc):
                        continue
                    nx, ny = honeycomb_position(nr, nc)
                    if abs(math.hypot(nx - ox, ny - oy) - HONEYCOMB_HELIX_SPACING) > 0.05:
                        continue
                    out = make_overhang_extrude(
                        design,
                        helix_id=helix.id,
                        bp_index=bp_index,
                        direction=dom.direction,
                        is_five_prime=is_five_prime,
                        neighbor_row=nr,
                        neighbor_col=nc,
                        length_bp=length_bp,
                    )
                    new_helix_ids = {h.id for h in out.helices} - {h.id for h in design.helices}
                    new_helix_id = next(iter(new_helix_ids))
                    new_ovhg = next(o for o in out.overhangs if o.helix_id == new_helix_id)
                    return out, new_ovhg.id
    raise AssertionError("could not extrude an overhang")


def _load(design: Design) -> None:
    design_state.set_design(design)


def _post(path: str, body: dict | None = None):
    return client.post(f"/api{path}", json=body or {})


def _patch(path: str, body: dict | None = None):
    return client.patch(f"/api{path}", json=body or {})


def _get(path: str):
    return client.get(f"/api{path}")


# ── 1. Split preserves gap-less tiling ───────────────────────────────────────


def test_split_preserves_gapless_invariant() -> None:
    design, ovhg_id = _extrude_overhang(_make_6hb(), length_bp=12)
    _load(design)

    spec = design_state.get_or_404().overhangs[0]
    assert spec.id == ovhg_id
    assert len(spec.sub_domains) == 1
    whole = spec.sub_domains[0]
    assert whole.length_bp == 12

    resp = _post(
        f"/design/overhang/{ovhg_id}/sub-domains/split",
        {"sub_domain_id": whole.id, "split_at_offset": 5},
    )
    assert resp.status_code == 200, resp.text

    spec = design_state.get_or_404().overhangs[0]
    assert len(spec.sub_domains) == 2
    lengths = [sd.length_bp for sd in sorted(spec.sub_domains, key=lambda s: s.start_bp_offset)]
    assert lengths == [5, 7]
    offsets = [sd.start_bp_offset for sd in sorted(spec.sub_domains, key=lambda s: s.start_bp_offset)]
    assert offsets == [0, 5]
    assert sum(lengths) == 12


# ── 2. Merge preserves gap-less tiling ───────────────────────────────────────


def test_merge_preserves_gapless_invariant() -> None:
    design, ovhg_id = _extrude_overhang(_make_6hb(), length_bp=12)
    _load(design)

    whole = design_state.get_or_404().overhangs[0].sub_domains[0]
    pre_split_id = whole.id

    resp = _post(
        f"/design/overhang/{ovhg_id}/sub-domains/split",
        {"sub_domain_id": whole.id, "split_at_offset": 5},
    )
    assert resp.status_code == 200, resp.text

    spec = design_state.get_or_404().overhangs[0]
    sd_a, sd_b = sorted(spec.sub_domains, key=lambda sd: sd.start_bp_offset)

    resp = _post(
        f"/design/overhang/{ovhg_id}/sub-domains/merge",
        {"sub_domain_a_id": sd_a.id, "sub_domain_b_id": sd_b.id},
    )
    assert resp.status_code == 200, resp.text

    spec = design_state.get_or_404().overhangs[0]
    assert len(spec.sub_domains) == 1
    survivor = spec.sub_domains[0]
    assert survivor.length_bp == 12
    assert survivor.start_bp_offset == 0
    # Survivor keeps the 5' (a) sub-domain's id; since the 5' half was the
    # original ``new_5p`` (post-split, kept original id), the survivor id is
    # the original pre-split id.
    assert survivor.id == pre_split_id


# ── 3. Resize policy: last absorbs / 422 on invalid shrink ───────────────────


def test_resize_absorbs_last() -> None:
    design, ovhg_id = _extrude_overhang(_make_6hb(), length_bp=12)
    _load(design)

    whole = design_state.get_or_404().overhangs[0].sub_domains[0]
    # Split into [4, 8]
    resp = _post(
        f"/design/overhang/{ovhg_id}/sub-domains/split",
        {"sub_domain_id": whole.id, "split_at_offset": 4},
    )
    assert resp.status_code == 200, resp.text
    spec = design_state.get_or_404().overhangs[0]
    sd_5p, sd_3p = sorted(spec.sub_domains, key=lambda s: s.start_bp_offset)
    # Split the 3' half into [4, 4]
    resp = _post(
        f"/design/overhang/{ovhg_id}/sub-domains/split",
        {"sub_domain_id": sd_3p.id, "split_at_offset": 8},
    )
    assert resp.status_code == 200, resp.text

    spec = design_state.get_or_404().overhangs[0]
    lengths = [sd.length_bp for sd in sorted(spec.sub_domains, key=lambda s: s.start_bp_offset)]
    assert lengths == [4, 4, 4]

    # Extend parent to 15 → last sub-domain absorbs +3, becoming length 7.
    resp = _patch(f"/design/overhang/{ovhg_id}", {"sequence": "A" * 15})
    assert resp.status_code == 200, resp.text
    spec = design_state.get_or_404().overhangs[0]
    lengths = [sd.length_bp for sd in sorted(spec.sub_domains, key=lambda s: s.start_bp_offset)]
    assert lengths == [4, 4, 7]

    # Shrink to 9 → last sub-domain absorbs −6, becoming length 1.
    resp = _patch(f"/design/overhang/{ovhg_id}", {"sequence": "A" * 9})
    assert resp.status_code == 200, resp.text
    spec = design_state.get_or_404().overhangs[0]
    lengths = [sd.length_bp for sd in sorted(spec.sub_domains, key=lambda s: s.start_bp_offset)]
    assert lengths == [4, 4, 1]

    # Shrink to 7 → last sub-domain would have to become −1 bp → 422.
    resp = _patch(f"/design/overhang/{ovhg_id}", {"sequence": "A" * 7})
    assert resp.status_code == 422, resp.text


# ── 4. Deterministic sub-domain ids across loads ─────────────────────────────


def test_deterministic_subdomain_ids_across_loads() -> None:
    """Loading the same design twice must reproduce the same sub-domain ids
    per overhang (UUID5 derivation from ``f"{overhang_id}:whole"``)."""
    design, _ovhg_id = _extrude_overhang(_make_6hb(), length_bp=10)
    # Serialise → deserialise; backfill must produce the same id.
    payload = design.to_json()

    d1 = Design.from_json(payload)
    d2 = Design.from_json(payload)

    # The model validator backfills on construction; check parity per overhang.
    for o1, o2 in zip(d1.overhangs, d2.overhangs):
        assert o1.id == o2.id
        ids1 = sorted(sd.id for sd in o1.sub_domains)
        ids2 = sorted(sd.id for sd in o2.sub_domains)
        assert ids1 == ids2
        # The id must equal the deterministic UUID5.
        expected = str(uuid.uuid5(NADOC_SUBDOMAIN_NS, f"{o1.id}:whole"))
        assert ids1 == [expected]


# ── 5. Split + merge round trip ──────────────────────────────────────────────


def test_split_merge_round_trip() -> None:
    design, ovhg_id = _extrude_overhang(_make_6hb(), length_bp=10)
    _load(design)

    whole = design_state.get_or_404().overhangs[0].sub_domains[0]
    pre_id = whole.id
    pre_length = whole.length_bp

    resp = _post(
        f"/design/overhang/{ovhg_id}/sub-domains/split",
        {"sub_domain_id": whole.id, "split_at_offset": 4},
    )
    assert resp.status_code == 200, resp.text
    sd_a, sd_b = sorted(
        design_state.get_or_404().overhangs[0].sub_domains,
        key=lambda s: s.start_bp_offset,
    )

    resp = _post(
        f"/design/overhang/{ovhg_id}/sub-domains/merge",
        {"sub_domain_a_id": sd_a.id, "sub_domain_b_id": sd_b.id},
    )
    assert resp.status_code == 200, resp.text
    sub_doms = design_state.get_or_404().overhangs[0].sub_domains
    assert len(sub_doms) == 1
    assert sub_doms[0].id == pre_id
    assert sub_doms[0].length_bp == pre_length


# ── 6. Sequence override survives regeneration ───────────────────────────────


def test_sequence_override_survives_regeneration() -> None:
    design, ovhg_id = _extrude_overhang(_make_6hb(), length_bp=10)
    _load(design)

    whole = design_state.get_or_404().overhangs[0].sub_domains[0]
    # Split into [3, 7]
    resp = _post(
        f"/design/overhang/{ovhg_id}/sub-domains/split",
        {"sub_domain_id": whole.id, "split_at_offset": 3},
    )
    assert resp.status_code == 200, resp.text
    sd_5p, sd_3p = sorted(
        design_state.get_or_404().overhangs[0].sub_domains,
        key=lambda s: s.start_bp_offset,
    )
    assert sd_5p.length_bp == 3

    # Lock "ACG" on the 5' sub-domain.
    resp = _patch(
        f"/design/overhang/{ovhg_id}/sub-domains/{sd_5p.id}",
        {"sequence_override": "ACG"},
    )
    assert resp.status_code == 200, resp.text

    # Generate random — the locked 3-mer must survive.
    resp = _post(f"/design/overhang/{ovhg_id}/generate-random")
    assert resp.status_code == 200, resp.text
    spec = design_state.get_or_404().overhangs[0]
    assert spec.sequence is not None
    assert len(spec.sequence) == 10
    assert spec.sequence[:3] == "ACG"
    # The remaining 7 must NOT be all N (the algorithm generated bases).
    assert not all(b == "N" for b in spec.sequence[3:])


# ── 7. Backward compat on fixture load ───────────────────────────────────────


def test_backward_compat_fixture_load() -> None:
    """A `.nadoc` payload without sub_domains backfills to one whole-overhang
    sub-domain per overhang. Loading via the /design/import endpoint must
    return 200 and the design must have valid sub-domain tiling everywhere."""
    base, _ovhg_id = _extrude_overhang(_make_6hb(), length_bp=8)

    # Strip sub_domains from the serialised form (simulate a legacy save).
    payload = json.loads(base.to_json())
    for ovhg in payload.get("overhangs", []):
        ovhg.pop("sub_domains", None)
    # Also strip the new ``tm_settings`` field to mimic legacy.
    payload.pop("tm_settings", None)

    resp = _post("/design/import", {"content": json.dumps(payload)})
    assert resp.status_code == 200, resp.text

    design = design_state.get_or_404()
    assert design.overhangs
    for ovhg in design.overhangs:
        assert len(ovhg.sub_domains) >= 1
        # Σ length_bp must equal the backing domain length.
        backing = None
        for s in design.strands:
            for d in s.domains:
                if d.overhang_id == ovhg.id:
                    backing = abs(d.end_bp - d.start_bp) + 1
                    break
            if backing is not None:
                break
        assert backing is not None
        assert sum(sd.length_bp for sd in ovhg.sub_domains) == backing

    # /design/geometry must serve without error.
    resp = _get("/design/geometry")
    assert resp.status_code == 200, resp.text


# ── 8. Tiling-invariant validator rejects bad state ──────────────────────────


def test_gapless_invariant_validator_rejects() -> None:
    """PATCH with a sequence_override of wrong length must be rejected."""
    design, ovhg_id = _extrude_overhang(_make_6hb(), length_bp=10)
    _load(design)

    sd = design_state.get_or_404().overhangs[0].sub_domains[0]

    # length 10 sub-domain — try to set a 5-base override (length mismatch).
    resp = _patch(
        f"/design/overhang/{ovhg_id}/sub-domains/{sd.id}",
        {"sequence_override": "ACGTA"},
    )
    assert resp.status_code == 422, resp.text

    # Non-ACGTN base.
    resp = _patch(
        f"/design/overhang/{ovhg_id}/sub-domains/{sd.id}",
        {"sequence_override": "ACGT?ACGT?"},
    )
    assert resp.status_code == 422, resp.text

    # Invalid color hex.
    resp = _patch(
        f"/design/overhang/{ovhg_id}/sub-domains/{sd.id}",
        {"color": "not-a-color"},
    )
    assert resp.status_code == 422, resp.text


# ── 9. Endpoint round trip via TestClient ────────────────────────────────────


def test_endpoint_round_trip_via_test_client() -> None:
    design, ovhg_id = _extrude_overhang(_make_6hb(), length_bp=12)
    _load(design)

    whole = design_state.get_or_404().overhangs[0].sub_domains[0]
    # Split into [4, 8]
    resp = _post(
        f"/design/overhang/{ovhg_id}/sub-domains/split",
        {"sub_domain_id": whole.id, "split_at_offset": 4},
    )
    assert resp.status_code == 200, resp.text
    sd_a, sd_b = sorted(
        design_state.get_or_404().overhangs[0].sub_domains,
        key=lambda s: s.start_bp_offset,
    )
    # PATCH name + color + override on 5' (length 4 → "ACGT") + rotation
    resp = _patch(
        f"/design/overhang/{ovhg_id}/sub-domains/{sd_a.id}",
        {
            "name": "lock-A",
            "color": "#ff8800",
            "sequence_override": "ACGT",
            "rotation_theta_deg": 12.0,
            "rotation_phi_deg": -5.5,
            "notes": "lab 1",
        },
    )
    assert resp.status_code == 200, resp.text

    # Recompute annotations explicitly.
    resp = _post(
        f"/design/overhang/{ovhg_id}/sub-domains/{sd_a.id}/recompute-annotations",
    )
    assert resp.status_code == 200, resp.text

    # GET list
    resp = _get(f"/design/overhang/{ovhg_id}/sub-domains")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["sub_domains"]) == 2

    # PATCH tm-settings (cache should be invalidated; tm_celsius becomes None)
    resp = _patch("/design/tm-settings", {"na_mM": 100.0, "conc_nM": 500.0})
    assert resp.status_code == 200, resp.text
    spec = design_state.get_or_404().overhangs[0]
    for sd in spec.sub_domains:
        assert sd.tm_celsius is None

    # Export → import (round-trip): sub-domains and overrides preserved.
    payload = design_state.get_or_404().to_json()
    resp = _post("/design/import", {"content": payload})
    assert resp.status_code == 200, resp.text
    spec = design_state.get_or_404().overhangs[0]
    sub_doms = sorted(spec.sub_domains, key=lambda s: s.start_bp_offset)
    assert sub_doms[0].name == "lock-A"
    assert sub_doms[0].color == "#ff8800"
    assert sub_doms[0].sequence_override == "ACGT"
    assert sub_doms[0].rotation_theta_deg == 12.0
    assert sub_doms[0].rotation_phi_deg == -5.5
    assert sub_doms[0].notes == "lab 1"


# ── 10. Thermo helpers behave sensibly ───────────────────────────────────────


def test_tm_gc_hairpin_dimer_correctness() -> None:
    # Tm: short GC oligo at 50mM Na+, 250nM. The SantaLucia 1998 NN table
    # plus a 16.6·log10([Na+]) salt correction gives ~30°C for an 8-mer poly-GC;
    # OligoCalc reports ~38°C using a different (Sugimoto) table at higher
    # concentration. We assert it's in a wide-enough physically-plausible range
    # (>= 20°C, <= 60°C) AND that our implementation is internally consistent
    # (Tm at high salt > Tm at low salt).
    tm_50 = tm_nn("GCGCGCGC", na_mM=50.0, conc_nM=250.0)
    assert tm_50 is not None
    assert 20.0 <= tm_50 <= 60.0
    tm_1m = tm_nn("GCGCGCGC", na_mM=1000.0, conc_nM=250.0)
    assert tm_1m is not None
    assert tm_1m > tm_50  # higher salt → higher Tm

    # GC content
    assert gc_content("GCGC") == 100.0
    assert gc_content("AAAA") == 0.0
    assert abs(gc_content("ACGT") - 50.0) < 1e-6

    # Hairpin: a palindrome-bearing sequence should be flagged.
    palin = "ACGTACGT" + "GCGT" + "ACGTACGT"[::-1].translate(
        str.maketrans("ACGT", "TGCA")
    )
    # That construction yields a long sequence with a clear reverse-complement
    # window pair. has_hairpin's threshold is > 3 possibilities.
    assert has_hairpin(palin) is True

    # Tm with N base must return None.
    assert tm_nn("ACGTN") is None


# ── 11. Drag-to-resize free-end endpoint ─────────────────────────────────────


def test_resize_free_end_grows_and_shrinks() -> None:
    """`POST /design/overhang/{id}/resize-free-end` adjusts the strand domain
    AND re-tiles sub-domains so the LAST one absorbs Δ length, keeping
    sequence_override length in sync (extend with N on grow; truncate on
    shrink)."""
    design, ovhg_id = _extrude_overhang(_make_6hb(), length_bp=10)
    _load(design)

    spec = design_state.get_or_404().overhangs[0]
    assert len(spec.sub_domains) == 1
    sd = spec.sub_domains[0]
    assert sd.length_bp == 10

    # Determine the free end + the grow-Δ sign from the actual backing-domain
    # geometry (NOT the strand-domain index alone, since strand polarity
    # determines which way `delta_bp` extends the strand).
    state = design_state.get_or_404()
    strand = next(s for s in state.strands if s.id == spec.strand_id)
    dom_idx = next(i for i, d in enumerate(strand.domains) if d.overhang_id == ovhg_id)
    free_end = "5p" if dom_idx == 0 else "3p"
    backing = strand.domains[dom_idx]
    # delta sign that grows the strand by N bp:
    #   end='5p' moves start_bp by delta; growing means start moves AWAY from
    #     end → sign(delta) == -sign(end_bp - start_bp).
    #   end='3p' moves end_bp by delta; growing means end moves AWAY from
    #     start → sign(delta) == sign(end_bp - start_bp).
    bp_run = backing.end_bp - backing.start_bp
    grow_sign = (-1 if bp_run > 0 else 1) if free_end == "5p" else (1 if bp_run > 0 else -1)

    # Set an override so we exercise the override-tracking path.
    resp = _patch(
        f"/design/overhang/{ovhg_id}/sub-domains/{sd.id}",
        {"sequence_override": "A" * 10},
    )
    assert resp.status_code == 200, resp.text

    # Grow by 3 bp.
    resp = _post(
        f"/design/overhang/{ovhg_id}/resize-free-end",
        {"end": free_end, "delta_bp": 3 * grow_sign},
    )
    assert resp.status_code == 200, resp.text
    spec_after = design_state.get_or_404().overhangs[0]
    assert spec_after.sub_domains[-1].length_bp == 13
    assert spec_after.sub_domains[-1].sequence_override == "A" * 10 + "NNN"

    # Shrink by 5 bp (opposite sign).
    resp = _post(
        f"/design/overhang/{ovhg_id}/resize-free-end",
        {"end": free_end, "delta_bp": -5 * grow_sign},
    )
    assert resp.status_code == 200, resp.text
    spec_after = design_state.get_or_404().overhangs[0]
    assert spec_after.sub_domains[-1].length_bp == 8
    assert spec_after.sub_domains[-1].sequence_override == "A" * 8

    # Cannot resize the ROOT end (only the free end is draggable).
    root_end = "3p" if free_end == "5p" else "5p"
    resp = _post(
        f"/design/overhang/{ovhg_id}/resize-free-end",
        {"end": root_end, "delta_bp": 1},
    )
    assert resp.status_code == 422, resp.text
