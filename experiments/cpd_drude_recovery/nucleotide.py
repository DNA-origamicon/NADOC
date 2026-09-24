"""Audit a candidate psfgen DNA build against an independent nuclear graph.

The only PSF repair allowed here removes terms involving invalid serial zero,
which psfgen retained after deleting the 5'-terminal phosphate. All surviving
nuclear atoms and bonds must match the existing independent additive precursor.
"""

from pathlib import Path
import argparse
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import write, source, PROBE, OLD
import openmm as mm
from openmm import app


def atoms_and_terms(text):
    lines = text.splitlines()
    atoms, sections = {}, {}
    for pos, line in enumerate(lines):
        if "!NATOM" in line:
            for row in lines[pos + 1 : pos + 1 + int(line.split()[0])]:
                f = row.split()
                atoms[int(f[0])] = f
        for tag, width in [("NBOND", 2), ("NTHETA", 3), ("NPHI", 4), ("NIMPHI", 4)]:
            if re.search(r"!" + tag + r"\b", line):
                count = int(line.split()[0])
                values = []
                end = pos + 1
                while len(values) < count * width:
                    values.extend(map(int, lines[end].split()))
                    end += 1
                if len(values) != count * width:
                    raise ValueError("Malformed PSF block")
                sections[tag] = (
                    pos,
                    end,
                    width,
                    [
                        tuple(values[i : i + width])
                        for i in range(0, len(values), width)
                    ],
                )
    return lines, atoms, sections


def nuclear_graph(text):
    _, atoms, blocks = atoms_and_terms(text)
    keep = {i for i, a in atoms.items() if a[5] != "DRUD" and float(a[7]) > 0}

    def key(i):
        name = atoms[i][4]
        name = {"C7": "C5M", "HO5'": "H5T", "HO3'": "H3T"}.get(name, name)
        return atoms[i][2], name

    return {key(i) for i in keep}, {
        tuple(sorted((key(a), key(b))))
        for a, b in blocks["NBOND"][3]
        if a in keep and b in keep
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(exist_ok=False)
    text = args.input.read_text()
    lines, atoms, blocks = atoms_and_terms(text)
    repairs = []
    for tag, (start, end, width, terms) in sorted(
        blocks.items(), key=lambda kv: kv[1][0], reverse=True
    ):
        for term in terms:
            if any(i < 0 or i > len(atoms) for i in term):
                raise ValueError("Unexpected invalid serial")
        bad = [t for t in terms if 0 in t]
        good = [t for t in terms if 0 not in t]
        if any(len(set(t)) != width for t in good):
            raise ValueError("Repeated atom within surviving interaction")
        if tag != "NIMPHI" and len({min(t, t[::-1]) for t in good}) != len(good):
            raise ValueError("Duplicate surviving interaction")
        if tag == "NBOND":
            if bad != [(2, 0)] or atoms[2][2:5] != ["1", "THY", "O5'"]:
                raise ValueError(
                    "Repair is restricted to the observed deleted-terminal-phosphate artifact"
                )
        repairs.append({"section": tag, "removed_zero_index_terms": bad})
        flat = [i for t in good for i in t]
        replacement = [f"{len(good):10d} !{tag}"]
        replacement.extend(
            "".join(f"{v:10d}" for v in flat[j : j + 8]) for j in range(0, len(flat), 8)
        )
        lines[start:end] = replacement
    candidate = "\n".join(lines) + "\n"
    reference = (
        OLD / "gate-troubleshooting-v1/namd-integration-v2/engine_smoke/reactant.psf"
    )
    aa, ab = nuclear_graph(candidate)
    ba, bb = nuclear_graph(reference.read_text())
    topology = {
        "nuclear_atom_count": len(aa),
        "nuclear_bond_count": len(ab),
        "atoms_equal": aa == ba,
        "bonds_equal": ab == bb,
        "extra_atoms": sorted(aa - ba),
        "missing_atoms": sorted(ba - aa),
        "extra_bonds": sorted(ab - bb),
        "missing_bonds": sorted(bb - ab),
    }
    write(args.output / "topology_audit.json", topology)
    if aa != ba or ab != bb:
        raise ValueError("Independent nuclear graph comparison failed")
    path = args.output / "reactant.psf"
    path.write_text(candidate)
    psf = app.CharmmPsfFile(str(path))
    centers = [v[0] for v in psf.aniso_list]
    if len(centers) != len(set(centers)):
        raise ValueError("Duplicated anisotropy center")
    pars = app.CharmmParameterSet(
        str(PROBE / "master.rtf"), str(PROBE / "master.prm"), str(PROBE / "na.prm")
    )
    system = psf.createSystem(
        pars, nonbondedMethod=app.NoCutoff, constraints=None, rigidWater=False
    )
    (args.output / "reactant_openmm.xml").write_text(mm.XmlSerializer.serialize(system))
    report = {
        "status": "passed_precursor_topology_and_parameter_load",
        "simulation_ready": False,
        "gate_effect": "none",
        "scope": "Unmodified d(TpT) precursor only; no CPD product or dynamics validation.",
        "particle_count": system.getNumParticles(),
        "drude_count": sum(a[5] == "DRUD" for a in atoms.values()),
        "lone_pair_count": sum(
            system.isVirtualSite(i) for i in range(system.getNumParticles())
        ),
        "anisotropy_count": len(centers),
        "net_charge_e": sum(a.charge for a in psf.atom_list),
        "nuclear_graph": topology,
        "repairs": repairs,
        "sources": {
            "input": source(args.input),
            "reference_nuclear_graph": source(reference),
            "code": source(__file__),
        },
    }
    write(args.output / "stage_assessment.json", report)
    print(report["status"], topology)


if __name__ == "__main__":
    main()
