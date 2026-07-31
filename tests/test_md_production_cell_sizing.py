"""A production run's cell must be big enough for a solute that actually tumbles.

Fast, pure tests — no NAMD, no GROMACS.  They pin the three links in the chain that
let a 1 us production run start in a cell sized for a 4.8 ns restrained ladder:

  1. ``production_ns_intent`` reaching the box sizer, so a package CAN be built
     rotation-sized (nothing after prep re-solvates, so this is the only chance);
  2. the production child manifest inheriting the parent's ``solvation`` block, so
     the rotation verdict survives the one hop from parent to child; and
  3. ``_assert_cell_fits_a_free_run`` refusing a long free run in a cell that fails
     ``box_check.fits_rotated`` — including on the child-spawn route, which is the
     one the panel's Start Production button actually calls.

Background (2hb_1xT, 2026-07-30): prep measured ``fits_rotated=False`` /
``image_gap_rotated_ang=-33.0`` and recorded it on the parent, the child manifest
dropped the whole ``solvation`` block, and the guard's ``fits_rotated=True`` default
then waved every child through.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.api.routes_md import _assert_cell_fits_a_free_run
from backend.core.md_protocols import _LADDER_FREE_NS
from backend.core.namd_solvate import ROTATION_FREE_NS_THRESHOLD, resolve_box_mode

# One DNA atom is enough: resolve_box_mode's short-circuit for a declared-short free
# run never reaches the atom-count estimate.
_PDB = "ATOM      1  P   ADE A   1       0.000   0.000   0.000  1.00  0.00      D000\n"


class TestIntentDrivesCellSizing:
    def test_no_intent_keeps_the_cheap_ladder_cell(self) -> None:
        mode, note = resolve_box_mode(_PDB, 2.0, max_atoms=None, free_ns=_LADDER_FREE_NS)
        assert mode == "bbox"
        # The note is the record of WHY, which the package manifest carries forward.
        assert "not trustworthy" in note.lower()

    def test_a_long_intent_asks_for_a_rotation_sized_cell(self) -> None:
        mode, note = resolve_box_mode(_PDB, 2.0, max_atoms=None, free_ns=1000.0)
        assert mode == "rotation"
        assert note is None

    @pytest.mark.parametrize("free_ns,expected", [
        (ROTATION_FREE_NS_THRESHOLD - 0.1, "bbox"),
        (ROTATION_FREE_NS_THRESHOLD, "bbox"),          # at the threshold: still cheap
        (ROTATION_FREE_NS_THRESHOLD + 0.1, "rotation"),
    ])
    def test_the_flip_is_at_the_documented_threshold(self, free_ns, expected) -> None:
        mode, _ = resolve_box_mode(_PDB, 2.0, max_atoms=None, free_ns=free_ns)
        assert mode == expected

    def test_none_means_size_for_an_arbitrarily_long_run(self) -> None:
        # The safe default: a caller that says nothing gets the conservative cell.
        mode, _ = resolve_box_mode(_PDB, 2.0, max_atoms=None, free_ns=None)
        assert mode == "rotation"


class _FakeJob:
    """Minimal stand-in for MdJob: the guard reads its manifest and its ancestry."""

    def __init__(self, package_dir, job_id="j0", parent_job_id=None):
        self._pkg = package_dir
        self.job_id = job_id
        self.parent_job_id = parent_job_id

    def package_dir(self, _workspace):
        return self._pkg


def _package(tmp_path, solvation) -> _FakeJob:
    import json
    pkg = tmp_path / "package"
    pkg.mkdir(parents=True, exist_ok=True)
    manifest = {"name_stem": "d"}
    if solvation is not None:
        manifest["solvation"] = solvation
    (pkg / "manifest.json").write_text(json.dumps(manifest))
    return _FakeJob(pkg)


# The verdict prep recorded for 2hb_1xT: a turned solute overlaps its image by 33 A.
_FAILS_ROTATED = {"box_check": {"measured": True, "fits_rotated": False,
                                "image_gap_rotated_ang": -33.04}}
_FITS_ROTATED = {"box_check": {"measured": True, "fits_rotated": True,
                               "image_gap_rotated_ang": 18.2}}


class TestFreeRunCellGuard:
    def test_refuses_a_long_run_in_a_cell_the_solute_turns_out_of(self, tmp_path) -> None:
        job = _package(tmp_path, _FAILS_ROTATED)
        with pytest.raises(HTTPException) as exc:
            _assert_cell_fits_a_free_run(job, 1000.0, allow=False)
        assert exc.value.status_code == 400
        detail = exc.value.detail
        assert "33" in detail                      # how far it overlaps
        assert "production_ns_intent" in detail    # the actual remedy
        assert "allow_undersized_cell" in detail   # the override

    def test_a_negative_gap_reads_as_an_overlap_not_a_clearance(self, tmp_path) -> None:
        # "within -33 A" is faithful and unreadable; a negative gap IS an overlap.
        job = _package(tmp_path, _FAILS_ROTATED)
        with pytest.raises(HTTPException) as exc:
            _assert_cell_fits_a_free_run(job, 1000.0, allow=False)
        assert "33 Å overlap" in exc.value.detail
        assert "-33" not in exc.value.detail

    def test_a_positive_gap_reads_as_a_clearance(self, tmp_path) -> None:
        tight = {"box_check": {"measured": True, "fits_rotated": False,
                               "image_gap_rotated_ang": 4.0}}
        job = _package(tmp_path, tight)
        with pytest.raises(HTTPException) as exc:
            _assert_cell_fits_a_free_run(job, 1000.0, allow=False)
        assert "4 Å clearance" in exc.value.detail

    def test_the_refusal_stays_short(self, tmp_path) -> None:
        # The panel renders its own one-liner; this text is the API-facing version and
        # had grown into a paragraph nobody reads.
        job = _package(tmp_path, _FAILS_ROTATED)
        with pytest.raises(HTTPException) as exc:
            _assert_cell_fits_a_free_run(job, 1000.0, allow=False)
        assert len(exc.value.detail) < 250, exc.value.detail

    def test_allows_a_short_run_in_the_same_cell(self, tmp_path) -> None:
        job = _package(tmp_path, _FAILS_ROTATED)
        # Under the threshold the solute cannot turn far enough to matter.
        _assert_cell_fits_a_free_run(job, ROTATION_FREE_NS_THRESHOLD, allow=False)

    def test_explicit_override_runs_anyway(self, tmp_path) -> None:
        job = _package(tmp_path, _FAILS_ROTATED)
        _assert_cell_fits_a_free_run(job, 1000.0, allow=True)

    def test_a_rotation_sized_cell_passes(self, tmp_path) -> None:
        job = _package(tmp_path, _FITS_ROTATED)
        _assert_cell_fits_a_free_run(job, 1000.0, allow=False)

    def test_a_package_with_no_verdict_is_not_blocked(self, tmp_path) -> None:
        # Legacy packages predate box_check; the guard must fail OPEN rather than
        # refuse every run prepared before it existed.
        job = _package(tmp_path, None)
        _assert_cell_fits_a_free_run(job, 1000.0, allow=False)

    def test_an_unreadable_package_is_not_blocked(self, tmp_path) -> None:
        job = _FakeJob(tmp_path / "gone")
        _assert_cell_fits_a_free_run(job, 1000.0, allow=False)


class TestVerdictIsInheritedThroughAncestry:
    """A child with no verdict of its own must resolve its parent's, not fail open.

    Children created before the child manifest carried ``solvation`` have no verdict,
    and a chained production puts two hops between the run and the solvated package.
    Treating "no block" as "unknown, allow" is what let the 1 us run through.
    """

    def test_walks_up_to_an_ancestor_that_has_the_verdict(self, tmp_path, monkeypatch) -> None:
        from backend.api import routes_md

        grandparent = _package(tmp_path / "gp", _FAILS_ROTATED)
        grandparent.job_id = "gp"
        child = _package(tmp_path / "c", None)          # no solvation block at all
        child.job_id, child.parent_job_id = "c", "gp"

        monkeypatch.setattr(routes_md.MdJob, "load",
                            staticmethod(lambda jid, ws: grandparent))
        check = routes_md._inherited_box_check(child)
        assert check is not None
        assert check["fits_rotated"] is False

        with pytest.raises(HTTPException):
            routes_md._assert_cell_fits_a_free_run(child, 1000.0, allow=False)

    def test_a_missing_ancestor_fails_open(self, tmp_path, monkeypatch) -> None:
        from backend.api import routes_md

        child = _package(tmp_path / "c", None)
        child.job_id, child.parent_job_id = "c", "pruned"

        def _boom(jid, ws):
            raise FileNotFoundError(jid)
        monkeypatch.setattr(routes_md.MdJob, "load", staticmethod(_boom))
        assert routes_md._inherited_box_check(child) is None
        routes_md._assert_cell_fits_a_free_run(child, 1000.0, allow=False)

    def test_a_parent_cycle_terminates(self, tmp_path, monkeypatch) -> None:
        from backend.api import routes_md

        job = _package(tmp_path / "c", None)
        job.job_id, job.parent_job_id = "c", "c"        # self-parent
        monkeypatch.setattr(routes_md.MdJob, "load", staticmethod(lambda jid, ws: job))
        assert routes_md._inherited_box_check(job) is None


class TestChildInheritsTheVerdict:
    def test_replica_manifest_carries_the_parents_solvation_block(self) -> None:
        # The child re-uses the parent's cell verbatim (hardlinked PSF/PDB, copied
        # box_ang), so the parent's verdict IS the child's. Dropping the block made
        # the guard read {} and fall through its fits_rotated=True default.
        import inspect

        from backend.core import md_ensemble
        src = inspect.getsource(md_ensemble.build_replica_package)
        assert '"solvation": manifest.get("solvation")' in src

    def test_guard_runs_on_the_child_spawn_route_not_only_the_append_route(self) -> None:
        # The panel's Start Production button calls spawn_md_production; for a long
        # time only its sibling append route checked the cell.
        import inspect

        from backend.api import routes_md
        for fn in (routes_md.spawn_md_production, routes_md.append_md_production):
            assert "_assert_cell_fits_a_free_run" in inspect.getsource(fn), fn.__name__
