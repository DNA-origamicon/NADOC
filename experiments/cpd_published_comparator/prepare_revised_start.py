"""Isolated 1T4I starting structures; preserve CPD v6 topology/parameters."""

from pathlib import Path
import json, shutil, subprocess
import numpy as np
import MDAnalysis as mda
from experiments.cpd_published_comparator.localize_dna_drift import fit
from experiments.cpd_published_comparator.reconstruct import source


def main():
    old = Path(".development-artifacts/cpd-cis-syn-joint-v6").resolve()
    audit = Path(".development-artifacts/cpd-starting-structure-audit-v1").resolve()
    root = Path(".development-artifacts/cpd-start-1t4i-v2").resolve()
    root.mkdir(exist_ok=False)
    for n in ["typing_manifest.json", "comparator_last.prm", "final_audit.json"]:
        shutil.copy2(old / n, root / n)
    lines = (audit / "1T4I.pdb").read_text().splitlines()
    mapped = []
    for l in lines:
        if not l.startswith("ATOM") or l[21] not in "AB":
            continue
        name = l[12:16].strip().replace("*", "'")
        name = {"OP1": "O1P", "OP2": "O2P", "C7": "C5M"}.get(name, name)
        res = {"DA": "ADE", "DT": "THY", "DC": "CYT", "DG": "GUA"}[l[17:20].strip()]
        num = int(l[22:26]) + (10 if l[21] == "B" else 0)
        mapped.append(
            l[:12] + f"{name:>4}" + l[16:17] + res + l[20:22] + f"{num:4}" + l[26:]
        )
    (root / "mapped_heavy.pdb").write_text(
        "\n".join(l[:72].ljust(72) + f"{l[21]:<4}" + l[76:] for l in mapped) + "\nEND\n"
    )
    for fixture in ["duplex", "undamaged_control"]:
        f = root / fixture
        f.mkdir()
        shutil.copy2(old / fixture / "system.psf", f / "system.psf")
        script = f"""package require psfgen
resetpsf
topology {Path("backend/data/forcefield/top_all36_na.rtf").resolve()}
topology {Path(".development-artifacts/cpd-published-comparator-v1/comparator.rtf").resolve()}
readpsf {f}/system.psf
coordpdb {root}/mapped_heavy.pdb
guesscoord
writepdb {f}/system.pdb
exit
"""
        (f / "build.tcl").write_text(script)
        p = subprocess.run(
            ["psfgen", str(f / "build.tcl")], capture_output=True, text=True
        )
        (f / "build.log").write_text(p.stdout + p.stderr)
        p.check_returncode()
        u = mda.Universe(str(f / "system.psf"), str(f / "system.pdb"))
        assert len(u.atoms) == 634
        expected = {
            (l[21], int(l[22:26]), l[12:16].strip()): np.array(
                [float(l[k : k + 8]) for k in [30, 38, 46]]
            )
            for l in mapped
        }
        for at in u.atoms:
            if at.mass > 2:
                assert (
                    np.linalg.norm(
                        at.position - expected[(at.segid, int(at.resid), at.name)]
                    )
                    < 1e-4
                )
        assert "failed to guess" not in p.stdout
        pl = (f / "system.pdb").read_text().splitlines()
        mask = []
        for l in pl:
            if l.startswith("ATOM"):
                l = l[:60] + f"{int(u.atoms[int(l[6:11]) - 1].mass > 2):6.2f}" + l[66:]
            mask.append(l)
        (f / "fixed_heavy.pdb").write_text("\n".join(mask) + "\n")
        conf = (
            (old / fixture / "startup.conf")
            .read_text()
            .replace(str(old / fixture), str(f))
        )
        (f / "startup.conf").write_text(conf)
    a = mda.Universe(str(old / "duplex/system.psf"), str(old / "duplex/system.pdb"))
    b = mda.Universe(str(root / "duplex/system.psf"), str(root / "duplex/system.pdb"))
    heavy = np.flatnonzero(a.atoms.masses > 2)
    x = a.atoms.positions.copy()
    y = fit(b.atoms.positions.copy(), x, heavy)
    d = {(a.segid, int(a.resid), a.name): a.index for a in a.atoms}
    rows = []
    for r in a.residues:
        ids = [i.index for i in r.atoms if i.mass > 2]
        rows.append(
            dict(
                residue=f"{r.segid}:{r.resid}",
                rms_displacement_A=float(
                    np.sqrt(np.mean(np.sum((y[ids] - x[ids]) ** 2, axis=1)))
                ),
            )
        )
    pairs = [(d["A", 8, "O4"], d["B", 13, "N6"]), (d["A", 8, "N3"], d["B", 13, "N1"])]
    report = dict(
        source=source(audit / "1T4I.pdb"),
        previous_source=source(
            Path(".development-artifacts/cpd-published-comparator-v1/1N4E.pdb")
        ),
        atom_count=634,
        topology_unchanged=True,
        pair8_before_A=[float(np.linalg.norm(x[i] - x[j])) for i, j in pairs],
        pair8_after_A=[float(np.linalg.norm(y[i] - y[j])) for i, j in pairs],
        residue_displacements=rows,
        scope="Isolated research simulation fixtures only; no production geometry change",
    )
    (root / "starting_structure_audit.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axs = plt.subplots(
        1, 3, figsize=(15, 5), subplot_kw={"projection": "3d"}, layout="constrained"
    )
    focus = [
        at.index
        for at in a.atoms
        if (at.segid, at.resid) in [("A", 8), ("B", 13)] and at.mass > 2
    ]
    fs = set(focus)
    for ax, title, sets in zip(
        axs,
        ["Previous 1N4E", "Candidate 1T4I", "Shared-frame overlay"],
        [[(x, "#db674c")], [(y, "#167caa")], [(x, "#db674c"), (y, "#167caa")]],
    ):
        for xyz, color in sets:
            for bond in a.bonds:
                i, j = bond.indices
                if i in fs and j in fs:
                    ax.plot(*xyz[[i, j]].T, color=color, lw=2)
            for i, j in pairs:
                ax.plot(*xyz[[i, j]].T, color=color, ls="--")
                ax.text(
                    *xyz[[i, j]].mean(0),
                    f"{np.linalg.norm(xyz[i] - xyz[j]):.2f} Å",
                    fontsize=8,
                )
        ax.set_title(title)
        ax.set_box_aspect([1, 1, 1])
        ax.view_init(25, 40)
        both = np.concatenate([x[focus], y[focus]])
        center = both.mean(0)
        extent = max(np.ptp(both, axis=0)) / 2 + 1
        ax.set_xlim(center[0] - extent, center[0] + extent)
        ax.set_ylim(center[1] - extent, center[1] + extent)
        ax.set_zlim(center[2] - extent, center[2] + extent)
    fig.savefig(root / "starting_pair_comparison.png", dpi=160)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
