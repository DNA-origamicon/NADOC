"""Phase-1b: motif-aware batch generator for the atomistic-propagator dataset.

Gates each currently-buildable motif (canonical duplex, staple nick, base
mismatch) through the automation round-trip oracle, and pins the metadata /
split / on-disk contract the downstream pipeline depends on.
"""
import json

import pytest

from backend.ml.propagator import systems as S
from tests.automation_harness import assert_roundtrip_stable

_SEQ16 = "GCGCATATGCGCATAT"
_HELDOUT = S._HELDOUT_SEQUENCE


def test_canonical_duplex_builds_and_roundtrips():
    gs = assert_roundtrip_stable(lambda: S.canonical_duplex(_SEQ16, seed=1).design)
    assert len(gs.helices) == 1
    scaf = [s for s in gs.strands if s.strand_type.name == "SCAFFOLD"][0]
    stpl = [s for s in gs.strands if s.strand_type.name == "STAPLE"][0]
    assert scaf.sequence == _SEQ16
    # staple is fully WC-complemented (no undefined bases)
    assert stpl.sequence and "N" not in stpl.sequence


def test_nicked_duplex_stays_single_scaffold_and_roundtrips():
    gs = S.nicked_duplex(_HELDOUT, seed=7)
    assert gs.motif_type == "nick" and gs.motif_location == len(_HELDOUT) // 2
    # nick is on the staple → still exactly one scaffold strand
    scaffolds = [s for s in gs.design.strands if s.strand_type.name == "SCAFFOLD"]
    assert len(scaffolds) == 1
    assert_roundtrip_stable(lambda: gs.design)


def test_mismatch_duplex_breaks_one_pair_only():
    gs = S.mismatch_duplex(_HELDOUT, seed=7)
    canonical = S.canonical_duplex(_HELDOUT, seed=7)
    mm = [s for s in gs.design.strands if s.strand_type.name == "STAPLE"][0].sequence
    wc = [s for s in canonical.design.strands if s.strand_type.name == "STAPLE"][0].sequence
    # exactly one staple base differs from the WC-correct duplex
    assert sum(a != b for a, b in zip(mm, wc)) == 1
    # topology unchanged → round-trip stable
    assert_roundtrip_stable(lambda: gs.design)


def test_origami_6hb_routes_sequences_and_roundtrips():
    """The 6hb origami rung: six helices, auto-routed (scaffold + crossovers +
    staple breaks) and fully sequenced (M13 scaffold + WC staples), stable under
    the round-trip oracle.  Crossovers must actually be placed (the whole point of
    the multi-helix rung) and every base defined (no undefined bases → solvatable)."""
    gs = S.origami_6hb(length_bp=21)
    assert gs.motif_type == "origami_6hb"
    d = gs.design
    assert len(d.helices) == 6
    scaf = [s for s in d.strands if s.strand_type.name == "SCAFFOLD"]
    stap = [s for s in d.strands
            if s.strand_type.name == "STAPLE" and not getattr(s, "is_reference", False)]
    assert len(scaf) >= 1 and len(stap) >= 1
    assert all(s.sequence and "N" not in s.sequence for s in scaf + stap)
    st = gs.topology_stats
    assert st["n_helices"] == 6 and st["n_nucleotides"] > 0
    assert st["n_crossovers"] and st["n_crossovers"] > 0   # crossovers really placed
    assert st["est_dna_atoms_allatom"] == round(st["n_nucleotides"] * 31)
    assert_roundtrip_stable(lambda: gs.design)


def test_origami_6hb_deterministic_id_and_scales_with_length():
    a = S.origami_6hb(length_bp=21)
    b = S.origami_6hb(length_bp=21)
    assert a.system_id == b.system_id and a.system_id.startswith("origami6hb_21bp_")
    big = S.origami_6hb(length_bp=42)
    # longer helices → strictly more nucleotides (a real second scaling point)
    assert big.topology_stats["n_nucleotides"] > a.topology_stats["n_nucleotides"]


def test_bulge_is_deferred_not_guessed():
    with pytest.raises(NotImplementedError):
        S.bulge_duplex()


def test_metadata_has_required_provenance():
    gs = S.canonical_duplex(_SEQ16, seed=3, nacl_mM=150.0, mgcl2_mM=12.5)
    meta = gs.metadata()
    for key in ("sequence", "motif_type", "motif_location", "length_bp",
                "nacl_mM", "mgcl2_mM", "temperature_K", "forcefield_version",
                "water_model", "seed", "split", "system_id"):
        assert key in meta, f"missing provenance key {key}"
    assert "design" not in meta          # design object never in system.json
    assert meta["forcefield_version"] == S.FORCEFIELD_VERSION


def test_write_emits_design_and_system_json(tmp_path):
    gs = S.canonical_duplex(_SEQ16, seed=1)
    out = gs.write(tmp_path / gs.system_id)
    assert (out / "design.nadoc").exists()
    loaded = json.loads((out / "system.json").read_text())
    assert loaded["system_id"] == gs.system_id
    assert loaded["motif_type"] == "canonical"


def test_deterministic_ids_across_calls():
    a = S.canonical_duplex(_SEQ16, seed=1)
    b = S.canonical_duplex(_SEQ16, seed=1)
    assert a.system_id == b.system_id     # no wall-clock / RNG in the id


def test_catalog_split_discipline():
    """The held-out sequence must never appear in a training system, and every
    training sequence must come from the declared training pool — so no duplex's
    frames can straddle the train/test boundary."""
    cat = S.default_catalog()
    ids = [gs.system_id for gs in cat]
    assert len(ids) == len(set(ids)), "system ids must be unique"
    train_seqs = {gs.sequence for gs in cat if gs.split == "train"}
    test_seqs = {gs.sequence for gs in cat if gs.split == "test"}
    pool = {s for seqs in S._TRAIN_SEQUENCES.values() for s in seqs}
    assert train_seqs <= pool
    assert _HELDOUT not in train_seqs
    assert _HELDOUT in test_seqs
