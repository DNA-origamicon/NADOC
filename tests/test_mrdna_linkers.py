"""Oracle for M4 — linkers / overhang connections threaded through to the ARBD model.

An :class:`~backend.core.models.OverhangConnection` (a linker) is a real
topological edit: ``connect_overhangs`` materializes the linker complement
strand(s) so each overhang HYBRIDIZES to the linker's reverse-complementary
binding domain — the linked overhang becomes locally **duplex** — plus a virtual
``__lnk__`` bridge helix.  The bridge is a **duplex** for a ``ds`` linker (two
strands' bridge halves paired antiparallel — a rigid connector) and a
**single-stranded tether** for a ``ss`` linker (one strand carries an unpaired
ssDNA run between the two complements — the flexible confinement element).

The mrDNA bridge (``_build_nt_arrays`` → ``model_from_basepair_stack_3prime``)
only READS this generated topology (Three-Layer Law); nothing here mutates the
``Design``.  These pins prove the linker survives coarse-graining into the built
ARBD SegmentModel with the CORRECT mechanical class — the ds bridge is a rigid
duplex segment, the ss bridge a flexible single-stranded segment — the same
rigid-duplex-vs-compliant-tether distinction C4 makes for the CanDo FEM, so the
two engines agree on what a linker *is*.

Contrast with :mod:`tests.test_mrdna_extra_bases`: crossover extra bases are
ALWAYS ssDNA inserts; a linker's bridge is ds OR ss by ``linker_type``.

See backend/core/mrdna_bridge.py ``_build_nt_arrays`` and
backend/core/lattice.py ``generate_linker_topology``.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.api import headless_build as hb
from backend.core.models import LatticeType
from backend.core.mrdna_bridge import _build_nt_arrays
from tests.test_headless_build import _place_two_overhangs_on_6hb

_LNK = "__lnk__"


# ── Fixtures ─────────────────────────────────────────────────────────────────
#
# ds and ss linkers require DIFFERENT (attach × attach) combos: the Watson-Crick
# polarity rule accepts a ds bridge only when both sides are comp-first and a ss
# bridge only when they differ (see lattice._is_comp_first / overhang_ops.
# _check_linker_compatibility).  But the COMPLEMENT domain (the overhang-
# hybridizing half) is attach-INDEPENDENT — `_make_complement_domain` keys off
# the overhang domain alone — so both linker types hybridize the SAME overhang
# nucleotides.  That lets a ds-model-vs-ss-model diff on the same two overhangs
# isolate the BRIDGE exactly (everything else is identical).

_DS_ATTACH = ("free_end", "free_end")  # both comp-first  → valid ds
_SS_ATTACH = ("root", "free_end")  # mixed polarity   → valid ss


def _link(linker_type, length_bp, attach):
    """A REAL routed 6HB with two extruded overhangs tied by a linker of the given
    type/length, deep-copied off the scratch session.  Returns (design, bridge_id)."""
    with hb.scratch_session(LatticeType.HONEYCOMB):
        _bare, (a_id, b_id) = _place_two_overhangs_on_6hb()
        d = hb.connect_overhangs(
            a_id,
            b_id,
            overhang_a_attach=attach[0],
            overhang_b_attach=attach[1],
            linker_type=linker_type,
            length_value=length_bp,
            length_unit="bp",
        )
        d = d.model_copy(deep=True)
    bridge = next(h.id for h in d.helices if h.id.startswith(_LNK))
    return d, bridge


def _bare_6hb():
    with hb.scratch_session(LatticeType.HONEYCOMB):
        bare, _ids = _place_two_overhangs_on_6hb()
        return bare.model_copy(deep=True)


def _bridge_indices(design):
    """(r, bp, tp, seq, bridge_idxs) — the bead indices whose nt_key names a
    ``__lnk__`` bridge helix (the linker bridge nucleotides)."""
    r, bp, stack, tp, orient, seq, ntkey = _build_nt_arrays(design, return_nt_key=True)
    bridge = sorted(i for k, i in ntkey.items() if str(k[0]).startswith(_LNK))
    return r, bp, tp, seq, bridge


# ── FAST (always-run): the coarse-grainer INPUT arrays carry the bridge ───────


def test_no_linker_no_bridge_beads():
    """Control: a bundle with no connection emits no ``__lnk__`` bridge beads."""
    *_ignore, bridge = _bridge_indices(_bare_6hb())
    assert bridge == []


def test_ds_bridge_is_a_duplex_in_the_arrays():
    """A ds linker's bridge nucleotides are ALL base-paired — a duplex bridge (a
    rigid connector), exactly ``2*linker_bp`` beads (both antiparallel halves)."""
    L = 6
    d, _bridge = _link("ds", L, _DS_ATTACH)
    _r, bp, _tp, _seq, bridge = _bridge_indices(d)
    assert len(bridge) == 2 * L  # both bridge halves present
    assert all(bp[i] != -1 for i in bridge)  # every bridge bead is WC-paired
    # each bridge bead's partner is the OTHER bridge half (paired within the bridge)
    assert all(bp[i] in bridge for i in bridge)


def test_ss_bridge_is_a_flexible_ssdna_tether_in_the_arrays():
    """A ss linker's bridge nucleotides are ALL unpaired — a single-stranded tether
    (the flexible confinement element), exactly ``linker_bp`` beads."""
    L = 6
    d, _bridge = _link("ss", L, _SS_ATTACH)
    _r, bp, _tp, _seq, bridge = _bridge_indices(d)
    assert len(bridge) == L
    assert all(bp[i] == -1 for i in bridge)  # unpaired ssDNA


def test_ss_bridge_threads_in_chain_between_the_two_parts():
    """The ss bridge is spliced INTO the linker strand's 3' chain between the two
    overhang complements: a real load path prev(part A) → bridge… → next(part B),
    non-coincident beads (FENE/LJ-safe).  Can-go-red if the bridge were an isolated
    fragment (no 3' neighbour) or dropped."""
    L = 6
    d, _bridge = _link("ss", L, _SS_ATTACH)
    r, _bp, tp, _seq, bridge = _bridge_indices(d)
    bset = set(bridge)
    # The bridge forms ONE contiguous 3' chain b0→b1→…→b_{L-1}.
    entry = [i for i in bridge if tp[i] in bset and not any(tp[j] == i for j in bridge)]
    assert len(entry) == 1  # a single 5' end of the tether
    chain = [entry[0]]
    while tp[chain[-1]] in bset:
        chain.append(tp[chain[-1]])
    assert sorted(chain) == bridge  # every bridge bead is on the chain
    # A real (non-bridge) predecessor enters the tether and a real successor exits it.
    prev = [j for j in range(len(tp)) if tp[j] == chain[0]]
    assert len(prev) == 1 and prev[0] not in bset  # part A → tether
    assert tp[chain[-1]] not in bset and tp[chain[-1]] >= 0  # tether → part B
    # No coincident beads along the spliced chain (LJ guard).
    walk = [prev[0], *chain, tp[chain[-1]]]
    seglens = [np.linalg.norm(r[a] - r[b]) for a, b in zip(walk, walk[1:])]
    assert min(seglens) > 0.1


# ── mrDNA-gated (FAST): the bridge survives into the built ARBD SegmentModel ──

_has_mrdna = False
try:
    import sys
    from backend.core.mrdna_bridge import mrdna_tool_path

    sys.path.insert(0, mrdna_tool_path())
    import mrdna  # noqa: F401

    _has_mrdna = True
except Exception:
    pass

skip_no_mrdna = pytest.mark.skipif(not _has_mrdna, reason="mrdna not installed")


def _seg_stats(design):
    """(ss_nt, ds_nt, n_beads, n_segs) of the built mrDNA SegmentModel — mrDNA's
    OWN coarse-grained classification.  Single-stranded segments count nucleotides;
    double-stranded segments count base pairs (their rigid length)."""
    from mrdna import SingleStrandedSegment, DoubleStrandedSegment
    from mrdna.readers.segmentmodel_from_lists import model_from_basepair_stack_3prime

    r, bp, stack, tp, orient, seq, _ = _build_nt_arrays(design, return_nt_key=True)
    m = model_from_basepair_stack_3prime(
        r, bp, stack, tp, sequence=seq, orientation=orient
    )
    ss = sum(s.num_nt for s in m.segments if isinstance(s, SingleStrandedSegment))
    ds = sum(s.num_nt for s in m.segments if isinstance(s, DoubleStrandedSegment))
    beads = sum(len(s.children) for s in m.segments)
    return ss, ds, beads, len(m.segments)


@skip_no_mrdna
@pytest.mark.parametrize("L", [4, 6, 8])
def test_bridge_mechanical_class_ds_duplex_vs_ss_tether_in_the_model(L):
    """THE bright line at the built-model level: the SAME two overhangs, linked once
    by a ds and once by a ss linker, differ by EXACTLY the bridge.  Because both
    linkers hybridize the overhangs identically (attach-independent complement), the
    ds-model-minus-ss-model diff is the bridge alone: the ds bridge contributes
    ``L`` base pairs of DOUBLE-stranded (rigid) content that the ss model instead
    carries as ``L`` nucleotides of SINGLE-stranded (flexible) content.  Proves the
    ds bridge coarse-grains as a rigid duplex and the ss bridge as a flexible
    tether — mrDNA's engine-level agreement with C4's CanDo distinction.  Can-go-red
    if the bridge were dropped (both zero) or mis-typed."""
    ds_ss, ds_ds, *_ = _seg_stats(_link("ds", L, _DS_ATTACH)[0])
    ss_ss, ss_ds, *_ = _seg_stats(_link("ss", L, _SS_ATTACH)[0])
    assert ds_ds - ss_ds == L  # ds bridge = L base pairs of rigid duplex
    assert ss_ss - ds_ss == L  # ss bridge = L nucleotides of flexible ssDNA


@skip_no_mrdna
@pytest.mark.parametrize("linker_type,attach", [("ds", _DS_ATTACH), ("ss", _SS_ATTACH)])
def test_bridge_beads_scale_with_bridge_length(linker_type, attach):
    """The bridge is REAL simulated matter (CG beads), not a bookkeeping count —
    and the growth is attributable to the BRIDGE, not the overhang complement: a
    LONGER bridge on the SAME two overhangs (identical, attach-independent
    complement) coarse-grains to strictly more model beads.  The bead delta is the
    bridge alone, so this can-go-red if the bridge were dropped."""
    short_beads = _seg_stats(_link(linker_type, 4, attach)[0])[2]
    long_beads = _seg_stats(_link(linker_type, 20, attach)[0])[2]
    assert (
        long_beads > short_beads
    )  # the extra bridge length materializes as extra CG beads


@skip_no_mrdna
def test_overhangs_hybridize_into_duplex_in_the_model():
    """The complement half is real too: linking pulls the previously single-stranded
    overhangs into duplex, so the model's ss-nucleotide content drops (net of the
    ss bridge the ss linker re-adds).  Cross-checks that the complement domains
    aren't silently dropped by the coarse-grainer."""
    bare_ss, *_ = _seg_stats(_bare_6hb())
    ds_ss, *_ = _seg_stats(_link("ds", 6, _DS_ATTACH)[0])
    ss_ss, *_ = _seg_stats(_link("ss", 6, _SS_ATTACH)[0])
    # ds: the two overhangs leave ssDNA entirely (bridge is duplex).
    assert bare_ss - ds_ss > 0
    # ss: same overhangs leave ssDNA but the 6-nt tether is re-added → smaller drop.
    assert bare_ss - ds_ss == (bare_ss - ss_ss) + 6


# ── SLOW (opt-in): a real ARBD CG sim runs with the linker + the bridge survives ─


@pytest.mark.slow
@skip_no_mrdna
@pytest.mark.parametrize("linker_type,attach", [("ds", _DS_ATTACH), ("ss", _SS_ATTACH)])
def test_real_arbd_runs_with_linker(tmp_path, linker_type, attach):
    """End-to-end on the real GPU: a linked bundle simulates AND the linker BRIDGE
    survives the coarse run into the reconstructed display frame — the connector the
    integrator actually saw emits ``__lnk__`` positions, absent from the unlinked
    control.  Presence-after-a-real-run (bridge-specific), NOT a dynamic co-movement
    measurement — the FAST mechanical-class pins carry the rigid-vs-flexible
    prediction; a 500-step Brownian co-motion correlation would be too noisy to
    assert here."""
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
            output_name=_SIM_STEM,
            directory=str(out),
            num_steps=500,
            timestep=200e-6,
            gpu=0,
            output_period=250,
        )
        return extract_mrdna_results(design, out)

    d, bridge = _link(linker_type, 6, attach)
    try:
        res_link = _run(d, tmp_path / "link")
        res_bare = _run(_bare_6hb(), tmp_path / "bare")
    except Exception as exc:
        pytest.skip(f"ARBD simulation unavailable: {exc}")

    # The bridge helix's nucleotides are reconstructed in the simulated display frame…
    assert any(p["helix_id"] == bridge for p in res_link["positions"])
    # …and are absent from the unlinked control (bridge-specific, not just "it ran").
    assert not any(str(p["helix_id"]).startswith(_LNK) for p in res_bare["positions"])
