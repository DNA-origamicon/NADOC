"""Exact scaffold availability, using authored nucleotide counts rather than budget."""

import pytest

from backend.core.models import Crossover, Domain, ForcedLigation, HalfCrossover, LoopSkip, StrandExtension
from backend.core.scaffold_length import scaffold_length_checks
from backend.core.sequences import assign_custom_scaffold_sequence, assign_scaffold_sequence
from tests.conftest import make_minimal_design


@pytest.mark.parametrize("length", [7249, 7560, 8064])
def test_each_library_length_passes_without_requiring_sequence_assignment(length):
    design = make_minimal_design(helix_length_bp=length)
    check, = scaffold_length_checks(design)
    assert check["complete"]
    assert check["actual_nt"] == length
    assert check["available_lengths_nt"] == [7249, 7560, 8064]
    assert design.scaffold().sequence is None


@pytest.mark.parametrize("length", [200, 7203, 7248, 7250, 8065])
def test_under_or_over_budget_does_not_pass_exact_length(length):
    design = make_minimal_design(helix_length_bp=length)
    design.scaffold().sequence = "A" * length
    check, = scaffold_length_checks(design)
    assert not check["complete"]
    assert check["actual_nt"] == length
    assert "does not exactly match" in check["detail"]
    assert "original source sequence" in check["detail"]


def test_each_scaffold_is_checked_independently_not_by_sum():
    design = make_minimal_design(n_helices=2, helix_length_bp=7249)
    first = design.scaffold()
    second = first.model_copy(update={
        "id": "second", "domains": [first.domains[0].model_copy(update={"helix_id": "h1"})],
    })
    design.strands.append(second)
    assert all(row["complete"] for row in scaffold_length_checks(design))
    first.domains[0].end_bp = 2999
    second.domains[0].end_bp = 4248
    checks = scaffold_length_checks(design)
    assert sum(row["actual_nt"] for row in checks) == 7249
    assert not any(row["complete"] for row in checks)


def test_loops_and_skips_affect_the_actual_length():
    design = make_minimal_design(helix_length_bp=7248)
    design.helices[0].loop_skips = [LoopSkip(bp_index=5, delta=1)]
    assert scaffold_length_checks(design)[0]["complete"]
    design.helices[0].loop_skips.append(LoopSkip(bp_index=6, delta=-1))
    assert scaffold_length_checks(design)[0]["actual_nt"] == 7248
    assert not scaffold_length_checks(design)[0]["complete"]


@pytest.mark.parametrize("junction_kind", ["crossover", "forced_ligation"])
def test_realized_junction_and_terminal_bases_count_once_on_the_owning_scaffold(junction_kind):
    design = make_minimal_design(n_helices=2, helix_length_bp=7249, with_staple=False)
    scaffold = design.scaffold()
    scaffold.domains = [
        Domain(helix_id="h0", start_bp=0, end_bp=7236, direction="FORWARD"),
        Domain(helix_id="h1", start_bp=7236, end_bp=7232, direction="REVERSE"),
    ]
    if junction_kind == "crossover":
        design.crossovers = [Crossover(
            half_a=HalfCrossover(helix_id="h0", index=7236, strand="FORWARD"),
            half_b=HalfCrossover(helix_id="h1", index=7236, strand="REVERSE"),
            extra_bases="ACGT",
        )]
    else:
        design.forced_ligations = [ForcedLigation(
            three_prime_helix_id="h0", three_prime_bp=7236, three_prime_direction="FORWARD",
            five_prime_helix_id="h1", five_prime_bp=7236, five_prime_direction="REVERSE",
            extra_bases="ACGT",
        )]
    design.extensions = [
        StrandExtension(strand_id=scaffold.id, end="five_prime", sequence="ACG"),
        StrandExtension(strand_id=scaffold.id, end="three_prime", modification="biotin"),
    ]
    check, = scaffold_length_checks(design)
    assert check["complete"]
    assert (check["domain_nt"], check["junction_nt"], check["terminal_nt"]) == (7242, 4, 3)
    assert check["actual_nt"] == 7249
    # A marker on the opposite direction is not this scaffold's inserted DNA.
    if junction_kind == "crossover":
        design.crossovers[0].half_a.strand = "REVERSE"
    else:
        design.forced_ligations[0].three_prime_direction = "REVERSE"
    assert scaffold_length_checks(design)[0]["junction_nt"] == 0


def test_custom_source_length_is_explicit_full_length_and_survives_roundtrip():
    design = make_minimal_design(helix_length_bp=200)
    assigned, _, _ = assign_custom_scaffold_sequence(design, "ACGT" * 75)
    assert len(assigned.scaffold().sequence) == 200
    assert assigned.scaffold().custom_scaffold_length == 300
    assert not scaffold_length_checks(assigned)[0]["complete"]
    assigned, _, _ = assign_custom_scaffold_sequence(assigned, "ACGT" * 50)
    loaded = type(design).from_json(assigned.to_json())
    check, = scaffold_length_checks(loaded)
    assert check["complete"]
    assert check["matched_scaffold"] == "declared custom scaffold"
    assert check["available_lengths_nt"] == [200, 7249, 7560, 8064]
    # Selecting a preset replaces, rather than silently retaining, a custom source.
    preset, _, _ = assign_scaffold_sequence(loaded, "M13mp18")
    assert preset.scaffold().custom_scaffold_length is None
    assert not scaffold_length_checks(preset)[0]["complete"]


def test_reference_scaffolds_and_unrelated_custom_sources_do_not_supply_lengths():
    design = make_minimal_design(n_helices=2, helix_length_bp=200)
    original = design.scaffold()
    design.strands.append(original.model_copy(update={
        "id": "reference", "is_reference": True, "custom_scaffold_length": 200,
        "domains": [original.domains[0].model_copy(update={"helix_id": "h1"})],
    }))
    check, = scaffold_length_checks(design)
    assert check["strand_id"] == original.id
    assert not check["complete"]
