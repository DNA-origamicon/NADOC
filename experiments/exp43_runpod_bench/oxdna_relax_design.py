#!/usr/bin/env python3
"""Headless oxDNA relaxation of a workspace design -> declashed coords for NAMD seeding.

    python experiments/exp43_runpod_bench/oxdna_relax_design.py 24hb_2xT

Matches the 24hb_1xT relax params (mc=1000, md_relax=1e6 CUDA, equil=1e5 CUDA). The
terminal job's last_conf.dat feeds build_namd_seed (see backend/core/oxdna_seed.py /
prep_24hb_seeded.py). Runs to terminal; launch under setsid+nohup so it survives the shell.
"""
import sys, logging
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]; sys.path.insert(0, str(ROOT))
from backend.core.models import Design
from backend.api.headless_oxdna_build import run_relaxation
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("oxrelax")

stem = sys.argv[1]
WS = ROOT / "workspace"
design = Design.model_validate_json((WS / f"{stem}.nadoc").read_text())
log.info("relaxing %s (mc=1000, md_relax=1e6 CUDA, equil=1e5 CUDA)", stem)
job = run_relaxation(
    design, WS, timeout=7200.0,
    backend="CUDA", mc_steps=1000, md_relax_steps=1_000_000, equil_steps=100_000,
)
log.info("DONE: job=%s status=%s stages=%s", job.job_id, job.status,
         [s.name for s in job.stages])
(Path(__file__).parent / f"OXDNA_JOB_{stem}").write_text(job.job_id + "\n")
