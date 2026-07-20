"""On-pod export: captured NAMD DCDs -> DNA-only training .npz via the REAL
backend.ml.propagator.windows.export_windows (shipped verbatim in ./_shim), so the
schema is byte-identical to what the BLADE trainer on the other computer consumes.

Also tags Mg-hexahydrate (MGH/MG) ions that sit persistently within a distance cutoff
of any DNA atom, as a companion .npz — the deferred "M2 condensed-ion shell" carve, so
a Mg-inclusive re-carve is possible from the same capture without re-running NAMD.

Runs on the pod (pip install MDAnalysis numpy scipy). Prints a JSON summary to stdout.

argv: <workdir> <name_stem> <capture_seg_name> <out_npz> [mg_cutoff_A=4.0]
The workdir must contain: <name_stem>.psf, manifest.json, output/<capture_seg_name>.{dcd,veldcd,forcedcd}
"""
import json
import sys
from pathlib import Path


def main() -> int:
    workdir = Path(sys.argv[1]).resolve()
    name_stem = sys.argv[2]
    seg_name = sys.argv[3]
    out_npz = Path(sys.argv[4]).resolve()
    mg_cutoff = float(sys.argv[5]) if len(sys.argv) > 5 else 4.0

    sys.path.insert(0, str(workdir / "_shim"))
    import numpy as np
    from backend.ml.propagator.windows import export_windows  # the REAL shared code

    # --- shim MdJob: export_windows needs package_dir(ws), name_stem, segments, job_id
    class _Seg:
        def __init__(self, name): self.name = name
    class _Job:
        job_id = f"blade_ref_{name_stem}"
        def __init__(self):
            self.name_stem = name_stem
            self.segments = [_Seg(seg_name)]
        def package_dir(self, _ws): return workdir
    job = _Job()

    manifest = export_windows(job, workdir, out_npz, dna_only=True,
                              system_meta={"design": name_stem, "seed": "04_MGHH_only_p100",
                                           "ensemble": "NVT", "note": "curved 6hbx100_90deg BLADE reference"})

    # --- validation of the emitted npz (fail loud if forces are absent/NaN)
    d = np.load(out_npz)
    forces = d["forces"]; pos = d["positions"]
    finite = bool(np.isfinite(forces).all()) and bool(np.isfinite(pos).all())
    frms = float(np.sqrt((forces.astype(np.float64) ** 2).sum(-1)).mean())

    # --- Mg-hexahydrate condensed-ion tagging (companion, does NOT touch the DNA npz)
    import MDAnalysis as mda
    from scipy.spatial import cKDTree
    psf = str(workdir / f"{name_stem}.psf")
    dcd = str(workdir / "output" / f"{seg_name}.dcd")
    u = mda.Universe(psf, dcd, format="DCD")
    dna = u.select_atoms("resname DA DT DG DC ADE THY GUA CYT A T G C "
                         "DA3 DA5 DT3 DT5 DG3 DG5 DC3 DC5")
    mg = u.select_atoms("resname MGH MG and name MG*")  # the Mg centre of each hexahydrate
    if len(mg) == 0:
        mg = u.select_atoms("resname MGH MG")
    n_frames = len(u.trajectory)
    within = np.zeros(len(mg), dtype=np.int32)
    for _ts in u.trajectory:
        tree = cKDTree(dna.positions)
        dmin, _ = tree.query(mg.positions, k=1)
        within += (dmin < mg_cutoff).astype(np.int32)
    persistence = within.astype(np.float64) / max(n_frames, 1)
    chelated = persistence >= 0.5  # persistently (>=50% of frames) within cutoff
    mg_out = out_npz.parent / (out_npz.stem + "_chelated_mg.npz")
    np.savez_compressed(
        mg_out,
        mg_atom_index=np.array(mg.indices, dtype=np.int64),   # 0-based global PSF index
        mg_resid=np.array(mg.resids, dtype=np.int32),
        persistence=persistence.astype(np.float32),
        chelated=chelated.astype(np.int8),
        cutoff_A=np.float32(mg_cutoff),
    )

    summary = {
        "npz": out_npz.name,
        "npz_bytes": out_npz.stat().st_size,
        "n_frames": manifest["n_frames"],
        "n_atoms": manifest["n_atoms"],
        "n_bonds": manifest["n_bonds"],
        "forces_finite": finite,
        "force_rms_kcal_mol_A": round(frms, 4),
        "dt_fs": manifest["dt_fs"],
        "dataset_version": manifest["propagator_dataset_version"],
        "n_mg_total": int(len(mg)),
        "n_mg_chelated": int(chelated.sum()),
        "mg_companion": mg_out.name,
        "mg_companion_bytes": mg_out.stat().st_size,
    }
    print("EXPORT_SUMMARY " + json.dumps(summary))
    return 0 if finite else 3


if __name__ == "__main__":
    sys.exit(main())
