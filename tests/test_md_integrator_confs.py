"""The emitted confs honour the three axes independently.

Before exp51 these were one dial: ``_segment_conf`` derived rigidBonds from ``spec.soft``
and the PSF from ``fast``; ``build_production_conf`` branched on the timestep alone. These
tests pin the decoupling, including the combinations the old writers could not express.
"""

import re

import pytest

from backend.core.md_protocols import SegmentSpec, _segment_conf, build_production_conf

BOX = (60.0, 60.0, 120.0)
STEM = "demo"


def directive(conf: str, name: str):
    """The value NAMD would read for `name`, or None when it is absent."""
    m = re.search(rf"^{name}\s+(\S+)\s*$", conf, re.IGNORECASE | re.MULTILINE)
    return m.group(1) if m else None


def spec(**kw) -> SegmentSpec:
    base = dict(
        name=f"{STEM}_01_k0p5",
        stage="k=0.5",
        percent=100.0,
        steps=1000,
        temp=300.0,
        damping=5.0,
        scale=0.5,
        npt=True,
        previous=f"{STEM}_00_min",
    )
    base.update(kw)
    return SegmentSpec(**base)


class TestProductionConf:
    def _conf(self, **kw):
        return build_production_conf(spec(scale=None), STEM, BOX, False, **kw)

    @pytest.mark.parametrize(
        "dt,rigid,hmr_psf",
        [
            (4.0, "all", True),  # the sanctioned fast path
            (2.0, "all", False),  # the paper's path
            (1.0, "none", False),  # the conservative reference
        ],
    )
    def test_auto_reproduces_the_sanctioned_diagonals(self, dt, rigid, hmr_psf):
        c = self._conf(timestep_fs=dt)
        assert directive(c, "timestep") == f"{dt:g}"
        assert directive(c, "rigidBonds") == rigid
        assert directive(c, "structure").endswith("_hmr.psf") is hmr_psf

    def test_4fs_can_be_run_without_hmr(self):
        # exp51 measured this failing RATTLE at 16.8 ps. It must still be EMITTABLE —
        # the audit was only possible because the unsanctioned cells could be run.
        c = self._conf(timestep_fs=4.0, hmr=False)
        assert directive(c, "timestep") == "4"
        assert directive(c, "rigidBonds") == "all"
        assert directive(c, "structure") == f"{STEM}.psf"

    def test_1fs_can_be_run_with_rigid_bonds(self):
        # Stable per exp51; the old writer forced rigidBonds none at 1 fs unconditionally.
        assert (
            directive(self._conf(timestep_fs=1.0, rigid_bonds="all"), "rigidBonds")
            == "all"
        )

    def test_2fs_can_be_run_with_hmr(self):
        c = self._conf(timestep_fs=2.0, hmr=True)
        assert directive(c, "timestep") == "2"
        assert directive(c, "structure") == f"{STEM}_hmr.psf"

    def test_4fs_without_an_explicit_psf_names_the_hmr_copy(self):
        # The hole the audit found: this used to fall back to the PLAIN psf, emitting a
        # 4 fs conf against unrepartitioned masses with no error and no warning.
        assert directive(self._conf(timestep_fs=4.0), "structure") == f"{STEM}_hmr.psf"

    def test_an_explicit_psf_still_wins_when_hmr_is_on(self):
        c = self._conf(timestep_fs=4.0, structure_psf="seeded_hmr.psf")
        assert directive(c, "structure") == "seeded_hmr.psf"


class TestSegmentConf:
    def _conf(self, s=None, **kw):
        return _segment_conf(s or spec(), STEM, BOX, False, **kw)

    def test_soft_tier_still_means_1fs_flexible_by_default(self):
        c = self._conf(spec(soft=True, timestep_fs=1.0))
        assert directive(c, "rigidBonds") == "none"
        assert directive(c, "timestep") == "1"

    def test_a_soft_segment_can_be_given_rigid_bonds_explicitly(self):
        c = self._conf(spec(soft=True, timestep_fs=1.0), rigid_bonds="all")
        assert directive(c, "rigidBonds") == "all"

    def test_hmr_off_keeps_the_plain_psf_even_on_a_fast_segment(self):
        c = self._conf(fast=True, structure_psf=f"{STEM}_hmr.psf", hmr=False)
        assert directive(c, "structure") == f"{STEM}.psf"

    def test_hmr_on_uses_the_repartitioned_psf(self):
        c = self._conf(fast=True, structure_psf=f"{STEM}_hmr.psf", hmr=True)
        assert directive(c, "structure") == f"{STEM}_hmr.psf"

    def test_implicit_solvent_never_gets_the_hmr_psf(self):
        # GBIS has no repartitioned copy to point at, whatever was asked for.
        c = self._conf(fast=True, structure_psf=f"{STEM}_hmr.psf", hmr=True, gbis=True)
        assert directive(c, "structure") == f"{STEM}.psf"


class TestForceSoftIsExpressible:
    """`force_soft` had a UI toggle; the three axes now express it exactly.

    That toggle was removed from the wizard on the claim that "1 fs + rigid bonds off"
    IS the soft ladder. This pins the claim: if the emitted directives ever diverge, the
    control was doing something the axes cannot say, and it needs to come back.
    """

    def _ladder(self, **kw):
        from backend.core.md_protocols import mgh_slow_release_segments

        return mgh_slow_release_segments(STEM, **kw)

    def test_the_soft_tier_and_the_explicit_axes_emit_the_same_integrator(self):
        _min, soft_specs = self._ladder(soft=True)
        _min2, axis_specs = self._ladder(timestep_fs=1.0)
        assert len(soft_specs) == len(axis_specs)
        for a, b in zip(soft_specs, axis_specs):
            soft_conf = _segment_conf(a, STEM, BOX, False, fast=False)
            axis_conf = _segment_conf(
                b,
                STEM,
                BOX,
                False,
                fast=False,
                rigid_bonds="none",
                base_timestep_fs=1.0,
            )
            for key in ("timestep", "rigidBonds", "structure"):
                assert directive(soft_conf, key) == directive(axis_conf, key), (
                    a.name,
                    key,
                )

    def test_and_that_integrator_really_is_1fs_flexible(self):
        _min, specs = self._ladder(timestep_fs=1.0)
        conf = _segment_conf(
            specs[-1],
            STEM,
            BOX,
            False,
            fast=False,
            rigid_bonds="none",
            base_timestep_fs=1.0,
        )
        assert directive(conf, "timestep") == "1"
        assert directive(conf, "rigidBonds") == "none"

    def test_the_step_counts_match_too_so_the_run_is_the_same_length(self):
        # Same simulated time, not just the same directives — a ladder that emits 1 fs
        # but keeps 4 fs step counts would run a quarter of the intended nanoseconds.
        _min, soft_specs = self._ladder(soft=True)
        _min2, axis_specs = self._ladder(timestep_fs=1.0)
        assert [s.steps for s in soft_specs] == [s.steps for s in axis_specs]
