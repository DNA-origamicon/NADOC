"""Synthetic PSF/PDB/DCD/log evidence for PEG protocol tests, never native evidence."""

import hashlib
import json

import MDAnalysis as mda
import numpy as np


def build_package(folder):
    folder.mkdir(parents=True)
    (folder / "output").mkdir()
    atoms = [
        ("PEG", "PEG", "C1", 12.011),
        ("PEG", "PEG", "H1", 1.008),
        ("PEG", "PEG", "C2", 12.011),
        ("WAT", "TIP3", "OH2", 15.999),
        ("WAT", "TIP3", "H1", 1.008),
        ("WAT", "TIP3", "H2", 1.008),
    ]
    xyz = np.array(
        [
            [10, 10, 4],
            [11, 10, 4],
            [10, 10, 8],
            [20, 20, 20],
            [20.9572, 20, 20],
            [19.760, 20.927, 20],
        ]
    )
    records, psf = [], ["PSF", "", "       6 !NATOM"]
    for i, ((seg, res, name, mass), (x, y, z)) in enumerate(zip(atoms, xyz), 1):
        psf.append(
            f"{i:8d} {seg:<4} 1 {res:<4} {name:<4} {name:<4} 0.000000 {mass:13.6f} 0"
        )
        records.append(
            f"ATOM  {i:5d} {name:<4} {res:<4}A{1:4d}    {x:8.3f}{y:8.3f}{z:8.3f}{0.0:6.2f}{0.0:6.2f}      {seg:<4}"
        )
    psf.extend(
        [
            "",
            "       4 !NBOND: bonds",
            "".join(f"{i:8d}" for i in [1, 2, 1, 3, 4, 5, 4, 6]),
            "",
        ]
    )
    (folder / "system.psf").write_text("\n".join(psf))
    for name in ("system.pdb", "grafts.pdb"):
        (folder / name).write_text("\n".join(records) + "\nEND\n")
    (folder / "wall.tcl").write_text(
        "# Controlled protocol fixture; never launch as MD.\n"
    )
    manifest = dict(
        schema="nadoc.peg_wall_qualification.v1",
        repeat_units=1,
        chemistry="synthetic protocol fixture",
        temperature_K=294,
        seed=17,
        graft_k_kcal_mol_A2=5.0,
        n_atoms=6,
        slit=dict(box_nm=[4.8] * 3, axis=2, inset_nm=0.2, k_kcal_mol_A2=10.0),
        audit=dict(atoms=6, chains=1, anchor_indices_0=[0], peg_indices_0=[0, 1, 2]),
    )
    manifest["input_hashes"] = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in folder.iterdir()
        if p.is_file()
    }
    (folder / "manifest.json").write_text(json.dumps(manifest))
    return manifest, xyz


def write_evidence(folder, *, warmup=False):
    manifest, xyz = build_package(folder)
    segment = "peg_warm_p100" if warmup else "peg_relax_p10"
    freq, final = (400, 12500) if warmup else (4000, 120000)
    manifest["segments"] = [dict(name=segment, steps=final, dcd_freq=freq)]
    (folder / "manifest.json").write_text(json.dumps(manifest))
    epochs = (
        [(0, 0, final)]
        if warmup
        else [(0, 0, 40000), (1, 40000, 80000), (2, 80000, 120000)]
    )
    u = mda.Universe.empty(6, trajectory=True)
    for epoch, start, stop in epochs:
        suffix = f".resume{epoch}" if epoch else ""
        dcd_suffix = f".cont{epoch}" if epoch else ""
        rows = ["ETITLE: TS POTENTIAL TOTAL TEMP BOUNDARY MISC"] if epoch == 0 else []
        if epoch:
            (folder / f"{segment}{suffix}.conf").write_text(f"firsttimestep {start}\n")
        with mda.Writer(
            str(folder / "output" / f"{segment}{dcd_suffix}.dcd"),
            6,
            istart=start + freq,
            nsavc=freq,
        ) as writer:
            for step in range(start + freq, stop + 1, freq):
                pos = xyz.copy()
                # Deliberate polymer drift: safety passes, convergence must not.
                pos[2, 2] += step / final * 6
                u.atoms.positions = pos
                u.dimensions = [48, 48, 48, 90, 90, 90]
                writer.write(u.atoms)
                rows.append(f"ENERGY: {step} -10000 -9000 294 0 0")
        rows += [
            "Running with GPU-resident mode",
            f"WRITING COORDINATES TO OUTPUT FILE AT STEP {stop}",
            "End of program",
        ]
        (folder / f"{segment}{suffix}.log").write_text("\n".join(rows) + "\n")
    return folder
