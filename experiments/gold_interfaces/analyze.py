"""Planar/radial density, water orientation, packing and structural diagnostics.

Short controls are descriptive, not literature-matched physical qualification.
"""

import argparse
import json
from pathlib import Path
import warnings

import matplotlib
import MDAnalysis as mda
import numpy as np
from scipy.spatial import cKDTree

matplotlib.use("Agg")
from matplotlib import pyplot as plt

from backend.core.md_charge import parse_psf_atoms
from experiments.gold_interfaces.native import read_binary
from experiments.electrode_relax.water_mode_check import mode_temperatures


def analyze(package, prefix):
    m = json.loads((package/"manifest.json").read_text())
    atoms = parse_psf_atoms((package/"system.psf").read_text())
    types = np.array([a.atomtype for a in atoms])
    ids = {t: np.flatnonzero(types == t) for t in ("NAUI", "OT", "SOD", "CLA")}
    initial = mda.Universe(str(package/"system.pdb")).atoms.positions.astype(float)/10
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        u = mda.Universe(str(package/"system.psf"), str(package/"output"/f"{prefix}.dcd"))
    cell = np.array(m["cell_nm"])
    g = m["geometry"]
    slab = g["kind"] == "slab"
    if slab:
        low, high = g["liquid_bounds_nm"]
        edges = np.linspace(0, (high-low)/2, 61)
        volumes = 2*cell[0]*cell[1]*np.diff(edges)
    else:
        edges = np.linspace(0, min(cell)/2, 81)
        volumes = 4*np.pi/3*np.diff(edges**3)
    counts = {t: np.zeros(len(edges)-1) for t in ("OT", "SOD", "CLA")}
    orientation = np.zeros(len(edges)-1)
    samples = []
    n_used = 0
    reference = initial[ids["NAUI"]]
    initial_rg = float(np.sqrt(np.mean(np.sum((reference-reference.mean(axis=0))**2, axis=1))))
    for ts in u.trajectory:
        xyz = ts.positions.astype(float)/10
        gold = xyz[ids["NAUI"]]
        tree = cKDTree(np.mod(gold, cell), boxsize=cell)
        nearest = tree.query(np.mod(gold, cell), k=2)[0][:, 1]
        rg = np.sqrt(np.mean(np.sum((gold-gold.mean(axis=0))**2, axis=1)))
        # MSD of the actual coordinates is a fixed-atom check; free-particle COM/rotation
        # can contribute. Rg and nearest neighbors provide translation-invariant checks.
        rms = np.sqrt(np.mean(np.sum((gold-reference)**2, axis=1)))
        samples.append([ts.time, rms, rg, float(np.median(nearest)),
                        float(tree.query(np.mod(xyz[ids["OT"]], cell))[0].min())])
        if ts.frame < len(u.trajectory)//2:
            continue
        n_used += 1
        center = gold.mean(axis=0)
        for t in counts:
            pos = xyz[ids[t]]
            if slab:
                distances = np.minimum(pos[:, 2]-low, high-pos[:, 2])
            else:
                dr = pos-center
                dr -= np.round(dr/cell)*cell
                distances = np.linalg.norm(dr, axis=1)
            counts[t] += np.histogram(distances, edges)[0]
            if t == "OT":
                ox = ids["OT"]
                dipole = (xyz[ox+1]+xyz[ox+2])/2-pos
                # Stored water molecules are unwrapped by NAMD; normalize full vector.
                dipole /= np.linalg.norm(dipole, axis=1)[:, None]
                if slab:
                    sign = np.where(pos[:, 2] < (low+high)/2, 1., -1.)
                    cosine = dipole[:, 2]*sign
                else:
                    cosine = np.sum(dipole*dr/np.linalg.norm(dr, axis=1)[:, None], axis=1)
                orientation += np.histogram(distances, edges, weights=cosine)[0]
    if not n_used:
        raise ValueError("No frames for profile analysis")
    profiles = {t: values/(volumes*n_used) for t, values in counts.items()}
    orient = np.divide(orientation, counts["OT"], out=np.full_like(orientation, np.nan), where=counts["OT"] > 0)
    mid = (edges[1:]+edges[:-1])/2
    out = package/f"{prefix}_analysis"
    out.mkdir(exist_ok=False)
    np.savetxt(out/"profiles.csv", np.c_[mid, profiles["OT"], profiles["SOD"], profiles["CLA"], orient],
               delimiter=",", header="distance_nm,water_per_nm3,Na_per_nm3,Cl_per_nm3,mean_cos_water_dipole", comments="")
    samples = np.array(samples)
    np.savetxt(out/"structure.csv", samples, delimiter=",",
               header="time_ps,Au_reference_RMSD_nm,Au_Rg_nm,Au_nearest_neighbor_median_nm,min_Au_O_nm", comments="")
    fig, axes = plt.subplots(2, 2, figsize=(10, 7), layout="constrained")
    axes[0, 0].plot(mid, profiles["OT"])
    axes[0, 0].axhline(33.4, color="gray", ls="--", label="1 g/cm³ reference")
    axes[0, 0].set(ylabel="Water molecules / nm³")
    axes[0, 0].legend()
    for t, label in (("SOD", "Na"), ("CLA", "Cl")):
        axes[0, 1].plot(mid, profiles[t], label=label)
    axes[0, 1].set(ylabel="Ions / nm³")
    axes[0, 1].legend()
    axes[1, 0].plot(mid, orient)
    axes[1, 0].set(ylabel="Mean water dipole cosine", ylim=(-1, 1))
    for ax in (axes[0, 0], axes[0, 1], axes[1, 0]):
        ax.set_xlabel("Distance from inner Au plane (nm)" if slab else "Distance from particle COM (nm)")
    axes[1, 1].plot(samples[:, 0], samples[:, 3])
    axes[1, 1].axhline(m["geometry"]["lattice_nm"]/np.sqrt(2), color="gray", ls="--")
    axes[1, 1].set(xlabel="Trajectory time (ps)", ylabel="Median Au nearest neighbor (nm)")
    fig.suptitle(f"{package.name}/{prefix}: descriptive short control; not adsorption validation")
    fig.savefig(out/"profiles.png", dpi=160)
    plt.close(fig)
    vel = read_binary(package/"output"/f"{prefix}.vel")
    masses = np.array([a.mass for a in atoms])
    water_ids = ids["OT"][:, None]+np.arange(3)
    modes = mode_temperatures(masses[water_ids], vel[water_ids])
    bulk = mid > (1.0 if slab else g["radius_nm"]+1.)
    report = {"case": package.name, "prefix": prefix, "frames": len(samples),
        "profile_frames_last_half": n_used, "mobility": m["mobility"],
        "initial_Au_Rg_nm": initial_rg, "final_Au_Rg_nm": float(samples[-1, 2]),
        "final_reference_RMSD_nm": float(samples[-1, 1]),
        "nearest_neighbor_median_nm": float(np.median(samples[:, 3])),
        "minimum_Au_O_nm": float(samples[:, 4].min()),
        "bulk_region_water_per_nm3": float(np.sum(counts["OT"][bulk])/np.sum(volumes[bulk])/n_used),
        "water_modes_single_final_checkpoint": modes,
        "physical_validation": False,
        "limitations": ["Short correlated trajectory; profiles descriptive only",
                        "No matching TIP3P/CUFIX published target reproduced",
                        "Few ions; no reliable adsorption or residence-time estimate",
                        "Final-checkpoint mode temperatures are noisy, not equipartition convergence"]}
    (out/"results.json").write_text(json.dumps(report, indent=2)+"\n")
    # Static coordinate review is usable even without application gold rendering.
    fig = plt.figure(figsize=(7, 6))
    ax = fig.add_subplot(projection="3d")
    ax.scatter(*initial[ids["NAUI"]].T, s=8, c="#c79720", label="Au")
    ax.scatter(*initial[ids["OT"]][::8].T, s=1, c="#3090cc", alpha=.2, label="Water O (1/8)")
    ax.set(xlabel="x (nm)", ylabel="y (nm)", zlabel="z (nm)")
    ax.legend()
    ax.set_box_aspect(np.maximum(np.ptp(initial, axis=0), 1))
    fig.savefig(out/"packing.png", dpi=140, bbox_inches="tight")
    plt.close(fig)
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("package", type=Path)
    p.add_argument("prefix")
    a = p.parse_args()
    print(json.dumps(analyze(a.package, a.prefix), indent=2))
