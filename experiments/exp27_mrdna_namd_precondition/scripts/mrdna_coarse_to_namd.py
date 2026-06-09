#!/usr/bin/env python3
"""Run/test mrDNA coarse preconditioning and write NAMD-ready atomistic files.

This script is intentionally scoped to designs with no explicit crossover
extra bases.  It never adds hidden bases.  If a design includes crossover
``extra_bases``, the default behavior is to stop with a clear error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from backend.core.md_precondition import (
    WORKFLOW_FLAG_NO_CROSSOVER_EXTRABASES_ONLY,
    assert_no_crossover_extrabases,
    build_model_from_override,
    build_precondition_report,
    crossover_extrabase_records,
    write_preconditioned_namd_inputs,
)
from backend.core.models import Design
from backend.core.mrdna_bridge import (
    mrdna_model_from_nadoc,
    nuc_pos_override_from_mrdna_coarse,
)


def _load_design(path: Path) -> Design:
    return Design.model_validate(json.loads(path.read_text()))


def _ensure_importable_mrdna() -> None:
    try:
        import mrdna  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "mrdna is not importable. Install mrDNA in the active Python "
            "environment, or set MRDNA_TOOL_PATH to a local mrDNA checkout."
        ) from exc


def _find_first(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def _find_mrdna_outputs(work_dir: Path, stem: str) -> tuple[Path, Path, Path | None]:
    psf = _find_first([
        work_dir / f"{stem}.psf",
        work_dir / f"{stem}-0.psf",
        work_dir / "coarse" / f"{stem}.psf",
        work_dir / "coarse" / f"{stem}-0.psf",
    ])
    pdb = _find_first([
        work_dir / f"{stem}.pdb",
        work_dir / f"{stem}-0.pdb",
        work_dir / "coarse" / f"{stem}.pdb",
        work_dir / "coarse" / f"{stem}-0.pdb",
    ])
    dcd = _find_first([
        work_dir / "output" / f"{stem}.dcd",
        work_dir / "output" / f"{stem}-0.dcd",
        work_dir / f"{stem}.dcd",
        work_dir / f"{stem}-0.dcd",
    ])
    if psf is None or pdb is None:
        raise SystemExit(
            f"Could not find mrDNA coarse PSF/PDB under {work_dir}. "
            "Inspect the mrdna/ directory and pass --reuse-psf/--reuse-dcd if needed."
        )
    return psf, pdb, dcd


def _write_single_frame_dcd(psf: Path, pdb: Path, dcd: Path) -> Path:
    try:
        import MDAnalysis as mda
    except ImportError as exc:
        raise SystemExit(
            "MDAnalysis is required to create a zero-step DCD from mrDNA PDB output."
        ) from exc

    u = mda.Universe(str(psf), str(pdb))
    with mda.Writer(str(dcd), n_atoms=u.atoms.n_atoms) as writer:
        for _ in u.trajectory:
            writer.write(u.atoms)
    return dcd


def _run_mrdna_coarse(design: Design, work_dir: Path, stem: str, steps: int, dry_run: bool) -> tuple[Path, Path, Path]:
    _ensure_importable_mrdna()
    work_dir.mkdir(parents=True, exist_ok=True)
    model = mrdna_model_from_nadoc(design)
    model.simulate(
        output_name=stem,
        directory=str(work_dir),
        output_directory="output",
        dry_run=dry_run,
        num_steps=steps,
    )
    psf, pdb, dcd = _find_mrdna_outputs(work_dir, stem)
    if dcd is None:
        dcd = _write_single_frame_dcd(psf, pdb, work_dir / f"{stem}_frame0.dcd")
    return psf, pdb, dcd


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--design", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--stem", default="mrdna_coarse_preconditioned")
    ap.add_argument("--mrdna-steps", type=int, default=100_000)
    ap.add_argument("--mrdna-dry-run", action="store_true")
    ap.add_argument("--frame", type=int, default=-1)
    ap.add_argument("--sigma-nt", type=float, default=1.0)
    ap.add_argument("--reuse-psf", type=Path, help="Existing mrDNA coarse PSF")
    ap.add_argument("--reuse-dcd", type=Path, help="Existing mrDNA coarse DCD or PDB")
    ap.add_argument(
        "--allow-crossover-extrabases",
        action="store_true",
        help="Bypass the no-crossover-extrabases guard for exploratory debugging only.",
    )
    args = ap.parse_args()

    design = _load_design(args.design)
    extrabases = crossover_extrabase_records(design)
    if extrabases and not args.allow_crossover_extrabases:
        assert_no_crossover_extrabases(design)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    mrdna_dir = args.out_dir / "mrdna"

    if args.reuse_psf and args.reuse_dcd:
        psf = args.reuse_psf
        dcd = args.reuse_dcd
        source = f"reuse psf={psf} trajectory={dcd} frame={args.frame}"
    elif args.reuse_psf or args.reuse_dcd:
        raise SystemExit("Pass both --reuse-psf and --reuse-dcd, or neither.")
    else:
        psf, _pdb, dcd = _run_mrdna_coarse(
            design,
            mrdna_dir,
            args.stem,
            steps=args.mrdna_steps,
            dry_run=args.mrdna_dry_run,
        )
        source = f"mrDNA coarse psf={psf} dcd={dcd} frame={args.frame}"

    override = nuc_pos_override_from_mrdna_coarse(
        design,
        str(psf),
        str(dcd),
        frame=args.frame,
        sigma_nt=args.sigma_nt,
    )
    model = build_model_from_override(design, override)
    report = build_precondition_report(
        design,
        source=source,
        override=override,
        model=model,
        allow_crossover_extrabases=args.allow_crossover_extrabases,
        notes=(
            f"workflow_flag={WORKFLOW_FLAG_NO_CROSSOVER_EXTRABASES_ONLY}; "
            "mrDNA coarse CG positions used as atomistic nucleotide position overrides."
        ),
    )
    files = write_preconditioned_namd_inputs(
        design,
        model,
        args.out_dir,
        name=args.stem,
        report=report,
    )

    print(json.dumps({
        "workflow_flag": WORKFLOW_FLAG_NO_CROSSOVER_EXTRABASES_ONLY,
        "out_dir": str(args.out_dir),
        "override_entries": len(override),
        "written_files": sorted(files),
        "strained_crossovers": report[
            "crossover_geometry_before_atomistic_rebuild"
        ]["counts"]["strained_crossovers"],
    }, indent=2))


if __name__ == "__main__":
    main()
