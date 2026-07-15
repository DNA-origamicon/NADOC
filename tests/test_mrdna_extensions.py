"""Strand extensions (5′/3′ terminal ssDNA tails) materialized as beads in the
mrDNA/ARBD path.

`StrandExtension` (e.g. the single T on every staple end of a scadnano import) was
already real DNA in oxDNA and NAMD, but `_build_nt_arrays` — the per-strand walk the
mrDNA SegmentModel is built from — dropped it: a CG relaxation of a design with tails
was byte-identical to one without.  These pins prove the bridge now emits one bead per
extension BASE, hung off a single anchor (the strand's first/last real nucleotide),
unpaired, threaded into the strand's 3′/stack chain, carrying its own base identity
without consuming the strand's designed sequence, and laid on the SAME 0.68 nm outward
Bézier arc the display + oxDNA + NAMD use.

Mirrors ``test_mrdna_extra_bases.py`` (the crossover-extra-base twin — an insert bridges
TWO anchors, a tail hangs off ONE and its far end is free).

THE TRAP (bit three times in the oxDNA work): an extension key is a 3-tuple whose
``bp_index`` is an ordinary ``int >= 0``, so it PASSES every ``isinstance(k[1], int)``
filter written to catch ``__xb__`` (whose bp_index is a crossover-id string).  Guards
must test ``helix_id.startswith("__")`` — pinned by ``test_tails_stay_out_of_*``.

See backend/core/mrdna_bridge.py ``_build_nt_arrays`` and
memory/project_mrdna_extensions.md / project_strand_extensions_sim.md.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from backend.api import headless_build as hb
from backend.api import state as design_state
from backend.core.constants import SSDNA_CONTOUR_PER_NT_NM
from backend.core.mrdna_bridge import _build_nt_arrays, _ssdna_runs
from backend.core.models import Design, LatticeType, StrandExtension
from tests.conftest import SIX_HB_CELLS

VOLTRON = Path("workspace/VoltronCoreScad.nadoc")


def _routed_6hb():
    """A seamless-autoscaffolded, fully-autostapled 6hb — real strand ends to hang
    tails off.  mrDNA is a CG model and needs no WC sequence."""
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(SIX_HB_CELLS, 84, lattice=LatticeType.HONEYCOMB, name="6hb")
        hb.auto_scaffold(seamless=True)
        hb.full_autostaple()
        return design_state.get_or_404().model_copy(deep=True)


@pytest.fixture(scope="module")
def routed_6hb():
    return _routed_6hb()


def _with_tails(design, **kw) -> Design:
    """6hb + a 2-base 3′ tail, a 1-base 5′ tail, a 5-base 3′ tail and (optionally) a
    modification-only extension, which is NOT DNA and must contribute zero beads."""
    d = design.model_copy(deep=True)
    d.extensions = [
        StrandExtension(strand_id=d.strands[1].id, end="three_prime", sequence="TT"),
        StrandExtension(strand_id=d.strands[2].id, end="five_prime",  sequence="A"),
        StrandExtension(strand_id=d.strands[4].id, end="three_prime", sequence="GCTAG"),
    ]
    if kw.get("modification_only"):
        d.extensions.append(
            StrandExtension(strand_id=d.strands[6].id, end="five_prime", modification="cy3")
        )
    return d


def _arrays(design):
    """(r, bp, stack, three_prime, seq, ext_idx_by_key) — ext_idx_by_key maps each
    ``("__ext_<id>", bead_i, direction)`` tail-bead key to its bead index."""
    r, bp, stack, tp, _orient, seq, ntkey = _build_nt_arrays(design, return_nt_key=True)
    ext = {(h, b, dr): i for (h, b, dr, k), i in ntkey.items() if h.startswith("__ext_")}
    return r, bp, stack, tp, seq, ext


def _five_prime_of(tp) -> dict:
    """bead index → its 5′ (chain-predecessor) bead index."""
    return {int(j): i for i, j in enumerate(tp) if int(j) >= 0}


# ── no-regression: extension-free designs are untouched ───────────────────────

def test_no_extensions_no_beads(routed_6hb):
    assert routed_6hb.extensions == []
    *_, ext = _arrays(routed_6hb)
    assert ext == {}


# ── pin #1: bead count grows by exactly the extension-base total ──────────────

def test_bead_count_grows_by_extension_base_total(routed_6hb):
    base_r, *_ = _build_nt_arrays(routed_6hb)
    d = _with_tails(routed_6hb)
    n_ext = sum(len(e.sequence or "") for e in d.extensions)
    assert n_ext == 8
    r, *_ = _build_nt_arrays(d)
    assert len(r) - len(base_r) == n_ext


def test_modification_only_extension_adds_no_beads(routed_6hb):
    """A cy3/biotin with no sequence is not DNA: zero beads (it still renders)."""
    plain = _with_tails(routed_6hb)
    mod   = _with_tails(routed_6hb, modification_only=True)
    assert len(mod.extensions) == len(plain.extensions) + 1
    r_plain, *_ = _build_nt_arrays(plain)
    r_mod,   *_ = _build_nt_arrays(mod)
    assert len(r_mod) == len(r_plain)


# ── pin #2: tail beads are single-stranded (unpaired) ─────────────────────────

def test_tail_beads_are_unpaired(routed_6hb):
    d = _with_tails(routed_6hb)
    _r, bp, _stack, _tp, _seq, ext = _arrays(d)
    assert len(ext) == 8
    assert all(bp[i] == -1 for i in ext.values())


# ── pin #3: the tail is threaded into the strand chain (3′ + stack) ───────────
#   Can-go-red: emit the beads without splicing strand_indices → every tp is −1.

def test_three_prime_tail_threads_anchor_to_tip(routed_6hb):
    """3′ tail: anchor → bead0 → … → bead n-1, and the outermost bead is a free 3′ end."""
    d = _with_tails(routed_6hb)
    ext3 = next(e for e in d.extensions if e.sequence == "GCTAG")
    _r, bp, stack, tp, _seq, ext = _arrays(d)
    beads = [ext[(f"__ext_{ext3.id}", i, dr)]
             for i in range(5) for dr in ("FORWARD", "REVERSE")
             if (f"__ext_{ext3.id}", i, dr) in ext]
    assert len(beads) == 5

    anchor = _five_prime_of(tp)[beads[0]]
    assert bp[anchor] >= 0                       # the anchor is real, paired duplex
    for a, b in zip([anchor, *beads[:-1]], beads):
        assert tp[a] == b                        # 3′ chain runs anchor → tip
        assert stack[a] == b                     # stacking mirrors it
    assert tp[beads[-1]] == -1                   # the tip is the strand's 3′ end


def test_five_prime_tail_threads_tip_to_anchor(routed_6hb):
    """5′ tail: the OUTERMOST bead is the strand's 5′ terminus, so the chain runs
    tip → … → bead0 → anchor.  Getting this backwards left a bond unconstrained in
    oxDNA (it collapsed under the FENE short cliff)."""
    d = _with_tails(routed_6hb)
    ext5 = next(e for e in d.extensions if e.end == "five_prime")
    _r, bp, stack, tp, _seq, ext = _arrays(d)
    (key, bead), = [(k, i) for k, i in ext.items() if k[0] == f"__ext_{ext5.id}"]
    assert key[1] == 0                           # a 1-base tail: bead 0 IS the tip

    assert bead not in _five_prime_of(tp)        # free 5′ end: no chain predecessor
    anchor = int(tp[bead])
    assert bp[anchor] >= 0                       # threads INTO the duplex anchor
    assert stack[bead] == anchor


def test_five_prime_tail_is_walked_outermost_first(routed_6hb):
    """A multi-base 5′ tail runs bead n-1 (outermost = 5′ terminus) → … → bead 0 →
    anchor, and its bases index ext.sequence 5′→3′ along that walk."""
    d = _with_tails(routed_6hb)
    d.extensions = [StrandExtension(
        strand_id=d.strands[2].id, end="five_prime", sequence="GCA")]
    _r, bp, _stack, tp, seq, ext = _arrays(d)
    e = d.extensions[0]
    dr = next(k[2] for k in ext)
    b2, b1, b0 = (ext[(f"__ext_{e.id}", i, dr)] for i in (2, 1, 0))

    assert b2 not in _five_prime_of(tp)          # outermost bead is the 5′ terminus
    assert tp[b2] == b1 and tp[b1] == b0         # walked inward toward the anchor
    assert bp[int(tp[b0])] >= 0                  # bead0's 3′ neighbour is the anchor
    assert [seq[b] for b in (b2, b1, b0)] == ["G", "C", "A"]   # ext.sequence 5′→3′


# ── pin #4: base identity from ext.sequence — the strand's cursor is NOT consumed ─
#   This bug bit TWICE in oxDNA (topology_rows and count_undefined_bases each had
#   their own copy of the sequence logic).

def test_tail_bases_come_from_the_extension_not_the_strand_sequence(routed_6hb):
    d = _with_tails(routed_6hb)
    for s in d.strands:
        s.sequence = "A" * 5000
    _r, _bp, _stack, _tp, seq, ext = _arrays(d)
    ext3 = next(e for e in d.extensions if e.sequence == "GCTAG")
    dr = next(k[2] for k in ext if k[0] == f"__ext_{ext3.id}")
    chars = [seq[ext[(f"__ext_{ext3.id}", i, dr)]] for i in range(5)]
    assert chars == list("GCTAG")                # own bases, i=0 nearest the anchor

    # and every REAL nucleotide still reads its own designed base (cursor not shifted).
    r0, *_ = _build_nt_arrays(routed_6hb)
    _r2, _bp2, _s2, _tp2, seq2, ext2 = _arrays(d)
    real = [c for i, c in enumerate(seq2) if i not in set(ext2.values())]
    assert real == ["A"] * len(r0)


# ── pin #5: bead geometry — the shared 0.68 nm ssDNA-contour arc ──────────────
#   The twin of test_insert_geometry_even_and_noncoincident.  Cross-engine: this is
#   the arc oxDNA and the atomistic model already put the tails on.

def test_tail_arc_spacing_is_ssdna_contour(routed_6hb):
    d = _with_tails(routed_6hb)
    r, _bp, _stack, tp, _seq, ext = _arrays(d)
    five_p = _five_prime_of(tp)

    seglens: list[float] = []
    for key, i in ext.items():
        for j in (int(tp[i]), five_p.get(i, -1)):    # both bonds this bead is in
            if j >= 0:
                seglens.append(float(np.linalg.norm(r[i] - r[j])) / 10.0)   # Å → nm
    assert seglens
    assert min(seglens) > 0.1                       # never coincident (steric blow-up)
    # One ssDNA contour length per bead; the Bézier bow bounds the spread (≤0.793 nm).
    assert min(seglens) >= SSDNA_CONTOUR_PER_NT_NM - 1e-6
    assert max(seglens) <= 0.80


def test_tail_bows_away_from_the_helix_axis(routed_6hb):
    """Beads march radially OUTWARD from the anchor (they must not be laid back into
    the duplex): each successive bead is farther from the helix axis than the last."""
    from backend.core.geometry import helix_axis_point

    d = _with_tails(routed_6hb)
    ext3 = next(e for e in d.extensions if e.sequence == "GCTAG")
    strand = next(s for s in d.strands if s.id == ext3.strand_id)
    dom = strand.domains[-1]
    helix = d.find_helix(dom.helix_id)
    axis_pt = helix_axis_point(helix, dom.end_bp)
    axis_vec = helix.axis_end.to_array() - helix.axis_start.to_array()
    axis_hat = axis_vec / np.linalg.norm(axis_vec)

    r, *_rest, ext = _arrays(d)
    dr = next(k[2] for k in ext if k[0] == f"__ext_{ext3.id}")

    def radial_nm(p_ang):
        v = p_ang / 10.0 - np.asarray(axis_pt)
        return float(np.linalg.norm(v - np.dot(v, axis_hat) * axis_hat))

    dists = [radial_nm(r[ext[(f"__ext_{ext3.id}", i, dr)]]) for i in range(5)]
    assert all(b > a for a, b in zip(dists, dists[1:]))


# ── pin #6: the tails surface as ssDNA runs (the relaxed read-back path) ──────
#   _ssdna_runs feeds nuc_pos_override_ssdna_from_arbd, which is what places tail
#   beads on the RELAXED structure.  It maps indices back through nt_key, so tail
#   beads only surface here because they carry a key.

def test_tails_surface_as_ssdna_runs_with_the_right_root_side(routed_6hb):
    d = _with_tails(routed_6hb)
    runs = _ssdna_runs(d)
    ext_runs = [
        run for run in runs
        if any(k is not None and k[0].startswith("__ext_") for k in run["keys"])
    ]
    assert len(ext_runs) == 3                      # one run per (sequence-carrying) tail

    by_end = {}
    for run in ext_runs:
        eid = next(k[0] for k in run["keys"] if k and k[0].startswith("__ext_"))
        by_end[eid] = run
    for e in d.extensions:
        run = by_end[f"__ext_{e.id}"]
        assert run["root_key"] is not None
        assert not run["root_key"][0].startswith("__")          # roots in the duplex
        # A 3′ tail's root PRECEDES it in the chain (root_side '5p'); a 5′ tail's
        # root FOLLOWS it ('3p') — the tail runs tip→anchor.
        assert run["root_side"] == ("5p" if e.end == "three_prime" else "3p")


# ── pin #7: THE TRAP — tail keys must not leak into dsDNA-core / anchor paths ──

def test_tails_stay_out_of_the_dsdna_core_shape_column(routed_6hb):
    """mrdna_shape_source's core mask + RMSF filter must drop tail beads.  A tail's
    bp_index is an int ≥ 0, so the isinstance(bp, int) filter written for __xb__ does
    NOT catch it — can-go-red by removing the ``__`` prefix guard in _rmsf_profile."""
    from backend.api.skip_twist_tuning import core_reference_geometry
    from backend.core.mrdna_shape_source import build_mrdna_shape_source

    d = _with_tails(routed_6hb)
    ref = core_reference_geometry(d)
    frame = [
        {"helix_id": p["helix_id"], "bp_index": p["bp_index"],
         "direction": p["direction"], "backbone_position": p["backbone_position"]}
        for p in ref
    ] + [
        {"helix_id": "__ext_abc", "bp_index": 0, "direction": "FORWARD",
         "backbone_position": [9.0, 9.0, 9.0]},
    ]
    rmsf = [
        {"helix_id": "__ext_abc", "bp_index": 0, "direction": "FORWARD",
         "copy": 0, "rmsf_nm": 5.0},
        {"helix_id": ref[0]["helix_id"], "bp_index": ref[0]["bp_index"],
         "direction": ref[0]["direction"], "copy": 0, "rmsf_nm": 0.2},
    ]
    src = build_mrdna_shape_source(frame, ref, rmsf=rmsf)
    assert all(p["helix_id"] != "__ext_abc" for p in src["shape_frame"])
    assert all(p["helix_id"] != "__ext_abc" for p in src["rmsf"])
    assert len(src["rmsf"]) == 1


def test_tail_beads_are_never_anchor_tether_points(routed_6hb):
    """A 'strand' anchor scope selects the tail's particles too (they carry the
    strand id), but a floppy terminal tail is not a rigid tether: mrdna_anchors must
    resolve only the strand's DUPLEX nucleotides."""
    from backend.core.mrdna_anchors import _anchor_nt_positions

    d = _with_tails(routed_6hb)
    ext3 = next(e for e in d.extensions if e.sequence == "GCTAG")
    anchors = [{"kind": "strand", "id": ext3.strand_id}]

    r, _bp, _stack, _tp, _seq, ext = _arrays(d)
    tail_pts = {tuple(np.round(r[i], 6)) for k, i in ext.items()
                if k[0] == f"__ext_{ext3.id}"}
    pos = _anchor_nt_positions(d, anchors)
    assert len(pos) > 0
    assert not any(tuple(np.round(p, 6)) in tail_pts for p in pos)


# ── cross-engine scale check: VoltronCoreScad's 334 tails ─────────────────────

@pytest.mark.skipif(not VOLTRON.exists(), reason="VoltronCoreScad.nadoc not present")
def test_voltroncore_model_grows_by_334_beads():
    """The cross-engine number: VoltronCoreScad carries 334 single-T extensions, and
    mrDNA must now grow by +334 beads — matching oxDNA's +334 particles and the
    atomistic model's +334 residues."""
    d = Design.model_validate(json.loads(VOLTRON.read_text()))
    n_ext = sum(len(e.sequence or "") for e in d.extensions)
    assert n_ext == 334

    r, bp, _stack, _tp, _seq, ext = _arrays(d)
    assert len(ext) == 334
    assert all(bp[i] == -1 for i in ext.values())

    d0 = d.model_copy(deep=True)
    d0.extensions = []
    r0, *_ = _build_nt_arrays(d0)
    assert len(r) - len(r0) == 334


# ── model-level: the tails survive mrDNA's coarse-grainer as flexible ssDNA ───

_has_mrdna = False
try:
    import sys

    from backend.core.mrdna_bridge import mrdna_tool_path
    sys.path.insert(0, mrdna_tool_path())
    import mrdna  # noqa: F401
    _has_mrdna = True
except Exception:  # noqa: BLE001
    pass

skip_no_mrdna = pytest.mark.skipif(not _has_mrdna, reason="mrdna not installed")


def _model_seg_stats(design):
    """(tot_nt, ss_nt, ds_nt) of the built mrDNA SegmentModel — nucleotides as
    classified by mrDNA's OWN coarse-grainer, not by our input arrays."""
    from mrdna import DoubleStrandedSegment, SingleStrandedSegment
    from mrdna.readers.segmentmodel_from_lists import model_from_basepair_stack_3prime

    r, bp, stack, tp, orient, seq, _ = _build_nt_arrays(design, return_nt_key=True)
    m = model_from_basepair_stack_3prime(
        r, bp, stack, tp, sequence=seq, orientation=orient)
    ss = sum(s.num_nt for s in m.segments if isinstance(s, SingleStrandedSegment))
    ds = sum(s.num_nt for s in m.segments if isinstance(s, DoubleStrandedSegment))
    return ss + ds, ss, ds


@skip_no_mrdna
def test_tails_are_flexible_ssdna_in_the_built_model(routed_6hb):
    """Past the bridge: every tail base becomes exactly one SIMULATED nucleotide, all of
    the growth lands in single-stranded (flexible, non-rigid) segments, and the rigid
    WC-paired ds content is invariant.  Can-go-red if a tail were ever base-paired into
    a rigid ds segment."""
    base_tot, base_ss, base_ds = _model_seg_stats(routed_6hb)
    d = _with_tails(routed_6hb)
    n_ext = sum(len(e.sequence or "") for e in d.extensions)
    with_tot, with_ss, with_ds = _model_seg_stats(d)

    assert with_tot - base_tot == n_ext
    assert with_ds == base_ds
    assert with_ss - base_ss == n_ext


# ── pin #8 (slow, opt-in): a real ARBD sim runs end-to-end with the tails ─────

@pytest.mark.slow
@skip_no_mrdna
def test_real_arbd_runs_with_extensions(tmp_path, routed_6hb):
    """End-to-end on the real GPU: the tails simulate (ARBD has finite bonded potentials
    and its own steric blow-up mode — 'mrDNA is forgiving' is an assumption, not a fact),
    the CG bead cloud grows, and the display emits ``__ext_``-keyed relaxed positions the
    frontend already addresses (same key as oxDNA/NAMD)."""
    from backend.core.mrdna_bridge import (
        ensure_wsl_cuda_libs,
        find_arbd,
        mrdna_model_from_nadoc,
    )
    from backend.core.mrdna_runner import _SIM_STEM, extract_mrdna_results

    if find_arbd() is None:
        pytest.skip("ARBD binary not found")
    ensure_wsl_cuda_libs()

    def _run(design, out):
        out.mkdir(parents=True, exist_ok=True)
        mrdna_model_from_nadoc(design).simulate(
            output_name=_SIM_STEM, directory=str(out),
            num_steps=500, timestep=200e-6, gpu=0, output_period=250)
        return extract_mrdna_results(design, out)

    d = _with_tails(routed_6hb)
    n_ext = sum(len(e.sequence or "") for e in d.extensions)
    try:
        res_with = _run(d, tmp_path / "with")
        res_base = _run(routed_6hb, tmp_path / "base")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"ARBD simulation unavailable: {exc}")

    ids = {f"__ext_{e.id}" for e in d.extensions}
    tails = [p for p in res_with["positions"] if p["helix_id"] in ids]
    assert len(tails) == n_ext                        # every tail bead follows the shape
    assert all(isinstance(p["bp_index"], int) for p in tails)
    assert not any(str(p["helix_id"]).startswith("__ext_") for p in res_base["positions"])

    # The tail beads join the simulated CG cloud — real particles, not bookkeeping.
    assert res_with["n_beads"] >= res_base["n_beads"]

    # Relaxed tails stay attached: no bead is flung away from the relaxed body.
    body = np.array([p["backbone_position"] for p in res_with["positions"]
                     if p["helix_id"] not in ids])
    for p in tails:
        dmin = np.linalg.norm(body - np.array(p["backbone_position"]), axis=1).min()
        assert dmin < 2.0                              # nm — still on the structure
