"""
run_hypothesis.py — Build and run a single-parameter hypothesis test for exp23.

Reads the hypothesis card from exp_cards/HXXX_*.md, applies the parameter change to
a copy of the baseline conf, runs NAMD, then calls metrics_extract.py and base_pairing.py.

Usage
-----
    python scripts/run_hypothesis.py H001 [--dry-run] [--steps N] [--threads T]

Steps default to the card's test_duration_ns × 500,000 (2 fs timestep).
Dry run prints the patched conf and exits.

Output
------
    results/hyp_runs/H001/H001.conf      — patched NAMD conf
    results/hyp_runs/H001/H001.log       — NAMD log
    results/hyp_runs/H001/H001.xst       — cell vectors
    results/hyp_runs/H001/H001.dcd       — trajectory
    metrics/H001_metrics.json            — extracted metrics (via metrics_extract.py)
    metrics/H001_bp.json + H001_bp.png   — base-pair integrity (via base_pairing.py)
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
_CARDS   = _EXP / "exp_cards"
_RUN_DIR = _EXP / "results" / "periodic_cell_run"
_METRICS = _EXP / "metrics"
_HYPRUNS = _EXP / "results" / "hyp_runs"

_TIMESTEP_FS = 2.0


def _find_namd3() -> str:
    for candidate in (
        "namd3",
        str(Path.home() / "Applications/NAMD_3.0.2/namd3"),
        str(Path.home() / "Applications/NAMD_3.0.2_Linux-x86_64-multicore-CUDA/namd3"),
    ):
        if shutil.which(candidate):
            return candidate
    raise RuntimeError("namd3 not found; add it to PATH or install in ~/Applications/")


def _find_card(hyp_id: str) -> Path:
    matches = list(_CARDS.glob(f"{hyp_id}_*.md"))
    if not matches:
        raise FileNotFoundError(f"No card found for {hyp_id} in {_CARDS}")
    return matches[0]


def _parse_card(card_path: Path) -> dict:
    """Extract YAML frontmatter fields from an exp card."""
    text = card_path.read_text()
    # Extract YAML block between first two ---
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not m:
        raise ValueError(f"No YAML frontmatter in {card_path}")
    raw = m.group(1)

    def _get(key: str) -> str | None:
        km = re.search(rf"^{key}:\s*(.+)$", raw, re.MULTILINE)
        return km.group(1).strip() if km else None

    baseline = _get("baseline_run") or "ramp_v2_03"
    duration_ns = float(_get("test_duration_ns") or 0.5)

    # parameter_change block
    param_key = param_from = param_to = None
    pc_m = re.search(r"parameter_change:\n((?:  .+\n)+)", raw)
    if pc_m:
        block = pc_m.group(1)
        km = re.search(r"key:\s*(.+)", block)
        fm = re.search(r"from:\s*(.+)", block)
        tm = re.search(r"to:\s*(.+)", block)
        if km: param_key = km.group(1).strip()
        if fm: param_from = fm.group(1).strip()
        if tm: param_to   = tm.group(1).strip()

    return dict(
        id=_get("id"),
        baseline=baseline,
        duration_ns=duration_ns,
        param_key=param_key,
        param_from=param_from,
        param_to=param_to,
    )


def _find_baseline_conf(baseline: str) -> Path:
    """Locate the .conf file for the baseline run name."""
    candidates = [
        _RUN_DIR / f"{baseline}.conf",
        _EXP / "results" / f"{baseline}.conf",
    ]
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError(
        f"Baseline conf '{baseline}.conf' not found in {_RUN_DIR} or results/")


def _find_baseline_restart(baseline: str) -> str:
    """Return the absolute restart .coor path for a baseline stage."""
    stem = f"B_tube_periodic_1x_{baseline}"
    coor = _RUN_DIR / "output" / f"{stem}.restart.coor"
    if coor.exists():
        return str(coor.resolve())
    # Fall back to whatever binCoordinates the baseline conf specifies
    conf = _find_baseline_conf(baseline)
    m = re.search(r"^binCoordinates\s+(.+)$", conf.read_text(), re.MULTILINE)
    if m:
        raw = m.group(1).strip()
        p = Path(raw)
        if not p.is_absolute():
            p = (_RUN_DIR / p).resolve()
        if p.exists():
            return str(p)
    raise FileNotFoundError(f"No restart .coor found for baseline '{baseline}'")


# ── Parameter patch functions ─────────────────────────────────────────────────

def _patch_conf_text(conf_text: str, card: dict, hyp_id: str, n_steps: int,
                     restart_coor: str) -> str:
    """Apply patches to the conf text for this hypothesis.

    Strategy:
      1. Strip all restart/run/restraint keys from the original entirely.
      2. Replace hypothesis-specific and output-name keys in-place.
      3. Append a clean restart + run block at the end (single occurrence).
    """
    restart_vel = restart_coor.replace(".coor", ".vel")
    restart_xsc = restart_coor.replace(".coor", ".xsc")
    out_stem = f"output/{hyp_id}"

    # Keys to replace in-place (preserving line position)
    inline: dict[str, str] = {
        "outputName": out_stem,
        "dcdFile":    f"{out_stem}.dcd",
        "xstFile":    f"{out_stem}.xst",
    }

    # Hypothesis-specific parameter change
    pk = (card["param_key"] or "").lower()
    pv = (card["param_to"] or "").strip()
    if "rigidbonds" in pk:
        inline["rigidBonds"] = pv
    if "fullelectfrequency" in pk or "fullElect" in (card["param_key"] or ""):
        inline["fullElectFrequency"] = pv
        if pv == "1":
            inline["stepspercycle"] = "20"
    if "langevindamping" in pk:
        inline["langevinDamping"] = pv
    if card["id"] == "H006":  # combined card
        inline["rigidBonds"] = "all"
        inline["langevinDamping"] = "1"

    # Keys to strip entirely (re-added cleanly in the block below)
    strip = {
        "run", "minimize", "reinitvels",
        "bincoordinates", "binvelocities", "extendedsystem",
        "constraintscaling", "constraints", "consref", "conskfile", "conskcol",
        "temperature",
    }

    out = []
    replaced: set[str] = set()
    for line in conf_text.splitlines():
        parts = line.lstrip().split()
        key = parts[0] if parts else ""
        low = key.lower()

        if low in strip:
            continue  # drop; appended cleanly below

        matched = False
        for ik, iv in inline.items():
            if low == ik.lower():
                out.append(f"{ik:<18} {iv}")
                replaced.add(ik.lower())
                matched = True
                break
        if not matched:
            out.append(line)

    # Add inline keys not present in the original file
    for ik, iv in inline.items():
        if ik.lower() not in replaced:
            out.append(f"{ik:<18} {iv}")

    # Clean restart + run block — always at the end, never duplicated
    out.append("")
    out.append(f"binCoordinates     {restart_coor}")
    out.append(f"binVelocities      {restart_vel}")
    out.append(f"extendedSystem     {restart_xsc}")
    out.append(f"run                {n_steps}    ;# {n_steps * _TIMESTEP_FS * 1e-6:.3f} ns")

    return "\n".join(out) + "\n"


def run_hypothesis(hyp_id: str, n_steps: int | None = None,
                   n_threads: int = 16, dry_run: bool = False) -> None:
    card_path = _find_card(hyp_id)
    card = _parse_card(card_path)

    steps = n_steps or int(card["duration_ns"] * 1e6 / _TIMESTEP_FS)

    baseline_conf = _find_baseline_conf(card["baseline"])
    restart_coor = _find_baseline_restart(card["baseline"])

    hyp_dir = _HYPRUNS / hyp_id
    hyp_dir.mkdir(parents=True, exist_ok=True)
    (hyp_dir / "output").mkdir(exist_ok=True)
    _METRICS.mkdir(parents=True, exist_ok=True)

    # Patch the conf
    conf_text = baseline_conf.read_text()
    patched = _patch_conf_text(conf_text, card, hyp_id, steps, restart_coor)

    out_conf = hyp_dir / f"{hyp_id}.conf"
    out_conf.write_text(patched)

    # Symlink forcefield and PSF/PDB into hyp_dir for NAMD to find
    for item in ("forcefield", "B_tube_periodic_1x.psf", "B_tube_periodic_1x.pdb",
                 "B_tube_periodic_1x_restraints.pdb"):
        src = _RUN_DIR / item
        dst = hyp_dir / item
        if src.exists() and not dst.exists():
            dst.symlink_to(src)

    if dry_run:
        print(f"=== DRY RUN: {hyp_id} ===")
        print(f"Baseline:  {baseline_conf}")
        print(f"Restart:   {restart_coor}")
        print(f"Steps:     {steps}  ({steps * _TIMESTEP_FS * 1e-6:.2f} ns)")
        print(f"Conf:      {out_conf}")
        print("\n--- Patched conf ---")
        print(patched[:3000])
        return

    # Run NAMD
    namd = _find_namd3()
    log_path = hyp_dir / f"{hyp_id}.log"
    print(f"Running {hyp_id}: {steps} steps ({steps * _TIMESTEP_FS * 1e-6:.2f} ns) "
          f"→ {log_path}")

    cmd = [namd, f"+p{n_threads}", "+devices", "0", out_conf.name]
    with open(log_path, "w") as log_fh:
        result = subprocess.run(cmd, cwd=hyp_dir, stdout=log_fh,
                                stderr=subprocess.STDOUT)

    print(f"NAMD exit code: {result.returncode}")

    # Extract metrics
    xst_path = hyp_dir / "output" / f"{hyp_id}.xst"
    metrics_out = _METRICS / f"{hyp_id}_metrics.json"
    metrics_cmd = [sys.executable, str(_SCRIPT / "metrics_extract.py"),
                   "--log", str(log_path),
                   "--id", hyp_id,
                   "--out", str(metrics_out),
                   "--print"]
    if xst_path.exists():
        metrics_cmd += ["--xst", str(xst_path)]
    subprocess.run(metrics_cmd, check=False)

    # Base-pair analysis
    dcd_path = hyp_dir / "output" / f"{hyp_id}.dcd"
    if dcd_path.exists():
        bp_out_json = _METRICS / f"{hyp_id}_bp.json"
        bp_out_png  = _METRICS / f"{hyp_id}_bp.png"
        subprocess.run(
            [sys.executable,
             str(_EXP / "base_pairing.py"),
             "--psf", str(_RUN_DIR / "B_tube_periodic_1x.psf"),
             "--pdb", str(_RUN_DIR / "B_tube_periodic_1x.pdb"),
             "--dcd", str(dcd_path),
             "--out", str(bp_out_png),
             "--json", str(bp_out_json)],
            check=False,
        )

    print(f"\nDone. Results in {hyp_dir} | Metrics in {metrics_out}")
    if result.returncode != 0:
        print("WARNING: NAMD exited non-zero — check the log for errors.", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description="Run a single hypothesis test for exp23.")
    ap.add_argument("hyp_id", help="Hypothesis ID, e.g. H001")
    ap.add_argument("--steps", type=int, default=None,
                    help="Override step count (default from card duration_ns)")
    ap.add_argument("--threads", type=int, default=16, help="NAMD +p threads (default 16)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print patched conf and exit without running NAMD")
    args = ap.parse_args()

    run_hypothesis(args.hyp_id, n_steps=args.steps,
                   n_threads=args.threads, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
