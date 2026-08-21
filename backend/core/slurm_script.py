"""Generate an Alpine (SLURM) sbatch script for a prepared NADOC MD job.

The other *offline* half of Phase 2 (see
``memory/project_alpine_cluster_submission.md``).  A NADOC MD package already
contains every NAMD input on disk: one minimization ``.conf`` plus one ``.conf``
per relaxation segment (each referencing the previous segment's restart coords by
relative path).  So the remote job is a single ``sbatch`` that ``cd``s into the
uploaded package on scratch and runs those confs **in order**, redirecting each to
its ``.log`` — exactly what the local runner does, minus the between-segment
Python health/reconcile bookkeeping (which is advisory-only and recomputed locally
after fetch — see the plan's decision #1).

Pure and offline: builds a string from a parsed manifest + a ClusterProfile + a
resource dict (from ``cluster_resources.recommend``).  No file IO, no network.
"""

from __future__ import annotations

import re

from backend.core.cluster_config import ClusterProfile

# A declash design needs a mid-chain Python step (``rebuild_declashed_references``)
# between minimization and the segments — that cannot run inside a plain sbatch on
# a node without NADOC.  Remote submission of declash jobs is therefore rejected
# here; Phase 3 can stage the rebuilt package locally before upload if needed.
_DECLASH_UNSUPPORTED_MSG = (
    "Declash jobs require a mid-chain reference rebuild that cannot run in a bare "
    "sbatch; run this design locally, or stage the declashed package before remote "
    "submission (not yet supported)."
)

# Filename of the node-side early-stop evaluator, staged into the package by the
# executor and invoked by the sbatch at each non-final relaxation chunk.
EARLY_STOP_EVAL_NAME = "nadoc_cutoff_eval.py"

# Node-side live-metrics collector: parses the NAMD log ON the node every 30 s and
# writes output/live_metrics.json, so NADOC can `cat` a ~200-byte file instead of
# pulling a growing multi-hundred-KB log on every poll.
LIVE_METRICS_NAME = "nadoc_live_metrics.py"
LIVE_METRICS_FILE = "output/live_metrics.json"
LIVE_METRICS_INTERVAL_S = 30
LIVE_HEALTH_NAME = "nadoc_live_health.py"
LIVE_HEALTH_FILE = "output/live_health.json"
LIVE_HEALTH_INTERVAL_S = 300
SETTLE_RETARGET_NAME = "nadoc_settle_retarget.py"

# RunPod's node WC health step + the verbatim md_health copy it imports. Alpine uses
# the portable pair-plan evaluator below because its bare Python has no MDAnalysis.
EARLY_STOP_HEALTH_NAME = "nadoc_health_eval.py"
STAGED_MD_HEALTH_NAME = "md_health.py"
# Alpine-specific portable WC path.  Its pair plan is built locally before upload,
# so both files run under the cluster's dependency-free Python 3.6.
ALPINE_WC_EVAL_NAME = "nadoc_wc_eval.py"
ALPINE_WC_PLAN_NAME = "nadoc_wc_plan.json"


def _stage_base(segment_name: str) -> str:
    """Stage identity = conf base-name minus the ``_pNN`` chunk suffix.

    Mirrors ``namd_runner._stage_base`` (the local early-stop path) — kept here so
    this pure/offline module doesn't import the heavy async runner.  The regex MUST
    stay identical to the runner's or the sbatch and the local runner would group
    chunks differently.
    """
    return re.sub(r"_p\d+$", "", segment_name)


def _is_production_segment(segment_name: str) -> bool:
    """Production / qualification stages are sampling, not relaxation — never skip.

    Mirrors ``namd_runner._is_production_segment``.
    """
    return bool(re.search(r"production|qualification", segment_name, re.I))


def _stage_last_chunk_index(chain: list[str], idx: int) -> int:
    """Index (in ``chain``) of the last chunk sharing ``chain[idx]``'s stage.

    Chunks of a stage are contiguous in the chain.  Mirrors
    ``namd_runner._stage_last_chunk_idx`` but keyed on the chain of conf names.
    """
    base = _stage_base(chain[idx])
    last = idx
    for j in range(idx + 1, len(chain)):
        if _stage_base(chain[j]) == base:
            last = j
        else:
            break
    return last


def _early_stop_eligible(chain, idx) -> bool:
    """True if ``chain[idx]`` is a NON-FINAL relaxation chunk whose stage may be
    skipped (the emitter decides eligibility; the node evaluator decides whether the
    plateau actually happened).

    No restraint-scale restriction: the node always tests energy AND WC together
    (``should_early_stop_stage``, same as the local path), and the WC criterion is
    what holds fragile/low-k stages directly — so every non-final relaxation chunk
    is eligible, including k=0.01 and the k=0/MGHH melt."""
    if idx == 0:
        return False  # minimization
    if _is_production_segment(chain[idx]):
        return False  # sampling, never skip
    if idx >= _stage_last_chunk_index(chain, idx):
        return False  # last chunk: nothing to bridge
    return True


def _bridge_lines(conf: str, remaining: list[str], indent: str) -> list[str]:
    """The copy-forward bridge.  Copies ``conf``'s final
    ``{coor,vel,xsc}`` onto every ``remaining`` chunk's expected names — plain
    ``<name>.<ext>`` (what the next stage reads + the skip guard checks) AND
    ``.restart.<ext>`` — exactly like ``namd_runner._alias_skipped_stage_outputs``.
    Names are listed explicitly (never globbed) with the full ``_pNN`` suffix, so
    ``_p50``/``_p100`` can't collide the way a ``output/<stem>_p10.*`` glob would
    sweep ``_p100`` files (the ensemble revert-glob lesson)."""
    skip_list = " ".join(f'"{s}"' for s in remaining)
    i = indent
    return [
        f'{i}echo "[NADOC] early-stop: {conf} plateaued — bridging {len(remaining)} chunk(s)"',
        f"{i}for __skip in {skip_list}; do",
        f"{i}  for __ext in coor vel xsc; do",
        f'{i}    if [ -f "output/{conf}.${{__ext}}" ]; then __src="output/{conf}.${{__ext}}";',
        f'{i}    elif [ -f "output/{conf}.restart.${{__ext}}" ]; then __src="output/{conf}.restart.${{__ext}}";',
        f'{i}    else __src=""; fi',
        f'{i}    if [ -n "${{__src}}" ]; then',
        f'{i}      cp "${{__src}}" "output/${{__skip}}.${{__ext}}"',
        f'{i}      cp "${{__src}}" "output/${{__skip}}.restart.${{__ext}}"',
        f"{i}    fi",
        f"{i}  done",
        f"{i}done",
    ]


def _early_stop_block(
    conf,
    remaining,
    *,
    name_stem,
    health_python,
    portable_wc=False,
) -> list[str]:
    """Emit the node-side evaluate-then-bridge block for one non-final chunk.

    Matches the local runner exactly: first compute the WC series (best-effort —
    ``|| true``) into ``output/<conf>.wc.json``, then only
    bridge if the cutoff evaluator says BOTH energy AND WC plateaued.  A
    missing/failed health step leaves no ``wc.json`` so the
    ``[ -f wc.json ] && …`` gate falls through to HOLD — this never skips on
    energy alone.
    """
    # The sbatch redirects each conf's stdout to ``<conf>.log`` in the run cwd (see
    # _exec_line), while coords/DCD land in ``output/`` (the confs write there).
    wc = f"output/{conf}.wc.json"
    if portable_wc:
        health_line = (
            f'    python3 {ALPINE_WC_EVAL_NAME} '
            f'--dcd "output/{conf}.dcd" --plan "{ALPINE_WC_PLAN_NAME}" '
            f'--out "{wc}" || true'
        )
    else:
        # RunPod has a proven modern Python environment and continues to use the
        # canonical full-health wrapper. Alpine selects the portable branch above.
        health_line = (
            f'    {health_python} {EARLY_STOP_HEALTH_NAME} --seg "{conf}" '
            f'--stem "{name_stem}" --out "{wc}" || true'
        )
    lines = [
        f'if [ -f "{conf}.log" ] && [ -f "output/{conf}.coor" ]; then',
        f'  if [ -f "output/{conf}.dcd" ]; then',
        health_line,
        "  fi",
        f'  if [ -f "{wc}" ] && python3 {EARLY_STOP_EVAL_NAME} '
        f'--log "{conf}.log" --wc "{wc}"; then',
    ]
    lines += _bridge_lines(conf, remaining, "    ")
    lines += ["  fi", "fi"]
    return lines


def sanitize_job_name(raw: str) -> str:
    """SLURM-safe job name: keep [A-Za-z0-9._-], collapse the rest to '_'.

    Raises ValueError on an empty / all-illegal name.
    """
    if raw is None:
        raise ValueError("job name must be non-empty")
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(raw)).strip("_")
    if not cleaned:
        raise ValueError(f"job name {raw!r} has no usable characters")
    return cleaned


def is_gpu_target(profile: ClusterProfile, resources: dict) -> bool:
    """True when the run uses the GPU-resident exec path.

    Single source of truth for the GPU/CPU branch: the sbatch exec line, the GRES
    directives, AND the conf amendment (whether staged confs keep ``GPUresident``)
    must all agree, or a CPU run inherits a ``GPUresident on`` conf and FATALs at the
    first fast segment.  Raises ValueError for an unknown partition.
    """
    part = profile.partition(resources["partition"])
    if part is None:
        raise ValueError(
            f"partition {resources['partition']!r} is not in profile {profile.name!r}"
        )
    return part.kind == "gpu"


def preview_header(
    profile: ClusterProfile, resources: dict, *, job_name: str = "nadoc_job"
) -> dict:
    """The sbatch header a job WOULD get, without needing a prepared package.

    ``generate_sbatch`` needs a manifest (the real segment chain), which only exists
    after solvation — far too late for the Job Wizard, where the user is still
    deciding whether to run on Alpine at all.  This renders the parts that depend
    only on the resolved *resources*: the ``#SBATCH`` block, the module loads and the
    NAMD invocation.

    It deliberately calls the SAME builders as the real script
    (``_sbatch_directives`` / ``_module_block`` / ``_exec_line``) rather than
    re-describing them, so the preview cannot drift from what actually gets submitted
    — the same reason ``/md/protocol-plan`` calls the real conf writers.

    Returns the pieces separately (so the UI can label them) plus a ready-to-read
    ``text`` rendering, and the two warnings that are worth seeing before submitting.
    """
    gpu = is_gpu_target(profile, resources)
    directives = list(_sbatch_directives(job_name, resources, gpu))
    if not gpu:
        directives.append("#SBATCH --constraint=ib")  # InfiniBand (OpenMPI)
    modules = list(profile.modules_for(gpu))
    exec_line = _exec_line(
        "<stage>", "output/<stage>.log", resources, gpu, profile.namd_command(gpu)
    )

    warnings: list[str] = []
    # Only meaningful when NAMD comes FROM a module.  A private binary is addressed by
    # absolute path, so a CPU-looking module set beside it (cuda/gcc, or even
    # namd/3.0.1_cpu left in place) says nothing about the exec path.
    if gpu and profile.namd_command(gpu) == "namd3" and _looks_cpu_only(modules):
        warnings.append(
            "This GPU partition is paired with a NAMD module that looks CPU-only "
            "(namd/*_cpu). The +devices exec line will FATAL. Confirm the GPU module "
            "and set gpu_module_loads in workspace/clusters.json before submitting."
        )
    # A clamped walltime is not a slower run — it is a run that CANNOT finish in one
    # submission and will need resume-from-checkpoint.  Saying so here is the whole
    # point of letting the user inspect this before committing.
    qos = profile.qos(resources.get("qos", ""))
    if qos is not None and float(resources.get("walltime_h", 0)) >= qos.max_walltime_h:
        warnings.append(
            f"Walltime is capped at the {qos.name} ceiling ({qos.max_walltime_h} h). "
            "The run will time out mid-ladder and need a Resume from its checkpoint."
        )

    text = "\n".join(
        [
            "#!/bin/bash",
            *directives,
            "",
            "source /etc/profile",
            "set -eo pipefail",
            "export SLURM_EXPORT_ENV=ALL",
            "",
            *_module_block(profile, gpu),
            "",
            "cd '<remote scratch dir>'",
            "mkdir -p output",
            "",
            "# for each stage in the ladder:",
            exec_line,
        ]
    )
    return {
        "directives": directives,
        "modules": modules,
        "exec_line": exec_line,
        "gpu": gpu,
        "warnings": warnings,
        "text": text,
    }


def _segment_chain(manifest: dict) -> list[str]:
    """Ordered conf base-names to run: minimization first, then every segment."""
    min_name = (manifest.get("minimization") or {}).get("name")
    if not min_name:
        raise ValueError("manifest has no minimization.name")
    chain = [min_name]
    for seg in manifest.get("segments", []):
        name = seg.get("name")
        if not name:
            raise ValueError("manifest segment missing a name")
        chain.append(name)
    if len(chain) == 1:
        raise ValueError("manifest has no segments to run")
    return chain


def _sbatch_directives(job_name: str, resources: dict, gpu: bool) -> list[str]:
    lines = [
        f"#SBATCH --job-name={job_name}",
        f"#SBATCH --output={job_name}_%j.out",
        f"#SBATCH --error={job_name}_%j.err",
        f"#SBATCH --partition={resources['partition']}",
        "#SBATCH --nodes=1",
        f"#SBATCH --ntasks={resources['cores']}",
        f"#SBATCH --time={resources['walltime']}",
        f"#SBATCH --mem={resources['mem_gb']}GB",
        f"#SBATCH --qos={resources['qos']}",
    ]
    if gpu:
        n_gpus = resources.get("gpus", 1)
        # aa100 requires a TYPED GRES (gpu:a100-40gb:N); a bare gpu:N is rejected.
        gres_type = resources.get("gres_type") or ""
        gres = f"gpu:{gres_type}:{n_gpus}" if gres_type else f"gpu:{n_gpus}"
        lines.append(f"#SBATCH --gres={gres}")
    return lines


def _module_block(profile: ClusterProfile, gpu: bool) -> list[str]:
    lines = ["module purge"]
    mods = profile.modules_for(gpu)
    if mods:
        lines.append("module load " + " ".join(mods))
    return lines


def _looks_cpu_only(modules: list[str]) -> bool:
    """True if a NAMD module in the set looks CPU-only (``namd/..._cpu``)."""
    return any(
        "namd" in m.lower() and (m.lower().endswith("_cpu") or "_cpu" in m.lower())
        for m in modules
    )


def _exec_line(
    conf: str, log: str, resources: dict, gpu: bool, namd: str = "namd3"
) -> str:
    """The NAMD invocation for one conf.

    GPU: NAMD3 GPU-resident, ``+p<cores> +setcpuaffinity +devices 0[,1,...]``.
    CPU: OpenMPI build, ``mpirun -np $SLURM_NTASKS namd3``.

    ``namd`` is the executable — a bare name resolved from a module's PATH, or the
    absolute path of a privately-built binary (Alpine has no CUDA NAMD module).
    """
    if gpu:
        cores = resources.get("cores", 1)
        gpus = resources.get("gpus", 1)
        devices = ",".join(str(i) for i in range(max(1, gpus)))
        return f"{namd} +p{cores} +setcpuaffinity +devices {devices} {conf}.conf > {log} 2>&1"
    return f"mpirun -np $SLURM_NTASKS {namd} {conf}.conf > {log} 2>&1"


def generate_sbatch(
    manifest: dict,
    profile: ClusterProfile,
    resources: dict,
    remote_scratch_dir: str,
    *,
    job_name: str | None = None,
    resume_conf_for: dict[str, str] | None = None,
    early_stop_relax: bool | None = None,
) -> str:
    """Build the sbatch script string for a prepared job.

    Args:
        manifest: the parsed ``manifest.json`` (minimization + segments + name_stem).
        profile:  the target cluster (module loads; partition kind → GPU vs CPU).
        resources: a ``cluster_resources.recommend`` dict.
        remote_scratch_dir: absolute scratch path the package was mirrored to.
        job_name: overrides the sanitized ``name_stem``.
        resume_conf_for: optional ``{segment_name: resume_conf_base}`` — for a
            mid-segment resume, run the resume conf (which reads the segment's restart
            checkpoint) instead of the fresh conf.  The skip guard still keys on the
            segment's final ``output/<name>.coor`` and the resume run logs to
            ``<name>.resume.log`` (so the partial ``<name>.log`` is preserved).
        early_stop_relax: opt-in in-sbatch relaxation early-stop (the cluster analogue
            of the local ``early_stop_relax`` accelerator).  ``None`` (default) reads
            ``manifest['early_stop_relax']`` — absent -> OFF -> the script is
            byte-identical to before.  When on, every non-final relaxation chunk gets
            an evaluate-then-bridge block (see ``_early_stop_block``) so a plateaued
            stage self-truncates on the node with no Python runner in the loop — the
            SAME energy-AND-WC test the local runner applies, no restraint-scale
            shortcut and no degraded energy-only mode.  A declash manifest is
            rejected before this matters; production-only packages carry no eligible
            chunks (no-op).

    Raises ValueError for a declash manifest, an empty segment chain, or an
    unknown partition.
    """
    resume_conf_for = resume_conf_for or {}
    if manifest.get("declash"):
        raise ValueError(_DECLASH_UNSUPPORTED_MSG)

    if early_stop_relax is None:
        early_stop_relax = bool(manifest.get("early_stop_relax"))
    # Alpine's WC evaluator is stdlib-only. The pair topology/reference distances
    # were computed locally and staged as ALPINE_WC_PLAN_NAME before this script runs.
    health_python = "python3"

    name_stem = manifest.get("name_stem") or "nadoc_md"
    job_name = sanitize_job_name(job_name if job_name is not None else name_stem)

    gpu = is_gpu_target(profile, resources)

    chain = _segment_chain(manifest)

    lines: list[str] = ["#!/bin/bash"]
    lines += _sbatch_directives(job_name, resources, gpu)
    # InfiniBand only matters for multi-node CPU/MPI jobs; a single-node GPU-resident
    # run doesn't need it, and over-constraining node selection can make aa100 report
    # "node configuration not available".
    if not gpu:
        lines.append("#SBATCH --constraint=ib")  # InfiniBand (OpenMPI)
    lines.append("")
    # A GPU run needs a GPU-resident NAMD module; if the resolved GPU module set
    # still looks CPU-only, the `+devices` exec line will FATAL — warn loudly rather
    # than pair a GPU exec line with a CPU build.
    if gpu and _looks_cpu_only(profile.modules_for(gpu)):
        lines.append(
            "# WARNING: GPU partition selected but the NAMD module looks CPU-only "
            "(namd/*_cpu). Confirm the GPU module via GET /api/cluster/namd-modules "
            "and set gpu_module_loads in workspace/clusters.json before submitting."
        )
        lines.append("")
    lines += [
        # Source the login profile BEFORE enabling errexit — Alpine's /etc/profile
        # references unbound vars (e.g. HISTCONTROL, line 47) that abort the job
        # under `set -u` before NAMD ever runs (live-confirmed 2026-07-03: a job
        # died with only "/etc/profile: line 47: HISTCONTROL: unbound variable").
        # We keep errexit + pipefail to catch real NAMD/module failures, but drop
        # `-u`: HPC profile/module scripts routinely reference unbound variables.
        "source /etc/profile",
        "set -eo pipefail",
        "export SLURM_EXPORT_ENV=ALL",  # required for OpenMPI
        "",
        f"cd '{remote_scratch_dir}'",
        # A freshly-staged package has no output/ (local run artifacts are excluded
        # from the upload); each conf writes to output/<name>.* so it must exist.
        "mkdir -p output",
        # These files describe the previous allocation, not durable simulation
        # checkpoints. Remove them before the new trap/collector can expose stale
        # failure or progress state to the UI.
        "rm -f output/nadoc_failure.log output/settle-restraint-retarget.log output/live_metrics.json output/live_health.json",
        "",
        # Install failure capture before module loading / NAMD startup. The scratch
        # output directory now exists, so even an environment failure leaves evidence.
        "NADOC_METRICS_PID=''",
        "NADOC_CURRENT_STAGE=''",
        "NADOC_CURRENT_LOG=''",
        "nadoc_on_exit() {",
        "  rc=$?",
        "  kill $NADOC_METRICS_PID 2>/dev/null || true",
        "  if [ $rc -ne 0 ]; then",
        "    {",
        '      echo "ERROR: NADOC remote stage failed (exit code $rc)"',
        '      echo "stage=${NADOC_CURRENT_STAGE:-unknown}"',
        '      echo "host=$(hostname)"',
        '      echo "slurm_job_id=${SLURM_JOB_ID:-unknown}"',
        '      echo "log=${NADOC_CURRENT_LOG:-unknown}"',
        '      if [ -n "$NADOC_CURRENT_LOG" ] && [ -f "$NADOC_CURRENT_LOG" ]; then',
        '        echo "--- last 240 log lines ---"',
        '        tail -n 240 "$NADOC_CURRENT_LOG"',
        "      fi",
        "    } > output/nadoc_failure.log 2>&1",
        "  fi",
        "  return $rc",
        "}",
        "trap nadoc_on_exit EXIT",
        "",
        *_module_block(profile, gpu),
        "",
        # Background live-metrics collector. Losing it must never fail the run; the
        # combined EXIT trap stops it and preserves diagnostics however the job ends.
        f"python3 {LIVE_METRICS_NAME} . {LIVE_METRICS_INTERVAL_S} >/dev/null 2>&1 &",
        "NADOC_METRICS_PID=$!",
        "",
        "# NADOC MD ladder: minimization, then each relaxation segment in order.",
        "# Each conf reads the previous segment's restart coords by relative path.",
        "# Each step is skipped if its final output/<conf>.coor already exists, so a",
        "# resubmit onto the same scratch resumes at the first unfinished step (the",
        "# interrupted one re-runs in full from the previous step's coords). This is",
        "# what makes auto-resubmit-on-TIMEOUT a slowdown, not a lost run.",
    ]
    for i, conf in enumerate(chain):
        resume_conf = resume_conf_for.get(conf)
        run_conf = resume_conf or conf
        log = f"{conf}.resume.log" if resume_conf else f"{conf}.log"
        verb = "resuming from checkpoint" if resume_conf else "running"
        lines.append(f'if [ -f "output/{conf}.coor" ]; then')
        lines.append(f'  echo "[NADOC] skip {conf} (already complete)"')
        lines.append("else")
        lines.append(f'  echo "[NADOC] {verb} {conf}"')
        lines.append(f"  NADOC_CURRENT_STAGE='{conf}'")
        lines.append(f"  NADOC_CURRENT_LOG='{log}'")
        lines.append(
            "  " + _exec_line(run_conf, log, resources, gpu, profile.namd_command(gpu))
        )
        lines.append("fi")
        # Local and RunPod retarget the restrained settle reference to the completed
        # minimization coordinates. Alpine must do the identical stdlib rewrite before
        # its first dynamics stage; the file guard keeps production-only packages inert.
        if i == 0:
            lines += [
                'if [ -f "restraints_settle.pdb" ] && '
                f'[ -f "output/{conf}.coor" ]; then',
                "  NADOC_CURRENT_STAGE='settle-restraint-retarget'",
                "  NADOC_CURRENT_LOG='output/settle-restraint-retarget.log'",
                f'  python3 {SETTLE_RETARGET_NAME} "output/{conf}.coor" '
                '"restraints_settle.pdb" > "$NADOC_CURRENT_LOG" 2>&1',
                "fi",
            ]
        # In-sbatch early-stop: after a non-final relaxation chunk, let the node
        # evaluate the plateau and bridge the stage's remaining chunks.
        if early_stop_relax and _early_stop_eligible(chain, i):
            last = _stage_last_chunk_index(chain, i)
            lines += _early_stop_block(
                conf,
                chain[i + 1 : last + 1],
                name_stem=name_stem,
                health_python=health_python,
                portable_wc=True,
            )
    lines.append("")
    lines.append('echo "[NADOC] ladder complete"')
    return "\n".join(lines) + "\n"
