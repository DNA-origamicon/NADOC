"""Biotin is a terminal modification, including after antiparallel binding."""

import pytest
from backend.core.biotin_extensions import ensure_biotin_extensions
from backend.core.design_geometry import fitting_geometry
from backend.core.duplex import (
    connect_register,
    relocate_duplex,
    revert_duplex_relocation,
)
from backend.core.models import (
    BiotinDNA,
    Design,
    Direction,
    Domain,
    Duplex,
    Helix,
    Nanoparticle,
    OverhangSpec,
    Strand,
    StrandExtension,
    Vec3,
)
from backend.physics.oxdna_interface import _walk_strand_nucleotides


def example():
    helices = [
        Helix(
            id=h,
            axis_start=Vec3(x=x, y=0, z=0),
            axis_end=Vec3(x=x, y=0, z=2.72),
            length_bp=8,
        )
        for h, x in [("target", 0), ("handle", 5)]
    ]
    strands = [
        Strand(
            id=h,
            sequence=seq,
            domains=[
                Domain(
                    helix_id=h,
                    start_bp=0,
                    end_bp=7,
                    direction=Direction.FORWARD,
                    overhang_id=h,
                )
            ],
        )
        for h, seq in [("target", "AAAAAAAA"), ("handle", "TTTTTTTT")]
    ]
    return Design(
        helices=helices,
        strands=strands,
        overhangs=[
            OverhangSpec(id=s.id, helix_id=s.id, strand_id=s.id, sequence=s.sequence)
            for s in strands
        ],
        nanoparticles=[
            Nanoparticle(
                diameter_nm=10,
                biotin_dna=[
                    BiotinDNA(strand_id="handle", helix_id="handle", chain="A")
                ],
            )
        ],
    )


def test_legacy_load_and_roundtrip_count_modification_once_not_as_dna():
    d = example()
    assert len(d.extensions) == 1
    ext = d.extensions[0]
    assert (ext.end, ext.modification, ext.sequence) == ("five_prime", "biotin", None)
    before = list(_walk_strand_nucleotides(d))
    assert len(before) == 16
    ensure_biotin_extensions(d)
    reloaded = Design.model_validate_json(d.model_dump_json())
    assert reloaded.extensions == [ext]
    assert len(list(_walk_strand_nucleotides(reloaded))) == 16
    bare = d.model_copy(update={"extensions": []})
    assert list(_walk_strand_nucleotides(bare)) == before


@pytest.mark.parametrize("end", ["five_prime", "three_prime"])
def test_extension_follows_bound_strand_and_reverts_without_entering_register(end):
    d = example()
    d.nanoparticles = []
    d.extensions = [StrandExtension(strand_id="handle", end=end, modification="biotin")]
    left, right = connect_register(d, "target", "root", "handle", "root")
    dx = Duplex(left=left, right=right, driver="left", bound=True)
    d.duplexes = [dx]
    bound = relocate_duplex(d, dx)
    handle = next(s for s in bound.strands if s.id == "handle")
    assert handle.domains[0].helix_id == "target"
    assert handle.domains[0].direction == Direction.REVERSE
    assert len(list(_walk_strand_nucleotides(bound))) == 16
    assert bound.extensions == d.extensions
    geom = fitting_geometry(bound)
    mods = [n for n in geom if n.get("modification") == "biotin"]
    assert len(mods) == 1 and mods[0]["strand_id"] == "handle"
    assert mods[0]["nucleobase"] is None
    assert any(n.get("strand_id") == "handle" and n.get("is_five_prime") for n in geom)
    restored = revert_duplex_relocation(bound, bound.duplexes[0])
    assert restored.extensions == d.extensions
    assert (
        next(s for s in restored.strands if s.id == "handle").domains[0].helix_id
        == "handle"
    )


def test_backfill_preserves_explicit_extension_identity():
    d = example()
    d.extensions[0].id = "user-chosen-id"
    assert (
        Design.model_validate_json(d.model_dump_json()).extensions[0].id
        == "user-chosen-id"
    )
