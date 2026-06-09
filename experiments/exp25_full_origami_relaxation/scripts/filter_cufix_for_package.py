#!/usr/bin/env python3
"""Filter a CUFIX stream to atom types defined in a package's parameter files."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


SECTION_RE = re.compile(r"^\s*(ATOMS|BONDS|ANGLES|DIHEDRALS|IMPROPER|CMAP|NONBONDED|NBFIX|HBOND|END)\b", re.I)


def collect_defined_types(parm_paths: list[Path]) -> set[str]:
    types: set[str] = set()
    for path in parm_paths:
        section = ""
        for raw in path.read_text(errors="replace").splitlines():
            line = raw.split("!", 1)[0].strip()
            if not line:
                continue
            match = SECTION_RE.match(line)
            if match:
                section = match.group(1).upper()
                continue
            parts = line.split()
            if not parts:
                continue
            if section == "NONBONDED" and len(parts) >= 4:
                types.add(parts[0])
    return types


def filter_cufix(src: Path, dst: Path, defined_types: set[str]) -> int:
    out: list[str] = []
    section = ""
    removed = 0
    for raw in src.read_text(errors="replace").splitlines():
        stripped = raw.strip()
        match = SECTION_RE.match(stripped)
        if match:
            section = match.group(1).upper()
            out.append(raw)
            continue
        if section == "NONBONDED":
            parts = stripped.split()
            if parts and not stripped.startswith("!") and len(parts) >= 4:
                defined_types.add(parts[0])
        if section == "NBFIX":
            parts = stripped.split()
            if parts and not stripped.startswith("!") and len(parts) >= 4:
                if parts[0] not in defined_types or parts[1] not in defined_types:
                    out.append("!" + raw + "  ! filtered: undefined atom type in DNA-only package")
                    removed += 1
                    continue
        out.append(raw)
    dst.write_text("\n".join(out) + "\n")
    return removed


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("package_dir", type=Path)
    args = ap.parse_args()
    forcefield = args.package_dir / "forcefield"
    src = forcefield / "toppar_water_ions_cufix.str"
    dst = forcefield / "toppar_water_ions_cufix_dna_only.str"
    defined = collect_defined_types([forcefield / "par_all36_na.prm"])
    removed = filter_cufix(src, dst, defined)
    print(f"Wrote {dst}; filtered {removed} NBFIX lines with undefined atom types")


if __name__ == "__main__":
    main()
