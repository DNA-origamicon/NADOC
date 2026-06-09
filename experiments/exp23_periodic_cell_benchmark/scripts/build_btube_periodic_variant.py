"""
Build a B_tube periodic-cell package with a selectable repeat count.

This keeps 1x/2x/3x package generation reproducible for the exp23 periodic MD
experiments instead of relying on one-off ZIP extraction commands.
"""

from __future__ import annotations

import argparse
import io
import json
import zipfile
from collections import Counter
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[3]))

from backend.core.models import Design
from backend.core.periodic_cell import build_periodic_cell_package, get_periodic_cell_stats


ROOT = Path(__file__).parents[3]
DEFAULT_DESIGN = ROOT / "workspace" / "B_tube.nadoc"
DEFAULT_RESULTS = ROOT / "experiments" / "exp23_periodic_cell_benchmark" / "results"


def _extract_zip(zip_bytes: bytes, run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "output").mkdir(exist_ok=True)

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            parts = Path(info.filename).parts
            rel = Path(*parts[1:]) if len(parts) > 1 else None
            if rel is None or str(rel) == ".":
                continue
            dest = run_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(zf.read(info))
            mode = (info.external_attr >> 16) & 0o777
            if mode:
                if dest.suffix in (".sh", ".py") and not (mode & 0o111):
                    mode = 0o755
                dest.chmod(mode)
            elif dest.suffix in (".sh", ".py"):
                dest.chmod(0o755)
            print(f"  wrote {dest.relative_to(run_dir)}")


def _verify_residue_mix(pdb_path: Path) -> None:
    counts: Counter[str] = Counter()
    with pdb_path.open() as fh:
        for line in fh:
            if line[:6] in ("ATOM  ", "HETATM"):
                resname = line[17:21].strip()
                if resname in ("DA", "DT", "DG", "DC"):
                    counts[resname] += 1

    total = sum(counts.values())
    print(f"  DNA residue atom counts: {dict(counts)}")
    if total == 0 or len(counts) < 2:
        raise SystemExit("FAIL: PDB does not contain mixed DNA residue names")
    pct_dt = counts.get("DT", 0) / total * 100.0
    if pct_dt > 95:
        raise SystemExit(f"FAIL: {pct_dt:.1f}% DT; sequence assignment may have failed")
    print(f"  OK: mixed residues confirmed ({pct_dt:.1f}% DT)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--periods", type=int, default=2, help="Number of 21 bp periods")
    ap.add_argument("--design", type=Path, default=DEFAULT_DESIGN)
    ap.add_argument("--run-dir", type=Path, default=None)
    ap.add_argument("--zip-path", type=Path, default=None)
    ap.add_argument("--stats-only", action="store_true")
    args = ap.parse_args()

    run_dir = args.run_dir or (DEFAULT_RESULTS / f"periodic_cell_{args.periods}x_run")
    zip_path = args.zip_path or (DEFAULT_RESULTS / f"periodic_cell_{args.periods}x.zip")

    print(f"Loading design: {args.design}")
    design = Design.model_validate(json.load(args.design.open()))
    print(f"  Helices: {len(design.helices)}, strands: {len(design.strands)}")

    print(f"Estimating {args.periods}x periodic cell...")
    stats = get_periodic_cell_stats(design, n_periods=args.periods)
    print(json.dumps(stats, indent=2, default=list))
    if args.stats_only:
        return

    print(f"Building {args.periods}x package (solvation can take a few minutes)...")
    zip_bytes = build_periodic_cell_package(design, n_periods=args.periods)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    zip_path.write_bytes(zip_bytes)
    print(f"  ZIP: {zip_path} ({len(zip_bytes) / 1e6:.1f} MB)")

    print(f"Extracting to: {run_dir}")
    _extract_zip(zip_bytes, run_dir)

    name = f"{(design.metadata.name or 'design').replace(' ', '_')}_periodic_{args.periods}x"
    _verify_residue_mix(run_dir / f"{name}.pdb")
    print("\nBuild complete.")
    print(f"  Run dir: {run_dir}")
    print(f"  Base name: {name}")


if __name__ == "__main__":
    main()
