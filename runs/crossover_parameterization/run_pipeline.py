#!/usr/bin/env python3
"""
End-to-end driver for crossover CG parameterization.

Usage
-----
Minimal test run (T=0, 10 ns production, skips restraint sweep):
    python run_pipeline.py --variants T0 --prod-ns 10 --no-sweep

Full first-batch run (T0/T1/T2, 200 ns production, with restraint sweep):
    python run_pipeline.py

Restraint sensitivity sweep only (50 ns each):
    python run_pipeline.py --sweep-only --variants T0

Extract parameters from completed trajectories:
    python run_pipeline.py --extract-only

Directory layout
----------------
runs/crossover_parameterization/
    T0/
        nominal/           ← production run (k=1.0 kcal/mol/Å²)
        sweep/
            k0p5/          ← sensitivity sweep (k=0.5)
            k1p0/          ← sensitivity sweep (k=1.0)
            k2p0/          ← sensitivity sweep (k=2.0)
        params.json        ← extracted CrossoverParameters
        sensitivity.json   ← sensitivity check result
    T1/  ...
    T2/  ...
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# ── Add project root to path ──────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from backend.parameterization.crossover_extract import (
    CrossoverVariant,
    FIRST_BATCH_VARIANTS,
    generate_variant_pdb,
    load_reference_design,
    assign_sequences_to_design,
    _apply_extra_t,
)
from backend.parameterization.md_setup import (
    setup_run_directory,
    setup_sensitivity_sweep,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("run_pipeline")

_BASE_DIR = Path(__file__).parent


def _variant_by_label(label: str) -> CrossoverVariant:
    for v in FIRST_BATCH_VARIANTS:
        if v.label == label:
            return v
    raise ValueError(f"Unknown variant label {label!r}.  Known: {[v.label for v in FIRST_BATCH_VARIANTS]}")


def run_setup(
    variants: list[str],
    prod_ns: int,
    do_sweep: bool,
    nacl_mM: float,
) -> None:
    """Build GROMACS run directories for requested variants."""
    logger.info("Setting up run directories for variants: %s", variants)

    for label in variants:
        variant = _variant_by_label(label)
        var_dir = _BASE_DIR / label

        # Generate PDB — generate_variant_pdb appends variant.label internally,
        # so pass the parent dir to avoid double-nesting T0/T0/.
        logger.info("[%s] Generating PDB...", label)
        pdb_path = generate_variant_pdb(
            variant,
            output_dir=var_dir.parent,
        )

        # Load sequenced design for GROMACS setup
        design = load_reference_design()
        design = assign_sequences_to_design(design)
        design = _apply_extra_t(design, variant.n_extra_t)

        # Nominal production run
        nominal_dir = var_dir / "nominal"
        logger.info("[%s] Setting up nominal run dir → %s", label, nominal_dir)
        setup_run_directory(
            design=design,
            pdb_path=pdb_path,
            run_dir=nominal_dir,
            variant_label=label,
            restraint_k_kcal=1.0,
            prod_ns=prod_ns,
            nacl_conc_mM=nacl_mM,
        )

        if do_sweep:
            sweep_dir = var_dir / "sweep"
            logger.info("[%s] Setting up restraint sensitivity sweep → %s", label, sweep_dir)
            setup_sensitivity_sweep(
                design=design,
                pdb_path=pdb_path,
                base_run_dir=sweep_dir,
                variant_label=label,
                prod_ns=min(50, prod_ns),   # sweep uses shorter runs
                nacl_conc_mM=nacl_mM,
            )

    logger.info("=== Setup complete ===")
    logger.info("To run simulations, cd into each run directory and execute ./run.sh")
    logger.info("Serial execution is recommended (see feedback_no_parallel_gromacs.md).")


def run_extraction(variants: list[str]) -> None:
    """Extract parameters from completed production trajectories."""
    from backend.parameterization.param_extract import extract_parameters
    from backend.parameterization.convergence import check, plot_diagnostics

    for label in variants:
        var_dir = _BASE_DIR / label
        nominal_dir = var_dir / "nominal"
        prod_xtc = nominal_dir / "prod.xtc"
        prod_tpr = nominal_dir / "prod.tpr"

        if not prod_xtc.exists():
            logger.warning(
                "[%s] prod.xtc not found at %s — skipping extraction. "
                "Has the production run completed?",
                label, prod_xtc,
            )
            continue

        logger.info("[%s] Extracting parameters from %s...", label, prod_xtc)
        params = extract_parameters(
            tpr_or_gro=prod_tpr if prod_tpr.exists() else nominal_dir / "npt.gro",
            xtc_path=prod_xtc,
            variant_label=label,
            restraint_k_kcal=1.0,
        )

        # Convergence check
        report = check(params)
        plot_diagnostics(
            q_series=None,   # Would need to reload Q from traj — skip plots here
            out_dir=var_dir / "diagnostics",
            variant_label=label,
        )

        params.save(var_dir / "params.json")
        (var_dir / "convergence_report.json").write_text(
            json.dumps(report, indent=2)
        )

        if not params.converged:
            logger.error(
                "[%s] Convergence check FAILED: %s",
                label, "; ".join(params.convergence_warnings),
            )
        else:
            logger.info("[%s] Parameters extracted and converged.", label)

    # Restraint sensitivity check (requires sweep trajectories)
    _run_sensitivity_checks(variants)


def _run_sensitivity_checks(variants: list[str]) -> None:
    """Run the restraint sensitivity check across sweep runs."""
    from backend.parameterization.param_extract import (
        extract_parameters,
        check_restraint_sensitivity,
        CrossoverParameters,
    )

    for label in variants:
        var_dir = _BASE_DIR / label
        sweep_dir = var_dir / "sweep"
        if not sweep_dir.exists():
            logger.info("[%s] No sweep directory — skipping sensitivity check.", label)
            continue

        params_by_k: dict[float, CrossoverParameters] = {}
        for k_dir in sweep_dir.iterdir():
            prod_xtc = k_dir / "prod.xtc"
            restraint_log = k_dir / "restraint_log.json"
            if not prod_xtc.exists():
                continue
            try:
                k_val = json.loads(restraint_log.read_text())["restraint_k_kcal_per_mol_per_A2"]
            except Exception:
                logger.warning("Could not read k value from %s", restraint_log)
                continue

            tpr = k_dir / "prod.tpr"
            gro = k_dir / "npt.gro"
            params = extract_parameters(
                tpr_or_gro=tpr if tpr.exists() else gro,
                xtc_path=prod_xtc,
                variant_label=label,
                restraint_k_kcal=k_val,
            )
            params_by_k[k_val] = params

        if len(params_by_k) >= 2:
            result = check_restraint_sensitivity(params_by_k)
            (var_dir / "sensitivity.json").write_text(
                json.dumps(result, indent=2)
            )
            if not result["passed"]:
                logger.error("[%s] RESTRAINT SENSITIVITY CHECK FAILED: %s",
                             label, result["recommendation"])
            else:
                logger.info("[%s] Restraint sensitivity OK.", label)
        else:
            logger.info("[%s] Not enough sweep runs for sensitivity check.", label)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crossover CG parameterization pipeline driver"
    )
    parser.add_argument(
        "--variants", nargs="+", default=["T0"],
        help="Variant labels to process (default: T0).  All: T0 T1 T2"
    )
    parser.add_argument(
        "--prod-ns", type=int, default=10,
        help="Production run length in nanoseconds (default: 10 for pipeline test; 200 for real runs)"
    )
    parser.add_argument(
        "--nacl-mM", type=float, default=150.0,
        help="NaCl concentration in mM (default: 150)"
    )
    parser.add_argument(
        "--no-sweep", action="store_true",
        help="Skip the restraint sensitivity sweep"
    )
    parser.add_argument(
        "--sweep-only", action="store_true",
        help="Only set up sweep runs, not the nominal run"
    )
    parser.add_argument(
        "--extract-only", action="store_true",
        help="Skip setup; only extract parameters from completed trajectories"
    )
    args = parser.parse_args()

    if args.extract_only:
        run_extraction(args.variants)
        return

    if not args.sweep_only:
        run_setup(
            variants=args.variants,
            prod_ns=args.prod_ns,
            do_sweep=not args.no_sweep,
            nacl_mM=args.nacl_mM,
        )
    else:
        # sweep_only: setup sweep dirs only (prod_ns shortened to 50 ns)
        run_setup(
            variants=args.variants,
            prod_ns=50,
            do_sweep=True,
            nacl_mM=args.nacl_mM,
        )


if __name__ == "__main__":
    main()
