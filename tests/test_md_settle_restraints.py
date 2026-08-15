"""The Note-4 settle stage holds the solute with restraints, never ``fixedAtoms``.

NAMD 3 refuses the combination outright — "FATAL ERROR: GPUresident is incompatible with
the following options: ... fixed atoms" — so emitting both killed the run at the START of
the first segment, hours into a job, and the runtime probe then misread a pure config
conflict as "this GPU cannot do resident" and offered to downgrade the WHOLE ladder to
offload + half timestep.

Restraining instead of fixing is not a throughput hack, it is the better physics for this
stage.  NAMD's own manual warns that "the use of constant pressure with significant
numbers of fixed atoms is not recommended" (and drops forces between fixed atoms from the
virial unless ``fixedAtomsForces`` is on — in the one stage that exists to let the
barostat find the right volume), and names harmonic restraints as the sanctioned
GPU-resident workaround.  Aksimentiev's own papers hold origami at k = 1 kcal/mol/Å² on
DNA heavy atoms.  Measured equivalence on 6hbx32 (234 646 atoms, 50 ps): the cell settles
to 95.34 % of its starting volume restrained vs 95.39 % fixed, while the DNA moves 0.35 Å
RMS — against 1.19 Å for minimisation alone and ~10 Å for the ladder that follows.
"""

from __future__ import annotations

import pytest

from backend.core import md_protocols as P


def _settle_and_ladder(**kw):
    """(settle spec, first relaxation spec) from a default full-box ladder."""
    _, segs = P.mgh_slow_release_segments("X", **kw)
    settle = [s for s in segs if s.restraint_ref_file]
    assert len(settle) == 1, "expected exactly one settle stage"
    return settle[0], next(s for s in segs if not s.restraint_ref_file)


def _directives(conf: str) -> dict[str, str]:
    out = {}
    for line in conf.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            out.setdefault(parts[0].lower(), parts[1].strip())
    return out


# ── the segment spec ──────────────────────────────────────────────────────────


def test_settle_stage_restrains_rather_than_fixes():
    settle, _ = _settle_and_ladder()
    assert settle.fixed_atoms_file is None
    assert settle.restraint_ref_file == P.SOLUTE_RESTRAINT_PDB
    assert settle.scale == P.SETTLE_RESTRAINT_K


def test_settle_stiffness_is_the_published_value():
    """Aksimentiev PNAS 2013 / NAR 2016: k = 1 kcal/mol/Å² on DNA heavy atoms."""
    assert P.SETTLE_RESTRAINT_K == 1.0


def test_settle_keeps_its_own_reference_file_separate_from_the_ladder():
    """The runner re-points it at the minimised coords; the ladder's must not move."""
    assert P.SOLUTE_RESTRAINT_PDB != "restraints_dna_heavy.pdb"


# ── the emitted conf ──────────────────────────────────────────────────────────


def test_settle_conf_emits_restraints_and_no_fixed_atoms():
    settle, _ = _settle_and_ladder()
    d = _directives(
        P._segment_conf(
            settle, "X", (100.0, 90.0, 80.0), mgh_extrabonds=True, n_atoms=250_000
        )
    )
    assert "fixedatoms" not in d
    assert d["constraints"] == "on"
    assert d["consref"] == P.SOLUTE_RESTRAINT_PDB
    assert d["conskfile"] == P.SOLUTE_RESTRAINT_PDB
    assert d["conskcol"] == "B"
    assert float(d["constraintscaling"]) == P.SETTLE_RESTRAINT_K


def test_settle_conf_keeps_gpu_resident_on_a_large_system():
    """The whole point: the stage no longer forfeits the fast GPU mode."""
    settle, _ = _settle_and_ladder()
    conf = P._segment_conf(
        settle, "X", (100.0, 90.0, 80.0), mgh_extrabonds=True, n_atoms=250_000
    )
    assert "GPUresident        on" in conf


def test_settle_is_soft_first_dynamics_after_minimization():
    _, segments = P.mgh_slow_release_segments("X", timestep_fs=4.0, high_aspect_ratio=True)
    settle = next(s for s in segments if "settle" in s.name)
    conf = P._segment_conf(
        settle, "X", (100.0, 90.0, 800.0), True, n_atoms=3_000_000
    )
    assert settle.soft is True
    assert "rigidBonds         none" in conf
    assert "timestep           1" in conf


def test_elongated_npt_cell_gets_bounded_patch_grid_headroom():
    settle, _ = _settle_and_ladder()
    elongated = P._segment_conf(
        settle, "X", (90.0, 90.0, 4080.0), True,
        npt_margin_ang=P.HIGH_ASPECT_NPT_MARGIN_ANG,
    )
    ordinary = P._segment_conf(settle, "X", (90.0, 90.0, 200.0), True)
    assert f"margin             {P.HIGH_ASPECT_NPT_MARGIN_ANG:g}" in elongated
    assert f"margin             {P.NPT_MARGIN_ANG:g}" in ordinary
    assert P.HIGH_ASPECT_NPT_MARGIN_ANG < 30.0


def test_settle_conf_still_runs_under_the_barostat():
    """Restraining must not quietly turn the settle stage into NVT — the box HAS to move."""
    settle, _ = _settle_and_ladder()
    d = _directives(
        P._segment_conf(
            settle, "X", (100.0, 90.0, 80.0), mgh_extrabonds=True, n_atoms=250_000
        )
    )
    assert d["langevinpiston"] == "on"


def test_settle_conf_carries_no_enm():
    """The ENM ladder starts AFTER the box has settled; this stage has only the restraint."""
    settle, _ = _settle_and_ladder()
    conf = P._segment_conf(
        settle, "X", (100.0, 90.0, 80.0), mgh_extrabonds=True, n_atoms=250_000
    )
    assert settle.extra_bonds_file is None
    assert ".enm.extra" not in conf


# ── the GPU-resident gate ─────────────────────────────────────────────────────
#
# The backstop that makes the whole failure class impossible: anything that emits
# fixedAtoms must not also ask for GPUresident.


def test_a_segment_with_a_fixed_atoms_marker_gives_up_gpu_resident():
    import dataclasses

    _, ladder = _settle_and_ladder()
    pinned = dataclasses.replace(ladder, fixed_atoms_file="anything.pdb")
    conf = P._segment_conf(
        pinned, "X", (100.0, 90.0, 80.0), mgh_extrabonds=True, n_atoms=250_000
    )
    assert "fixedAtoms         on" in conf
    assert "GPUresident" not in conf


def test_hard_anchors_give_up_gpu_resident():
    """Job-level anchors ride ``fixedAtoms`` too — they must not be paired with resident."""
    _, ladder = _settle_and_ladder()
    conf = P._segment_conf(
        ladder,
        "X",
        (100.0, 90.0, 80.0),
        mgh_extrabonds=True,
        n_atoms=250_000,
        anchors_file="anchors.pdb",
    )
    assert "fixedAtoms         on" in conf
    assert "GPUresident" not in conf


def test_an_unanchored_large_segment_still_gets_gpu_resident():
    """The gate must not have taken resident away from the ordinary ladder."""
    _, ladder = _settle_and_ladder()
    conf = P._segment_conf(
        ladder, "X", (100.0, 90.0, 80.0), mgh_extrabonds=True, n_atoms=250_000
    )
    assert "GPUresident        on" in conf


# ``_segment_conf`` is not the only conf writer that emits GPUresident —
# ``build_production_conf`` has its own copy of the size gate, and a fix applied to only
# one of them leaves the other still emitting the fatal pair (LESSONS H16: "fixed the leaf,
# not the path in use", whose own example was this very gate).


def _prod_spec():
    return P.SegmentSpec(
        name="demo_production",
        stage="production",
        percent=100.0,
        steps=1000,
        temp=300.0,
        damping=1.0,
        scale=None,
        npt=True,
        previous="prev",
    )


def test_hard_anchored_production_gives_up_gpu_resident():
    conf = P.build_production_conf(
        _prod_spec(),
        "demo",
        (100.0, 100.0, 100.0),
        False,
        timestep_fs=2.0,
        anchors_file="a.pdb",
        n_atoms=250_000,
    )
    assert "fixedAtoms         on" in conf
    assert "GPUresident" not in conf


def test_hard_anchored_production_gives_up_resident_even_when_forced():
    """The Advanced-card "on" is a size override, not a licence to emit an illegal conf."""
    conf = P.build_production_conf(
        _prod_spec(),
        "demo",
        (100.0, 100.0, 100.0),
        False,
        timestep_fs=2.0,
        anchors_file="a.pdb",
        n_atoms=250_000,
        force_resident=True,
    )
    assert "GPUresident" not in conf


def test_soft_anchored_production_keeps_gpu_resident():
    """Harmonic restraints are resident-compatible — the gate must not overreach."""
    conf = P.build_production_conf(
        _prod_spec(),
        "demo",
        (100.0, 100.0, 100.0),
        False,
        timestep_fs=2.0,
        anchors_file="a.pdb",
        anchor_k=0.02,
        n_atoms=250_000,
    )
    assert "constraints        on" in conf
    assert "fixedAtoms" not in conf
    assert "GPUresident        on" in conf


def test_unanchored_production_keeps_gpu_resident():
    conf = P.build_production_conf(
        _prod_spec(),
        "demo",
        (100.0, 100.0, 100.0),
        False,
        timestep_fs=2.0,
        n_atoms=250_000,
    )
    assert "GPUresident        on" in conf


# ── manifest round-trip ───────────────────────────────────────────────────────


def test_restraint_reference_survives_a_manifest_round_trip(tmp_path):
    """A resumed job must rebuild the same settle stage, not fall back to the ladder's."""
    import json

    settle, _ = _settle_and_ladder()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "minimization": {"name": "X_00_min"},
                "segments": [
                    {
                        "name": settle.name,
                        "stage": settle.stage,
                        "percent": settle.percent,
                        "steps": settle.steps,
                        "temp": settle.temp,
                        "damping": settle.damping,
                        "scale": settle.scale,
                        "npt": settle.npt,
                        "previous": settle.previous,
                        "restraint_ref_file": settle.restraint_ref_file,
                        "fixed_atoms_file": settle.fixed_atoms_file,
                    }
                ],
            }
        )
    )
    _, rebuilt = P.segments_from_manifest(manifest)
    assert rebuilt[0].restraint_ref_file == P.SOLUTE_RESTRAINT_PDB
    assert rebuilt[0].scale == P.SETTLE_RESTRAINT_K


def test_a_pre_change_manifest_still_resumes_on_its_own_confs(tmp_path):
    """An in-flight package prepped with fixedAtoms keeps that mechanism, not a mix."""
    import json

    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "minimization": {"name": "X_00_min"},
                "segments": [
                    {
                        "name": "X_0S_300K_NPT_settle_fixed_dna_p100",
                        "stage": "300K NPT settle",
                        "percent": 100.0,
                        "steps": 1000,
                        "temp": 300.0,
                        "damping": 5.0,
                        "scale": None,
                        "npt": True,
                        "previous": "X_00_min",
                        "fixed_atoms_file": "fixed_dna_all.pdb",  # no restraint_ref_file key
                    }
                ],
            }
        )
    )
    _, rebuilt = P.segments_from_manifest(manifest)
    assert rebuilt[0].restraint_ref_file is None
    assert rebuilt[0].fixed_atoms_file == "fixed_dna_all.pdb"


# ── the runner's re-referencing step ──────────────────────────────────────────


def test_retarget_settle_restraints_moves_the_reference_to_the_minimised_coords(
    tmp_path,
):
    """Restraining to the BUILD pose would stand against the minimiser all stage long."""
    import struct

    from backend.core.namd_runner import retarget_settle_restraints

    ref = tmp_path / P.SOLUTE_RESTRAINT_PDB
    ref.write_text(
        "ATOM      1  P   THY A   1       1.000   2.000   3.000  0.00  1.00      D000 P\n"
        "ATOM      2  OH2 TIP3W   2       9.000   9.000   9.000  0.00  0.00      W000 O\n"
    )
    coor = tmp_path / "min.coor"
    coor.write_bytes(struct.pack("<i", 2) + struct.pack("<6d", 4.5, 5.5, 6.5, 9, 9, 9))

    assert retarget_settle_restraints(tmp_path, coor) is True
    lines = ref.read_text().splitlines()
    assert lines[0][30:54] == f"{4.5:8.3f}{5.5:8.3f}{6.5:8.3f}"
    # the force-constant column is what makes it a conskfile — it must survive
    assert float(lines[0][60:66]) == 1.0
    assert float(lines[1][60:66]) == 0.0


def test_retarget_settle_restraints_is_idempotent(tmp_path):
    """Resume repeats it; the second write must be identical to the first."""
    import struct

    from backend.core.namd_runner import retarget_settle_restraints

    ref = tmp_path / P.SOLUTE_RESTRAINT_PDB
    ref.write_text(
        "ATOM      1  P   THY A   1       1.000   2.000   3.000  0.00  1.00      D000 P\n"
    )
    coor = tmp_path / "min.coor"
    coor.write_bytes(struct.pack("<i", 1) + struct.pack("<3d", 4.5, 5.5, 6.5))

    retarget_settle_restraints(tmp_path, coor)
    once = ref.read_text()
    retarget_settle_restraints(tmp_path, coor)
    assert ref.read_text() == once


def test_remote_and_local_retarget_are_byte_identical(tmp_path):
    """Both execution targets use one canonical coordinate-column rewrite."""
    import struct

    from backend.core.namd_runner import retarget_settle_restraints
    from backend.core.remote_settle_retarget import retarget_pdb_coordinates

    pdb = (
        "ATOM      1  P   THY A   1       1.000   2.000   3.000  0.00  1.00      D000 P\n"
        "ATOM      2  OH2 TIP3W   2       9.000   9.000   9.000  0.00  0.00      W000 O\n"
    )
    local_dir = tmp_path / "local"
    remote_dir = tmp_path / "remote"
    local_dir.mkdir()
    remote_dir.mkdir()
    for directory in (local_dir, remote_dir):
        (directory / P.SOLUTE_RESTRAINT_PDB).write_text(pdb)
    coor = tmp_path / "min.coor"
    coor.write_bytes(struct.pack("<i", 2) + struct.pack("<6d", 4.5, 5.5, 6.5, 8, 9, 10))

    assert retarget_settle_restraints(local_dir, coor)
    retarget_pdb_coordinates(
        coor,
        remote_dir / P.SOLUTE_RESTRAINT_PDB,
        remote_dir / P.SOLUTE_RESTRAINT_PDB,
    )
    assert (local_dir / P.SOLUTE_RESTRAINT_PDB).read_bytes() == (
        remote_dir / P.SOLUTE_RESTRAINT_PDB
    ).read_bytes()


def test_remote_retarget_helper_remains_python36_compatible():
    """Alpine compute nodes expose Python 3.6 even when the login host is newer."""
    from pathlib import Path

    from backend.core import remote_settle_retarget

    source = Path(remote_settle_retarget.__file__).read_text()
    assert "from __future__ import annotations" not in source
    assert "list[str]" not in source


@pytest.mark.parametrize("missing", ["ref", "coor"])
def test_retarget_settle_restraints_is_a_no_op_when_there_is_nothing_to_do(
    tmp_path, missing
):
    """A carved/NVT package has no settle stage; that must not fail a job."""
    import struct

    from backend.core.namd_runner import retarget_settle_restraints

    if missing != "ref":
        (tmp_path / P.SOLUTE_RESTRAINT_PDB).write_text("ATOM      1  P   THY A   1\n")
    coor = tmp_path / "min.coor"
    if missing != "coor":
        coor.write_bytes(struct.pack("<i", 0))
    assert retarget_settle_restraints(tmp_path, coor) is False
