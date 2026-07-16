"""Crossover extra bases materialized as single-stranded oxDNA nucleotides.

`Crossover.extra_bases` (e.g. "TT") are single-stranded thymines inserted at a
crossover junction.  They are junction metadata outside the strand graph; these
pins prove the oxDNA writer now materializes them as real ssDNA nucleotides —
inserted on the crossover-owning strand, threaded 3'/5' in-chain between their
flanking real nucleotides, carrying their own base identity, without consuming the
strand's designed sequence — while the relaxed read-back stays keyed to the real
design nucleotides.  See backend/physics/oxdna_interface.py.
"""

from types import SimpleNamespace

import numpy as np
import pytest

from backend.api import headless_build as hb
from backend.api import state as design_state
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import LatticeType
from backend.physics import oxdna_interface as ox

from tests.automation_harness import assert_extra_bases_in_oxdna
from tests.conftest import SIX_HB_CELLS
from tests.test_oxdna_relaxation import _sequence_for_oxdna


def _routed_6hb_sequenced():
    """A seamless-autoscaffolded, fully-autostapled, fully-sequenced 6hb — has a
    real crossover graph to hang extra bases on, and definite A/C/G/T everywhere."""
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(SIX_HB_CELLS, 84, lattice=LatticeType.HONEYCOMB, name="6hb")
        hb.auto_scaffold(seamless=True)
        hb.full_autostaple()
        d = design_state.get_or_404().model_copy(deep=True)
    return _sequence_for_oxdna(d)


@pytest.fixture(scope="module")
def routed_6hb():
    return _routed_6hb_sequenced()


def _with_extra(design, sequence="TT", *, all_crossovers=False):
    d = design.model_copy(deep=True)
    if all_crossovers:
        for x in d.crossovers:
            x.extra_bases = sequence
    else:
        d.crossovers[0].extra_bases = sequence
    return d


# ── no-regression: the centralized walk is identical for extra-base-free designs ──

def test_walk_is_consistent_without_extra_bases(routed_6hb):
    order = ox._strand_nucleotide_order(routed_6hb)
    rows, n_strands = ox.topology_rows(routed_6hb)
    prov = ox._strand_nucleotide_provenance(routed_6hb)
    assert len(order) == len(rows) == len(prov)
    assert n_strands == len(routed_6hb.strands)
    # No design carries extra bases until we add them: zero inserts.
    assert not any(k[0] == ox._XB_SENTINEL for k in order)
    assert ox.crossover_extra_base_junctions(routed_6hb) == {}


# ── pins #1–3, #6: topology materialization ───────────────────────────────────

def test_precise_extra_bases_materialized(routed_6hb):
    """TT at one crossover → 2 extra ssDNA nucleotides, right base, in-chain."""
    d = _with_extra(routed_6hb, "TT")
    assert_extra_bases_in_oxdna(d, expected_count=2, expected_sequence="TT")


def test_bulk_extra_bases_materialized(routed_6hb):
    """A single T on every crossover materializes one nucleotide per junction."""
    d = _with_extra(routed_6hb, "T", all_crossovers=True)
    junctions = ox.crossover_extra_base_junctions(d)
    expected = sum(len(extra) for _xo_id, extra in junctions.values())
    assert expected > 1, "bulk case should insert at several junctions"
    assert_extra_bases_in_oxdna(d, expected_count=expected)


def test_single_t_precise(routed_6hb):
    """n=1 insert sits at the chord midpoint and still threads in-chain."""
    d = _with_extra(routed_6hb, "T")
    assert_extra_bases_in_oxdna(d, expected_count=1, expected_sequence="T")


# ── pin #4: configuration geometry is FENE-safe and orthonormal ───────────────

def test_extra_base_config_geometry_is_sane(routed_6hb):
    d = _with_extra(routed_6hb, "TT")
    rm = ox.resolved_nuc_map(d, _geometry_for_design(d))
    inserts = ox._extra_base_inserts(d)
    assert len(inserts) == 2
    (_xb, (prev_key, next_key, _k, _n)) = next(iter(inserts.items()))
    xb_keys = sorted((k for k in rm if k[0] == ox._XB_SENTINEL), key=lambda k: k[2])
    chain = [prev_key, *xb_keys, next_key]
    pts = [np.asarray(rm[k]["backbone_position"], float) for k in chain]
    for a, b in zip(pts, pts[1:]):
        dlen = float(np.linalg.norm(b - a))
        assert 0.2 < dlen < 1.0, f"insert backbone bond {dlen:.3f} nm out of sane range"
    for k in xb_keys:
        a1 = np.asarray(rm[k]["base_normal"], float)
        a3 = np.asarray(rm[k]["axis_tangent"], float)
        assert abs(float(a1 @ a3)) < 1e-6, "a1 must be perpendicular to a3"
        assert abs(np.linalg.norm(a1) - 1.0) < 1e-6
        assert abs(np.linalg.norm(a3) - 1.0) < 1e-6


# ── file consistency: topology header + config line counts include the inserts ─

def test_topology_and_config_line_counts_match(routed_6hb, tmp_path):
    d = _with_extra(routed_6hb, "TT")
    order = ox._strand_nucleotide_order(d)
    top = tmp_path / "t.top"
    conf = tmp_path / "c.dat"
    ox.write_topology(d, top)
    ox.write_configuration(d, _geometry_for_design(d), conf, oxdna_native_seed=True)

    top_lines = top.read_text().splitlines()
    assert int(top_lines[0].split()[0]) == len(order) == len(top_lines) - 1
    conf_data = [l for l in conf.read_text().splitlines()
                 if l and not l.startswith(("t ", "b ", "E "))]
    assert len(conf_data) == len(order)


# ── read-back stays design-keyed (inserts hold their slot, then drop out) ──────

def test_readback_drops_inserts_keeps_real_alignment(routed_6hb, tmp_path):
    d = _with_extra(routed_6hb, "TT")
    geom = _geometry_for_design(d)
    conf = tmp_path / "c.dat"
    ox.write_configuration(d, geom, conf, oxdna_native_seed=True)

    order = ox._strand_nucleotide_order(d)
    real_keys = {k[:3] for k in order if k[0] != ox._XB_SENTINEL}

    full = ox.read_configuration_full(conf, d)
    assert not any(k[0] == ox._XB_SENTINEL for k in full), "inserts must drop from read-back"
    # Read-back covers exactly the strand-covered real nucleotides (a subset of the
    # geometry kernel, which also emits dangling helix-end positions no strand uses).
    assert set(full.keys()) == real_keys

    # Off-by-N guard: a real nucleotide AFTER the insert must read back the exact
    # position written for it — if the inserts shifted the particle alignment, these
    # would read a neighbour's coordinates instead.
    resolved = ox.oxdna_native_seed_map(d, ox.resolved_nuc_map(d, geom))
    first_xb = min(i for i, k in enumerate(order) if k[0] == ox._XB_SENTINEL)
    after = [k for k in order[first_xb:] if k[0] != ox._XB_SENTINEL][:5]
    assert after, "expected real nucleotides after the insert"
    for k in after:
        got = np.asarray(full[k[:3]]["backbone_position"], float)
        exp = np.asarray(resolved[k]["backbone_position"], float)
        assert np.allclose(got, exp, atol=1e-4), f"misaligned read-back for {k}"


# ── health check must not phantom-bond across the inserts ─────────────────────

def test_health_check_threads_inserts_not_phantom_bond(routed_6hb):
    """The over-stretch/FENE health check pairs consecutive backbone nucleotides.
    With extra bases at a junction, the two flanking real nucleotides are NOT
    directly bonded — pairing them would measure one phantom bond spanning the
    widened gap and spuriously fail an otherwise-healthy relaxation."""
    d = _with_extra(routed_6hb, "TT")
    (_xb, (prev_key, next_key, _k, _n)) = next(iter(ox._extra_base_inserts(d).items()))

    # Without extra bases the flanks ARE a direct backbone bond (proves scoping).
    bare = set(ox.backbone_bond_pairs(routed_6hb))
    assert (prev_key, next_key) in bare or (next_key, prev_key) in bare

    # With extra bases the direct bond is gone, bridged by sentinel placeholders.
    pairs = set(ox.backbone_bond_pairs(d))
    assert (prev_key, next_key) not in pairs and (next_key, prev_key) not in pairs
    assert any(a == prev_key and b[0] == ox._XB_SENTINEL for a, b in pairs)
    assert any(a[0] == ox._XB_SENTINEL and b == next_key for a, b in pairs)


# ── display readers can surface inserts for rendering ─────────────────────────

def test_display_readers_surface_extra_bases_on_request(routed_6hb, tmp_path):
    """The relaxed-display readers drop inserts by default (design-keyed display +
    recovery oracle stay clean) but keep them under ``include_extra_bases=True`` so
    the renderer can place extra bases at their real simulated positions."""
    d = _with_extra(routed_6hb, "TT")
    conf = tmp_path / "c.dat"
    ox.write_configuration(d, _geometry_for_design(d), conf, oxdna_native_seed=True)

    base = ox.read_configuration_full(conf, d)
    kept = ox.read_configuration_full(conf, d, include_extra_bases=True)
    assert not any(k[0] == ox._XB_SENTINEL for k in base)
    xb = [k for k in kept if k[0] == ox._XB_SENTINEL]
    assert len(xb) == 2 and all(k[1] == d.crossovers[0].id for k in xb)
    # The flag only ADDS inserts — the real-nucleotide map is identical either way.
    assert set(base) == {k for k in kept if k[0] != ox._XB_SENTINEL}

    # The unwrap path (what /display uses) carries them with finite positions.
    uw = ox.read_configuration_unwrapped(conf, d, conf, include_extra_bases=True)
    xb_uw = [uw[k]["backbone_position"] for k in uw if k[0] == ox._XB_SENTINEL]
    assert len(xb_uw) == 2 and all(np.all(np.isfinite(p)) for p in xb_uw)


# ── heavy reps (atomistic): inserts follow the simulated positions ────────────

def test_heavy_rep_extra_bases_follow_sim_positions(routed_6hb):
    """The atomistic heavy rep places each extra base at its REAL simulated position
    (``xb_pos_override``) instead of the geometric junction arc; without the override
    the placement is the geometric one (exact fallback), and the atom count/topology
    is unchanged either way."""
    from backend.core.atomistic import build_atomistic_model

    d = _with_extra(routed_6hb, "TT")
    xoid = d.crossovers[0].id

    geo = build_atomistic_model(d)  # no override → geometric arc
    ov = {(xoid, 0): np.array([40.0, 40.0, 40.0]), (xoid, 1): np.array([41.0, 41.0, 41.0])}
    # The display flags (close_backbone + relaxed_oxdna_phase) are what build_display_model uses.
    sim = build_atomistic_model(d, xb_pos_override=ov,
                                close_backbone=True, relaxed_oxdna_phase=True)

    def centroid(m, k):
        pts = [(a.x, a.y, a.z) for a in m.atoms
               if a.crossover_id == xoid and a.extra_base_k == k]
        return np.mean(pts, axis=0)

    assert len(geo.atoms) == len(sim.atoms), "override changes positions, not topology"
    # 40 atoms tagged for the two inserts (20 each), in both builds.
    assert sum(1 for a in sim.atoms if a.crossover_id == xoid) == 40
    # Sim-overridden inserts sit at their targets; the geometric ones are far away.
    assert np.linalg.norm(centroid(sim, 0) - np.array([40, 40, 40])) < 2.0
    assert np.linalg.norm(centroid(sim, 1) - np.array([41, 41, 41])) < 2.0
    assert np.linalg.norm(centroid(geo, 0) - np.array([40, 40, 40])) > 10.0


def test_heavy_rep_extra_base_uses_full_simulated_orientation(routed_6hb):
    """A full oxDNA override carries a1/a3, not merely the insert position."""
    from backend.core.atomistic import build_atomistic_model

    d = _with_extra(routed_6hb, "T")
    xoid = d.crossovers[0].id
    cm = np.array([40.0, 40.0, 40.0])

    def built(a1):
        # The position is the corresponding backbone site; the calibrated rigid
        # placer consumes CM+a1+a3 while legacy array-only overrides remain valid.
        ov = {(xoid, 0): {"cm": cm, "position": cm - 0.3 * np.asarray(a1),
                          "a1": np.asarray(a1), "a3": np.array([0.0, 0.0, 1.0])}}
        return build_atomistic_model(d, xb_pos_override=ov, close_backbone=True,
                                     relaxed_oxdna_phase=True, fast_bridges=True)

    def glycosidic_vector(model):
        aa = [a for a in model.atoms if a.crossover_id == xoid]
        pos = {a.name: np.array([a.x, a.y, a.z]) for a in aa}
        return pos["N1"] - pos["C1'"]

    vx = glycosidic_vector(built([1.0, 0.0, 0.0]))
    vy = glycosidic_vector(built([0.0, 1.0, 0.0]))
    assert np.linalg.norm(vx) == pytest.approx(np.linalg.norm(vy), abs=1e-8)
    cosine = float(np.dot(vx, vy) / (np.linalg.norm(vx) * np.linalg.norm(vy)))
    assert cosine < 0.99, "changing simulated a1 must change base orientation"


# ── MD viz: extra-base P atoms get unique keys (no source collision) ──────────

def test_md_chain_map_keys_extra_bases_uniquely(routed_6hb):
    """MD P-atom mapping (build_chain_map): crossover extra-base P atoms get unique
    ``("__xb__", crossover_id, k)`` keys instead of colliding on the SOURCE
    nucleotide's (helix, bp, direction) — so the MD trajectory can address each
    insert (matching the oxDNA ``__xb__`` contract the frontend routes)."""
    from backend.core.atomistic import build_atomistic_model
    from backend.core.atomistic_to_nadoc import build_chain_map

    d = _with_extra(routed_6hb, "TT")
    xoid = d.crossovers[0].id
    cm = build_chain_map(build_atomistic_model(d))
    vals = list(cm.values())

    # Every P atom now maps to a DISTINCT nucleotide key (the collision is gone).
    assert len(set(vals)) == len(vals)
    xb_keys = sorted(v for v in vals if v[0] == "__xb__")
    assert xb_keys == [("__xb__", xoid, 0), ("__xb__", xoid, 1)]
    # Real nucleotides keep their (helix, bp, direction) keys.
    assert any(v[0] != "__xb__" and isinstance(v[1], int) for v in vals)


def test_md_rigid_reference_tolerates_extra_base_keys(routed_6hb):
    """md_rigid_reference (shared by md_trajectory AND the live-display ws handler)
    must not crash on extra-base ``__xb__`` keys (string crossover_id) and must mark
    them NON-rigid — the str-vs-int ``bp_index >= 0`` compare that crashed Display MD
    on an extra-base design."""
    from backend.core.atomistic import build_atomistic_model
    from backend.core.atomistic_to_nadoc import build_chain_map, md_rigid_reference

    d = _with_extra(routed_6hb, "TT")
    model = build_atomistic_model(d)
    p_order = list(build_chain_map(model).values())   # real + __xb__ keys
    _eq, eq_valid, rigid = md_rigid_reference(model, p_order)

    xb_idx = [i for i, k in enumerate(p_order) if k[0] == "__xb__"]
    assert xb_idx, "expected __xb__ entries in p_order"
    assert not any(bool(rigid[i]) for i in xb_idx), "extra-base inserts must be non-rigid"
    assert int(rigid.sum()) > 0, "real nucleotides must remain rigid"
    assert bool(eq_valid.all()), "every P atom should resolve to a design equilibrium position"


# ── regression: reciprocal crossover must own the insert on ONE strand only ────

def _half(helix_id, index, direction):
    return SimpleNamespace(
        helix_id=helix_id, index=index, strand=SimpleNamespace(value=direction)
    )


def _dom(helix_id, start_bp, end_bp, direction):
    return SimpleNamespace(
        helix_id=helix_id, start_bp=start_bp, end_bp=end_bp,
        direction=SimpleNamespace(value=direction),
    )


def test_reciprocal_crossover_owns_insert_on_one_strand():
    """A reciprocal crossover — two strands swapping helices at the SAME junction
    position — must materialize its extra bases on exactly ONE owning strand.

    Pins the VoltronCore failure: when both halves were registered, both strands
    matched the same crossover and emitted identical ``(_XB_SENTINEL, xo_id, k)``
    insert keys, colliding in ``topology_rows``' index map and writing cross-strand
    n3/n5 pointers that fail oxDNA's topology-consistency check at startup.
    Mirrors the atomistic ground truth (``domain_end_to_strand``, half_a preferred).
    """
    # Strand 1: helix h0 (5→10) → helix h1 (10→15); 3′ exit of dom0 at (h0, 10).
    s1 = SimpleNamespace(id="s1", domains=[
        _dom("h0", 5, 10, "FORWARD"), _dom("h1", 10, 15, "FORWARD")])
    # Strand 2 reciprocates: helix h1 (5→10) → helix h0 (10→15); 3′ exit at (h1, 10).
    s2 = SimpleNamespace(id="s2", domains=[
        _dom("h1", 5, 10, "REVERSE"), _dom("h0", 10, 15, "REVERSE")])
    xo = SimpleNamespace(
        id="xo-recip", extra_bases="TT",
        half_a=_half("h0", 10, "FORWARD"),   # domain end of s1 → atomistic src
        half_b=_half("h1", 10, "REVERSE"),   # domain end of s2
    )
    design = SimpleNamespace(strands=[s1, s2], crossovers=[xo])

    junctions = ox.crossover_extra_base_junctions(design)
    owners = [sid for (sid, _di) in junctions]
    assert owners == ["s1"], f"expected single owning strand s1, got {owners}"
    assert all(v == ("xo-recip", "TT") for v in junctions.values())


# ── regression: bulk extra bases keep every insert key unique + topology sane ──

def test_all_crossovers_insert_keys_unique_and_topology_consistent(routed_6hb):
    """Every insert key is unique and n3/n5 pointers are reciprocal even with TT on
    every crossover — the global invariant the reciprocal-crossover bug broke."""
    d = _with_extra(routed_6hb, "TT", all_crossovers=True)
    insert_keys = [s.key for s in ox._walk_strand_nucleotides(d) if s.is_extra_base]
    assert insert_keys, "expected inserts on a fully-crossed design"
    assert len(insert_keys) == len(set(insert_keys)), "insert keys must be unique"

    rows, _n = ox.topology_rows(d)
    for i, (_si, _b, n3, n5) in enumerate(rows):
        if n3 != -1:
            assert rows[n3][3] == i, f"particle {i} n3={n3} not reciprocated"
        if n5 != -1:
            assert rows[n5][2] == i, f"particle {i} n5={n5} not reciprocated"


# ── the oracle is can-go-red ──────────────────────────────────────────────────

def test_oracle_fires_without_extra_bases(routed_6hb):
    with pytest.raises(AssertionError):
        assert_extra_bases_in_oxdna(routed_6hb, expected_count=2, expected_sequence="TT")
