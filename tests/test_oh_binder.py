"""Tests for the OH-binder (overhang-binding oligo) feature.

Covers: the StrandType.OH_BINDER enum + Domain.binds_overhang_id field, the
convert-to-binder operation (links + tags partner overhang), the keystone
scaffold-coverage regression, pen-tool auto-designation, linker complement
unification, and bidirectional reverse-complement sequence sync.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.core.lattice import (
    _scaffold_coverage_by_helix,
    convert_strand_to_binder,
    convert_binder_to_scaffold,
    tag_painted_binder,
    make_binder_for_overhang,
    generate_linker_topology,
)
from backend.core.models import (
    Design,
    Helix,
    Strand,
    Domain,
    Direction,
    StrandType,
    Vec3,
    OverhangSpec,
    SubDomain,
    OverhangConnection,
    NADOC_SUBDOMAIN_NS,
)
from backend.core.sequences import (
    assign_staple_sequences,
    is_watson_crick_complement,
)

client = TestClient(app)


def _design_with_overhang_and_complement(
    *, binder_type=StrandType.SCAFFOLD, binder_binds=None, overhang_seq=None
):
    """One helix; a staple whose single domain is a tagged overhang tip, plus a
    strand antiparallel over the same bp range (the prospective binder)."""
    h = Helix(
        id="h0",
        axis_start=Vec3(x=0, y=0, z=0),
        axis_end=Vec3(x=0, y=0, z=20),
        length_bp=40,
        bp_start=0,
    )
    oh_dom = Domain(
        helix_id="h0",
        start_bp=20,
        end_bp=27,
        direction=Direction.FORWARD,
        overhang_id="ovhg_test",
    )
    staple = Strand(id="stap", strand_type=StrandType.STAPLE, domains=[oh_dom])
    spec = OverhangSpec(
        id="ovhg_test",
        helix_id="h0",
        strand_id="stap",
        sequence=overhang_seq,
        sub_domains=[
            SubDomain(
                id=str(uuid.uuid5(NADOC_SUBDOMAIN_NS, "ovhg_test:whole")),
                name="a",
                start_bp_offset=0,
                length_bp=8,
            )
        ],
    )
    binder = Strand(
        id="bind",
        strand_type=binder_type,
        domains=[
            Domain(
                helix_id="h0",
                start_bp=27,
                end_bp=20,
                direction=Direction.REVERSE,
                binds_overhang_id=binder_binds,
            )
        ],
    )
    return Design(helices=[h], strands=[staple, binder], overhangs=[spec])


# ── Model ─────────────────────────────────────────────────────────────────────


def test_strand_type_enum_has_oh_binder():
    assert StrandType.OH_BINDER.value == "oh_binder"


def test_domain_binds_overhang_field_default_and_property():
    d = Domain(helix_id="h", start_bp=0, end_bp=5, direction=Direction.FORWARD)
    assert d.binds_overhang_id is None
    s = Strand(strand_type=StrandType.OH_BINDER, domains=[d])
    assert s.is_oh_binder is True
    assert Strand(strand_type=StrandType.STAPLE, domains=[d]).is_oh_binder is False


def test_oh_binder_json_round_trip():
    d = _design_with_overhang_and_complement(
        binder_type=StrandType.OH_BINDER, binder_binds="ovhg_test"
    )
    reloaded = Design.model_validate_json(d.model_dump_json())
    b = next(s for s in reloaded.strands if s.id == "bind")
    assert b.strand_type == StrandType.OH_BINDER
    assert b.domains[0].binds_overhang_id == "ovhg_test"


# ── Convert ─────────────────────────────────────────────────────────────────--


def test_convert_links_and_keeps_existing_overhang():
    d = _design_with_overhang_and_complement()
    d2 = convert_strand_to_binder(d, "bind")
    binder = next(s for s in d2.strands if s.id == "bind")
    assert binder.strand_type == StrandType.OH_BINDER
    assert binder.color is not None
    # links to the pre-existing overhang (no new OverhangSpec created)
    assert binder.domains[0].binds_overhang_id == "ovhg_test"
    assert len(d2.overhangs) == 1


def test_convert_tags_untagged_partner_as_overhang():
    # Partner staple has NO overhang_id yet — convert must create one.
    h = Helix(
        id="h0",
        axis_start=Vec3(x=0, y=0, z=0),
        axis_end=Vec3(x=0, y=0, z=20),
        length_bp=40,
        bp_start=0,
    )
    staple = Strand(
        id="stap",
        strand_type=StrandType.STAPLE,
        domains=[
            Domain(helix_id="h0", start_bp=20, end_bp=27, direction=Direction.FORWARD)
        ],
    )
    binder = Strand(
        id="bind",
        strand_type=StrandType.SCAFFOLD,
        domains=[
            Domain(helix_id="h0", start_bp=27, end_bp=20, direction=Direction.REVERSE)
        ],
    )
    d = Design(helices=[h], strands=[staple, binder])
    d2 = convert_strand_to_binder(d, "bind")
    new_ovhg_id = (
        next(s for s in d2.strands if s.id == "bind").domains[0].binds_overhang_id
    )
    assert new_ovhg_id is not None
    partner = next(s for s in d2.strands if s.id == "stap")
    assert partner.domains[0].overhang_id == new_ovhg_id
    spec = next(o for o in d2.overhangs if o.id == new_ovhg_id)
    assert spec.strand_id == "stap"
    assert len(spec.sub_domains) == 1 and spec.sub_domains[0].length_bp == 8


def test_convert_no_partner_raises():
    h = Helix(
        id="h0",
        axis_start=Vec3(x=0, y=0, z=0),
        axis_end=Vec3(x=0, y=0, z=20),
        length_bp=40,
        bp_start=0,
    )
    lonely = Strand(
        id="lonely",
        strand_type=StrandType.SCAFFOLD,
        domains=[
            Domain(helix_id="h0", start_bp=0, end_bp=7, direction=Direction.FORWARD)
        ],
    )
    d = Design(helices=[h], strands=[lonely])
    with pytest.raises(ValueError):
        convert_strand_to_binder(d, "lonely")


def test_convert_endpoint_round_trip():
    design_state.set_design(_design_with_overhang_and_complement())
    r = client.post("/api/design/strands/bind/convert-to-binder")
    assert r.status_code == 200, r.text
    design = r.json()["design"]
    binder = next(s for s in design["strands"] if s["id"] == "bind")
    assert binder["strand_type"] == "oh_binder"
    assert binder["domains"][0]["binds_overhang_id"] == "ovhg_test"


def test_convert_endpoint_404_on_missing():
    design_state.set_design(_design_with_overhang_and_complement())
    r = client.post("/api/design/strands/nope/convert-to-binder")
    assert r.status_code == 404


# ── Convert back to scaffold (reverse) ───────────────────────────────────────-


def test_convert_back_to_scaffold_round_trip_removes_auto_overhang():
    # scaffold → binder (auto-creates an overhang) → scaffold (removes it).
    h = Helix(
        id="h0",
        axis_start=Vec3(x=0, y=0, z=0),
        axis_end=Vec3(x=0, y=0, z=20),
        length_bp=40,
        bp_start=0,
    )
    staple = Strand(
        id="stap",
        strand_type=StrandType.STAPLE,
        domains=[
            Domain(helix_id="h0", start_bp=20, end_bp=27, direction=Direction.FORWARD)
        ],
    )
    binder = Strand(
        id="bind",
        strand_type=StrandType.SCAFFOLD,
        domains=[
            Domain(helix_id="h0", start_bp=27, end_bp=20, direction=Direction.REVERSE)
        ],
    )
    d = Design(helices=[h], strands=[staple, binder])
    d2 = convert_strand_to_binder(d, "bind")
    assert len(d2.overhangs) == 1
    d3 = convert_binder_to_scaffold(d2, "bind")
    b = next(s for s in d3.strands if s.id == "bind")
    p = next(s for s in d3.strands if s.id == "stap")
    assert b.strand_type == StrandType.SCAFFOLD and b.color is None
    assert b.domains[0].binds_overhang_id is None
    assert p.domains[0].overhang_id is None  # auto-created overhang removed
    assert d3.overhangs == []


def test_convert_back_keeps_preexisting_overhang():
    d = _design_with_overhang_and_complement()  # overhang ovhg_test pre-exists
    d2 = convert_strand_to_binder(d, "bind")
    assert (
        next(s for s in d2.strands if s.id == "bind").domains[0].binds_overhang_id
        == "ovhg_test"
    )
    d3 = convert_binder_to_scaffold(d2, "bind")
    assert (
        next(s for s in d3.strands if s.id == "bind").strand_type == StrandType.SCAFFOLD
    )
    assert [o.id for o in d3.overhangs] == ["ovhg_test"]  # pre-existing kept
    assert (
        next(s for s in d3.strands if s.id == "stap").domains[0].overhang_id
        == "ovhg_test"
    )


def test_convert_to_scaffold_endpoint():
    design_state.set_design(
        _design_with_overhang_and_complement(
            binder_type=StrandType.OH_BINDER, binder_binds="ovhg_test"
        )
    )
    r = client.post("/api/design/strands/bind/convert-to-scaffold")
    assert r.status_code == 200, r.text
    binder = next(s for s in r.json()["design"]["strands"] if s["id"] == "bind")
    assert binder["strand_type"] == "scaffold"
    assert binder["domains"][0]["binds_overhang_id"] is None


def test_convert_to_scaffold_endpoint_404():
    design_state.set_design(_design_with_overhang_and_complement())
    assert (
        client.post("/api/design/strands/nope/convert-to-scaffold").status_code == 404
    )


# ── Keystone scaffold-coverage regression ───────────────────────────────────--


def test_binder_strand_not_counted_as_scaffold_coverage():
    d = _design_with_overhang_and_complement(
        binder_type=StrandType.OH_BINDER, binder_binds="ovhg_test"
    )
    cov = _scaffold_coverage_by_helix(d)
    # No genuine scaffold strand → no coverage, even though a binder spans h0.
    assert "h0" not in cov


# ── Pen-tool auto-designation ────────────────────────────────────────────────-


def test_tag_painted_binder_over_existing_overhang():
    d = _design_with_overhang_and_complement()  # binder strand still SCAFFOLD here
    fresh = Strand(
        id="painted",
        strand_type=StrandType.STAPLE,
        domains=[
            Domain(helix_id="h0", start_bp=27, end_bp=20, direction=Direction.REVERSE)
        ],
    )
    tagged = tag_painted_binder(d, fresh)
    assert tagged.strand_type == StrandType.OH_BINDER
    assert tagged.domains[0].binds_overhang_id == "ovhg_test"


def test_tag_painted_binder_noop_without_overhang():
    h = Helix(
        id="h0",
        axis_start=Vec3(x=0, y=0, z=0),
        axis_end=Vec3(x=0, y=0, z=20),
        length_bp=40,
        bp_start=0,
    )
    d = Design(helices=[h], strands=[])
    fresh = Strand(
        id="painted",
        strand_type=StrandType.STAPLE,
        domains=[
            Domain(helix_id="h0", start_bp=0, end_bp=7, direction=Direction.FORWARD)
        ],
    )
    assert tag_painted_binder(d, fresh).strand_type == StrandType.STAPLE


# ── Generate binder for overhang ─────────────────────────────────────────────-


def test_make_binder_for_overhang_with_sequence():
    d = _design_with_overhang_and_complement(overhang_seq="AAACCCGG")
    # drop the prospective binder strand so only the staple+overhang remain
    d = d.model_copy(update={"strands": [s for s in d.strands if s.id != "bind"]})
    out = make_binder_for_overhang(d, "ovhg_test")
    binder = next(s for s in out.strands if s.strand_type == StrandType.OH_BINDER)
    dom = binder.domains[0]
    assert dom.binds_overhang_id == "ovhg_test"
    assert dom.direction == Direction.REVERSE  # antiparallel to FORWARD overhang
    assert (dom.start_bp, dom.end_bp) == (27, 20)  # same bp range, swapped
    assert binder.sequence == "CCGGGTTT"  # reverse complement
    assert is_watson_crick_complement(binder.sequence, "AAACCCGG")


def test_make_binder_for_overhang_without_sequence():
    d = _design_with_overhang_and_complement(overhang_seq=None)
    d = d.model_copy(update={"strands": [s for s in d.strands if s.id != "bind"]})
    out = make_binder_for_overhang(d, "ovhg_test")
    binder = next(s for s in out.strands if s.strand_type == StrandType.OH_BINDER)
    assert binder.sequence is None
    assert abs(binder.domains[0].end_bp - binder.domains[0].start_bp) + 1 == 8


def test_generate_binder_endpoint():
    design_state.set_design(
        _design_with_overhang_and_complement(overhang_seq="AAACCCGG")
    )
    r = client.post("/api/design/overhang/ovhg_test/generate-binder")
    assert r.status_code == 201, r.text
    strands = r.json()["design"]["strands"]
    binders = [s for s in strands if s["strand_type"] == "oh_binder"]
    assert any(b["domains"][0]["binds_overhang_id"] == "ovhg_test" for b in binders)


def test_generate_binder_endpoint_404():
    design_state.set_design(_design_with_overhang_and_complement())
    assert (
        client.post("/api/design/overhang/missing/generate-binder").status_code == 404
    )


# ── Sequence sync (overhang → binder) ────────────────────────────────────────-


def test_overhang_to_binder_reverse_complement():
    d = _design_with_overhang_and_complement(
        binder_type=StrandType.OH_BINDER,
        binder_binds="ovhg_test",
        overhang_seq="AAACCCGG",
    )
    # Add a sequenced scaffold so assign_staple_sequences runs.
    scaf = Strand(
        id="scaf",
        strand_type=StrandType.SCAFFOLD,
        domains=[
            Domain(helix_id="h0", start_bp=0, end_bp=7, direction=Direction.FORWARD)
        ],
        sequence="ACGTACGT",
    )
    d = d.model_copy(update={"strands": [scaf, *d.strands]})
    out = assign_staple_sequences(d)
    binder_seq = next(s for s in out.strands if s.id == "bind").sequence
    assert binder_seq == "CCGGGTTT"  # antiparallel reverse complement
    assert is_watson_crick_complement(binder_seq, "AAACCCGG")


def test_overhang_to_binder_partial_sequence_pads_n():
    # Overhang sequence shorter than the 8-bp domain (LESSONS F3).
    d = _design_with_overhang_and_complement(
        binder_type=StrandType.OH_BINDER, binder_binds="ovhg_test", overhang_seq="AAAA"
    )
    scaf = Strand(
        id="scaf",
        strand_type=StrandType.SCAFFOLD,
        domains=[
            Domain(helix_id="h0", start_bp=0, end_bp=7, direction=Direction.FORWARD)
        ],
        sequence="ACGTACGT",
    )
    d = d.model_copy(update={"strands": [scaf, *d.strands]})
    out = assign_staple_sequences(d)
    binder_seq = next(s for s in out.strands if s.id == "bind").sequence
    assert len(binder_seq) == 8
    # Overhang 5'→3' = AAAA + NNNN; binder 5'→3' = revcomp = NNNN + TTTT
    assert binder_seq == "NNNNTTTT"


# ── Linker complement unification ────────────────────────────────────────────-


def test_linker_complement_domains_carry_binds_overhang_id():
    h = Helix(
        id="oh_a",
        axis_start=Vec3(x=0, y=0, z=0),
        axis_end=Vec3(x=0, y=0, z=8),
        length_bp=8,
        bp_start=0,
        grid_pos=(0, 0),
    )
    h2 = Helix(
        id="oh_b",
        axis_start=Vec3(x=3, y=0, z=0),
        axis_end=Vec3(x=3, y=0, z=8),
        length_bp=8,
        bp_start=0,
        grid_pos=(0, 3),
    )
    sa = Strand(
        id="sa",
        strand_type=StrandType.STAPLE,
        domains=[
            Domain(
                helix_id="oh_a",
                start_bp=0,
                end_bp=7,
                direction=Direction.FORWARD,
                overhang_id="oh_a_5p",
            )
        ],
    )
    sb = Strand(
        id="sb",
        strand_type=StrandType.STAPLE,
        domains=[
            Domain(
                helix_id="oh_b",
                start_bp=0,
                end_bp=7,
                direction=Direction.REVERSE,
                overhang_id="oh_b_5p",
            )
        ],
    )
    overhangs = [
        OverhangSpec(id="oh_a_5p", helix_id="oh_a", strand_id="sa", label="OHA"),
        OverhangSpec(id="oh_b_5p", helix_id="oh_b", strand_id="sb", label="OHB"),
    ]
    d = Design(helices=[h, h2], strands=[sa, sb], overhangs=overhangs)
    conn = OverhangConnection(
        overhang_a_id="oh_a_5p",
        overhang_a_attach="free_end",
        overhang_b_id="oh_b_5p",
        overhang_b_attach="free_end",
        linker_type="ds",
        length_value=6,
        length_unit="bp",
    )
    out = generate_linker_topology(d, conn)
    linker_strands = [s for s in out.strands if s.strand_type == StrandType.LINKER]
    assert linker_strands
    bound = {
        d.binds_overhang_id
        for s in linker_strands
        for d in s.domains
        if d.binds_overhang_id is not None
    }
    assert bound == {"oh_a_5p", "oh_b_5p"}
