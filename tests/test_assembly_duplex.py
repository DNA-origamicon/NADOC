"""
Tests for the cross-part AssemblyDuplex model + ``backend.core.assembly_duplex``.

Covers Phase A/B of the assembly overhang convergence onto the Proposal-B Duplex
graph: the model (equal-length + self-pair validators, round-trip), the
migration from legacy AssemblyOverhangBinding, and the cross-part classifier /
coverage that reuses the per-design ``classify_antiparallel`` kernel.
"""

from __future__ import annotations

import pytest

from backend.core.assembly_duplex import (
    assembly_overhang_pairing_map,
    classify_assembly_duplex,
    summarize_assembly_duplexes,
    sync_assembly_duplexes_from_bindings,
    synthesize_assembly_duplexes_from_bindings,
)
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.models import (
    Assembly,
    AssemblyDuplex,
    AssemblyDuplexEnd,
    AssemblyOverhangBinding,
    Design,
    Direction,
    Domain,
    Helix,
    Mat4x4,
    OverhangSpec,
    PartInstance,
    PartSourceInline,
    Strand,
    StrandType,
    Vec3,
)


def _design_with_real_oh(oh_id: str, sequence: str | None) -> Design:
    length_bp = 8
    helix_id = f"hx_{oh_id}"
    strand_id = f"str_{oh_id}"
    helix = Helix(
        id=helix_id,
        axis_start=Vec3(x=0.0, y=0.0, z=0.0),
        axis_end=Vec3(x=0.0, y=0.0, z=length_bp * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        length_bp=length_bp,
    )
    direction = Direction.FORWARD if oh_id.endswith("_5p") else Direction.REVERSE
    strand = Strand(
        id=strand_id,
        domains=[
            Domain(
                helix_id=helix_id,
                start_bp=0,
                end_bp=length_bp - 1,
                direction=direction,
                overhang_id=oh_id,
            )
        ],
        strand_type=StrandType.STAPLE,
    )
    ovhg = OverhangSpec(
        id=oh_id,
        helix_id=helix_id,
        strand_id=strand_id,
        sequence=sequence,
        label=oh_id,
    )
    return Design(helices=[helix], strands=[strand], overhangs=[ovhg])


def _two_part(seq_a="ACGTACGT", seq_b="ACGTACGT") -> Assembly:
    """Two-part assembly with real OH-tagged domains. ``ACGTACGT`` is
    self-reverse-complementary, so the default pair is fully Watson-Crick."""
    d_a = _design_with_real_oh("oh-A_5p", seq_a)
    d_b = _design_with_real_oh("oh-B_3p", seq_b)
    t_b = Mat4x4(values=[1, 0, 0, 10, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])
    return Assembly(
        instances=[
            PartInstance(
                id="inst-A", name="PartA", source=PartSourceInline(design=d_a)
            ),
            PartInstance(
                id="inst-B",
                name="PartB",
                source=PartSourceInline(design=d_b),
                transform=t_b,
            ),
        ]
    )


def _binding(assembly: Assembly) -> AssemblyOverhangBinding:
    sda = assembly.instances[0].source.design.overhangs[0].sub_domains[0].id
    sdb = assembly.instances[1].source.design.overhangs[0].sub_domains[0].id
    return AssemblyOverhangBinding(
        name="AB1",
        instance_a_id="inst-A",
        sub_domain_a_id=sda,
        overhang_a_id="oh-A_5p",
        instance_b_id="inst-B",
        sub_domain_b_id=sdb,
        overhang_b_id="oh-B_3p",
    )


# ── Model ──────────────────────────────────────────────────────────────────────


def test_assembly_duplex_roundtrip_on_assembly():
    dx = AssemblyDuplex(
        name="AD1",
        left=AssemblyDuplexEnd(
            instance_id="inst-A", overhang_id="oh-A_5p", start_bp=0, end_bp=7
        ),
        right=AssemblyDuplexEnd(
            instance_id="inst-B", overhang_id="oh-B_3p", start_bp=0, end_bp=7
        ),
    )
    a = Assembly(duplexes=[dx])
    a2 = Assembly.from_json(a.to_json())
    assert len(a2.duplexes) == 1
    assert a2.duplexes[0].name == "AD1"
    assert a2.duplexes[0].left.instance_id == "inst-A"


def test_assembly_duplex_rejects_unequal_length():
    with pytest.raises(ValueError):
        AssemblyDuplex(
            left=AssemblyDuplexEnd(
                instance_id="i", overhang_id="oA", start_bp=0, end_bp=7
            ),
            right=AssemblyDuplexEnd(
                instance_id="j", overhang_id="oB", start_bp=0, end_bp=3
            ),
        )


def test_assembly_duplex_rejects_self_pair_overlap():
    with pytest.raises(ValueError):
        AssemblyDuplex(
            left=AssemblyDuplexEnd(
                instance_id="i", overhang_id="oA", start_bp=0, end_bp=3
            ),
            right=AssemblyDuplexEnd(
                instance_id="i", overhang_id="oA", start_bp=3, end_bp=0
            ),
        )


# ── Migration ──────────────────────────────────────────────────────────────────


def test_migration_from_binding_builds_register():
    a = _two_part()
    a = a.model_copy(update={"overhang_bindings": [_binding(a)]})
    dux = synthesize_assembly_duplexes_from_bindings(a)
    assert len(dux) == 1
    dx = dux[0]
    assert dx.name == "AB1"
    assert dx.left.instance_id == "inst-A" and dx.left.overhang_id == "oh-A_5p"
    assert dx.right.instance_id == "inst-B" and dx.right.overhang_id == "oh-B_3p"
    assert dx.left.length == 8 and dx.right.length == 8


def test_migration_skips_unresolved_binding():
    a = _two_part()
    bad = AssemblyOverhangBinding(
        name="ABx",
        instance_a_id="inst-A",
        sub_domain_a_id="nope",
        overhang_a_id="oh-A_5p",
        instance_b_id="inst-B",
        sub_domain_b_id="nope",
        overhang_b_id="oh-B_3p",
    )
    a = a.model_copy(update={"overhang_bindings": [bad]})
    assert synthesize_assembly_duplexes_from_bindings(a) == []


def test_sync_is_idempotent():
    a = _two_part()
    a = a.model_copy(update={"overhang_bindings": [_binding(a)]})
    a = sync_assembly_duplexes_from_bindings(a)
    assert len(a.duplexes) == 1
    a2 = sync_assembly_duplexes_from_bindings(a)
    assert len(a2.duplexes) == 1  # no duplicate for the same pair


# ── Cross-part classifier / coverage ────────────────────────────────────────────


def test_classify_full_watson_crick():
    a = _two_part(seq_a="ACGTACGT", seq_b="ACGTACGT")
    a = a.model_copy(update={"overhang_bindings": [_binding(a)]})
    a = a.model_copy(update={"duplexes": synthesize_assembly_duplexes_from_bindings(a)})
    cls = classify_assembly_duplex(a, a.duplexes[0])
    assert cls["length"] == 8
    assert cls["n_complementary"] == 8
    assert cls["n_mismatch"] == 0


def test_classify_detects_mismatch():
    # Break WC by giving B a non-complementary sequence.
    a = _two_part(seq_a="ACGTACGT", seq_b="TTTTTTTT")
    a = a.model_copy(update={"overhang_bindings": [_binding(a)]})
    a = a.model_copy(update={"duplexes": synthesize_assembly_duplexes_from_bindings(a)})
    cls = classify_assembly_duplex(a, a.duplexes[0])
    assert cls["n_mismatch"] > 0


def test_coverage_map_and_summary():
    a = _two_part()
    a = a.model_copy(update={"overhang_bindings": [_binding(a)]})
    a = a.model_copy(update={"duplexes": synthesize_assembly_duplexes_from_bindings(a)})
    cov = assembly_overhang_pairing_map(a, "inst-A", "oh-A_5p")
    assert set(cov.values()) == {"paired"}
    summary = summarize_assembly_duplexes(a)
    assert summary["overhangs"]["inst-A::oh-A_5p"]["paired"] == 8
    assert summary["overhangs"]["inst-A::oh-A_5p"]["toehold"] == 0
