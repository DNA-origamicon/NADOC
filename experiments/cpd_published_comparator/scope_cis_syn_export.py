"""Keep only terms involving CPD-specific types in a CHARMM candidate overlay."""

import argparse
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_published_comparator.reconstruct import source, write


def scope_parameters(text):
    counts = {
        "BONDS": 2,
        "ANGLES": 3,
        "DIHEDRALS": 4,
        "IMPROPERS": 4,
        "NONBONDED": 1,
        "NBFIX": 2,
    }
    section = None
    lines = []
    for line in text.splitlines():
        words = line.split("!", 1)[0].split()
        if not words or words[0].startswith("*"):
            lines.append(line)
            continue
        key = words[0].upper()
        if key in counts or key in ("ATOMS", "END"):
            section = key
            lines.append(line)
            continue
        if key == "MASS":
            if words[2].startswith("CS"):
                lines.append(line)
        elif key in ("CUTNB", "CTOFNB", "CTONNB"):
            lines.append(line)
        elif section in counts:
            if any(w.startswith("CS") for w in words[: counts[section]]):
                lines.append(line)
        else:
            raise ValueError(f"Unrecognized parameter line: {line}")
    return "\n".join(lines) + "\n"


def main(parent, root):
    root.mkdir(exist_ok=False)
    for name in [
        "assessment.json",
        "plan.json",
        "optimizer.json",
        "typing_manifest.json",
        "aliases.rtf",
        "executed_source.py",
    ]:
        shutil.copy2(parent / name, root / name)
    for name in ["endpoint-1", "endpoint-2", "core"]:
        out = root / name
        out.mkdir()
        for filename in [
            "assessment.json",
            "minimum_A.txt",
            "system.xml",
            "fragment.psf",
        ]:
            shutil.copy2(parent / name / filename, out / filename)
        if name == "core":
            shutil.copy2(parent / name / "candidate.xml", out / "candidate.xml")
    (root / "comparator_last.prm").write_text(
        scope_parameters((parent / "comparator_last.prm").read_text())
    )
    (root / "scope_export.executed.py").write_text(Path(__file__).read_text())
    write(
        root / "export_scope.json",
        dict(
            simulation_ready=False,
            parent=source(parent / "comparator_last.prm"),
            output=source(root / "comparator_last.prm"),
            rule="Every parameter term includes at least one CS-prefixed CPD type; ordinary DNA uses original force fields",
            source=source(Path(__file__)),
        ),
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--root", required=True, type=Path)
    a = p.parse_args()
    main(a.input.resolve(), a.root.resolve())
