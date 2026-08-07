"""Unit tests for backend/core/slurm_script.py — pure, offline."""

from __future__ import annotations

from dataclasses import replace

import pytest

from backend.core import cluster_config as cc
from backend.core import cluster_resources as cr
from backend.core import slurm_script as ss


@pytest.fixture
def alpine():
    return cc.alpine_profile()


def _manifest(declash=False):
    return {
        "name_stem": "6hb_demo",
        "declash": declash,
        "relax_protocol_settings": {"timestep_fs": 2.0},
        "charge_audit": {"final_solvated": {"n_atoms": 100_000}},
        "minimization": {"name": "6hb_demo_00_min"},
        "segments": [
            {"name": "6hb_demo_01_p100", "steps": 1_000_000},
            {"name": "6hb_demo_02_p100", "steps": 1_000_000},
        ],
    }


@pytest.fixture
def gpu_resources(alpine):
    return cr.recommend(alpine, n_atoms=100_000, total_ns=4.0, measured_ns_per_day=50.0)


# ── is_gpu_target ─────────────────────────────────────────────────────────────

def test_is_gpu_target_gpu_partition(alpine, gpu_resources):
    assert gpu_resources["partition"] == "ah200"
    assert ss.is_gpu_target(alpine, gpu_resources) is True


def test_is_gpu_target_cpu_partition(alpine):
    cpu = cr.recommend(alpine, n_atoms=100_000, total_ns=4.0, partition="acpu")
    assert cpu["kind"] == "cpu"
    assert ss.is_gpu_target(alpine, cpu) is False


def test_is_gpu_target_unknown_partition_raises(alpine):
    with pytest.raises(ValueError):
        ss.is_gpu_target(alpine, {"partition": "nope"})


# ── strip_gpu_resident (conf amendment for CPU/multicore targets) ──────────────

def test_strip_gpu_resident_removes_directive():
    from backend.core.md_protocols import strip_gpu_resident
    conf = "timestep           4\nGPUresident        on\nrun                600000\n"
    out = strip_gpu_resident(conf)
    assert "GPUresident" not in out
    # surrounding directives are preserved, no blank-line pileup that breaks NAMD
    assert "timestep           4" in out
    assert "run                600000" in out


def test_strip_gpu_resident_noop_when_absent():
    from backend.core.md_protocols import strip_gpu_resident
    conf = "timestep           1\nrigidBonds         none\nrun                120000\n"
    assert strip_gpu_resident(conf) == conf


def test_strip_gpu_resident_idempotent():
    from backend.core.md_protocols import strip_gpu_resident
    conf = "a\nGPUresident on\nb\n"
    once = strip_gpu_resident(conf)
    assert strip_gpu_resident(once) == once
    assert "GPUresident" not in once


# ── build_remote_resume_conf (mid-segment checkpoint resume) ───────────────────

def test_build_remote_resume_conf_continues_from_checkpoint():
    from backend.core.md_protocols import build_remote_resume_conf
    conf = (
        "structure          x.psf\n"
        "binCoordinates     start.coor\n"
        "firsttimestep      0\n"
        "dcdFile            output/seg.dcd\n"
        "run                480000\n"
    )
    out = build_remote_resume_conf(conf, segment_name="seg", restart_step=144000,
                                   total_steps=480000, cont_index=2)
    # original coord/run/dcd/firsttimestep dropped, restart directives re-emitted
    assert "binCoordinates     output/seg.restart.coor" in out
    assert "binVelocities      output/seg.restart.vel" in out
    assert "extendedSystem     output/seg.restart.xsc" in out
    assert "firsttimestep      144000" in out
    assert "run                336000" in out             # 480000 - 144000
    assert "output/seg.cont2.dcd" in out
    assert "structure          x.psf" in out              # untouched directives kept
    assert "binCoordinates     start.coor" not in out     # old coords directive gone


def test_build_remote_resume_conf_rejects_completed_step():
    from backend.core.md_protocols import build_remote_resume_conf
    with pytest.raises(ValueError):
        build_remote_resume_conf("run 100\n", segment_name="s",
                                 restart_step=100, total_steps=100)


def test_generate_resume_sbatch_runs_resume_conf_for_interrupted(alpine, gpu_resources):
    interrupted = "6hb_demo_01_p100"
    script = ss.generate_sbatch(
        _manifest(), alpine, gpu_resources, "/scratch/x",
        resume_conf_for={interrupted: f"{interrupted}.resume"},
    )
    # completed-segment skip guard still keys on the segment's final .coor
    assert f'if [ -f "output/{interrupted}.coor" ]; then' in script
    # the interrupted segment runs its resume conf + logs to .resume.log
    assert f"{interrupted}.resume.conf" in script
    assert f"{interrupted}.resume.log" in script
    assert "resuming from checkpoint" in script
    # a NON-resumed segment still runs its normal conf
    assert "6hb_demo_02_p100.conf" in script


# ── sanitize_job_name ─────────────────────────────────────────────────────────

def test_sanitize_keeps_safe_chars():
    assert ss.sanitize_job_name("6hb_2xT.v3-1") == "6hb_2xT.v3-1"


def test_sanitize_collapses_bad_chars():
    assert ss.sanitize_job_name("my job / name!") == "my_job_name"


def test_sanitize_rejects_empty():
    with pytest.raises(ValueError):
        ss.sanitize_job_name("   ")
    with pytest.raises(ValueError):
        ss.sanitize_job_name("///")


# ── generate_sbatch: structure ────────────────────────────────────────────────

def test_generate_has_shebang_and_directives(alpine, gpu_resources):
    script = ss.generate_sbatch(_manifest(), alpine, gpu_resources, "/scratch/alpine/jojo/nadoc_jobs/j1")
    assert script.startswith("#!/bin/bash\n")
    assert "#SBATCH --job-name=6hb_demo" in script
    assert f"#SBATCH --partition={gpu_resources['partition']}" in script
    assert f"#SBATCH --time={gpu_resources['walltime']}" in script
    assert f"#SBATCH --qos={gpu_resources['qos']}" in script
    assert "#SBATCH --nodes=1" in script


def test_generate_runs_min_then_all_segments_in_order(alpine, gpu_resources):
    script = ss.generate_sbatch(_manifest(), alpine, gpu_resources, "/scratch/x")
    i_min = script.index("6hb_demo_00_min.conf")
    i_s1 = script.index("6hb_demo_01_p100.conf")
    i_s2 = script.index("6hb_demo_02_p100.conf")
    assert i_min < i_s1 < i_s2


def test_ladder_is_idempotent_skip_guarded(alpine, gpu_resources):
    """Each step is guarded by an ``output/<conf>.coor`` existence check so a
    resubmit onto the same scratch resumes at the first unfinished segment
    (auto-resubmit-on-TIMEOUT recovery)."""
    script = ss.generate_sbatch(_manifest(), alpine, gpu_resources, "/scratch/x")
    assert 'if [ -f "output/6hb_demo_01_p100.coor" ]; then' in script
    assert "skip 6hb_demo_01_p100 (already complete)" in script
    # The min step is guarded too.
    assert 'if [ -f "output/6hb_demo_00_min.coor" ]; then' in script


def test_gpu_exec_line_is_gpu_resident(alpine, gpu_resources):
    script = ss.generate_sbatch(_manifest(), alpine, gpu_resources, "/scratch/x")
    # Alpine GPU partitions require a TYPED GRES — bare "gpu:1" is rejected by SLURM.
    assert "#SBATCH --gres=gpu:h200:1" in script


def test_untyped_gres_when_partition_has_no_gres_type(alpine):
    # A GPU partition without a gres_type falls back to the untyped form.
    res = cr.recommend(alpine, n_atoms=100_000, total_ns=4.0, measured_ns_per_day=50.0)
    res["gres_type"] = ""       # simulate a profile that doesn't specify the type
    script = ss.generate_sbatch(_manifest(), alpine, res, "/scratch/x")
    assert "#SBATCH --gres=gpu:1" in script
    assert "+setcpuaffinity +devices 0" in script
    assert "namd3 +p" in script
    assert "mpirun" not in script


def test_cpu_partition_uses_mpirun(alpine):
    res = cr.recommend(alpine, n_atoms=cr.gpu_atom_ceiling("ah200") + 1, total_ns=4.0,
                       measured_ns_per_day=5.0)
    script = ss.generate_sbatch(_manifest(), alpine, res, "/scratch/x")
    assert "mpirun -np $SLURM_NTASKS namd3" in script
    assert "+devices" not in script
    assert "--gres=gpu" not in script


def test_module_block_present(alpine, gpu_resources):
    # A GPU target loads the GPU (CUDA) NAMD build, not the CPU MPI module set.
    script = ss.generate_sbatch(_manifest(), alpine, gpu_resources, "/scratch/x")
    assert "module purge" in script
    assert "module load " + " ".join(alpine.modules_for(gpu=True)) in script
    assert "namd/3.0.1_gpu" in script


def test_cpu_target_loads_cpu_module_block(alpine):
    cpu = cr.recommend(alpine, n_atoms=100_000, total_ns=4.0, partition="acpu")
    script = ss.generate_sbatch(_manifest(), alpine, cpu, "/scratch/x")
    assert "module load " + " ".join(alpine.module_loads) in script
    assert "namd/3.0.1_cpu" in script and "namd/3.0.1_gpu" not in script


def test_profile_sourced_before_errexit_and_no_nounset(alpine, gpu_resources):
    # Regression: Alpine's /etc/profile references unbound vars; `set -u` before the
    # source aborted a real job at "line 47: HISTCONTROL: unbound variable" before
    # NAMD ran.  Source must precede errexit, and -u must be gone.
    script = ss.generate_sbatch(_manifest(), alpine, gpu_resources, "/scratch/x")
    assert "set -euo pipefail" not in script          # no nounset
    assert "set -uo" not in script and "set -u\n" not in script
    assert "set -eo pipefail" in script
    assert script.index("source /etc/profile") < script.index("set -eo pipefail")


def test_cd_into_scratch(alpine, gpu_resources):
    script = ss.generate_sbatch(_manifest(), alpine, gpu_resources, "/scratch/alpine/jojo/nadoc_jobs/j1")
    assert "cd '/scratch/alpine/jojo/nadoc_jobs/j1'" in script


def test_job_name_override_is_sanitized(alpine, gpu_resources):
    script = ss.generate_sbatch(_manifest(), alpine, gpu_resources, "/scratch/x",
                                job_name="run for paper")
    assert "#SBATCH --job-name=run_for_paper" in script


# ── module/partition sanity warning ───────────────────────────────────────────

def test_gpu_with_cpu_module_warns(alpine, gpu_resources):
    # A GPU partition whose GPU module set is (mis)configured CPU-only must warn.
    cpu_gpu_profile = replace(alpine, gpu_module_loads=["gcc/14.2.0", "namd/3.0.1_cpu"])
    script = ss.generate_sbatch(_manifest(), cpu_gpu_profile, gpu_resources, "/scratch/x")
    assert "WARNING" in script and "CPU-only" in script


def test_gpu_with_gpu_module_does_not_warn(alpine, gpu_resources):
    # The default Alpine profile now ships a GPU-resident module for GPU partitions.
    script = ss.generate_sbatch(_manifest(), alpine, gpu_resources, "/scratch/x")
    assert "WARNING" not in script


# ── generate_sbatch: guards ───────────────────────────────────────────────────

def test_declash_manifest_is_rejected(alpine, gpu_resources):
    with pytest.raises(ValueError, match="[Dd]eclash"):
        ss.generate_sbatch(_manifest(declash=True), alpine, gpu_resources, "/scratch/x")


def test_unknown_partition_is_rejected(alpine, gpu_resources):
    bad = dict(gpu_resources, partition="nonexistent")
    with pytest.raises(ValueError, match="partition"):
        ss.generate_sbatch(_manifest(), alpine, bad, "/scratch/x")


def test_manifest_without_segments_is_rejected(alpine, gpu_resources):
    m = _manifest()
    m["segments"] = []
    with pytest.raises(ValueError, match="segments"):
        ss.generate_sbatch(m, alpine, gpu_resources, "/scratch/x")


def test_gpu_job_omits_infiniband_constraint(alpine, gpu_resources):
    # Single-node GPU-resident runs must NOT request --constraint=ib (over-constrains
    # aa100 node selection → "node configuration not available").
    script = ss.generate_sbatch(_manifest(), alpine, gpu_resources, "/scratch/x")
    assert "--constraint=ib" not in script


def test_cpu_job_keeps_infiniband_constraint(alpine):
    # CPU/MPI runs still want InfiniBand.
    res = cr.recommend(alpine, n_atoms=8_000_000, total_ns=2.0, measured_ns_per_day=50.0)
    assert res["kind"] == "cpu"
    script = ss.generate_sbatch(_manifest(), alpine, res, "/scratch/x")
    assert "#SBATCH --constraint=ib" in script


# ── in-sbatch relaxation early-stop ────────────────────────────────────────────

def _ladder_manifest(early_stop=None, min_k=None, declash=False, production=False):
    """A realistic mgh_slow_release ladder: 4 stages × (p10,p50,p100), k = 0.5,
    0.1, 0.01, None (MGHH). Mirrors md_protocols.mgh_slow_release_segments naming."""
    stem = "6hb_demo"
    ladder = [(1, "300K_NPT_ENM_k0p5", 0.5), (2, "300K_NPT_ENM_k0p1", 0.1),
              (3, "300K_NPT_ENM_k0p01", 0.01), (4, "300K_NPT_MGHH_only", None)]
    segs = []
    for stage_idx, label, scale in ladder:
        for pct in (10, 50, 100):
            segs.append({"name": f"{stem}_{stage_idx:02d}_{label}_p{pct}",
                         "steps": 100_000, "scale": scale})
    if production:
        segs.append({"name": f"{stem}_05_production_20ns_k0_p100", "steps": 500_000, "scale": None})
    m = {
        "name_stem": stem,
        "declash": declash,
        "relax_protocol_settings": {"timestep_fs": 2.0},
        "charge_audit": {"final_solvated": {"n_atoms": 100_000}},
        "minimization": {"name": f"{stem}_00_min_enm_k0p5"},
        "segments": segs,
    }
    if early_stop is not None:
        m["early_stop_relax"] = early_stop
    if min_k is not None:
        m["early_stop_min_k"] = min_k
    return m


def _gen(alpine, gpu_resources, m, **kw):
    return ss.generate_sbatch(m, alpine, gpu_resources, "/scratch/x", **kw)


def test_early_stop_off_is_byte_identical(alpine, gpu_resources):
    m_no_key = _ladder_manifest()                      # manifest lacks the key
    m_false = _ladder_manifest(early_stop=False)
    base = _gen(alpine, gpu_resources, m_no_key)
    assert _gen(alpine, gpu_resources, m_no_key, early_stop_relax=False) == base
    assert _gen(alpine, gpu_resources, m_false) == base
    # default (no key, no param) emits NOTHING early-stop related
    assert ss.EARLY_STOP_EVAL_NAME not in base
    assert "early-stop" not in base


def test_param_overrides_manifest_off(alpine, gpu_resources):
    m = _ladder_manifest(early_stop=True)
    off = _gen(alpine, gpu_resources, m, early_stop_relax=False)
    assert ss.EARLY_STOP_EVAL_NAME not in off


def test_early_stop_emits_for_nonfinal_restrained_chunks_only(alpine, gpu_resources):
    script = _gen(alpine, gpu_resources, _ladder_manifest(early_stop=True))
    # eligible: p10 and p50 of the k=0.5 and k=0.1 stages (non-final, k >= 0.1)
    for stage in ("300K_NPT_ENM_k0p5", "300K_NPT_ENM_k0p1"):
        for pct in (10, 50):
            assert f'--log "6hb_demo_0{ "1" if "k0p5" in stage else "2"}_{stage}_p{pct}.log"' in script
    # NOT the last chunk of a stage (p100 has nothing to bridge)
    assert '--log "6hb_demo_01_300K_NPT_ENM_k0p5_p100.log"' not in script
    assert '--log "6hb_demo_02_300K_NPT_ENM_k0p1_p100.log"' not in script
    # NOT the low-restraint k=0.01 stage (energy-alone unsafe below min_k)
    assert '--log "6hb_demo_03_300K_NPT_ENM_k0p01_p10.log"' not in script
    # NOT the MGHH / k=0 melt (scale None) — always run in full
    assert '--log "6hb_demo_04_300K_NPT_MGHH_only_p10.log"' not in script
    # NOT minimization
    assert '--log "6hb_demo_00_min_enm_k0p5.log"' not in script


def test_early_stop_bridge_targets_are_dot_safe(alpine, gpu_resources):
    script = _gen(alpine, gpu_resources, _ladder_manifest(early_stop=True))
    # the k=0.5 p10 block must bridge BOTH remaining chunks by FULL name (never a
    # glob) — plain + .restart. — so _p50/_p100 can't collide (ensemble-glob lesson).
    block = _extract_block(script, "6hb_demo_01_300K_NPT_ENM_k0p5_p10")
    assert '"6hb_demo_01_300K_NPT_ENM_k0p5_p50"' in block
    assert '"6hb_demo_01_300K_NPT_ENM_k0p5_p100"' in block
    assert 'cp "${__src}" "output/${__skip}.${__ext}"' in block
    assert 'cp "${__src}" "output/${__skip}.restart.${__ext}"' in block
    # the p50 block bridges ONLY p100 (p10 is already behind it)
    block50 = _extract_block(script, "6hb_demo_01_300K_NPT_ENM_k0p5_p50")
    assert '"6hb_demo_01_300K_NPT_ENM_k0p5_p100"' in block50
    assert '"6hb_demo_01_300K_NPT_ENM_k0p5_p10"' not in block50


def _extract_block(script, conf):
    """The early-stop block for `conf` = from its evaluator line to the next chunk's
    run guard (or end)."""
    lines = script.splitlines()
    start = next(i for i, ln in enumerate(lines) if f'--log "{conf}.log"' in ln)
    end = start + 1
    while end < len(lines) and not lines[end].startswith('if [ -f "output/6hb_demo'):
        # stop at the next chunk's run/skip guard (a top-level `if [ -f ...coor ]`)
        if lines[end].startswith('if [ -f "output/') and ".coor" in lines[end] and "then" in lines[end]:
            break
        end += 1
    return "\n".join(lines[start:end])


def test_early_stop_never_on_production_segments(alpine, gpu_resources):
    script = _gen(alpine, gpu_resources, _ladder_manifest(early_stop=True, production=True))
    assert '--log "6hb_demo_05_production_20ns_k0_p100.log"' not in script


def test_early_stop_min_k_widens_eligibility(alpine, gpu_resources):
    # min_k=0.01 makes the k=0.01 stage eligible too (its p10/p50 get blocks)
    script = _gen(alpine, gpu_resources, _ladder_manifest(early_stop=True, min_k=0.01))
    assert '--log "6hb_demo_03_300K_NPT_ENM_k0p01_p10.log"' in script
    # MGHH (scale None) still never eligible
    assert '--log "6hb_demo_04_300K_NPT_MGHH_only_p10.log"' not in script


def test_early_stop_invalid_tier_rejected(alpine, gpu_resources):
    m = _ladder_manifest(early_stop=True)
    m["early_stop_tier"] = "Z"
    with pytest.raises(ValueError, match="tier"):
        _gen(alpine, gpu_resources, m)


def _tier_a_manifest(**kw):
    m = _ladder_manifest(early_stop=True, **kw)
    m["early_stop_tier"] = "A"
    return m


def test_tier_a_emits_health_step_and_wc_gate(alpine, gpu_resources):
    script = _gen(alpine, gpu_resources, _tier_a_manifest())
    conf = "6hb_demo_01_300K_NPT_ENM_k0p5_p10"
    # WC health step produces output/<conf>.wc.json (best-effort, || true)
    assert f'{ss.EARLY_STOP_HEALTH_NAME} --seg "{conf}" --stem "6hb_demo" ' \
           f'--out "output/{conf}.wc.json" || true' in script
    # only bridge when BOTH the wc.json exists AND the cutoff eval (with --wc) says plateau
    assert f'if [ -f "output/{conf}.wc.json" ] && python3 {ss.EARLY_STOP_EVAL_NAME} ' \
           f'--log "{conf}.log" --wc "output/{conf}.wc.json"; then' in script


def test_tier_a_considers_low_k_and_mghh_chunks(alpine, gpu_resources):
    # Tier A's WC guard holds fragile stages, so (unlike B) k=0.01 AND the k=0/MGHH
    # melt's non-final chunks are eligible — the node evaluator holds them via WC.
    script = _gen(alpine, gpu_resources, _tier_a_manifest())
    for conf in ("6hb_demo_03_300K_NPT_ENM_k0p01_p10", "6hb_demo_04_300K_NPT_MGHH_only_p10"):
        assert f'--out "output/{conf}.wc.json"' in script
    # still NOT the last chunk of a stage, production, or minimization
    assert '--out "output/6hb_demo_04_300K_NPT_MGHH_only_p100.wc.json"' not in script
    assert "6hb_demo_00_min_enm_k0p5.wc.json" not in script


def test_tier_a_health_python_override(alpine, gpu_resources):
    m = _tier_a_manifest()
    m["early_stop_health_python"] = "/curc/sw/anaconda/bin/python"
    script = _gen(alpine, gpu_resources, m)
    assert f"/curc/sw/anaconda/bin/python {ss.EARLY_STOP_HEALTH_NAME}" in script


def test_tier_b_default_emits_no_health_step(alpine, gpu_resources):
    script = _gen(alpine, gpu_resources, _ladder_manifest(early_stop=True))   # tier B
    assert ss.EARLY_STOP_HEALTH_NAME not in script
    assert ".wc.json" not in script


def test_early_stop_declash_still_rejected(alpine, gpu_resources):
    # declash guard fires first — early-stop never reaches emission for a declash job
    with pytest.raises(ValueError, match="[Dd]eclash"):
        _gen(alpine, gpu_resources, _ladder_manifest(early_stop=True, declash=True))


def test_early_stop_run_guards_still_present(alpine, gpu_resources):
    # the per-conf skip guard that no-ops a bridged chunk must remain
    script = _gen(alpine, gpu_resources, _ladder_manifest(early_stop=True))
    assert 'if [ -f "output/6hb_demo_01_300K_NPT_ENM_k0p5_p50.coor" ]; then' in script


# ── preview_header: the wizard's manifest-free sbatch preview ─────────────────

def test_preview_header_needs_no_manifest(alpine):
    """generate_sbatch needs a prepared package; the wizard asks BEFORE one exists."""
    res = cr.recommend(alpine, n_atoms=62_673, total_ns=200.0, partition="ah200")
    h = ss.preview_header(alpine, res, job_name="nadoc_2hb")
    assert "#SBATCH --partition=ah200" in h["directives"]
    assert "#SBATCH --gres=gpu:h200:1" in h["directives"]
    assert "#SBATCH --job-name=nadoc_2hb" in h["directives"]
    assert h["gpu"] is True


def test_preview_header_matches_the_real_script(alpine):
    """The preview must not drift from what is actually submitted, so it calls the
    same builders — assert the directives are a subset of the real script."""
    res = cr.recommend(alpine, n_atoms=100_000, total_ns=4.0, partition="ah200")
    h = ss.preview_header(alpine, res, job_name="j")
    real = ss.generate_sbatch(_manifest(), alpine, res, "/scratch/x", job_name="j")
    for line in h["directives"]:
        assert line in real, line
    assert h["exec_line"].split()[0] in real          # same NAMD invocation form


def test_preview_header_cpu_adds_infiniband_and_mpirun(alpine):
    res = cr.recommend(alpine, n_atoms=100_000, total_ns=4.0, partition="acpu")
    h = ss.preview_header(alpine, res)
    assert h["gpu"] is False
    assert "#SBATCH --constraint=ib" in h["directives"]
    assert "mpirun" in h["exec_line"]
    assert not any("--gres" in d for d in h["directives"])


def test_preview_header_warns_when_walltime_is_capped(alpine):
    """A capped walltime is not a slower run — it cannot finish in one submission."""
    res = cr.recommend(alpine, n_atoms=62_673, total_ns=5000.0, partition="ami100")
    h = ss.preview_header(alpine, res)
    assert any("capped" in w and "Resume" in w for w in h["warnings"]), h["warnings"]


def test_preview_header_no_warning_when_walltime_fits(alpine):
    res = cr.recommend(alpine, n_atoms=62_673, total_ns=1.0, partition="ah200")
    h = ss.preview_header(alpine, res)
    assert not any("capped" in w for w in h["warnings"])


def test_preview_header_warns_on_a_cpu_module_for_a_gpu_partition(alpine):
    from dataclasses import replace as _replace
    bad = _replace(alpine, gpu_module_loads=["gcc/14.2.0", "namd/3.0.1_cpu"])
    res = cr.recommend(bad, n_atoms=62_673, total_ns=10.0, partition="ah200")
    h = ss.preview_header(bad, res)
    assert any("CPU-only" in w for w in h["warnings"])


def test_preview_header_text_is_readable_shell(alpine):
    res = cr.recommend(alpine, n_atoms=62_673, total_ns=10.0, partition="ah200")
    text = ss.preview_header(alpine, res)["text"]
    assert text.startswith("#!/bin/bash")
    assert "module load" in text
    assert "namd3" in text


# ── private NAMD build (Alpine has no CUDA NAMD module) ──────────────────────

def _with_private_namd(alpine, path="/projects/me/namd3-git/namd3"):
    from dataclasses import replace as _replace
    return _replace(alpine, gpu_namd_bin=path)


def test_private_binary_replaces_the_bare_command(alpine):
    prof = _with_private_namd(alpine)
    res = cr.recommend(prof, n_atoms=62_673, total_ns=10.0, partition="ah200")
    h = ss.preview_header(prof, res)
    assert h["exec_line"].startswith("/projects/me/namd3-git/namd3 ")
    assert "+devices" in h["exec_line"]


def test_private_binary_reaches_the_real_sbatch(alpine):
    prof = _with_private_namd(alpine)
    res = cr.recommend(prof, n_atoms=62_673, total_ns=10.0, partition="ah200")
    script = ss.generate_sbatch(_manifest(), prof, res, "/scratch/x", job_name="j")
    assert "/projects/me/namd3-git/namd3 +p" in script


def test_cpu_target_still_uses_the_module_binary(alpine):
    prof = _with_private_namd(alpine)          # gpu-only override
    res = cr.recommend(prof, n_atoms=100_000, total_ns=4.0, partition="acpu")
    h = ss.preview_header(prof, res)
    assert "mpirun -np $SLURM_NTASKS namd3" in h["exec_line"]


def test_no_cpu_module_warning_when_namd_comes_from_a_private_path(alpine):
    """Alpine's only NAMD modules are 2.14 and 3.0.1_cpu, so a GPU run legitimately
    loads a CPU-looking module set (just cuda/gcc) beside a private binary."""
    from dataclasses import replace as _replace
    prof = _replace(alpine, gpu_namd_bin="/projects/me/namd3", gpu_module_loads=["namd/3.0.1_cpu"])
    res = cr.recommend(prof, n_atoms=62_673, total_ns=10.0, partition="ah200")
    assert not any("CPU-only" in w for w in ss.preview_header(prof, res)["warnings"])


def test_namd_command_roundtrips_through_json(tmp_path):
    import json as _json
    from backend.core import cluster_config as _cc
    (tmp_path / "clusters.json").write_text(_json.dumps([{
        "name": "c", "host": "h", "project_base": "/p/$USER", "scratch_base": "/s/$USER",
        "default_partition": "g", "default_qos": "n", "gpu_namd_bin": "/opt/namd3",
    }]))
    prof = _cc.load_profiles(tmp_path)["c"]
    assert prof.namd_command(gpu=True) == "/opt/namd3"
    assert prof.namd_command(gpu=False) == "namd3"


def test_sbatch_runs_the_live_metrics_collector_in_background(alpine):
    """Without it a remote job reports nothing while it runs."""
    res = cr.recommend(alpine, n_atoms=62_673, total_ns=10.0, partition="ah200")
    script = ss.generate_sbatch(_manifest(), alpine, res, "/scratch/x", job_name="j")
    assert "nadoc_live_metrics.py . 30 >/dev/null 2>&1 &" in script
    assert "NADOC_METRICS_PID=$!" in script
    # However the job ends, the collector must not outlive it.
    assert "trap 'kill $NADOC_METRICS_PID" in script
    assert script.index("nadoc_live_metrics.py") < script.index("namd3")
