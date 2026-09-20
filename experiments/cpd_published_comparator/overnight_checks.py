"""Budget admission and descriptive per-block checks for overnight DNA sampling."""

import json
import re
import warnings
import numpy as np
import MDAnalysis as mda
from scipy.spatial.distance import pdist
from experiments.cpd_published_comparator.analyze_dna_replicas import aligned_rmsd
from experiments.cpd_published_comparator.localize_dna_drift import torsion


def admit_block(remaining, durations, fallback):
    estimate = float(np.median(durations[-6:])) if durations else fallback
    return remaining > 1.2 * estimate + 120


def estimate_block_seconds(parent):
    rates = []
    for p in parent.glob("*/replica-*/run.log"):
        lines = [l for l in p.read_text().splitlines() if l.startswith("TIMING:")]
        for line in lines[-3:]:
            m = re.search(r"Wall: [^,]+, ([0-9.eE+-]+)/step", line)
            if m:
                rates.append(float(m[1]))
    if not rates:
        raise ValueError("No measured parent throughput available")
    return float(np.median(rates)) * 250000 + 30


def extra_checks(folder):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        u = mda.Universe(str(folder / "system.psf"), str(folder / "trajectory.dcd"))
        ref = mda.Universe(str(folder / "system.psf"), str(folder / "system.pdb"))
    atoms = u.atoms[:634]
    initial = ref.atoms[:634].positions.copy()
    heavy = np.flatnonzero(atoms.masses > 2)
    idx = {(a.segid, int(a.resid), a.name): a.index for a in atoms}
    central = np.array(
        [
            a.index
            for a in atoms
            if a.mass > 2
            and (
                (a.segid == "A" and 3 <= a.resid <= 8)
                or (a.segid == "B" and 13 <= a.resid <= 18)
            )
        ]
    )
    lesion = [
        idx["B", n, a]
        for n in [15, 16]
        for a in ["N1", "C2", "N3", "C4", "C5", "C6", "O2", "O4"]
    ]
    chi = [[idx["B", n, a] for a in ["O4'", "C1'", "N1", "C2"]] for n in [15, 16]]
    sugar = [
        [idx["B", n, a] for a in ["O4'", "C1'", "C2'", "C3'", "C4'"]] for n in [15, 16]
    ]
    contacts = []
    for n in range(1, 11):
        residue = atoms[idx["A", n, "C1'"]].resname
        pairs = {
            "ADE": [("N6", "O4"), ("N1", "N3")],
            "THY": [("O4", "N6"), ("N3", "N1")],
            "GUA": [("O6", "N4"), ("N1", "N3"), ("N2", "O2")],
            "CYT": [("N4", "O6"), ("N3", "N1"), ("O2", "N2")],
        }[residue]
        contacts.append([(idx["A", n, a], idx["B", 21 - n, b]) for a, b in pairs])
    measurements = []
    for ts in u.trajectory:
        x = atoms.positions.copy()
        if not np.allclose(ts.dimensions[3:], 90):
            raise ValueError("Image bound requires orthorhombic box")
        measurements.append(
            dict(
                frame=ts.frame,
                central_fit_rmsd_A=aligned_rmsd(x[central], initial[central]),
                lesion_base_local_rmsd_A=aligned_rmsd(x[lesion], initial[lesion]),
                image_gap_lower_bound_A=float(
                    min(ts.dimensions[:3]) - max(pdist(x[heavy]))
                ),
                pair_contacts=[
                    float(np.mean([np.linalg.norm(x[a] - x[b]) < 3.5 for a, b in pair]))
                    for pair in contacts
                ],
                lesion_chi_deg=[torsion(x[ids]) for ids in chi],
                lesion_sugar_ring_torsions_deg=[
                    [torsion(x[np.roll(ids, -k)[:4]]) for k in range(5)]
                    for ids in sugar
                ],
            )
        )
    (folder / "local_diagnostics.json").write_text(
        json.dumps(
            dict(
                frame_spacing_ps=2,
                measurements=measurements,
                limits=[
                    "Contacts use distance only",
                    "Image bound is conservative; a low bound requires geometric review",
                    "Raw torsions, not a converged population estimate",
                ],
            )
        )
        + "\n"
    )
    return dict(
        minimum_image_gap_lower_bound_A=min(
            v["image_gap_lower_bound_A"] for v in measurements
        ),
        central_fit_rmsd_mean_A=float(
            np.mean([v["central_fit_rmsd_A"] for v in measurements])
        ),
        lesion_base_local_rmsd_mean_A=float(
            np.mean([v["lesion_base_local_rmsd_A"] for v in measurements])
        ),
        base_pair_contact_fractions=np.mean(
            [v["pair_contacts"] for v in measurements], axis=0
        ).tolist(),
    )
