"""
run_h007_pipeline.py — H007 full pipeline with rigidBonds all throughout.

Stages (all with rigidBonds all, separate output namespace):
  1. H007_npt      — 500 ps restrained isotropic NPT from raw PDB  (clean start)
  2. H007_relax    — 100 ps restrained locked-Z NVT
  3. H007_ramp_00  — 200 ps locked NVT, constraint k = 0.50 kcal/mol/Å²
  4. H007_ramp_01  — 200 ps locked NVT, constraint k = 0.25
  5. H007_ramp_02  — 200 ps locked NVT, constraint k = 0.10
  6. H007_ramp_03  — 200 ps locked NVT, constraint k = 0.03
  7. H007_prod     — 500 ps unrestrained locked-Z NVT (the test stage)

Usage
-----
    python scripts/run_h007_pipeline.py [--dry-run] [--threads T] [--from STAGE]

--from STAGE  skip earlier stages, assuming their output already exists
              (useful to resume after a partial run). STAGE = npt|relax|ramp_00|...|prod
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

_SCRIPT  = Path(__file__).parent
_EXP     = _SCRIPT.parent
_RUN_DIR = _EXP / "results" / "periodic_cell_run"
_METRICS = _EXP / "metrics"
_H007    = _EXP / "results" / "hyp_runs" / "H007"
_OUT     = _H007 / "output"
_TIMESTEP_FS = 2.0


def _find_namd3() -> str:
    for c in ("namd3",
              str(Path.home() / "Applications/NAMD_3.0.2/namd3"),
              str(Path.home() / "Applications/NAMD_3.0.2_Linux-x86_64-multicore-CUDA/namd3")):
        if shutil.which(c):
            return c
    raise RuntimeError("namd3 not found")


def _patch_conf(src: Path, replacements: dict[str, str]) -> str:
    """Apply key→value replacements to conf text.

    - Existing keys are replaced in-place.
    - New keys (not in original) are inserted just BEFORE the first `run` or
      `minimize` command so NAMD sees them at startup, not after run.
    """
    lines = src.read_text().splitlines()
    out = []
    replaced: set[str] = set()
    run_line_idx = None  # index in `out` of the first run/minimize

    for line in lines:
        parts = line.lstrip().split()
        key_low = parts[0].lower() if parts else ""

        if key_low in ("run", "minimize") and run_line_idx is None:
            run_line_idx = len(out)

        matched = False
        for rk, rv in replacements.items():
            if key_low == rk.lower():
                out.append(f"{rk:<18} {rv}")
                replaced.add(rk.lower())
                matched = True
                break
        if not matched:
            out.append(line)

    # Insert new keys (not found in original) just before run/minimize
    new_lines = [f"{rk:<18} {rv}"
                 for rk, rv in replacements.items()
                 if rk.lower() not in replaced]
    if new_lines:
        insert_at = run_line_idx if run_line_idx is not None else len(out)
        for i, nl in enumerate(new_lines):
            out.insert(insert_at + i, nl)

    return "\n".join(out) + "\n"


def _write_conf(text: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text)


def _run_stage(conf: Path, log: Path, namd: str, threads: int,
               dry_run: bool) -> int:
    if dry_run:
        print(f"  [DRY RUN] would run: {namd} +p{threads} {conf.name}")
        return 0
    print(f"  Running NAMD: {conf.name} → {log.name}")
    with open(log, "w") as fh:
        r = subprocess.run([namd, f"+p{threads}", "+devices", "0", conf.name],
                           cwd=conf.parent, stdout=fh, stderr=subprocess.STDOUT)
    print(f"  Exit code: {r.returncode}")
    return r.returncode


def _check_fatal(log: Path) -> list[str]:
    fatals = []
    sentinel = re.compile(r"-9{7,}")
    for line in log.read_text().splitlines():
        if "FATAL ERROR" in line or "Atoms moving too fast" in line:
            fatals.append(line.strip())
        elif sentinel.search(line):
            fatals.append("Sentinel: " + line.strip()[:80])
    return fatals


def build_confs(dry_run: bool = False) -> dict[str, Path]:
    """Build all H007 conf files and return a {stage: conf_path} dict."""
    _H007.mkdir(parents=True, exist_ok=True)
    _OUT.mkdir(exist_ok=True)

    # Symlink required files into H007 dir
    for item in ("forcefield", "B_tube_periodic_1x.psf", "B_tube_periodic_1x.pdb",
                 "B_tube_periodic_1x_restraints.pdb"):
        src = _RUN_DIR / item
        dst = _H007 / item
        if src.exists() and not dst.exists():
            dst.symlink_to(src)

    # ── Helper: out stem ──────────────────────────────────────────────────────
    def _stem(stage: str) -> str:
        return f"output/H007_{stage}"

    # ── COMMON replacements applied to all stages ─────────────────────────────
    rigidall = {"rigidBonds": "all   ;# CHARMM36 DNA requires all at 2 fs (SHAKE)"}

    # ── Stage 1: NPT equilibration from raw PDB ───────────────────────────────
    npt_repl = {
        **rigidall,
        "outputName":  _stem("npt"),
        "dcdFile":     f"{_stem('npt')}.dcd",
        "xstFile":     f"{_stem('npt')}.xst",
        "timestep":    "2.0        ;# 2 fs — CHARMM36 DNA with rigidBonds all",
    }
    npt_text = _patch_conf(_RUN_DIR / "namd.conf", npt_repl)
    npt_conf = _H007 / "H007_npt.conf"
    _write_conf(npt_text, npt_conf)

    # ── Stage 2: locked-Z relax (restrained, k=1.0) from raw PDB ────────────
    # Start from raw PDB at Z=70.14 Å (hardcoded cellBasisVectors in conf).
    # Do NOT load extendedSystem from NPT: the 500 ps H007 NPT compressed Z to
    # 68.18 Å (not yet equilibrated). Z=70.14 Å is the confirmed stable value
    # from the production_iso_npt 17.9 ns tail.
    relax_repl = {
        **rigidall,
        "outputName": _stem("relax"),
        "dcdFile":    f"{_stem('relax')}.dcd",
        "xstFile":    f"{_stem('relax')}.xst",
        "timestep":   "2.0        ;# 2 fs — CHARMM36 DNA with rigidBonds all",
    }
    relax_text = _patch_conf(_RUN_DIR / "relax_locked_nvt.conf", relax_repl)
    # Strip binCoordinates: let the `coordinates B_tube_periodic_1x.pdb` line
    # already in the conf supply atomic positions (PDB-format text read).
    relax_text = re.sub(r"^binCoordinates\s+.*$", "", relax_text, flags=re.MULTILINE)
    # temperature 310 + reinitvels 310 already in conf; keep them for velocity init.
    relax_conf = _H007 / "H007_relax.conf"
    _write_conf(relax_text, relax_conf)

    # ── Stages 3-6: ramp (k descends 0.50 → 0.25 → 0.10 → 0.03) ────────────
    # ramp_v2_XX.conf has binCoordinates + binVelocities before run and hardcoded
    # cellBasisVector3 = 70.140.  Do NOT carry extendedSystem between stages:
    # the cell is locked by the hardcoded cellBasisVectors throughout the ramp.
    ramp_scalings = [("00", "0.500"), ("01", "0.250"), ("02", "0.100"), ("03", "0.030")]
    prev_stem = "H007_relax"
    ramp_confs: dict[str, Path] = {}
    for tag, kscale in ramp_scalings:
        src_conf = _RUN_DIR / f"ramp_v2_{tag}.conf"
        repl = {
            **rigidall,
            "outputName":      _stem(f"ramp_{tag}"),
            "dcdFile":         f"{_stem(f'ramp_{tag}')}.dcd",
            "xstFile":         f"{_stem(f'ramp_{tag}')}.xst",
            "binCoordinates":  f"output/{prev_stem}.restart.coor",
            "binVelocities":   f"output/{prev_stem}.restart.vel",
            "constraintScaling": kscale,
            "timestep":        "2.0        ;# 2 fs — CHARMM36 DNA with rigidBonds all",
        }
        text = _patch_conf(src_conf, repl)
        conf_path = _H007 / f"H007_ramp_{tag}.conf"
        _write_conf(text, conf_path)
        ramp_confs[f"ramp_{tag}"] = conf_path
        prev_stem = f"H007_ramp_{tag}"

    # ── Stage 7: unrestrained production (locked-Z NVT, 500 ps) ─────────────
    # ramp_v2_03.conf has binCoordinates + binVelocities before run.
    # Turn off constraints and extend the run.
    prod_repl = {
        **rigidall,
        "outputName":      _stem("prod"),
        "dcdFile":         f"{_stem('prod')}.dcd",
        "xstFile":         f"{_stem('prod')}.xst",
        "binCoordinates":  "output/H007_ramp_03.restart.coor",
        "binVelocities":   "output/H007_ramp_03.restart.vel",
        "extendedSystem":  "output/H007_ramp_03.restart.xsc",
        "constraints":     "off",
        "constraintScaling": "0.0",
        "run":             "250000     ;# 500 ps unrestrained production",
        "timestep":        "2.0        ;# 2 fs — CHARMM36 DNA with rigidBonds all",
    }
    prod_text = _patch_conf(_RUN_DIR / "ramp_v2_03.conf", prod_repl)
    prod_conf = _H007 / "H007_prod.conf"
    _write_conf(prod_text, prod_conf)

    return {
        "npt":      npt_conf,
        "relax":    relax_conf,
        **ramp_confs,
        "prod":     prod_conf,
    }


def run_pipeline(threads: int = 16, dry_run: bool = False,
                 start_from: str = "npt") -> None:
    namd = _find_namd3()
    _METRICS.mkdir(parents=True, exist_ok=True)

    confs = build_confs(dry_run=dry_run)
    stages = ["npt", "relax", "ramp_00", "ramp_01", "ramp_02", "ramp_03", "prod"]

    skip_stages = set()
    if start_from in stages:
        skip_stages = set(stages[:stages.index(start_from)])
    else:
        print(f"WARNING: unknown --from stage '{start_from}', running all stages")

    for stage in stages:
        conf = confs[stage]
        log  = _H007 / f"H007_{stage}.log"

        if stage in skip_stages:
            print(f"Skipping stage '{stage}' (--from {start_from})")
            continue

        print(f"\n{'='*60}")
        print(f"Stage: {stage}")
        print(f"{'='*60}")

        rc = _run_stage(conf, log, namd, threads, dry_run)
        if dry_run:
            continue

        if not log.exists():
            print(f"ERROR: log not created for stage {stage}", file=sys.stderr)
            sys.exit(1)

        fatals = _check_fatal(log)
        if fatals:
            print(f"\nFATAL ERRORS in stage {stage}:", file=sys.stderr)
            for e in fatals:
                print(f"  {e}", file=sys.stderr)
            sys.exit(2)

        if rc != 0 and stage not in ("npt",):
            print(f"WARNING: NAMD exited {rc} in stage {stage}", file=sys.stderr)

    if dry_run:
        print("\nDry run complete. Conf files written to:", _H007)
        return

    # ── Post-processing ───────────────────────────────────────────────────────
    log_path  = _H007 / "H007_prod.log"
    dcd_path  = _OUT  / "H007_prod.dcd"
    xst_path  = _OUT  / "H007_prod.xst"
    bp_json   = _METRICS / "H007_bp.json"
    bp_png    = _METRICS / "H007_bp.png"
    met_json  = _METRICS / "H007_metrics.json"

    print("\n=== Extracting metrics ===")
    subprocess.run(
        [sys.executable, str(_SCRIPT / "metrics_extract.py"),
         "--log", str(log_path), "--xst", str(xst_path),
         "--id", "H007", "--out", str(met_json), "--print"],
        check=False,
    )

    if dcd_path.exists():
        psf = _RUN_DIR / "B_tube_periodic_1x.psf"
        pdb = _RUN_DIR / "B_tube_periodic_1x.pdb"
        print("\n=== Base pair analysis ===")
        subprocess.run(
            [sys.executable, str(_EXP / "base_pairing.py"),
             "--psf", str(psf), "--pdb", str(pdb),
             "--dcd", str(dcd_path),
             "--out", str(bp_png), "--json", str(bp_json)],
            check=False,
        )

    print(f"\nH007 complete. Results in {_H007}")
    print(f"Metrics: {met_json}")
    print(f"BP:      {bp_json}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--dry-run", action="store_true",
                    help="Write conf files and print commands, do not run NAMD")
    ap.add_argument("--threads", type=int, default=16, help="NAMD +p threads")
    ap.add_argument("--from", dest="start_from", default="npt",
                    help="Start from this stage (npt|relax|ramp_00|ramp_01|ramp_02|ramp_03|prod)")
    args = ap.parse_args()
    run_pipeline(threads=args.threads, dry_run=args.dry_run,
                 start_from=args.start_from)


if __name__ == "__main__":
    main()
