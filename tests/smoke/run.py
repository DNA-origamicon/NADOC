#!/usr/bin/env python3
"""
End-to-end pipeline smoke test.

Exercises every stage:
  NADOC design → pdb2gmx (CHARMM36) → solvation → ionisation
  → EM → NVT → NPT → 1 ns production
  → q extraction → covariance → param output → mrdna injection format

Exits 0 on success, 1 on any failure.
Diffs output against tests/smoke/reference_params.json to catch regressions.

Usage:
    python tests/smoke/run.py [--keep]   # --keep preserves the tmp run dir
    make smoketest
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from backend.core.models import Design
from backend.parameterization.crossover_extract import assign_sequences_to_design
from backend.parameterization.md_setup import setup_run_directory
from backend.parameterization.param_extract import extract_parameters
from backend.parameterization.convergence import check as conv_check
from tests.smoke.compare import params_match

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("smoketest")

_SMOKE_DIR   = Path(__file__).parent
_DESIGN_FILE = ROOT / "Examples" / "2hb_xover_val.nadoc"
_REFERENCE   = _SMOKE_DIR / "reference_params.json"

# Measurement region — same as production (local 0-based indices, helix bp_start=7)
# Crossovers at bp 14 and 34; central 20-bp measurement region local idx 8-26.
_SMOKE_BP_LO = 8
_SMOKE_BP_HI = 26

_PROD_NS = 1


def _load_design() -> Design:
    design = Design.model_validate_json(_DESIGN_FILE.read_text())
    return assign_sequences_to_design(design, seed=42)


def _run_simulation(run_dir: Path, design: Design) -> None:
    """Write PDB, set up GROMACS dir, and run EM→NVT→NPT→production."""
    from backend.core.gromacs_package import _build_gromacs_input_pdb
    import tempfile

    pdb_text = _build_gromacs_input_pdb(design, ff="charmm36-feb2026_cgenff-5.0")
    with tempfile.NamedTemporaryFile(suffix=".pdb", mode="w", delete=False) as f:
        f.write(pdb_text)
        tmp_pdb = Path(f.name)

    try:
        setup_run_directory(
            design=design,
            pdb_path=tmp_pdb,
            run_dir=run_dir,
            variant_label="smoke",
            restraint_k_kcal=1.0,
            prod_ns=_PROD_NS,
        )
    finally:
        tmp_pdb.unlink(missing_ok=True)

    log.info("Launching EM→NVT→NPT→production (1 ns)…")
    t0 = time.time()
    r = subprocess.run(
        ["bash", "run.sh"],
        cwd=run_dir,
        capture_output=False,   # stream to terminal so user can see progress
    )
    elapsed = time.time() - t0
    if r.returncode != 0:
        raise RuntimeError(f"run.sh exited {r.returncode} after {elapsed:.0f}s")
    log.info("Simulation finished in %.0f s (%.1f min)", elapsed, elapsed / 60)


def _extract(run_dir: Path) -> dict:
    """Extract parameters and return mrdna_params dict."""
    import json as _json

    restraint_k = _json.loads(
        (run_dir / "restraint_log.json").read_text()
    )["restraint_k_kcal_per_mol_per_A2"]

    params = extract_parameters(
        str(run_dir / "prod.tpr"),
        str(run_dir / "prod.xtc"),
        variant_label="smoke",
        restraint_k_kcal=restraint_k,
        bp_lo=_SMOKE_BP_LO,
        bp_hi=_SMOKE_BP_HI,
    )

    # Convergence is not expected to pass at 1 ns — that's fine for a smoke test.
    q_series = getattr(params, "_q_series", None)
    conv = conv_check(params, q_series=q_series)
    log.info("Convergence: passed=%s (not required for smoke test)", conv["passed"])

    result = params.to_dict()
    (run_dir / "smoke_params.json").write_text(json.dumps(result, indent=2))
    log.info("Wrote smoke_params.json")
    return result


def _update_reference(result: dict) -> None:
    _REFERENCE.write_text(json.dumps(result, indent=2))
    log.info("Updated reference_params.json — commit this file.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true",
                        help="Keep temporary run directory on success")
    parser.add_argument("--update-reference", action="store_true",
                        help="Overwrite reference_params.json with current output")
    args = parser.parse_args()

    log.info("=== NADOC pipeline smoke test ===")
    log.info("Design: %s", _DESIGN_FILE)

    run_dir = Path(tempfile.mkdtemp(prefix="nadoc_smoke_"))
    log.info("Run directory: %s", run_dir)

    try:
        # 1. Load design
        log.info("Stage 1: load design")
        design = _load_design()
        log.info("  %d helices, %d strands", len(design.helices), len(design.strands))

        # 2. Setup + run simulation
        log.info("Stage 2–6: GROMACS setup + simulation")
        _run_simulation(run_dir, design)

        # 3. Parameter extraction
        log.info("Stage 7–9: parameter extraction + covariance + mrdna format")
        result = _extract(run_dir)
        p = result["mrdna_params"]
        log.info(
            "  r0=%.2f Å  k_bond=%.4f  hj_angle=%.1f°  k_dihedral=%.4f",
            p["r0_ang"], p["k_bond_kJ_mol_ang2"],
            p["hj_equilibrium_angle_deg"], p["k_dihedral_kJ_mol_rad2"],
        )

        # 4. Reference comparison
        if args.update_reference:
            _update_reference(result)
            log.info("Reference updated — re-run without --update-reference to validate.")
            return 0

        if not _REFERENCE.exists():
            log.warning("No reference_params.json found — writing it now.")
            _update_reference(result)
            log.info("Run again to validate against reference.")
            return 0

        log.info("Stage 10: diff against reference_params.json")
        ok, report = params_match(result, json.loads(_REFERENCE.read_text()))
        if ok:
            log.info("  Reference check PASSED")
        else:
            log.error("  Reference check FAILED:\n%s", report)
            return 1

    except Exception as exc:
        log.error("Smoke test FAILED: %s", exc, exc_info=True)
        return 1
    finally:
        if not args.keep:
            shutil.rmtree(run_dir, ignore_errors=True)
        else:
            log.info("Run directory kept at %s", run_dir)

    log.info("=== Smoke test PASSED ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
