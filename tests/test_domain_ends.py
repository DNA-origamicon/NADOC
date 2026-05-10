"""Tests for domain-end position correctness.

A domain end is a bp index on a (helix, direction) pair with exactly one covered
neighbor (hasPlus XOR hasMinus).  Staple domain ends are suppressed when the open
side (bp + openSide) has scaffold coverage on the same helix.

Invariants verified:
  1. No duplicate (helix_id, disk_bp) — deduplication key.
  2. Every entry's bp lies within [h.bp_start, phys_end_bp].
  3. Every disk position lies on the helix axis (±0.01 nm), extrapolated if needed.
  4. Every result bp satisfies XOR (has exactly one covered neighbor).
  5. No staple result entry has its open side covered by scaffold.
  6. For every overhang domain (overhang_id != null), both lo and hi appear.
  7. Known snapshot counts for specific designs.
"""
from __future__ import annotations

import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import pytest

from scripts.blunt_ends_report import (
    compute_domain_ends,
    phys_end_bp,
    axis_point,
    dist3,
    RISE,
)

# ── Design loading ─────────────────────────────────────────────────────────────

EXAMPLES  = pathlib.Path(__file__).parent.parent / "Examples"
CADNANO   = EXAMPLES / "cadnano"
WORKSPACE = pathlib.Path(__file__).parent.parent / "workspace"


def _load(path: pathlib.Path):
    if not path.exists():
        pytest.skip(f"fixture not present: {path}")
    from backend.core.lattice import autodetect_all_overhangs
    from backend.api.crud     import _recenter_design
    if str(path).endswith('.sc'):
        from backend.core.scadnano import import_scadnano
        d, _ = import_scadnano(json.loads(path.read_text()))
    elif str(path).endswith('.nadoc'):
        from backend.core.models import Design
        d = Design.model_validate_json(path.read_text())
    else:
        from backend.core.cadnano import import_cadnano
        d, _ = import_cadnano(json.loads(path.read_text()))
    d = autodetect_all_overhangs(d)
    d = _recenter_design(d)
    return d


DESIGNS = {
    '6hb':     CADNANO  / 'Honeycomb_6hb_test1.json',
    'hinge':   CADNANO  / 'Ultimate Polymer Hinge 191016.json',
    'voltron': EXAMPLES / 'Voltron_Core_Arm_V6.sc',
    'ohtest2': WORKSPACE / 'OHtest2.nadoc',
}


def _build_cov_maps(design):
    """Return (covMap, scaffoldCovMap) for design.

    covMap:         (helix_id, direction_str) -> set[bp]
    scaffoldCovMap: helix_id -> set[bp]  (scaffold only, all directions merged)
    """
    cov: dict[tuple[str, str], set[int]] = {}
    scaf_cov: dict[str, set[int]] = {}
    for strand in design.strands:
        st = strand.strand_type.value if hasattr(strand.strand_type, 'value') \
             else str(strand.strand_type)
        for d in strand.domains:
            lo = min(d.start_bp, d.end_bp)
            hi = max(d.start_bp, d.end_bp)
            dir_str = d.direction.value if hasattr(d.direction, 'value') \
                      else str(d.direction)
            key = (d.helix_id, dir_str)
            if key not in cov:
                cov[key] = set()
            cov[key].update(range(lo, hi + 1))
            if st == 'scaffold':
                if d.helix_id not in scaf_cov:
                    scaf_cov[d.helix_id] = set()
                scaf_cov[d.helix_id].update(range(lo, hi + 1))
    return cov, scaf_cov


def _build_strand_cov_map(design):
    """Return (strand_id, helix_id, direction_str) -> set[bp]."""
    cov: dict[tuple[str, str, str], set[int]] = {}
    for strand in design.strands:
        for d in strand.domains:
            lo = min(d.start_bp, d.end_bp)
            hi = max(d.start_bp, d.end_bp)
            dir_str = d.direction.value if hasattr(d.direction, 'value') \
                      else str(d.direction)
            key = (strand.id, d.helix_id, dir_str)
            if key not in cov:
                cov[key] = set()
            cov[key].update(range(lo, hi + 1))
    return cov


@pytest.fixture(scope='module', params=list(DESIGNS.keys()))
def design_and_ends(request):
    path   = DESIGNS[request.param]
    design = _load(path)
    ends   = compute_domain_ends(design)
    return design, ends, request.param


# ── Structural invariants (all designs) ───────────────────────────────────────

class TestStructuralInvariants:

    def test_no_duplicate_disk_bp(self, design_and_ends):
        _, ends, name = design_and_ends
        seen: set[tuple[str, int]] = set()
        for e in ends:
            key = (e['helix_id'], e['disk_bp'])
            assert key not in seen, \
                f"{name}: duplicate (helix_id, disk_bp)=({e['helix_id']}, {e['disk_bp']})"
            seen.add(key)

    def test_bp_within_physical_range(self, design_and_ends):
        design, ends, name = design_and_ends
        hmap = {h.id: h for h in design.helices}
        for e in ends:
            h  = hmap[e['helix_id']]
            pe = phys_end_bp(h)
            assert h.bp_start <= e['bp'] <= pe, \
                (f"{name}: domain end at helix {e['label']} bp {e['bp']} "
                 f"outside physical range [{h.bp_start}, {pe}]")

    def test_disk_pos_on_axis(self, design_and_ends):
        """Disk position must match axis_point(h, disk_bp, clamp=False) within 0.01 nm."""
        design, ends, name = design_and_ends
        hmap = {h.id: h for h in design.helices}
        for e in ends:
            h   = hmap[e['helix_id']]
            exp = axis_point(h, e['disk_bp'], clamp=False)
            d   = dist3((e['x'], e['y'], e['z']), exp)
            assert d < 0.01, \
                (f"{name}: disk at helix {e['label']} disk_bp {e['disk_bp']} "
                 f"has pos ({e['x']:.3f},{e['y']:.3f},{e['z']:.3f}) "
                 f"but axis gives ({exp[0]:.3f},{exp[1]:.3f},{exp[2]:.3f}), dist={d:.4f}")

    def test_end_pos_on_axis(self, design_and_ends):
        """end_x/y/z must match axis_point(h, bp, clamp=True) within 0.01 nm."""
        design, ends, name = design_and_ends
        hmap = {h.id: h for h in design.helices}
        for e in ends:
            h   = hmap[e['helix_id']]
            exp = axis_point(h, e['bp'], clamp=True)
            d   = dist3((e['end_x'], e['end_y'], e['end_z']), exp)
            assert d < 0.01, \
                (f"{name}: end_pos at helix {e['label']} bp {e['bp']} "
                 f"has pos ({e['end_x']:.3f},{e['end_y']:.3f},{e['end_z']:.3f}) "
                 f"but axis gives ({exp[0]:.3f},{exp[1]:.3f},{exp[2]:.3f}), dist={d:.4f}")

    def test_open_side_is_pm1(self, design_and_ends):
        _, ends, name = design_and_ends
        for e in ends:
            assert e['open_side'] in (1, -1), \
                f"{name}: open_side={e['open_side']!r} not ±1 at helix {e['label']}"

    def test_disk_bp_equals_bp_plus_open_side(self, design_and_ends):
        _, ends, name = design_and_ends
        for e in ends:
            assert e['disk_bp'] == e['bp'] + e['open_side'], \
                (f"{name}: disk_bp={e['disk_bp']} != bp+open_side="
                 f"{e['bp']}+{e['open_side']}={e['bp']+e['open_side']}")

    def test_strand_type_values(self, design_and_ends):
        _, ends, name = design_and_ends
        for e in ends:
            assert e['strand_type'] in ('scaffold', 'staple'), \
                f"{name}: unknown strand_type {e['strand_type']!r}"


# ── Detection invariants ───────────────────────────────────────────────────────

class TestDomainEndDetection:

    def test_unrelated_adjacent_strand_does_not_hide_overhang_end(self):
        """A dense imported row may place another staple at bp+1 of an overhang.

        Domain-end continuity is strand-local, so that unrelated neighbor must
        not make the overhang terminus look like an internal nick.
        """
        from backend.core.models import (
            Design, Direction, Domain, Helix, OverhangSpec, Strand, StrandType, Vec3,
        )

        h = Helix(
            id='h0',
            axis_start=Vec3(x=0, y=0, z=0),
            axis_end=Vec3(x=0, y=0, z=19 * RISE),
            length_bp=20,
            label='0',
        )
        design = Design(
            helices=[h],
            strands=[
                Strand(
                    id='overhang_strand',
                    strand_type=StrandType.STAPLE,
                    domains=[Domain(
                        helix_id='h0',
                        start_bp=0,
                        end_bp=4,
                        direction=Direction.FORWARD,
                        overhang_id='ovhg0',
                    )],
                ),
                Strand(
                    id='unrelated_neighbor',
                    strand_type=StrandType.STAPLE,
                    domains=[Domain(
                        helix_id='h0',
                        start_bp=5,
                        end_bp=9,
                        direction=Direction.FORWARD,
                    )],
                ),
            ],
            overhangs=[OverhangSpec(id='ovhg0', helix_id='h0', strand_id='overhang_strand')],
        )

        ends = compute_domain_ends(design)
        overhang_bps = {e['bp'] for e in ends if e['overhang_id'] == 'ovhg0'}
        assert overhang_bps == {0, 4}

    def test_result_bp_satisfies_xor(self, design_and_ends):
        """Every result entry's bp must satisfy XOR on at least one (helix, direction) pair.

        We look for a domain where bp is exactly the lo or hi endpoint, which is the
        only domain that could have generated this entry via the detection algorithm.
        """
        design, ends, name = design_and_ends
        cov, _ = _build_cov_maps(design)
        strand_cov = _build_strand_cov_map(design)
        for e in ends:
            satisfied = False
            for strand in design.strands:
                for d in strand.domains:
                    if d.helix_id != e['helix_id']:
                        continue
                    lo = min(d.start_bp, d.end_bp)
                    hi = max(d.start_bp, d.end_bp)
                    if e['bp'] not in (lo, hi):
                        continue  # only check domains where bp is an endpoint
                    dir_str  = d.direction.value if hasattr(d.direction, 'value') \
                               else str(d.direction)
                    cov_set = (
                        strand_cov.get((strand.id, e['helix_id'], dir_str), set())
                        if getattr(d, 'overhang_id', None)
                        else cov.get((e['helix_id'], dir_str), set())
                    )
                    has_plus  = (e['bp'] + 1) in cov_set
                    has_minus = (e['bp'] - 1) in cov_set
                    if has_plus != has_minus:
                        satisfied = True
                        break
                if satisfied:
                    break
            assert satisfied, \
                (f"{name}: result entry at helix {e['label']} bp {e['bp']} "
                 f"has no domain endpoint satisfying XOR")

    def test_no_staple_nick_in_results(self, design_and_ends):
        """No staple entry should have both bp±1 covered on its helix+direction."""
        design, ends, name = design_and_ends
        cov, _ = _build_cov_maps(design)
        strand_cov = _build_strand_cov_map(design)
        for e in ends:
            if e['strand_type'] != 'staple':
                continue
            for strand in design.strands:
                for d in strand.domains:
                    if d.helix_id != e['helix_id']:
                        continue
                    lo = min(d.start_bp, d.end_bp)
                    hi = max(d.start_bp, d.end_bp)
                    if not (lo <= e['bp'] <= hi):
                        continue
                    dir_str  = d.direction.value if hasattr(d.direction, 'value') \
                               else str(d.direction)
                    cov_set = (
                        strand_cov.get((strand.id, e['helix_id'], dir_str), set())
                        if getattr(d, 'overhang_id', None)
                        else cov.get((e['helix_id'], dir_str), set())
                    )
                    has_plus  = (e['bp'] + 1) in cov_set
                    has_minus = (e['bp'] - 1) in cov_set
                    assert has_plus != has_minus, \
                        (f"{name}: nick (both sides covered) in results at "
                         f"helix {e['label']} bp {e['bp']}")


# ── Scaffold-suppression invariants ───────────────────────────────────────────

class TestScaffoldSuppression:

    def test_no_staple_end_has_scaffold_on_open_side(self, design_and_ends):
        """Staple domain ends must be absent when open side has scaffold coverage."""
        design, ends, name = design_and_ends
        _, scaf_cov = _build_cov_maps(design)
        for e in ends:
            if e['strand_type'] != 'staple':
                continue
            assert e['disk_bp'] not in scaf_cov.get(e['helix_id'], set()), \
                (f"{name}: staple domain end at helix {e['label']} bp {e['bp']} "
                 f"(disk_bp={e['disk_bp']}) not suppressed — scaffold present on open side")

    def test_scaffold_suppressed_staples_absent(self, design_and_ends):
        """Build the full expected-suppressed set and confirm none appear."""
        design, ends, name = design_and_ends
        cov, scaf_cov = _build_cov_maps(design)
        result_keys = {(e['helix_id'], e['disk_bp']) for e in ends}

        for strand in design.strands:
            st = strand.strand_type.value if hasattr(strand.strand_type, 'value') \
                 else str(strand.strand_type)
            if st != 'staple':
                continue
            for d in strand.domains:
                lo = min(d.start_bp, d.end_bp)
                hi = max(d.start_bp, d.end_bp)
                dir_str = d.direction.value if hasattr(d.direction, 'value') \
                          else str(d.direction)
                cov_set = cov.get((d.helix_id, dir_str), set())
                for bp in (lo, hi):
                    has_plus  = (bp + 1) in cov_set
                    has_minus = (bp - 1) in cov_set
                    if has_plus == has_minus:
                        continue
                    open_side = 1 if not has_plus else -1
                    disk_bp   = bp + open_side
                    if disk_bp in scaf_cov.get(d.helix_id, set()):
                        assert (d.helix_id, disk_bp) not in result_keys, \
                            (f"{name}: scaffold-suppressed staple end at "
                             f"helix {d.helix_id} disk_bp {disk_bp} appears in results")


# ── Overhang domain ends regression (OHtest2) ─────────────────────────────────

class TestOverhangDomainEnds:

    def test_both_endpoints_per_overhang_domain(self):
        """Every overhang domain contributes BOTH its lo and hi bp to the results.

        Regression: the old algorithm missed the lo end of the first overhang domain
        on h_XY_1_0 in OHtest2 (bp=0 was absent; only bp=9, 32, 42 were emitted).
        """
        design = _load(DESIGNS['ohtest2'])
        ends   = compute_domain_ends(design)
        result_bps: dict[str, set[int]] = {}
        for e in ends:
            if e['helix_id'] not in result_bps:
                result_bps[e['helix_id']] = set()
            result_bps[e['helix_id']].add(e['bp'])

        for strand in design.strands:
            for d in strand.domains:
                if not getattr(d, 'overhang_id', None):
                    continue
                lo = min(d.start_bp, d.end_bp)
                hi = max(d.start_bp, d.end_bp)
                present = result_bps.get(d.helix_id, set())
                assert lo in present, \
                    (f"OHtest2: overhang domain {d.overhang_id} on helix {d.helix_id} "
                     f"missing lo bp={lo}")
                assert hi in present, \
                    (f"OHtest2: overhang domain {d.overhang_id} on helix {d.helix_id} "
                     f"missing hi bp={hi}")

    def test_ohtest2_stub_helix_has_four_ends(self):
        """h_XY_1_0 carries two overhang domains (bp 0-9 and bp 32-41) → 4 domain ends."""
        design = _load(DESIGNS['ohtest2'])
        ends   = compute_domain_ends(design)
        stub   = [e for e in ends if e['helix_id'] == 'h_XY_1_0']
        bps    = sorted(e['bp'] for e in stub)
        assert bps == [0, 9, 32, 41], \
            f"OHtest2 h_XY_1_0: expected bp=[0, 9, 32, 41], got {bps}"

    def test_overhang_ends_have_correct_overhang_ids(self):
        """Each overhang domain's lo/hi should carry the overhang_id from that domain."""
        design = _load(DESIGNS['ohtest2'])
        ends   = compute_domain_ends(design)
        # h_XY_1_0: bp 0 and 9 → ovhg_h_XY_1_1_0_3p;  bp 32 and 41 → ovhg_h_XY_1_1_41_5p
        end_map = {e['bp']: e for e in ends if e['helix_id'] == 'h_XY_1_0'}
        assert end_map[0]['overhang_id']  == 'ovhg_h_XY_1_1_0_3p'
        assert end_map[9]['overhang_id']  == 'ovhg_h_XY_1_1_0_3p'
        assert end_map[32]['overhang_id'] == 'ovhg_h_XY_1_1_41_5p'
        assert end_map[41]['overhang_id'] == 'ovhg_h_XY_1_1_41_5p'

    def test_all_overhang_domains_general(self, design_and_ends):
        """For every overhang domain in any design, both lo and hi bp appear."""
        design, ends, name = design_and_ends
        _, scaf_cov = _build_cov_maps(design)
        result_bps: dict[str, set[int]] = {}
        for e in ends:
            if e['helix_id'] not in result_bps:
                result_bps[e['helix_id']] = set()
            result_bps[e['helix_id']].add(e['bp'])

        cov, _ = _build_cov_maps(design)
        strand_cov = _build_strand_cov_map(design)
        for strand in design.strands:
            for d in strand.domains:
                if not getattr(d, 'overhang_id', None):
                    continue
                lo = min(d.start_bp, d.end_bp)
                hi = max(d.start_bp, d.end_bp)
                dir_str = d.direction.value if hasattr(d.direction, 'value') \
                          else str(d.direction)
                cov_set = strand_cov.get((strand.id, d.helix_id, dir_str), set())
                present = result_bps.get(d.helix_id, set())
                for bp in (lo, hi):
                    has_plus  = (bp + 1) in cov_set
                    has_minus = (bp - 1) in cov_set
                    if has_plus == has_minus:
                        continue  # nick or isolated — no domain end expected
                    open_side = 1 if not has_plus else -1
                    disk_bp   = bp + open_side
                    if disk_bp in scaf_cov.get(d.helix_id, set()):
                        continue  # scaffold-suppressed
                    assert bp in present, \
                        (f"{name}: overhang domain {d.overhang_id} on helix {d.helix_id} "
                         f"bp={bp} missing from results")


# ── Snapshot counts for specific designs ──────────────────────────────────────

class TestSnapshotCounts:

    def _counts(self, design):
        ends = compute_domain_ends(design)
        return dict(
            total        = len(ends),
            scaffold     = sum(1 for e in ends if e['strand_type'] == 'scaffold'),
            staple       = sum(1 for e in ends if e['strand_type'] == 'staple'),
            with_overhang = sum(1 for e in ends if e['overhang_id']),
        )

    def test_6hb(self):
        """6-helix honeycomb: 12 scaffold ends (6 helices × 2), no staples."""
        d = _load(DESIGNS['6hb'])
        c = self._counts(d)
        assert c == dict(total=12, scaffold=12, staple=0, with_overhang=0), \
            f"6HB counts wrong: {c}"

    def test_hinge(self):
        """Polymer hinge: 324 total domain ends."""
        d = _load(DESIGNS['hinge'])
        c = self._counts(d)
        assert c['total']         == 324, f"hinge total={c['total']}, expected 324"
        assert c['scaffold']      == 252, f"hinge scaffold={c['scaffold']}, expected 252"
        assert c['staple']        == 72,  f"hinge staple={c['staple']}, expected 72"
        assert c['with_overhang'] == 72,  f"hinge with_overhang={c['with_overhang']}, expected 72"

    def test_voltron(self):
        """Voltron (multi-scaffold scadnano): 196 total domain ends."""
        d = _load(DESIGNS['voltron'])
        c = self._counts(d)
        assert c['total']         == 196, f"voltron total={c['total']}, expected 196"
        assert c['scaffold']      == 118, f"voltron scaffold={c['scaffold']}, expected 118"
        assert c['staple']        == 78,  f"voltron staple={c['staple']}, expected 78"
        assert c['with_overhang'] == 72,  f"voltron with_overhang={c['with_overhang']}, expected 72"

    def test_ohtest2(self):
        """OHtest2: 8 total, 3 scaffold, 5 staple, 4 with overhang."""
        d = _load(DESIGNS['ohtest2'])
        c = self._counts(d)
        assert c == dict(total=8, scaffold=3, staple=5, with_overhang=4), \
            f"OHtest2 counts wrong: {c}"
