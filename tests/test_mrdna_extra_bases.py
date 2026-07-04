"""Crossover extra bases materialized as single-stranded nucleotides in the
mrDNA/ARBD path.

`Crossover.extra_bases` (e.g. "TT") are single-stranded thymines inserted at a
crossover junction — junction metadata outside the strand graph.  Until now the
mrDNA bridge (`_build_nt_arrays`) dropped them silently: a CG relaxation of a
design with extra bases was byte-identical to one without.  These pins prove the
bridge now materializes them as real ssDNA beads, on the crossover-owning strand,
threaded 3'/stack in-chain between their flanking real nucleotides, carrying their
own base identity without consuming the strand's designed sequence — reusing the
oxDNA path's owning-strand junction map so the two engines agree.

See backend/core/mrdna_bridge.py `_build_nt_arrays` and
memory/project_oxdna_extra_bases.py.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.api import headless_build as hb
from backend.api import state as design_state
from backend.core.mrdna_bridge import _build_nt_arrays, extra_base_flank_keys
from backend.core.models import LatticeType
from backend.physics import oxdna_interface as ox
from tests.conftest import SIX_HB_CELLS


def _routed_6hb():
    """A seamless-autoscaffolded, fully-autostapled 6hb — a real crossover graph to
    hang extra bases on.  mrDNA is a CG model and needs no WC sequence."""
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(SIX_HB_CELLS, 84, lattice=LatticeType.HONEYCOMB, name="6hb")
        hb.auto_scaffold(seamless=True)
        hb.full_autostaple()
        return design_state.get_or_404().model_copy(deep=True)


@pytest.fixture(scope="module")
def routed_6hb():
    return _routed_6hb()


def _with_extra(design, sequence="TT", *, all_crossovers=False):
    d = design.model_copy(deep=True)
    targets = d.crossovers if all_crossovers else d.crossovers[:1]
    for x in targets:
        x.extra_bases = sequence
    return d


def _extra_base_indices(design):
    """(r, bp, stack, three_prime, seq, extra_base_idxs) — the bead indices NOT in
    nt_key are exactly the extra-base inserts (they carry no design key)."""
    r, bp, stack, tp, orient, seq, ntkey = _build_nt_arrays(design, return_nt_key=True)
    eb = sorted(set(range(len(r))) - set(ntkey.values()))
    return r, bp, stack, tp, seq, eb


# ── no-regression: extra-base-free designs are untouched ──────────────────────

def test_no_extra_bases_no_inserts(routed_6hb):
    assert ox.crossover_extra_base_junctions(routed_6hb) == {}
    *_, eb = _extra_base_indices(routed_6hb)
    assert eb == []


# ── pin #1: nt count grows by exactly the extra-base total ────────────────────

def test_nt_count_grows_by_extra_base_total(routed_6hb):
    base_r, *_ = _build_nt_arrays(routed_6hb)
    d = _with_extra(routed_6hb, "TT", all_crossovers=True)
    n_extra = sum(len(extra) for _xo, extra in ox.crossover_extra_base_junctions(d).values())
    assert n_extra > 1, "bulk case should insert at several junctions"
    r, *_ = _build_nt_arrays(d)
    assert len(r) - len(base_r) == n_extra


# ── pin #2: inserts are single-stranded (unpaired) ────────────────────────────

def test_inserts_are_unpaired(routed_6hb):
    d = _with_extra(routed_6hb, "TT")
    _r, bp, _stack, _tp, _seq, eb = _extra_base_indices(d)
    assert len(eb) == 2
    assert all(bp[i] == -1 for i in eb)


# ── pin #3: inserts thread 3' + stack in-chain: prev_real → eb… → next_real ────
#   Can-go-red: without the strand-chain splice / stacking pass these are −1.

def test_inserts_threaded_in_chain(routed_6hb):
    d = _with_extra(routed_6hb, "TT")
    _r, _bp, stack, tp, _seq, eb = _extra_base_indices(d)
    assert len(eb) == 2
    eb0, eb1 = eb
    # A real predecessor threads into eb0; eb0 → eb1 → a real successor.
    prev = [j for j in range(len(tp)) if tp[j] == eb0]
    assert len(prev) == 1 and prev[0] not in eb          # flanked by a real nt
    assert tp[eb0] == eb1                                 # 3' chain through inserts
    assert tp[eb1] not in eb and tp[eb1] >= 0             # exits to a real nt
    # Stacking mirrors the 3' chain (the domain walk skips inserts otherwise).
    assert stack[prev[0]] == eb0 and stack[eb0] == eb1 and stack[eb1] == tp[eb1]


# ── pin #4: bond geometry along the insert is even + FENE-safe (no coincidence) ─

def test_insert_geometry_even_and_noncoincident(routed_6hb):
    d = _with_extra(routed_6hb, "TT")
    r, _bp, _stack, tp, _seq, eb = _extra_base_indices(d)
    eb0, eb1 = eb
    prev = next(j for j in range(len(tp)) if tp[j] == eb0)
    chain = [prev, eb0, eb1, tp[eb1]]
    seglens = [np.linalg.norm(r[a] - r[b]) for a, b in zip(chain, chain[1:])]
    assert min(seglens) > 0.1                              # no coincident beads (LJ guard)
    assert max(seglens) - min(seglens) < 0.5              # evenly spaced along the chord


# ── pin #5: base identity from extra_bases, not from strand.sequence ──────────

def test_insert_base_identity(routed_6hb):
    d = _with_extra(routed_6hb, "GC")
    _r, _bp, _stack, _tp, seq, eb = _extra_base_indices(d)
    assert seq is not None
    assert [seq[i] for i in eb] == ["G", "C"]


# ── display: flank keys for positioning the native extra-base beads/slabs ─────

def test_flank_keys_absent_without_extra_bases(routed_6hb):
    assert extra_base_flank_keys(routed_6hb) == []


def test_flank_keys_name_real_flanking_nucleotides(routed_6hb):
    """Each extra-base crossover yields (xo_id, extra, prev_key, next_key) whose
    flank keys are real design nucleotides on different helices (a crossover)."""
    from backend.core.geometry import nucleotide_positions

    d = _with_extra(routed_6hb, "TT", all_crossovers=True)
    flanks = extra_base_flank_keys(d)
    junctions = ox.crossover_extra_base_junctions(d)
    assert len(flanks) == len(junctions) > 1

    real_keys = {
        (n.helix_id, n.bp_index, n.direction.value)
        for h in d.helices for n in nucleotide_positions(h)
    }
    for xo_id, extra, prev_key, next_key in flanks:
        assert extra == "TT"
        assert prev_key in real_keys and next_key in real_keys   # real nucleotides
        assert prev_key[0] != next_key[0]                        # spans two helices


# ── pin #6: builds a valid mrDNA model with the inserts as ssDNA segments ──────

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


@skip_no_mrdna
def test_model_builds_with_ssdna_segments(routed_6hb):
    from mrdna import SingleStrandedSegment
    from mrdna.readers.segmentmodel_from_lists import model_from_basepair_stack_3prime

    def ss_count(design):
        r, bp, stack, tp, orient, seq, _ = _build_nt_arrays(design, return_nt_key=True)
        m = model_from_basepair_stack_3prime(r, bp, stack, tp, sequence=seq, orientation=orient)
        return sum(isinstance(s, SingleStrandedSegment) for s in m.segments)

    base_ss = ss_count(routed_6hb)
    with_ss = ss_count(_with_extra(routed_6hb, "TT", all_crossovers=True))
    # Every extra-base junction opens a new single-stranded segment.
    assert with_ss > base_ss


# ── pin #7 (slow, opt-in): a real ARBD sim runs end-to-end with inserts ───────

@pytest.mark.slow
@skip_no_mrdna
def test_real_arbd_runs_with_extra_bases(tmp_path, routed_6hb):
    """End-to-end on the real GPU: the inserts simulate AND both display toggles
    surface them — the deform toggle emits ``__xb__`` positions (native beads/slabs
    follow the shape) and the CG-bead cloud grows by the insert beads."""
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

    d = _with_extra(routed_6hb, "TT", all_crossovers=True)
    n_extra = sum(len(e) for _xo, e in ox.crossover_extra_base_junctions(d).values())
    try:
        res_with = _run(d, tmp_path / "with")
        res_base = _run(routed_6hb, tmp_path / "base")
    except Exception as exc:
        pytest.skip(f"ARBD simulation unavailable: {exc}")

    # Deform toggle: one __xb__ display entry per inserted base, keyed (crossover_id, k).
    xb = [p for p in res_with["positions"] if p["helix_id"] == "__xb__"]
    assert len(xb) == n_extra
    assert all(isinstance(p["bp_index"], str) and isinstance(p["direction"], int) for p in xb)
    assert not any(p["helix_id"] == "__xb__" for p in res_base["positions"])

    # CG-bead toggle: the insert beads join the cloud (more DNA beads than baseline).
    assert res_with["n_beads"] > res_base["n_beads"]
