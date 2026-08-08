"""Loop-insertion bases must survive the whole MD readback + display pipeline.

A ``+1`` loop insertion emits a SECOND physical nucleotide at the same
``(helix_id, bp_index, direction)`` as its companion base (see
``geometry.nucleotide_positions``).  Crossover extra-bases were given a
disambiguator (``crossover_id``/``extra_base_k`` → ``"__xb__"`` key); intra-helix
loop copies were NOT.  So every MD readback/display path that keyed by the bare
3-tuple collapsed the two copies into one, and the loop base kept its original
geometric position after a NAMD relaxation / production run (reported on
``6hbx100_90deg``: 16 loop + 16 skip bases, loop bases never moved).

The fix mirrors the oxDNA path (which already carries a per-copy ``copy`` key):
``Atom.copy_k`` → ``md_pkey`` emits a 4-tuple ``(helix,bp,dir,copy)`` for copy≥1,
propagated through ``chain_map``/``p_order``/``md_rigid_reference`` and the
``md_rmsf``/live-MD payloads (``copy`` field).

These are fast/in-memory: build the atomistic model of a tiny loop design and
assert every nucleotide — including each loop copy — is DISTINCTLY addressable and
receives its OWN relaxed position.  No MDAnalysis / on-disk trajectory required.
"""

from __future__ import annotations

import numpy as np

from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.models import (
    Design,
    Helix,
    Strand,
    Domain,
    Vec3,
    DesignMetadata,
    LatticeType,
    StrandType,
    Direction,
    LoopSkip,
)
from backend.core.atomistic import build_atomistic_model
from backend.core.atomistic_to_nadoc import (
    build_chain_map,
    md_pkey,
    md_rigid_reference,
    _map_positions,
)


def _loop_design(delta: int = 1, bp: int = 5, L: int = 10) -> Design:
    """1 helix, scaffold FORWARD + staple REVERSE, one loop insertion at ``bp``."""
    h = Helix(
        id="h0",
        axis_start=Vec3(x=0, y=0, z=0),
        axis_end=Vec3(x=0, y=0, z=L * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        length_bp=L,
        loop_skips=[LoopSkip(bp_index=bp, delta=delta)],
    )
    fwd = Strand(
        id="scaf",
        strand_type=StrandType.SCAFFOLD,
        domains=[
            Domain(helix_id="h0", direction=Direction.FORWARD, start_bp=0, end_bp=L - 1)
        ],
    )
    rev = Strand(
        id="stap",
        strand_type=StrandType.STAPLE,
        domains=[
            Domain(helix_id="h0", direction=Direction.REVERSE, start_bp=L - 1, end_bp=0)
        ],
    )
    return Design(
        metadata=DesignMetadata(name="loop"),
        helices=[h],
        strands=[fwd, rev],
        lattice_type=LatticeType.HONEYCOMB,
    )


def _p_order_from_model(model):
    """The design keys for each P atom, in model atom order — exactly what the
    universe P-order path (``build_p_order_from_universe``) reconstructs."""
    return [md_pkey(a) for a in model.atoms if a.name == "P"]


def _p_positions_from_model(model):
    return [np.array([a.x, a.y, a.z]) for a in model.atoms if a.name == "P"]


# ── Stage 2/3: keys stay distinct per loop copy ───────────────────────────────


def test_loop_copies_get_distinct_md_keys():
    """The core invariant: two P atoms at the same (helix,bp,dir) but different loop
    copy must produce DIFFERENT md_pkey values, so neither collapses in a dict."""
    model = build_atomistic_model(_loop_design(delta=1))
    p_atoms = [a for a in model.atoms if a.name == "P"]
    keys = [md_pkey(a) for a in p_atoms]

    # One P atom per nucleotide, one design key per P atom — no drop.
    assert len(keys) == len(p_atoms)
    # And the keys are pairwise UNIQUE (the loop copy no longer aliases its base).
    assert len(set(keys)) == len(keys), (
        f"key collision: {len(keys) - len(set(keys))} P atoms share a design key "
        "(loop copies not disambiguated)"
    )
    # Concretely: the loop bp on the FORWARD strand carries >=2 distinct keys.
    fwd_at_loop = [
        md_pkey(a)
        for a in p_atoms
        if a.helix_id == "h0" and a.bp_index == 5 and a.direction == "FORWARD"
    ]
    assert len(fwd_at_loop) == 2  # base + one insertion copy
    assert len(set(fwd_at_loop)) == 2  # ...and they are distinct


def test_chain_map_addresses_every_loop_copy():
    """build_chain_map must map each loop copy's (chain,seq) to its OWN design key —
    no two residues silently sharing a value that a reverse lookup would collapse."""
    model = build_atomistic_model(_loop_design(delta=1))
    cm = build_chain_map(model)
    n_p = sum(1 for a in model.atoms if a.name == "P")
    assert len(cm) == n_p  # one (chain,seq) per P atom
    # Every distinct residue resolves to a distinct design key.
    assert len(set(cm.values())) == n_p, (
        "chain_map values collide across residues — loop copies indistinguishable"
    )


def test_p_order_covers_every_nucleotide_including_loops():
    model = build_atomistic_model(_loop_design(delta=1))
    p_order = _p_order_from_model(model)
    # delta=+1 adds one nucleotide per strand at the loop bp: 2 strands × (10 + 1).
    assert len(p_order) == 22
    assert len(set(p_order)) == len(p_order)  # no duplicate keys


# ── Stage 3: the Kabsch equilibrium reference keeps loop copies apart ──────────


def test_md_rigid_reference_gives_loop_copies_distinct_eq_positions():
    """md_rigid_reference builds a dict keyed by md_pkey; if loop copies alias, both
    are handed the SAME equilibrium position and can never be told apart (or moved)
    against the relaxed frame.  Each loop copy must keep its own eq position."""
    model = build_atomistic_model(_loop_design(delta=1))
    p_order = _p_order_from_model(model)
    eq_positions, eq_valid, _rigid = md_rigid_reference(model, p_order)

    assert eq_valid.all()  # every P atom has an eq position
    # The two FORWARD loop-copy entries must be at different eq positions.
    idxs = [
        i
        for i, k in enumerate(p_order)
        if k[0] == "h0" and k[1] == 5 and k[2] == "FORWARD"
    ]
    assert len(idxs) == 2
    d = float(np.linalg.norm(eq_positions[idxs[0]] - eq_positions[idxs[1]]))
    assert d > 1e-3, f"loop copies collapsed onto one eq position (sep {d:.2e} nm)"


# ── Stage 3/4: after "relaxation" NO base sits at its starting position ───────


def test_relaxed_readback_moves_every_base_including_loops():
    """Give every P atom a DISTINCT relaxed displacement, read it back, and assert
    every nucleotide — loop copies included — reports its own moved position (none
    collapsed onto a neighbour, none left at its start)."""
    model = build_atomistic_model(_loop_design(delta=1))
    p_order = _p_order_from_model(model)
    start = _p_positions_from_model(model)

    # A unique NON-ZERO per-atom shift so any two-into-one collapse is detectable.
    relaxed = [
        p + np.array([0.11 * (i + 1), -0.07 * (i + 1), 0.05 * (i + 3)])
        for i, p in enumerate(start)
    ]
    beads = _map_positions(relaxed, p_order)

    assert len(beads) == len(p_order)  # every base processed
    # Every base moved off its start.
    for b, s in zip(beads, start):
        assert np.linalg.norm(b.pos - s) > 1e-6
    # Every reported position is distinct (loop copies didn't collapse together).
    stacked = np.array([b.pos for b in beads])
    dmat = np.linalg.norm(stacked[:, None, :] - stacked[None, :, :], axis=-1)
    np.fill_diagonal(dmat, np.inf)
    assert dmat.min() > 1e-6, "two bases share a relaxed position (loop-copy collapse)"


# ── Stage 3 payload: md_rmsf emits a per-copy `copy` field ────────────────────


def test_md_rmsf_payload_carries_copy_for_loop_bases(monkeypatch):
    """md_rmsf's per-nucleotide payload must carry a ``copy`` index so the frontend
    (applyFemPositions / rmsfColorMap, both already copy-aware) routes each loop
    copy to the RIGHT bead.  Driven with a faked ctx + frame extractor so no
    MDAnalysis / trajectory is needed."""
    from backend.core import md_trajectory as mt

    # A p_order with a loop copy at h0/bp5/FORWARD (copy 0 = 3-tuple, copy 1 = 4-tuple).
    p_order = [
        ("h0", 4, "FORWARD"),
        ("h0", 5, "FORWARD"),
        ("h0", 5, "FORWARD", 1),  # the loop insertion copy
        ("h0", 6, "FORWARD"),
    ]
    n = len(p_order)
    fake_ctx = {
        "universe": object(),
        "p_order": p_order,
        "n_frames": 3,
        "term_specs": [],
        "n_dna_p": n,
        "p_order_source": "segid",
        "eq_positions": np.zeros((n, 3)),
        "rigid_mask": np.ones(n, bool),
    }

    def _fake_ctx(*a, **k):
        return fake_ctx

    def _fake_frame(ctx, gidx, with_c1p=False, with_termini=False):
        # distinct, frame-varying positions per nucleotide; unit +z normals
        base = np.arange(n, dtype=float)[:, None] * np.array([1.0, 0.5, 0.25])
        p_nm = base + gidx * 0.01
        normals = np.tile([0.0, 0.0, 1.0], (n, 1))
        empty = np.zeros((0, 3))
        if with_termini:
            return p_nm, normals, empty, empty
        return p_nm, normals

    monkeypatch.setattr(mt, "_build_md_nadoc_ctx", _fake_ctx)
    monkeypatch.setattr(mt, "_extract_md_nadoc_frame", _fake_frame)

    out = mt.md_rmsf("top.psf", [(0, 0, "seg.dcd")], "coord.pdb", _loop_design())
    assert out.get("ready") is True
    positions = out["positions"]
    assert len(positions) == n  # every nucleotide, incl. loop copy
    # Every payload entry exposes `copy`; the loop copy carries copy==1.
    assert all("copy" in p for p in positions)
    loop = [
        p
        for p in positions
        if p["helix_id"] == "h0" and p["bp_index"] == 5 and p["direction"] == "FORWARD"
    ]
    assert sorted(p["copy"] for p in loop) == [0, 1]
