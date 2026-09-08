from backend.core.atomistic import Atom, AtomisticModel
from backend.core.base_keys import resolve_base_keys
from backend.core.models import (
    Crossover,
    Design,
    Direction,
    HalfCrossover,
    LoopSkip,
    PhotoproductJunction,
    StrandExtension,
)
from backend.core.photoproducts import preflight_photoproduct, stale_photoproduct_ids
from tests.conftest import make_minimal_design


def _atom(serial, name, *, k=1):
    return Atom(
        serial=serial,
        name=name,
        element="C",
        residue="DT",
        chain_id="A",
        seq_num=1,
        x=float(serial),
        y=0.0,
        z=0.0,
        strand_id="insert-strand",
        helix_id="h0",
        bp_index=5,
        direction="FORWARD",
        crossover_id="xo:colon",
        extra_base_k=k,
    )


def test_crossover_extra_resolves_by_unambiguous_provenance_not_anchor_identity():
    crossover = Crossover(
        id="xo:colon",
        half_a=HalfCrossover(helix_id="h0", index=5, strand=Direction.FORWARD),
        half_b=HalfCrossover(helix_id="h1", index=5, strand=Direction.REVERSE),
        extra_bases="AT",
    )
    model = AtomisticModel(atoms=[_atom(0, "C5"), _atom(1, "C6")], bonds=[])
    resolved, errors = resolve_base_keys(
        Design(crossovers=[crossover]), ["__xb__:xo:colon:1"], atomistic_model=model
    )
    assert errors == []
    assert resolved[0].base == "T"
    assert resolved[0].source_class == "crossover-extra"
    assert resolved[0].strand_id == "insert-strand"
    assert resolved[0].atom_serials == {"C5": 0, "C6": 1}


def test_loop_copies_and_colon_bearing_extensions_resolve_with_c5_c6_atoms():
    design = make_minimal_design(helix_length_bp=8)
    design.helices[0].loop_skips = [LoopSkip(bp_index=3, delta=1)]
    design = design.copy_with(
        strands=[
            strand.model_copy(update={"sequence": "T" * 9}) for strand in design.strands
        ],
        extensions=[
            StrandExtension(
                id="tail:colon", strand_id="scaf", end="three_prime", sequence="TT"
            )
        ],
    )
    keys = [
        "h0:3:FORWARD",
        "h0:3:FORWARD:1",
        "__ext_tail:colon:0:FORWARD",
        "__ext_tail:colon:1:FORWARD",
    ]
    resolved, errors = resolve_base_keys(design, keys)
    assert errors == []
    assert [item.source_class for item in resolved] == [
        "ordinary",
        "loop-copy",
        "extension",
        "extension",
    ]
    assert all(item.base == "T" and item.has_cpd_atoms for item in resolved)


def test_crossover_extra_pair_is_eligible_design_intent_with_real_atom_provenance():
    crossover = Crossover(
        id="xo:colon",
        half_a=HalfCrossover(helix_id="h0", index=5, strand=Direction.FORWARD),
        half_b=HalfCrossover(helix_id="h1", index=5, strand=Direction.REVERSE),
        extra_bases="TT",
    )
    model = AtomisticModel(
        atoms=[
            _atom(0, "C5", k=0),
            _atom(1, "C6", k=0),
            _atom(2, "C5", k=1),
            _atom(3, "C6", k=1),
        ],
        bonds=[],
    )
    report = preflight_photoproduct(
        Design(crossovers=[crossover]),
        ["__xb__:xo:colon:0", "__xb__:xo:colon:1"],
        atomistic_model=model,
    )
    assert report["eligible"] is True
    assert report["simulation_ready"] is False
    assert report["relationship"]["extra_pairing"] == "extra-extra"
    assert report["relationship"]["strand_relationship"] == "intrastrand"


def test_crossover_extra_edit_cannot_leave_a_stale_or_non_thymine_product():
    crossover = Crossover(
        id="xo:colon",
        half_a=HalfCrossover(helix_id="h0", index=5, strand=Direction.FORWARD),
        half_b=HalfCrossover(helix_id="h1", index=5, strand=Direction.REVERSE),
        extra_bases="TT",
    )
    lesion = PhotoproductJunction(
        id="extra-lesion",
        base_key_1="__xb__:xo:colon:0",
        base_key_2="__xb__:xo:colon:1",
    )
    design = Design(crossovers=[crossover], photoproduct_junctions=[lesion])
    assert stale_photoproduct_ids(design) == []

    changed = crossover.model_copy(update={"extra_bases": "TA"})
    assert stale_photoproduct_ids(
        design.copy_with(crossovers=[changed])
    ) == ["extra-lesion"]
    removed = crossover.model_copy(update={"extra_bases": "T"})
    assert stale_photoproduct_ids(
        design.copy_with(crossovers=[removed])
    ) == ["extra-lesion"]


def test_extension_edit_cannot_leave_a_stale_or_non_thymine_product():
    design = make_minimal_design(helix_length_bp=8)
    extension = StrandExtension(
        id="tail:colon", strand_id="scaf", end="three_prime", sequence="TT"
    )
    lesion = PhotoproductJunction(
        id="extension-lesion",
        base_key_1="__ext_tail:colon:0:FORWARD",
        base_key_2="__ext_tail:colon:1:FORWARD",
    )
    design = design.copy_with(
        extensions=[extension], photoproduct_junctions=[lesion]
    )
    assert stale_photoproduct_ids(design) == []

    changed = extension.model_copy(update={"sequence": "TA"})
    assert stale_photoproduct_ids(
        design.copy_with(extensions=[changed])
    ) == ["extension-lesion"]
    assert stale_photoproduct_ids(
        design.copy_with(extensions=[])
    ) == ["extension-lesion"]
