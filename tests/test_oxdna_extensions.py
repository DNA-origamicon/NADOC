"""Strand extensions (5′/3′ terminal ssDNA tails) → oxDNA topology + configuration.

`StrandExtension` was a display-only feature: it had a model, CRUD, validation and 3D
geometry, but appeared in NO simulation exporter, so a scadnano import whose staples all
carry single-T extensions relaxed as if the T's were not there.  These tests pin the
materialisation, mirroring ``test_oxdna_extra_bases.py`` (the crossover-extra-base twin).

Getting a tail into the topology is easy; getting it in without oxDNA killing the run is the
whole problem.  FOUR separate mistakes each produce a config that dies, and each has its own
oracle here — verified to go red against a deliberately regressed build:

  1. ARC — seeding the tail at the display arc's old ``n * 0.34`` nm spacing with a phantom
     slot past the tip, so a lone T sits 0.177 nm from its anchor, deep inside it.
     Pinned by ``test_extension_arc_spacing_is_ssdna_contour``, and (for the world-axis bow,
     which degenerates under rotation) ``test_extension_arc_is_rigid_under_cluster_rotation``.
  2. SEED — letting ``oxdna_native_seed_map`` shift a tail bead along its OWN a1 (the free /
     naive behaviour): the bond's two ends then move in different directions by ~0.44 nm and
     163 of VoltronCoreScad's 334 tails land past the FENE cliff.
  3. SEED — exempting tail beads from that shift entirely: worse (all 334 over), because the
     anchor still moves away from them.
  4. WALK — solving a 5′ tail in chain order rather than anchor-outward, which leaves the
     bead0→anchor bond unconstrained (it collapsed to 0.476 units, under the SHORT cliff).
  2–4 are pinned by ``test_extension_seed_bonds_sit_inside_the_fene_window``.

Two things worth knowing before you edit these:

* The FENE potential diverges at r0 ± delta, so a bond that is too SHORT kills the run
  exactly as dead as one that is too long — while ``backbone_fene_stretch`` only reports the
  long side.  These tests assert the window on BOTH sides.
* The FENE oracle does NOT catch a bad arc, which is why (1) has its own test.
  ``_resolve_extension_geometry`` SOLVES for the base's a1, and the backbone site's ~0.41 nm
  lever arm can reach r0 even when the beads are sitting on top of each other — a legal bond
  between overlapping nucleotides (a steric blow-up rather than a FENE one).  Don't merge
  the arc test into the FENE test on the assumption that one implies the other.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Design, StrandExtension
from backend.core.oxdna_health import (
    FENE_DELTA,
    FENE_R0_OXDNA2,
    FENE_SAFE_MAX_UNITS,
    oxdna_backbone_site,
)
from backend.physics.oxdna_interface import (
    OXDNA_LENGTH_UNIT,
    StaleJobTopologyError,
    _strand_nucleotide_order,
    assert_topology_matches_design,
    backbone_bond_pairs,
    is_extension_key,
    read_configuration_full,
    topology_rows,
    write_configuration,
    write_topology,
)

FENE_LO = FENE_R0_OXDNA2 - FENE_DELTA      # 0.5064 units — the SHORT-bond cliff
FENE_HI = FENE_R0_OXDNA2 + FENE_DELTA      # 1.0064 units — the LONG-bond cliff

VOLTRON = Path("workspace/VoltronCoreScad.nadoc")
SMALL   = Path("Examples/6hb_test.nadoc")

# VOLTRON is a real user design (334 single-T extensions) kept in the local workspace, not
# committed to the repo — skip its regressions cleanly on a checkout that doesn't have it
# rather than erroring with FileNotFoundError.
_needs_voltron = pytest.mark.skipif(
    not VOLTRON.exists(), reason=f"{VOLTRON} not present (user-local design)")


def _load(path: Path) -> Design:
    return Design.model_validate(json.loads(path.read_text()))


def _small_with_extensions(**kw) -> Design:
    """6hb with a 2-base 3′ tail, a 1-base 5′ tail, and a 5-base 3′ tail."""
    d = _load(SMALL)
    d.extensions = [
        StrandExtension(strand_id=d.strands[1].id, end="three_prime", sequence="TT"),
        StrandExtension(strand_id=d.strands[2].id, end="five_prime",  sequence="A"),
        StrandExtension(strand_id=d.strands[4].id, end="three_prime", sequence="TTTTT"),
    ]
    return d


def _seed(design: Design, tmp_path: Path):
    """Write the relaxation seed config the way ``prepare_oxdna_job`` does, then read it
    back the way the health check does — so we measure what oxDNA is actually handed."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    geo = _geometry_for_design(design)
    conf = tmp_path / "conf.dat"
    write_configuration(design, geo, conf, oxdna_native_seed=True)
    return read_configuration_full(conf, design, include_extensions=True)


def _bond_units(full_map: dict, a: tuple, b: tuple) -> float | None:
    """Backbone-SITE separation of a bonded pair, in oxDNA units — the exact quantity
    oxDNA's FENE term checks (the centre-of-mass distance badly under-reads it)."""
    pa, pb = full_map.get(a), full_map.get(b)
    if pa is None or pb is None:
        return None
    sa = oxdna_backbone_site(pa["backbone_position"], pa["a1"], pa["a3"])
    sb = oxdna_backbone_site(pb["backbone_position"], pb["a1"], pb["a3"])
    return float(np.linalg.norm(sa - sb)) / OXDNA_LENGTH_UNIT


def _extension_bonds(design: Design, full_map: dict) -> list[float]:
    return [
        u for a, b in backbone_bond_pairs(design)
        if (is_extension_key(a) or is_extension_key(b))
        and (u := _bond_units(full_map, a, b)) is not None
    ]


# ── Materialisation ───────────────────────────────────────────────────────────


def test_extension_bases_become_particles():
    """One particle per extension BASE — and none for a modification-only extension."""
    bare = _load(SMALL)
    bare.extensions = []
    d = _small_with_extensions()
    d.extensions.append(       # a fluorophore is not DNA: it must add ZERO particles
        StrandExtension(strand_id=d.strands[3].id, end="five_prime", modification="cy3")
    )

    n_bare = len(_strand_nucleotide_order(bare))
    n_ext  = len(_strand_nucleotide_order(d))
    assert n_ext - n_bare == 2 + 1 + 5 == sum(len(e.sequence or "") for e in d.extensions)


def test_extension_does_not_consume_the_strand_sequence():
    """Extension bases carry their OWN base char and must not advance the strand's
    sequence cursor — a staple with a GGG tail still writes its designed bases, in order,
    on its real nucleotides.  (If the tail consumed the cursor, the strand's own sequence
    would be shifted by three and the last three real bases would go undefined.)"""
    from backend.physics.oxdna_interface import _walk_strand_nucleotides

    d = _load(SMALL)
    strand = d.strands[1]
    n_real = sum(1 for s in _walk_strand_nucleotides(d) if s.strand.id == strand.id)
    designed = "".join("ACGT"[i % 4] for i in range(n_real))
    strand.sequence = designed

    d.extensions = [
        StrandExtension(strand_id=strand.id, end="three_prime", sequence="GGG"),
    ]

    # walk THIS strand only, in emission order
    steps = [s for s in _walk_strand_nucleotides(d) if s.strand.id == strand.id]
    rows, _ = topology_rows(d)
    order = _strand_nucleotide_order(d)
    base_of = {k: r[1] for k, r in zip(order, rows)}

    real = "".join(base_of[s.key] for s in steps if not s.is_extension)
    tail = "".join(base_of[s.key] for s in steps if s.is_extension)

    assert real == designed
    assert tail == "GGG"


def test_five_prime_tail_is_walked_outermost_first():
    """A 5′ tail's OUTERMOST bead is the 5′ terminus, so the walk must emit it FIRST
    (i = n-1 … 0) and index ext.sequence (stored 5′→3′) from there."""
    d = _load(SMALL)
    d.extensions = [
        StrandExtension(strand_id=d.strands[1].id, end="five_prime", sequence="ACG"),
    ]
    order = _strand_nucleotide_order(d)
    rows, _ = topology_rows(d)
    base_of = {k: r[1] for k, r in zip(order, rows)}
    tail = [k for k in order if is_extension_key(k)]

    assert [k[1] for k in tail] == [2, 1, 0]              # outermost bead first
    assert [base_of[k] for k in tail] == ["A", "C", "G"]  # 5′→3′


def test_topology_and_config_line_counts_match():
    d = _small_with_extensions()
    order = _strand_nucleotide_order(d)
    rows, _ = topology_rows(d)
    assert len(rows) == len(order)


def test_extension_threads_into_the_backbone_chain():
    """n3/n5 must bond anchor → tail (3′) and tail → anchor (5′), with the tail's free
    tip left dangling.  The tail must NOT be an isolated 2-particle strand."""
    d = _load(SMALL)
    s3, s5 = d.strands[1], d.strands[2]
    d.extensions = [
        StrandExtension(strand_id=s3.id, end="three_prime", sequence="TT"),
        StrandExtension(strand_id=s5.id, end="five_prime",  sequence="TT"),
    ]
    order = _strand_nucleotide_order(d)
    rows, _ = topology_rows(d)
    idx = {k: i for i, k in enumerate(order)}

    for e in d.extensions:
        tail = [k for k in order if is_extension_key(k) and k[0].endswith(e.id)]
        assert len(tail) == 2
        # order[] is chain order, so the free 5′/3′ terminus is the outer end.
        first, last = idx[tail[0]], idx[tail[-1]]
        n5_first = rows[first][3]
        n3_last  = rows[last][2]
        if e.end == "three_prime":
            # tail runs anchor → t0 → t1;  t1 (the tip) has no 3′ neighbour
            assert n5_first != -1 and rows[n5_first][0] == rows[first][0]
            assert n3_last == -1
        else:
            # tail runs t_outer → t_inner → anchor;  t_outer (the tip) has no 5′ neighbour
            assert n5_first == -1
            assert n3_last != -1 and rows[n3_last][0] == rows[last][0]


# ── The arc itself (bead SPACING, independent of the oxDNA frame) ────────────


def _arc_spacings(design: Design) -> dict[str, list[float]]:
    """Consecutive backbone separations along each tail, anchor outward (nm)."""
    geo  = _geometry_for_design(design)
    real = {(n["helix_id"], n["bp_index"], n["direction"]): n for n in geo
            if not n["helix_id"].startswith("__ext_")}
    beads: dict[str, dict[int, np.ndarray]] = {}
    for n in geo:
        if n["helix_id"].startswith("__ext_"):
            beads.setdefault(n["extension_id"], {})[n["bp_index"]] = \
                np.asarray(n["backbone_position"], dtype=float)

    strands = {s.id: s for s in design.strands}
    out: dict[str, list[float]] = {}
    for e in design.extensions:
        s = strands[e.strand_id]
        five = e.end == "five_prime"
        dom = s.domains[0] if five else s.domains[-1]
        bp  = dom.start_bp if five else dom.end_bp
        anchor = real[(dom.helix_id, bp, dom.direction.value)]
        chain = [np.asarray(anchor["backbone_position"], dtype=float)]
        chain += [beads[e.id][i] for i in sorted(beads[e.id])]
        out[e.id] = [float(np.linalg.norm(chain[i + 1] - chain[i]))
                     for i in range(len(chain) - 1)]
    return out


@pytest.mark.parametrize("n", [1, 2, 3, 5, 10])
def test_extension_arc_spacing_is_ssdna_contour(n):
    """CAN-GO-RED. Tail beads are REAL NUCLEOTIDES, so the arc's bead spacing IS a set of
    oxDNA backbone bonds and an all-atom O3′→P chain — it is load-bearing, not cosmetic.

    The old display arc used ``n * 0.34`` nm (the dsDNA rise) AND put bead i at
    ``t=(i+1)/(n_total+1)``, reserving a phantom slot past the tip — so a lone T landed
    0.177 nm from its anchor, less than a third of an ssDNA contour length and deep inside
    the neighbouring nucleotide.  This pins both fixes.

    Upper bound 0.794 nm is the analytic worst case: the radial part of B(t) is exactly
    linear in t (p1's radial component is half of p2's), so all non-uniformity comes from
    the bow term, bounded by sqrt(1 + (2·0.30)²)·0.68 independent of n.
    """
    d = _load(SMALL)
    d.extensions = [
        StrandExtension(strand_id=d.strands[1].id, end="three_prime", sequence="T" * n),
        StrandExtension(strand_id=d.strands[2].id, end="five_prime",  sequence="T" * n),
    ]
    for spacings in _arc_spacings(d).values():
        assert len(spacings) == n
        assert all(0.68 - 1e-6 <= s <= 0.794 for s in spacings), spacings


def test_extension_arc_is_rigid_under_cluster_rotation():
    """CAN-GO-RED. The bow must be taken in the anchor's own deformed frame, not along a
    WORLD axis.  A world bow degenerates when a rotation lines the radial up with it (the
    arc doubles back), which both over- and under-shoots the FENE window.  Rotating the
    whole design must leave every bead spacing identical.
    """
    d = _load(SMALL)
    d.extensions = [
        StrandExtension(strand_id=d.strands[1].id, end="three_prime", sequence="TTTTT"),
    ]
    before = _arc_spacings(d)

    # Rotate the structure so the radial swings toward the old world-+Z bow axis.
    for h in d.helices:
        for p in (h.axis_start, h.axis_end):
            p.x, p.y, p.z = p.x, -p.z, p.y      # 90° about X
    after = _arc_spacings(d)

    for ext_id, spacings in before.items():
        assert np.allclose(spacings, after[ext_id], atol=1e-9), (
            f"arc changed under rotation: {spacings} -> {after[ext_id]}")


# ── The FENE oracle (the reason this feature is hard) ─────────────────────────


@pytest.mark.parametrize("n", [1, 2, 3, 5, 10])
@pytest.mark.parametrize("end", ["three_prime", "five_prime"])
def test_extension_seed_bonds_sit_inside_the_fene_window(tmp_path, n, end):
    """CAN-GO-RED, and the whole point of the feature. Every backbone bond touching a
    tail must be inside oxDNA's FENE window — on BOTH sides, since the potential
    diverges at r0 ± delta and a too-short bond kills the run just as dead as a
    too-long one.

    Goes red on: a naive own-a1 native-seed shift (bonds over FENE_HI — 163 of
    VoltronCoreScad's 334); exempting tails from that shift (all 334 over); and solving a
    5′ tail in chain order rather than anchor-outward, which leaves the bead0→anchor bond
    unconstrained (it collapsed to 0.476, under FENE_LO).

    It does NOT catch a bad ARC — the a1 solve reaches r0 via its 0.41 nm lever arm even
    when the beads are on top of each other, which would leave the bond legal but the
    nucleotides overlapping (a steric blow-up instead of a FENE one).  The arc has its own
    pin: ``test_extension_arc_spacing_is_ssdna_contour``.
    """
    d = _load(SMALL)
    d.extensions = [
        StrandExtension(strand_id=d.strands[1].id, end=end, sequence="T" * n),
    ]
    full_map = _seed(d, tmp_path)
    bonds = _extension_bonds(d, full_map)

    assert len(bonds) == n
    assert all(FENE_LO < u < FENE_HI for u in bonds), f"outside FENE window: {bonds}"
    # would not trip the relaxation's fene_safe gate either
    assert max(bonds) < FENE_SAFE_MAX_UNITS, bonds
    # the bond touching the ANCHOR is solved exactly onto the FENE rest length, so the
    # tail starts relaxed rather than merely legal
    assert min(bonds) == pytest.approx(FENE_R0_OXDNA2, abs=1e-6), bonds


@_needs_voltron
def test_voltroncore_334_tails_are_all_fene_safe(tmp_path):
    """The real design that motivated this: 334 single-T extensions, every one of which
    used to be dropped from the simulation entirely."""
    d = _load(VOLTRON)
    assert len(d.extensions) == 334

    full_map = _seed(d, tmp_path)
    bonds = _extension_bonds(d, full_map)

    assert len(bonds) == 334
    assert min(bonds) > FENE_LO and max(bonds) < FENE_HI
    assert max(bonds) < FENE_SAFE_MAX_UNITS      # would not trip the relax fene_safe gate


def _assert_real_bonds_undisturbed(with_tails: Design, bare: Design, tmp_path: Path):
    """Every REAL backbone bond must be byte-identical with and without the tails — the
    tails hang off the structure, they do not move it.  (Shared by the fast 6hb pin and
    the slow full-scale VoltronCore pin below.)"""
    assert with_tails.extensions and not bare.extensions

    fm      = _seed(with_tails, tmp_path / "with")
    fm_bare = _seed(bare,       tmp_path / "bare")
    real      = [u for a, b in backbone_bond_pairs(with_tails)
                 if not (is_extension_key(a) or is_extension_key(b))
                 and (u := _bond_units(fm, a, b)) is not None]
    real_bare = [u for a, b in backbone_bond_pairs(bare)
                 if (u := _bond_units(fm_bare, a, b)) is not None]

    assert real and len(real) == len(real_bare)
    assert np.allclose(sorted(real), sorted(real_bare))


def test_extensions_do_not_disturb_the_rest_of_the_design(tmp_path):
    """Adding tails must leave every REAL backbone bond byte-identical — the tails hang
    off the structure, they do not move it.

    Proven here on the small 6hb (2-base 3′ tail + 1-base 5′ tail + 5-base 3′ tail, i.e.
    both ends and several lengths), which is what makes this cheap enough to keep in the
    per-change loop.  The invariant is scale-free: the failure it guards is the native
    seed's per-particle a1 shift LEAKING from a tail into its anchor's own solve, which is
    a purely local coupling — a 6hb tail exercises exactly the same code path as one of
    VoltronCoreScad's 334.  The full-scale version runs as
    ``test_voltroncore_extensions_do_not_disturb_the_rest_of_the_design`` in the slow
    suite."""
    bare = _load(SMALL)
    bare.extensions = []
    _assert_real_bonds_undisturbed(_small_with_extensions(), bare, tmp_path)


@_needs_voltron
def test_voltroncore_extensions_do_not_disturb_the_rest_of_the_design(tmp_path):
    """Full-scale twin of the test above: 206 strands / 15020 particles / 334 tails.

    SLOW (registered in ``tests/conftest.py`` → ``_SLOW_TESTS``, area ``oxdna``): it builds
    the whole design's geometry + seeded configuration TWICE (~9.6 s).  The invariant it
    checks is already pinned per-change on the 6hb; this one guards against a
    scale-dependent surprise (an ordering/aggregation bug that only shows up with hundreds
    of tails)."""
    d    = _load(VOLTRON)
    bare = _load(VOLTRON)
    bare.extensions = []
    assert len(d.extensions) == 334
    _assert_real_bonds_undisturbed(d, bare, tmp_path)


def test_tail_a3_points_five_prime_to_three_prime(tmp_path):
    """a3 is the 5′→3′ vector.  A 3′ tail runs OUTWARD along the arc and a 5′ tail runs
    INWARD — neither follows its anchor domain's FORWARD/REVERSE direction, which is what
    ``nuc_conf_line`` would otherwise use.  Goes red on a display-dict passthrough.
    """
    d = _small_with_extensions()
    full_map = _seed(d, tmp_path)

    for a, b in backbone_bond_pairs(d):
        if not (is_extension_key(a) or is_extension_key(b)):
            continue
        pa, pb = full_map.get(a), full_map.get(b)
        if pa is None or pb is None:
            continue
        step = np.asarray(pb["backbone_position"]) - np.asarray(pa["backbone_position"])
        assert float(np.dot(pa["a3"], step)) > 0, f"a3 points backwards on {a}->{b}"


def test_tail_frame_is_orthonormal(tmp_path):
    """The display dict has base_normal ≈ -radial and axis_tangent ≈ +radial, i.e.
    |a1·a3| ≈ 1.  oxDNA needs an orthonormal frame, so the resolver must REBUILD it —
    passing the display dict straight through gives a degenerate frame."""
    d = _small_with_extensions()
    full_map = _seed(d, tmp_path)
    tails = [v for k, v in full_map.items() if is_extension_key(k)]
    assert tails
    for v in tails:
        assert abs(float(np.dot(v["a1"], v["a3"]))) < 1e-6


# ── Read-back contract + the stale-job guard ─────────────────────────────────


def test_readback_drops_tails_by_default(tmp_path):
    """Every existing design-keyed consumer expects real (helix, bp, dir) keys only, so
    tail beads must be absent unless the caller opts in — while still occupying their
    particle slot, so real-nucleotide indices stay aligned."""
    d = _small_with_extensions()
    geo = _geometry_for_design(d)
    conf = tmp_path / "conf.dat"
    write_configuration(d, geo, conf, oxdna_native_seed=True)

    default = read_configuration_full(conf, d)
    opted   = read_configuration_full(conf, d, include_extensions=True)

    assert not any(is_extension_key(k) for k in default)
    assert sum(is_extension_key(k) for k in opted) == 8

    bare = _load(SMALL)
    bare.extensions = []
    bare_conf = tmp_path / "bare.dat"
    write_configuration(bare, _geometry_for_design(bare), bare_conf, oxdna_native_seed=True)
    # the design-keyed view is exactly what it was before the feature existed
    assert set(default) == set(read_configuration_full(bare_conf, bare))


def test_stale_job_topology_is_rejected(tmp_path):
    """A job run BEFORE extension support has fewer particles than the design now walks
    to.  The reader clamps that deficit to zero and would silently hand every nucleotide
    after the first extension the WRONG particle line — so it must be caught up front."""
    bare = _load(SMALL)
    bare.extensions = []
    top = tmp_path / "topology.top"
    write_topology(bare, top)                 # the "old" job's topology

    assert_topology_matches_design(top, bare)  # same build: fine

    grown = _small_with_extensions()           # design now has tails → more particles
    with pytest.raises(StaleJobTopologyError, match="predates"):
        assert_topology_matches_design(top, grown)


# ── Trajectory frame 0 (the "everything at the origin" regression) ────────────


def _write_traj(design, geo, path, n_frames, box_nm=80.0):
    """A tiny oxDNA trajectory of *n_frames* identical design-pose frames."""
    one = path.parent / f"_one_{path.stem}.dat"
    write_configuration(design, geo, one, box_nm=box_nm)
    lines = [l for l in one.read_text().splitlines() if l.strip()]
    hdr, data = lines[:3], lines[3:]
    out = []
    for t in range(n_frames):
        out.append(f"t = {t}")
        out.extend(hdr[1:])
        out.extend(data)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def test_trajectory_first_frame_places_tails_not_the_origin(tmp_path):
    """CAN-GO-RED. The composite trajectory PREPENDS the design-reference conf as frame 0.
    That reference used to be read with the synthetic particles dropped, so every
    extension tail bead (and crossover extra base) was a MISSING key -> six zeros ->
    drawn at the world origin.  The player opened on a starburst of tails converging on
    (0,0,0) that snapped into place at frame 1.

    Frame 0 must carry real coordinates for the tail beads, like every later frame does.
    """
    from backend.core.oxdna_health import composite_trajectory

    d = _small_with_extensions()
    geo = _geometry_for_design(d)
    ref = tmp_path / "design_ref.dat"; _write_traj(d, geo, ref, 1)
    prod = tmp_path / "prod.dat";      _write_traj(d, geo, prod, 2)

    r = composite_trajectory(d, [("4_production", "production", prod)], ref, align=False)
    assert r["n_frames"] == 3                       # seed + 2

    ext_idx = [i for i, k in enumerate(r["keys"]) if is_extension_key(tuple(k))]
    assert len(ext_idx) == 8                        # 2 + 1 + 5 tail beads

    for f, frame in enumerate(r["frames"]):
        for i in ext_idx:
            xyz = np.array(frame[6 * i:6 * i + 3])
            assert np.linalg.norm(xyz) > 1e-6, (
                f"frame {f}: extension bead {r['keys'][i]} sits at the origin")
        # and the seed must agree with the (identical) physical frames it precedes
        if f:
            assert np.allclose(frame, r["frames"][0], atol=1e-6)
