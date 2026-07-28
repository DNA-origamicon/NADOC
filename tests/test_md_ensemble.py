"""Tests for the Alpine ensemble production-replica machinery (backend.core.md_ensemble).

Pure/offline: builds a fake parent package, fans out replica packages, and checks the
generated confs + manifest are stageable and sbatch-able.  No network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.core import cluster_config as cc
from backend.core import cluster_resources as cr
from backend.core import md_ensemble as me
from backend.core.md_job import MdStatus, new_job
from backend.core.md_protocols import SegmentSpec, build_production_conf
from backend.core.slurm_script import generate_sbatch

READY = "demo_09_310K_NPT_k0p05_p100"


def _make_parent(ws: Path, *, fast: bool = False, mgh: bool = False):
    job = new_job("demo", "mgh_slow_release", name_stem="demo", package_subdir="pkg")
    job.status = MdStatus.completed
    job.save(ws)
    pkg = job.package_dir(ws)
    (pkg / "forcefield").mkdir(parents=True)
    (pkg / "output").mkdir(parents=True)
    (pkg / "demo.psf").write_text("psf")
    (pkg / "demo.pdb").write_text("pdb")
    (pkg / "forcefield" / "par_all36_na.prm").write_text("ff")
    if fast:
        (pkg / "demo_hmr.psf").write_text("hmrpsf")
    if mgh:
        (pkg / "mgh_extrabonds.txt").write_text("bonds")
    (pkg / "output" / f"{READY}.coor").write_text("coor")
    (pkg / "output" / f"{READY}.xsc").write_text("xsc")
    (pkg / "charge_audit.json").write_text(json.dumps({
        "topology_metadata": {"segments": [{"segid": "D000", "chain_id": "A"}]}
    }))
    manifest = {
        "name_stem": "demo",
        "protocol": "mgh_slow_release",
        "box_ang": [100.0, 110.0, 120.0],
        "mgh_extrabonds": mgh,
        "charge_audit": {"final_solvated": {"n_atoms": 120_000}},
        "relax_protocol_settings": {"timestep_fs": 2.0},
        "fast_relaxation": {"enabled": fast},
        "files": {"topology": "demo.psf", "coordinates": "demo.pdb"},
        "minimization": {"name": "demo_00_min", "steps": 4800},
        "segments": [{"name": READY, "steps": 2_400_000}],
    }
    (pkg / "manifest.json").write_text(json.dumps(manifest))
    return job


def _build_replica(ws: Path, parent, *, seed=54321, index=0, fast=False,
                   timestep_fs=None, total_steps=500_000):
    child = new_job("demo", "mgh_slow_release", name_stem="", package_subdir="",
                    parent_job_id=parent.job_id, ensemble_seed=seed, ensemble_index=index)
    child.execution_target = "alpine"
    child.cluster_name = "alpine"
    if timestep_fs is None:
        timestep_fs = 4.0 if fast else 1.0
    length_ns = total_steps * timestep_fs / 1_000_000.0
    me.build_replica_package(
        parent, child, seed=seed, index=index,
        total_steps=total_steps, length_ns=length_ns, timestep_fs=timestep_fs,
        fast=fast, ready_checkpoint=READY, workspace=ws,
    )
    return child


# ── generate_seeds ──────────────────────────────────────────────────────────────

def test_generate_seeds_distinct_and_reproducible():
    seeds = me.generate_seeds(54321, 5)
    assert seeds == [54321, 54322, 54323, 54324, 54325]
    assert len(set(seeds)) == 5
    assert me.generate_seeds(54321, 5) == seeds


def test_generate_seeds_rejects_zero():
    with pytest.raises(ValueError):
        me.generate_seeds(1, 0)


def test_replica_label():
    assert me.replica_label(2, 54323) == "Replica 3 · seed 54323"


# ── build_replica_package ────────────────────────────────────────────────────────

def test_replica_package_layout(tmp_path):
    parent = _make_parent(tmp_path)
    child = _build_replica(tmp_path, parent, seed=54322, index=1)

    assert child.name_stem == "demo"
    assert child.package_subdir == "pkg"
    assert child.status == MdStatus.queued
    assert len(child.segments) == 1

    pkg = child.package_dir(tmp_path)
    # Equilibrated start copied to package ROOT (so stage_plan uploads it).
    assert (pkg / "equilibrated.coor").exists()
    assert (pkg / "equilibrated.xsc").exists()
    # Structure files shared in.
    assert (pkg / "demo.psf").exists()
    assert (pkg / "demo.pdb").exists()
    assert (pkg / "forcefield" / "par_all36_na.prm").exists()
    # Segid→chain map shared in so the replica flexibility map resolves the 5' termini
    # via the segid P-order path (else those 21 bases render un-positioned/un-coloured).
    assert (pkg / "charge_audit.json").exists()

    manifest = json.loads((pkg / "manifest.json").read_text())
    assert manifest["minimization"]["name"] == "demo_00_reseed"
    assert len(manifest["segments"]) == 1
    # No declash key → generate_sbatch accepts it.
    assert not manifest.get("declash")
    assert manifest["ensemble"]["seed"] == 54322
    assert manifest["ensemble"]["index"] == 1
    assert manifest["ensemble"]["reinit_velocities"] is True


def test_reseed_conf_reinits_from_root_equilibrated(tmp_path):
    parent = _make_parent(tmp_path)
    child = _build_replica(tmp_path, parent, seed=77777)
    pkg = child.package_dir(tmp_path)
    reseed = (pkg / "demo_00_reseed.conf").read_text()
    assert "seed               77777" in reseed
    assert "reinitvels         300" in reseed
    assert "binCoordinates     equilibrated.coor" in reseed
    assert "extendedSystem     equilibrated.xsc" in reseed
    # coords preserved — a zero-step run, no minimize
    assert "run                0" in reseed
    assert "minimize" not in reseed
    assert "outputName         output/demo_00_reseed" in reseed


def test_production_conf_reads_reseed_and_carries_seed(tmp_path):
    parent = _make_parent(tmp_path)
    child = _build_replica(tmp_path, parent, seed=88888)
    pkg = child.package_dir(tmp_path)
    prod = next(pkg.glob("demo_01_production_*.conf")).read_text()
    assert "seed               88888" in prod
    assert "binCoordinates     output/demo_00_reseed.coor" in prod
    assert "binVelocities      output/demo_00_reseed.vel" in prod


def test_replica_manifest_total_ns(tmp_path):
    # A 4 fs replica needs a fast (HMR) parent — else it downgrades to 1 fs (see
    # test_replica_4fs_without_hmr_parent_downgrades). 500k steps × 4 fs = 2 ns.
    parent = _make_parent(tmp_path, fast=True)
    child = _build_replica(tmp_path, parent, fast=True)
    manifest = json.loads((child.package_dir(tmp_path) / "manifest.json").read_text())
    # One production segment at the production timestep → total_ns == length_ns.
    assert cr.total_ns_from_manifest(manifest) == pytest.approx(2.0)
    assert cr.n_atoms_from_manifest(manifest) == 120_000


def _prod_conf(child, ws) -> str:
    return next(child.package_dir(ws).glob("demo_01_production_*.conf")).read_text()


def test_replica_2fs_conf_runs_at_2fs(tmp_path):
    # REGRESSION: the ensemble path used to pass only ``fast`` to build_production_conf,
    # so a manual 2 fs replica silently emitted a 1 fs conf and ran HALF its labelled time.
    parent = _make_parent(tmp_path)
    child = _build_replica(tmp_path, parent, fast=False, timestep_fs=2.0, total_steps=500_000)
    conf = _prod_conf(child, tmp_path)
    assert "timestep           2" in conf
    assert "rigidBonds         all" in conf          # 2 fs medium path, not the 1 fs ref
    manifest = json.loads((child.package_dir(tmp_path) / "manifest.json").read_text())
    # 500k steps × 2 fs = 1 ns — label + manifest reflect the ACTUAL integrated time.
    assert cr.total_ns_from_manifest(manifest) == pytest.approx(1.0)
    assert manifest["ensemble"]["timestep_fs"] == 2.0
    assert next(child.package_dir(tmp_path).glob("demo_01_production_1ns_*"))


def test_replica_4fs_conf_runs_at_4fs(tmp_path):
    parent = _make_parent(tmp_path, fast=True)
    child = _build_replica(tmp_path, parent, fast=True, timestep_fs=4.0)
    conf = _prod_conf(child, tmp_path)
    assert "timestep           4" in conf
    assert "structure          demo_hmr.psf" in conf


def test_replica_4fs_without_hmr_parent_downgrades(tmp_path):
    # 4 fs needs the HMR PSF; a parent without one can't run it, so it falls back to the
    # safe 1 fs reference — and the label follows so simulated time never lies.
    parent = _make_parent(tmp_path)          # no demo_hmr.psf
    child = _build_replica(tmp_path, parent, fast=True, timestep_fs=4.0, total_steps=500_000)
    conf = _prod_conf(child, tmp_path)
    assert "timestep           1" in conf
    assert "rigidBonds         none" in conf
    manifest = json.loads((child.package_dir(tmp_path) / "manifest.json").read_text())
    assert manifest["ensemble"]["timestep_fs"] == 1.0
    assert cr.total_ns_from_manifest(manifest) == pytest.approx(0.5)  # 500k × 1 fs


def test_fast_replica_uses_hmr_psf(tmp_path):
    parent = _make_parent(tmp_path, fast=True)
    child = _build_replica(tmp_path, parent, fast=True)
    pkg = child.package_dir(tmp_path)
    assert (pkg / "demo_hmr.psf").exists()
    prod = next(pkg.glob("demo_01_production_*.conf")).read_text()
    assert "structure          demo_hmr.psf" in prod
    assert "GPUresident        on" in prod          # stripped later for a CPU target


def test_replica_generates_valid_amilan_sbatch(tmp_path):
    parent = _make_parent(tmp_path)
    child = _build_replica(tmp_path, parent)
    manifest = json.loads((child.package_dir(tmp_path) / "manifest.json").read_text())
    profile = cc.alpine_profile()
    resources = cr.recommend(profile, n_atoms=120_000, total_ns=2.0, partition="amilan")
    sbatch = generate_sbatch(manifest, profile, resources, "/scratch/x", job_name="demo")
    # Two-step chain: reseed (min slot) then production, each idempotent-guarded.
    assert "demo_00_reseed" in sbatch
    assert "demo_01_production" in sbatch
    assert "mpirun" in sbatch                       # CPU exec line
    assert 'if [ -f "output/demo_00_reseed.coor" ]' in sbatch


def test_mgh_extrabonds_propagates(tmp_path):
    parent = _make_parent(tmp_path, mgh=True)
    child = _build_replica(tmp_path, parent)
    pkg = child.package_dir(tmp_path)
    assert (pkg / "mgh_extrabonds.txt").exists()
    reseed = (pkg / "demo_00_reseed.conf").read_text()
    assert "extraBondsFile     mgh_extrabonds.txt" in reseed


def test_design_snapshot_propagates_to_child(tmp_path):
    # A production/ensemble child runs the parent's PSF/PDB, so it must inherit the
    # parent's frozen design.json — else the metrics/trajectory endpoints can't map
    # P atoms → base pairs and fail with a misleading "no NAMD trajectory".
    parent = _make_parent(tmp_path)
    (parent.job_dir(tmp_path) / "design.json").write_text('{"snapshot": true}')
    child = _build_replica(tmp_path, parent)
    child_snap = child.job_dir(tmp_path) / "design.json"
    assert child_snap.exists()
    assert json.loads(child_snap.read_text()) == {"snapshot": True}


def test_child_build_tolerates_missing_parent_snapshot(tmp_path):
    # Legacy parent with no snapshot: the build must still succeed (the read-side
    # parent-chain walk in routes_md._md_snapshot_design covers this case).
    parent = _make_parent(tmp_path)
    child = _build_replica(tmp_path, parent)
    assert not (child.job_dir(tmp_path) / "design.json").exists()


def test_missing_checkpoint_raises(tmp_path):
    parent = _make_parent(tmp_path)
    (parent.package_dir(tmp_path) / "output" / f"{READY}.coor").unlink()
    child = new_job("demo", "p", name_stem="", package_subdir="")
    with pytest.raises(FileNotFoundError):
        me.build_replica_package(
            parent, child, seed=1, index=0, total_steps=1000, length_ns=1.0,
            timestep_fs=1.0, fast=False, ready_checkpoint=READY, workspace=tmp_path,
        )


# ── conf-builder parity (the delegate refactor preserves the local path) ─────────

def test_conservative_production_conf_delegates_verbatim():
    """routes_md._conservative_production_conf must be byte-identical to the shared
    build_production_conf with default seed/start_checkpoint — proves the extraction
    didn't change the local production path."""
    from backend.api.routes_md import _conservative_production_conf

    spec = SegmentSpec(
        name="d_01_production_2ns_k0_p100", stage="2 ns conservative production run",
        percent=100.0, steps=500_000, temp=300.0, damping=5.0, scale=None, npt=True,
        previous="d_00_min", dcd_freq=1000,
    )
    box = (100.0, 110.0, 120.0)
    for fast in (False, True):
        legacy = _conservative_production_conf(spec, "d", box, False, fast=fast,
                                               structure_psf="d_hmr.psf" if fast else None)
        shared = build_production_conf(spec, "d", box, False, fast=fast,
                                       structure_psf="d_hmr.psf" if fast else None)
        assert legacy == shared
        assert "seed               54321" in legacy


def test_production_conf_seed_and_start_overrides():
    spec = SegmentSpec(name="p", stage="s", percent=100.0, steps=100, temp=300.0,
                       damping=5.0, scale=None, npt=True, previous="orig", dcd_freq=1000)
    conf = build_production_conf(spec, "d", (10.0, 10.0, 10.0), False,
                                 seed=42, start_checkpoint="reseed")
    assert "seed               42" in conf
    assert "binCoordinates     output/reseed.coor" in conf
    assert "output/orig" not in conf                # start_checkpoint overrode previous


# ── GPU-resident: the path the panel's Start-Production actually takes ───────────
#
# build_replica_package is what /md/jobs/{id}/production-run calls — NOT the
# _append_production_segments path.  It was the LAST un-threaded build_production_conf
# call site, so it kept passing n_atoms=None ("unknown" → resident ON) and a 32.5k-atom
# 2 fs production stayed on GPU-resident at 1.357 ms/step no matter what the Advanced-card
# dropdown said or what ⚡ Optimize reported.  Unit tests on build_production_conf all
# passed while the route the UI uses never reached the new arguments.

def _parent_with_sized_psf(ws: Path, n_atoms: int, *, fast=False):
    parent = _make_parent(ws, fast=fast)
    # A real !NATOM header so psf_atom_count() sees a size (the base fixture writes "psf").
    (parent.package_dir(ws) / "demo.psf").write_text(
        "PSF\n\n       2 !NTITLE\n\n" + f"{n_atoms:8d} !NATOM\n")
    return parent


def _prod_conf(child, ws: Path) -> str:
    pkg = child.package_dir(ws)
    return next(p for p in pkg.glob("*production*.conf")).read_text()


def test_replica_small_system_drops_gpu_resident(tmp_path):
    parent = _parent_with_sized_psf(tmp_path, 32_566)
    child = _build_replica(tmp_path, parent, timestep_fs=2.0)
    assert "GPUresident" not in _prod_conf(child, tmp_path)


def test_replica_large_system_keeps_gpu_resident(tmp_path):
    parent = _parent_with_sized_psf(tmp_path, 3_139_238)
    child = _build_replica(tmp_path, parent, timestep_fs=2.0)
    assert "GPUresident        on" in _prod_conf(child, tmp_path)


def test_replica_force_resident_off_overrides_a_large_system(tmp_path):
    parent = _parent_with_sized_psf(tmp_path, 3_139_238)
    child = new_job("demo", "mgh_slow_release", name_stem="", package_subdir="",
                    parent_job_id=parent.job_id, ensemble_seed=54321, ensemble_index=0)
    me.build_replica_package(
        parent, child, seed=54321, index=0, total_steps=500_000, length_ns=1.0,
        timestep_fs=2.0, fast=False, ready_checkpoint=READY, workspace=tmp_path,
        force_resident=False)
    assert "GPUresident" not in _prod_conf(child, tmp_path)


def test_replica_force_resident_on_overrides_a_small_system(tmp_path):
    parent = _parent_with_sized_psf(tmp_path, 32_566)
    child = new_job("demo", "mgh_slow_release", name_stem="", package_subdir="",
                    parent_job_id=parent.job_id, ensemble_seed=54321, ensemble_index=0)
    me.build_replica_package(
        parent, child, seed=54321, index=0, total_steps=500_000, length_ns=1.0,
        timestep_fs=2.0, fast=False, ready_checkpoint=READY, workspace=tmp_path,
        force_resident=True)
    assert "GPUresident        on" in _prod_conf(child, tmp_path)


def test_replica_unsized_psf_keeps_the_historical_default(tmp_path):
    """The base fixture's PSF has no !NATOM — unknown must stay 'resident on', so this
    change cannot silently alter any package whose size we cannot read."""
    parent = _make_parent(tmp_path)
    child = _build_replica(tmp_path, parent, timestep_fs=2.0)
    assert "GPUresident        on" in _prod_conf(child, tmp_path)
