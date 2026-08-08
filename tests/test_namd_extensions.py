"""Strand extensions (5′/3′ terminal ssDNA tails) → all-atom / NAMD.

The atomistic twin of ``test_oxdna_extensions.py``, mirroring ``test_namd_extra_bases.py``.

A tail differs from a crossover extra base in the one way that matters to the builder: an
extra base BRIDGES two anchors (C3′(src) → C5′(dst)), a tail hangs off ONE.  That rules out
the bridge minimisers ``_minimize_{1,2,3}_extra_base`` (they solve for a linker pinned at
both ends) and it changes the chain's TERMINI — a 5′ tail means the anchor is no longer the
strand's 5′ end, which is exactly what psfgen's ``5TER`` / ``DEO5`` patches key off.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from backend.core.atomistic import build_atomistic_model
from backend.core.md_protocols import design_has_extensions
from backend.core.models import Design, StrandExtension

SMALL = Path("Examples/6hb_test.nadoc")


def _load() -> Design:
    return Design.model_validate(json.loads(SMALL.read_text()))


def _residues(model) -> set[tuple[str, int]]:
    return {(a.chain_id, a.seq_num) for a in model.atoms}


def _with_tails() -> Design:
    d = _load()
    d.extensions = [
        StrandExtension(strand_id=d.strands[1].id, end="three_prime", sequence="TT"),
        StrandExtension(strand_id=d.strands[2].id, end="five_prime", sequence="A"),
    ]
    return d


# ── Materialisation ───────────────────────────────────────────────────────────


def test_model_grows_by_exactly_the_tail_base_count():
    bare = _load()
    bare.extensions = []
    d = _with_tails()

    n_bare = len(_residues(build_atomistic_model(bare)))
    n_ext = len(_residues(build_atomistic_model(d)))
    assert n_ext - n_bare == 3  # TT + A


def test_modification_only_extension_builds_no_residue():
    """A fluorophore is not DNA.  It has a display bead, but no atoms and no residue —
    otherwise psfgen would be handed a nucleotide that does not exist."""
    bare = _load()
    bare.extensions = []
    d = _load()
    d.extensions = [
        StrandExtension(
            strand_id=d.strands[1].id, end="five_prime", modification="cy3"
        ),
    ]
    assert len(_residues(build_atomistic_model(d))) == len(
        _residues(build_atomistic_model(bare))
    )
    assert not design_has_extensions(d)


def test_tail_atoms_carry_their_own_identity():
    """Tail atoms keep the ANCHOR's (helix, bp, direction) — so the existing topology
    writers need no change — but carry extension_id/ext_k so the display and the MD P-atom
    map can address them as ``("__ext_<id>", ext_k, direction)``, the same key oxDNA uses."""
    d = _with_tails()
    m = build_atomistic_model(d)
    tail = [a for a in m.atoms if a.extension_id is not None]
    assert tail

    ids = {e.id for e in d.extensions}
    assert {a.extension_id for a in tail} <= ids
    for e in d.extensions:
        ks = {a.ext_k for a in tail if a.extension_id == e.id}
        assert ks == set(range(len(e.sequence)))


def test_md_pkey_matches_the_oxdna_key():
    from backend.core.atomistic_to_nadoc import is_synthetic_pkey, md_pkey

    d = _with_tails()
    m = build_atomistic_model(d)
    p_tail = [a for a in m.atoms if a.name == "P" and a.extension_id is not None]
    assert p_tail
    for a in p_tail:
        k = md_pkey(a)
        assert k[0] == f"__ext_{a.extension_id}"
        assert k[1] == a.ext_k
        # A tail key's bp_index is a plain int >= 0, so it sails past every
        # `isinstance(k[1], int)` filter written to catch __xb__.  It must be caught here.
        assert is_synthetic_pkey(k)


def test_simulated_tail_backbone_closure_reseats_linkers_at_both_ends():
    """oxDNA tail beads stay fixed while their atom-level O3'-P linkers are closed."""
    from backend.api.crud import _geometry_for_design

    d = _with_tails()
    ext_override = {
        (n["extension_id"], int(n["bp_index"])): np.asarray(
            n["backbone_position"], dtype=float
        )
        for n in _geometry_for_design(d)
        if n.get("extension_id") and not n.get("is_modification")
    }
    raw = build_atomistic_model(d, ext_pos_override=ext_override, close_backbone=False)
    closed = build_atomistic_model(
        d, ext_pos_override=ext_override, close_backbone=True
    )

    def extension_o3p_distances(model):
        by = {a.serial: a for a in model.atoms}
        distances = []
        for i, j in model.bonds:
            a, b = by[i], by[j]
            if {a.name, b.name} != {"O3'", "P"}:
                continue
            if a.extension_id is None and b.extension_id is None:
                continue
            distances.append(
                float(np.linalg.norm(np.array([a.x - b.x, a.y - b.y, a.z - b.z])))
                * 10.0
            )
        return distances

    raw_dist = extension_o3p_distances(raw)
    closed_dist = extension_o3p_distances(closed)
    assert len(raw_dist) == len(closed_dist) == 3
    # The oxDNA bead separation is coarser than the atomistic linker contour;
    # closure distributes the small residual instead of breaking an adjacent bond.
    assert max(closed_dist) < 3.0
    assert max(closed_dist) < max(raw_dist)

    # Closure may move linker atoms, but never the simulated ribose/base anchors.
    rigid_names = {"C1'", "C2'", "C3'", "C4'", "O4'", "N1", "N9"}
    for before, after in zip(raw.atoms, closed.atoms):
        if before.extension_id is not None and before.name in rigid_names:
            assert np.allclose(
                [before.x, before.y, before.z], [after.x, after.y, after.z]
            )


# ── Chain termini — what makes the psfgen patches land ───────────────────────


def test_five_prime_tail_becomes_the_chain_five_prime_terminus():
    """CAN-GO-RED. ``namd_topology`` derives the CHARMM terminal patches purely from
    residue ORDER (``first 5TER`` / ``patch DEO5 {first_resid}`` / ``last 3TER``).  So a
    5′ tail has to sort BEFORE its strand's first real residue, outermost base first —
    that base IS the strand's new 5′ terminus, and the anchor becomes an internal DEOX.

    Without the threading pass the tail is appended at the END of the chain, which would
    put the 5′ patch on the wrong residue and bond the tail to the strand's 3′ end.
    """
    d = _load()
    d.extensions = [
        StrandExtension(strand_id=d.strands[2].id, end="five_prime", sequence="ACG"),
    ]
    m = build_atomistic_model(d)
    ext = d.extensions[0]
    tail = [a for a in m.atoms if a.extension_id == ext.id]
    chain = tail[0].chain_id
    in_chain = [a for a in m.atoms if a.chain_id == chain]

    lo = min(a.seq_num for a in in_chain)
    tail_seqs = sorted({a.seq_num for a in tail})

    assert tail_seqs == [lo, lo + 1, lo + 2]  # the tail IS the head of the chain
    outermost = [a for a in tail if a.ext_k == 2]  # ext_k = distance from the anchor
    assert {a.seq_num for a in outermost} == {lo}  # …and its tip is residue #1


def test_three_prime_tail_becomes_the_chain_three_prime_terminus():
    d = _load()
    d.extensions = [
        StrandExtension(strand_id=d.strands[1].id, end="three_prime", sequence="TT"),
    ]
    m = build_atomistic_model(d)
    ext = d.extensions[0]
    tail = [a for a in m.atoms if a.extension_id == ext.id]
    chain = tail[0].chain_id
    hi = max(a.seq_num for a in m.atoms if a.chain_id == chain)

    tail_seqs = sorted({a.seq_num for a in tail})
    assert tail_seqs == [hi - 1, hi]
    tip = [a for a in tail if a.ext_k == 1]  # outermost base
    assert {a.seq_num for a in tip} == {hi}


# ── Backbone through the tail ────────────────────────────────────────────────


def test_tail_backbone_is_bonded_through_the_anchor():
    """The tail must be covalently continuous with its strand: an O3′→P bond joins the
    anchor to the tail (3′) or the tail to the anchor (5′).  A tail bonded to nothing
    would simulate as a free-floating dimer."""
    d = _with_tails()
    m = build_atomistic_model(d)
    by = {a.serial: a for a in m.atoms}

    joins = [
        (by[s1], by[s2])
        for s1, s2 in m.bonds
        if {by[s1].name, by[s2].name} == {"O3'", "P"}
        and ((by[s1].extension_id is None) != (by[s2].extension_id is None))
    ]
    # exactly one anchor↔tail junction per extension
    assert len(joins) == len(d.extensions)


def test_tail_backbone_bonds_are_physical():
    """O3′→P through the tail must be a covalent bond, not a stretched artifact.  The seed
    is not perfect (the NAMD declash minimisation is what finishes the job) but it must be
    at least as good as the crossover extra-base seed that already ships."""
    d = _load()
    d.extensions = [
        StrandExtension(strand_id=d.strands[1].id, end="three_prime", sequence="TTT"),
        StrandExtension(strand_id=d.strands[2].id, end="five_prime", sequence="TT"),
    ]
    m = build_atomistic_model(d)
    by = {a.serial: a for a in m.atoms}
    pos = {a.serial: np.array([a.x, a.y, a.z]) for a in m.atoms}

    lens = [
        float(np.linalg.norm(pos[s1] - pos[s2])) * 10.0  # nm → Å
        for s1, s2 in m.bonds
        if {by[s1].name, by[s2].name} == {"O3'", "P"}
        and (by[s1].extension_id is not None or by[s2].extension_id is not None)
    ]
    assert len(lens) == 5
    # canonical O3′–P is 1.60 Å; the shipping extra-base seed lands at 2.6–3.2 Å
    assert all(1.5 <= v <= 3.2 for v in lens), lens


def test_no_bond_between_two_different_tails():
    """Tails are appended at the chain tail before threading; if the seq_num re-threading
    were wrong, two unrelated tails could end up adjacent and get bonded together."""
    d = _with_tails()
    m = build_atomistic_model(d)
    by = {a.serial: a for a in m.atoms}
    for s1, s2 in m.bonds:
        a, b = by[s1], by[s2]
        if a.extension_id and b.extension_id:
            assert a.extension_id == b.extension_id


# ── Declash ──────────────────────────────────────────────────────────────────


def test_extensions_enable_declash():
    """Tails are free ssDNA seeded on a geometric arc poking out of the duplex, so — like
    crossover extra bases — they can start in steric contact.  Declash must switch on
    automatically, exactly as it does for extra bases."""
    bare = _load()
    bare.extensions = []
    assert not design_has_extensions(bare)

    d = _with_tails()
    assert design_has_extensions(d)

    from backend.core.md_protocols import design_has_extra_bases

    assert not design_has_extra_bases(d)  # so declash can only be coming from the tails
