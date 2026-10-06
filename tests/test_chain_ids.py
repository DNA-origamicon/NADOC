"""Large-design chain bookkeeping must agree across construction and export."""

import pytest

from backend.core.chain_ids import alphabetic_chain_id, alphabetic_chain_index


@pytest.mark.parametrize(
    ("index", "label"),
    [
        (0, "A"),
        (25, "Z"),
        (26, "AA"),
        (51, "AZ"),
        (52, "BA"),
        (701, "ZZ"),
        (702, "AAA"),
        (3061, "DMT"),
        (18277, "ZZZ"),
        (18278, "AAAA"),
    ],
)
def test_chain_labels_at_boundaries(index, label):
    assert alphabetic_chain_id(index) == label
    assert alphabetic_chain_index(label) == index


def test_existing_702_chain_labels_are_unchanged():
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    original_labels = list(letters) + [a + b for a in letters for b in letters]
    assert [alphabetic_chain_id(i) for i in range(702)] == original_labels


def test_chain_labels_reject_invalid_inputs():
    with pytest.raises(ValueError):
        alphabetic_chain_id(-1)
    for label in ("", "a", "A0", "A-A"):
        with pytest.raises(ValueError):
            alphabetic_chain_index(label)


@pytest.mark.parametrize(
    ("label", "pdb_char"),
    [
        ("A", "A"),
        ("Z", "Z"),
        ("AA", "a"),
        ("AZ", "z"),
        ("BA", "0"),
        ("ZZ", "T"),
        ("AAA", "U"),
        ("DMT", "X"),
        ("ST0", "R"),
        ("AB1", "b"),
    ],
)
def test_pdb_chain_cycle_decodes_every_character(label, pdb_char):
    from backend.core.pdb_export import _chain_char

    assert _chain_char(label) == pdb_char


def test_namd_segment_order_accepts_three_letter_chains():
    from backend.core.namd_topology import psfgen_dna_segids_for_design

    segids = psfgen_dna_segids_for_design(3062)
    assert len(set(segids)) == 3062
    # Lexical package order starts A, AA, AAA, AAB, independently of design order.
    assert [segids[i] for i in (0, 26, 702, 703)] == ["D000", "D001", "D002", "D003"]


def test_atomistic_build_preserves_3062_distinct_strand_identities():
    from backend.core.atomistic import build_atomistic_model
    from backend.core.lattice import make_bundle_design
    from backend.core.models import Direction, Domain, Strand, StrandType

    # One nucleotide per strand keeps the real geometry build small while
    # reproducing the 3062-strand Benchy export that formerly failed at 702.
    design = make_bundle_design(cells=[(0, 0)], length_bp=1531, plane="XY")
    helix_id = design.helices[0].id
    strands = [
        Strand(
            id=f"strand_{i}",
            strand_type=StrandType.SCAFFOLD,
            domains=[
                Domain(
                    helix_id=helix_id,
                    start_bp=i // 2,
                    end_bp=i // 2,
                    direction=Direction.FORWARD if i % 2 == 0 else Direction.REVERSE,
                )
            ],
        )
        for i in range(3062)
    ]
    model = build_atomistic_model(design.copy_with(strands=strands))
    phosphates = [atom for atom in model.atoms if atom.name == "P"]
    assert len(phosphates) == 3062
    assert len({atom.chain_id for atom in phosphates}) == 3062
    labels = {atom.strand_id: atom.chain_id for atom in phosphates}
    assert {i: labels[f"strand_{i}"] for i in (0, 701, 702, 3061)} == {
        0: "A",
        701: "ZZ",
        702: "AAA",
        3061: "DMT",
    }
