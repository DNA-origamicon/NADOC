"""The Aksimentiev §3.4 equilibration criteria that NADOC was missing.

The chapter names four ways to tell an origami run has equilibrated.  Only the box trace
was implemented.  These pin the two that go in md_health (which is staged VERBATIM to
compute nodes, so they may use nothing beyond numpy/scipy/MDAnalysis):

* broken base pairs by the TUTORIAL's definition — purine-N1 / pyrimidine-N3 contacts
  within 3.0 Å, counted GEOMETRICALLY per frame and subtracted from the idealised count.
  NADOC's own measure (heavy-atom donor/acceptor within 3.6 Å, plus a reference-relative
  band) stays the gate; this one is the number comparable to a published figure.
* the net charge within 2 nm of the DNA — their ion-atmosphere convergence check, and
  the direct instrument for whether the Mg(H2O)6 cloud has formed at all.

See backend/core/md_health.py and Literature/Aksimentiev_Tutorial.pdf §3.4.
"""

from __future__ import annotations

import numpy as np

from backend.core.md_health import (
    BROKEN_BP_DIST_ANG,
    CHARGE_SHELL_NM,
    charge_within_shell,
    count_broken_base_pairs,
    count_intact_base_pairs,
)


# ── Broken base pairs, the tutorial's definition ──────────────────────────────
# countBrokenBps.tcl counts intact purine-N1 / pyrimidine-N3 contacts GEOMETRICALLY and
# subtracts from the idealised count.  It does not consult a partner list — and it must
# not: build_wc_pairs assigns partners greedily by shortest C1'...C1', which prefers
# cross-strand neighbours (8.7-9.6 A) over true partners (~10.4 A).  Measured on a real
# idealised 2hb build, that made this criterion report 34 of 39 pairs broken on a
# structure whose nearest correct partners were all 2.5-3.5 A apart.

def _pair_positions(distances):
    """Donors on a line, each with one acceptor at the given separation."""
    don, acc = [], []
    for k, d in enumerate(distances):
        don.append([0.0, 20.0 * k, 0.0])
        acc.append([d, 20.0 * k, 0.0])
    return (np.asarray(don + acc, dtype=float),
            np.arange(len(distances)),
            np.arange(len(distances)) + len(distances))


def test_intact_pairs_are_counted_within_three_angstrom():
    pos, don, acc = _pair_positions([2.8, 2.9, 3.5, 6.0])
    assert count_intact_base_pairs(pos, don, acc) == 2       # 2.8 and 2.9 only
    assert BROKEN_BP_DIST_ANG == 3.0


def test_broken_is_the_shortfall_against_the_reference():
    pos, don, acc = _pair_positions([2.8, 2.9, 6.0])
    assert count_broken_base_pairs(pos, don, acc, n_expected=3) == 1
    assert count_broken_base_pairs(pos, don, acc, n_expected=2) == 0


def test_broken_never_goes_negative():
    """A frame can show MORE contacts than the reference; that is not -1 broken."""
    pos, don, acc = _pair_positions([2.8, 2.8, 2.8])
    assert count_broken_base_pairs(pos, don, acc, n_expected=1) == 0


def test_a_donor_between_two_acceptors_is_counted_once():
    """One-to-one matching: without it a frayed region inflates the intact count."""
    pos = np.array([[0.0, 0, 0], [2.6, 0, 0], [-2.7, 0, 0]])
    assert count_intact_base_pairs(pos, np.array([0]), np.array([1, 2])) == 1


def test_no_atoms_means_nothing_intact():
    pos = np.zeros((2, 3))
    assert count_intact_base_pairs(pos, np.empty(0, int), np.array([1])) == 0
    assert count_intact_base_pairs(pos, np.array([0]), np.empty(0, int)) == 0


def test_minimum_image_is_applied():
    """A pair straddling the cell boundary is intact, not 9 A apart."""
    box = np.array([10.0, 10.0, 10.0])
    pos = np.array([[0.2, 0, 0], [9.9, 0, 0]])          # 0.3 A across the boundary
    don, acc = np.array([0]), np.array([1])
    assert count_intact_base_pairs(pos, don, acc, box=box) == 1
    assert count_intact_base_pairs(pos, don, acc) == 0   # without the box, not a contact


# ── Charge within 2 nm of the DNA ─────────────────────────────────────────────

def test_shell_radius_is_two_nanometres():
    assert CHARGE_SHELL_NM == 2.0


def test_only_ions_inside_the_shell_count():
    # DNA at the origin carrying -2 e; one +2 counterion at 5 Å (inside 20 Å) and one
    # at 50 Å (outside).
    pos = np.array([[0.0, 0, 0], [0.0, 0, 0], [5.0, 0, 0], [50.0, 0, 0]])
    charges = np.array([-1.0, -1.0, 2.0, 2.0])
    q, n = charge_within_shell(pos, charges, np.array([0, 1]), np.array([2, 3]))
    assert n == 1
    assert q == 0.0          # -2 from the DNA + 2 from the one ion inside


def test_a_bare_origami_reads_its_own_negative_charge():
    """Before any counterion condenses, the shell charge IS the backbone charge — which
    is what makes the trace a convergence signal rather than a constant."""
    pos = np.array([[0.0, 0, 0], [500.0, 0, 0]])
    charges = np.array([-10.0, 2.0])
    q, n = charge_within_shell(pos, charges, np.array([0]), np.array([1]))
    assert n == 0
    assert q == -10.0


def test_no_ions_or_no_dna_is_zero_not_a_crash():
    pos = np.zeros((2, 3))
    charges = np.array([-1.0, 1.0])
    assert charge_within_shell(pos, charges, np.array([0]), np.empty(0, int)) == (0.0, 0)
    assert charge_within_shell(pos, charges, np.empty(0, int), np.array([1])) == (0.0, 0)


def test_periodic_wrap_is_applied_before_the_periodic_tree():
    """With wrapAll off (what the relax ladder runs) coordinates are NOT inside [0, L),
    which is what cKDTree's boxsize mode requires — so they must be wrapped first or the
    query raises."""
    box = np.array([100.0, 100.0, 100.0])
    pos = np.array([[-5.0, 0, 0], [104.0, 0, 0]])    # both outside [0, L)
    charges = np.array([-1.0, 1.0])
    q, n = charge_within_shell(pos, charges, np.array([0]), np.array([1]), box=box)
    assert n == 1            # 9 Å apart across the boundary — well inside 20 Å
    assert q == 0.0
