"""Tests for chained overhangs (Alt A foundation).

Covers ONLY the data-model + topology-helper layer landed in the audit-07
follow-up commit. The chain-link extrude *builder* and the chain *rotation
composition* through `apply_overhang_rotation_if_needed` /
`_apply_ovhg_rotations_to_axes` are deferred — see
`refactor_prompts/07-multi-domain-overhang-audit-FINDINGS.md`.

What is tested:
  • `OverhangSpec.parent_overhang_id` round-trip (model_dump / model_validate)
  • `_overhang_chain_root` / `_overhang_chain_path` /
    `_overhang_chain_descendants` / `_overhang_chain_links_root_first`
  • Validator rule: missing parent → fails; cycle → fails
  • Cascade-delete: removing the parent strand cascades to descendants

What is NOT tested (deferred):
  • Geometry / rotation composition through a chain
  • Building a chain link via API (no builder yet)
"""

from __future__ import annotations

from backend.core.lattice import (
    _overhang_chain_descendants,
    _overhang_chain_links_root_first,
    _overhang_chain_path,
    _overhang_chain_root,
)
from backend.core.models import (
    Design, Direction, Domain, Helix, OverhangSpec, Strand, StrandType, Vec3,
)
from backend.core.validator import validate_design


# ── Fixtures ────────────────────────────────────────────────────────────────

def _empty_design() -> Design:
    """Minimal design — one helix, one scaffold strand. Enough for the
    validator and helpers, no scaffold-coverage logic exercised."""
    helix = Helix(
        id="h0",
        axis_start=Vec3(x=0.0, y=0.0, z=0.0),
        axis_end=Vec3(x=0.0, y=0.0, z=10.0),
        phase_offset=0.0,
        length_bp=30,
    )
    scaffold = Strand(
        id="scaf",
        domains=[Domain(helix_id="h0", start_bp=0, end_bp=29, direction=Direction.FORWARD)],
        strand_type=StrandType.SCAFFOLD,
    )
    return Design(id="d", helices=[helix], strands=[scaffold])


def _strand_with_oh(strand_id: str, ovhg_id: str) -> Strand:
    return Strand(
        id=strand_id,
        domains=[Domain(
            helix_id="h0", start_bp=0, end_bp=4,
            direction=Direction.REVERSE, overhang_id=ovhg_id,
        )],
        strand_type=StrandType.STAPLE,
    )


def _design_with_chain(length: int) -> Design:
    """Design with a length-N OH chain. OH ids: oh_0, oh_1, …, oh_{N-1}.
    Each on its own dedicated strand stp_i. Parent pointer set so oh_0 is
    bundle-anchored (parent=None) and oh_i has parent=oh_{i-1}.
    """
    base = _empty_design()
    strands = list(base.strands)
    overhangs: list[OverhangSpec] = []
    for i in range(length):
        sid = f"stp_{i}"
        oid = f"oh_{i}"
        strands.append(_strand_with_oh(sid, oid))
        overhangs.append(OverhangSpec(
            id=oid,
            helix_id="h0",
            strand_id=sid,
            parent_overhang_id=(f"oh_{i-1}" if i > 0 else None),
        ))
    return base.model_copy(update={"strands": strands, "overhangs": overhangs})


# ── Data model round-trip ───────────────────────────────────────────────────

def test_parent_overhang_id_defaults_to_none() -> None:
    spec = OverhangSpec(id="oh", helix_id="h", strand_id="s")
    assert spec.parent_overhang_id is None


def test_parent_overhang_id_round_trip() -> None:
    design = _design_with_chain(3)
    dumped = design.model_dump(mode="json")
    reloaded = Design.model_validate(dumped)
    parents = {o.id: o.parent_overhang_id for o in reloaded.overhangs}
    assert parents == {"oh_0": None, "oh_1": "oh_0", "oh_2": "oh_1"}


def test_legacy_overhang_load_has_no_parent() -> None:
    """Designs saved before Alt A (no parent_overhang_id field) load with
    parent=None — Pydantic default. Guards against silently breaking old
    .nadoc files."""
    legacy_dump = {
        "id": "d",
        "helices": [{"id": "h0", "axis_start": {"x": 0, "y": 0, "z": 0},
                     "axis_end": {"x": 0, "y": 0, "z": 10}, "phase_offset": 0.0,
                     "length_bp": 30}],
        "strands": [{
            "id": "scaf",
            "domains": [{"helix_id": "h0", "start_bp": 0, "end_bp": 29, "direction": "FORWARD"}],
            "strand_type": "scaffold",
        }],
        "overhangs": [{"id": "oh", "helix_id": "h0", "strand_id": "scaf"}],
    }
    reloaded = Design.model_validate(legacy_dump)
    assert reloaded.overhangs[0].parent_overhang_id is None


# ── Chain-walk helpers ──────────────────────────────────────────────────────

def test_chain_root_walks_to_bundle_anchored_root() -> None:
    design = _design_with_chain(3)
    assert _overhang_chain_root(design, "oh_2") == "oh_0"
    assert _overhang_chain_root(design, "oh_1") == "oh_0"
    assert _overhang_chain_root(design, "oh_0") == "oh_0"


def test_chain_root_returns_none_for_unknown_id() -> None:
    design = _design_with_chain(2)
    assert _overhang_chain_root(design, "ghost") is None


def test_chain_path_root_to_leaf() -> None:
    design = _design_with_chain(3)
    assert _overhang_chain_path(design, "oh_2") == ["oh_0", "oh_1", "oh_2"]
    assert _overhang_chain_path(design, "oh_0") == ["oh_0"]


def test_chain_path_returns_empty_on_broken_chain() -> None:
    design = _design_with_chain(2)
    # Introduce a missing-parent reference.
    bad = design.overhangs[1].model_copy(update={"parent_overhang_id": "ghost"})
    design = design.model_copy(update={"overhangs": [design.overhangs[0], bad]})
    assert _overhang_chain_path(design, "oh_1") == []


def test_chain_descendants_excludes_self() -> None:
    design = _design_with_chain(4)
    desc = _overhang_chain_descendants(design, "oh_1")
    assert sorted(desc) == ["oh_2", "oh_3"]
    assert _overhang_chain_descendants(design, "oh_3") == []


def test_chain_descendants_branched() -> None:
    """oh_0 → oh_1 (chain). oh_0 → oh_2 (branch). Descendants of oh_0 = both."""
    base = _design_with_chain(1)
    strands = list(base.strands) + [_strand_with_oh("stp_b", "oh_b")]
    overhangs = list(base.overhangs) + [
        OverhangSpec(id="oh_1", helix_id="h0", strand_id="stp_1",
                     parent_overhang_id="oh_0"),
        OverhangSpec(id="oh_b", helix_id="h0", strand_id="stp_b",
                     parent_overhang_id="oh_0"),
    ]
    strands.append(_strand_with_oh("stp_1", "oh_1"))
    design = base.model_copy(update={"strands": strands, "overhangs": overhangs})
    assert sorted(_overhang_chain_descendants(design, "oh_0")) == ["oh_1", "oh_b"]


def test_chain_links_root_first_topological_order() -> None:
    design = _design_with_chain(4)
    # Reorder overhangs so children come before parents; helper must sort.
    shuffled = list(reversed(design.overhangs))
    design = design.model_copy(update={"overhangs": shuffled})
    order = [o.id for o in _overhang_chain_links_root_first(design)]
    # oh_0 must come before oh_1, etc. — exact order beyond that is irrelevant.
    assert order.index("oh_0") < order.index("oh_1") < order.index("oh_2") < order.index("oh_3")


def test_chain_links_root_first_drops_cycles() -> None:
    design = _design_with_chain(2)
    cyclic = [
        design.overhangs[0].model_copy(update={"parent_overhang_id": "oh_1"}),
        design.overhangs[1],   # parent_overhang_id="oh_0"
    ]
    design = design.model_copy(update={"overhangs": cyclic})
    order = _overhang_chain_links_root_first(design)
    assert order == []   # entire cycle is unreachable from any zero-in-degree node


# ── Validator rules ─────────────────────────────────────────────────────────

def test_validator_passes_on_valid_chain() -> None:
    design = _design_with_chain(3)
    report = validate_design(design)
    chain_results = [r for r in report.results if "chain" in r.message.lower()
                                                 or "parent" in r.message.lower()]
    # No chain-related FAILURES (no entries at all is also fine — the helper
    # is silent on success).
    for r in chain_results:
        assert r.ok, r.message


def test_validator_fails_on_missing_parent() -> None:
    design = _design_with_chain(2)
    bad = design.overhangs[1].model_copy(update={"parent_overhang_id": "ghost"})
    design = design.model_copy(update={"overhangs": [design.overhangs[0], bad]})
    report = validate_design(design)
    failures = [r for r in report.results if not r.ok]
    assert any("parent_overhang_id" in r.message and "ghost" in r.message
               for r in failures)


def test_validator_fails_on_cycle() -> None:
    design = _design_with_chain(2)
    cyclic = [
        design.overhangs[0].model_copy(update={"parent_overhang_id": "oh_1"}),
        design.overhangs[1],   # parent_overhang_id="oh_0"
    ]
    design = design.model_copy(update={"overhangs": cyclic})
    report = validate_design(design)
    failures = [r for r in report.results if not r.ok]
    assert any("cycle" in r.message.lower() for r in failures)


# ── Cascade-delete ──────────────────────────────────────────────────────────

def test_cascade_delete_removes_chain_descendants() -> None:
    """Deleting the strand owning oh_0 must remove oh_1 and oh_2 (and their
    strands) too — otherwise they would orphan with parent_overhang_id
    pointing at a missing record."""
    from backend.api.crud import _delete_regular_strands_from_design

    design = _design_with_chain(3)
    after = _delete_regular_strands_from_design(design, {"stp_0"})
    remaining_oh_ids = {o.id for o in after.overhangs}
    remaining_strand_ids = {s.id for s in after.strands}
    assert remaining_oh_ids == set()
    # The original scaffold strand must survive.
    assert "scaf" in remaining_strand_ids
    assert "stp_0" not in remaining_strand_ids
    assert "stp_1" not in remaining_strand_ids
    assert "stp_2" not in remaining_strand_ids


def test_cascade_delete_keeps_unrelated_chains() -> None:
    """Two independent chains. Deleting the root of one must NOT touch the
    other.
    """
    from backend.api.crud import _delete_regular_strands_from_design

    base = _design_with_chain(2)   # oh_0 → oh_1 on strands stp_0, stp_1
    extra_strands = list(base.strands) + [
        _strand_with_oh("stp_x", "oh_x"),
        _strand_with_oh("stp_y", "oh_y"),
    ]
    extra_overhangs = list(base.overhangs) + [
        OverhangSpec(id="oh_x", helix_id="h0", strand_id="stp_x"),
        OverhangSpec(id="oh_y", helix_id="h0", strand_id="stp_y", parent_overhang_id="oh_x"),
    ]
    design = base.model_copy(update={"strands": extra_strands, "overhangs": extra_overhangs})

    after = _delete_regular_strands_from_design(design, {"stp_0"})
    remaining = {o.id for o in after.overhangs}
    assert remaining == {"oh_x", "oh_y"}


def test_cascade_delete_mid_chain_removes_below_only() -> None:
    """Deleting the strand owning a *middle* chain link removes that link
    and everything below — but NOT the parent."""
    from backend.api.crud import _delete_regular_strands_from_design

    design = _design_with_chain(4)   # oh_0 → oh_1 → oh_2 → oh_3
    after = _delete_regular_strands_from_design(design, {"stp_2"})
    remaining = {o.id for o in after.overhangs}
    assert remaining == {"oh_0", "oh_1"}
