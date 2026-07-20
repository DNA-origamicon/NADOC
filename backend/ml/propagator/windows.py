"""Phase-1d: turn a captured NAMD reference trajectory into propagator training data.

Reads a finished propagator-reference job's captured production segments (position
DCD + velocity DCD + force DCD, all frame-aligned at the same cadence) and writes a
compact ``.npz`` shard + a ``dataset_manifest.json`` describing the schema — the
contract the propagator/baseline (next step) consumes.

Key trick: NAMD's ``velDCDfile`` / ``forceDCDfile`` are structurally ordinary
coordinate DCDs, so ``MDAnalysis.Universe(psf, veldcd).atoms.positions`` returns the
*velocity* array (and likewise forces). Same PSF + same atom selection → identical
atom ordering across the three, so they stack directly.

Units (recorded in the manifest, NOT converted here — the propagator verifies the
velocity scale empirically against finite-difference displacements):
  positions  Å
  velocities NAMD velDCD internal units (× 20.45482706 → Å/ps)
  forces     kcal/mol/Å

Training pairs are built WITHIN each captured segment only (a clean, fixed dt between
consecutive frames); ``segment_starts`` marks segment boundaries so the consumer never
forms a cross-boundary pair (where the restart makes dt ill-defined).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import numpy as np

# NAMD velocity DCD internal unit → Å/ps (PDBVELFACTOR). Recorded for the consumer;
# the propagator also re-derives the effective factor from displacements as a check.
NAMD_VEL_TO_A_PER_PS = 20.45482706
PROPAGATOR_TIMESTEP_FS = 2.0  # prepare_propagator_reference pins 2 fs, no HMR

_ELEMENT_Z = {
    "H": 1, "C": 6, "N": 7, "O": 8, "P": 15, "S": 16,
    "NA": 11, "MG": 12, "CL": 17, "K": 19, "CA": 20,
}

# CHARMM monatomic-ion RESIDUE names → element.  These MUST be resolved by resname:
# atom-name guessing mistypes them (SOD→S, POT→P, CAL→C…) because the name's leading
# letters collide with real elements.  (Verified: NaCl ions are resname/atomname "SOD"
# / "CLA" in our solvated PSFs; Mg is "MG".)  Bug this fixes: Na+ was exported as z=16.
_ION_RESNAME_EL = {
    "SOD": "NA", "CLA": "CL", "POT": "K", "MG": "MG",
    "MGH": "MG", "CAL": "CA", "CES": "K",
}


def _dna_resnames() -> list[str]:
    from backend.core.atomistic_to_nadoc import _GRO_DNA_RESNAMES  # noqa: PLC0415
    return sorted(_GRO_DNA_RESNAMES)


def _element_of(atom) -> str:
    # Monatomic ions FIRST, by resname — their atom-name leading letters collide with
    # other elements (SOD→S, POT→P), so name-guessing mistypes them (see _ION_RESNAME_EL).
    try:
        rn = (atom.resname or "").strip().upper()
        if rn in _ION_RESNAME_EL:
            return _ION_RESNAME_EL[rn]
    except Exception:
        pass
    try:
        el = (atom.element or "").strip()
        if el:
            return el.upper()
    except Exception:
        pass
    # Fall back to the leading alphabetic run of the atom name (CHARMM naming).
    name = "".join(c for c in atom.name if c.isalpha()).upper()
    return (name[:2] if name[:2] in _ELEMENT_Z else name[:1]) or "X"


def _read_values(psf: str, dcd_paths: list[str], sel: str) -> np.ndarray:
    """Frames × Natoms × 3 array of the selected atoms' DCD values (pos OR vel OR force).

    ``.veldcd`` / ``.forcedcd`` are DCD-format but MDAnalysis can't guess that from
    the extension, so force ``format="DCD"``."""
    import MDAnalysis as mda  # noqa: PLC0415
    u = mda.Universe(psf, dcd_paths if len(dcd_paths) > 1 else dcd_paths[0],
                     format="DCD")
    ag = u.select_atoms(sel)
    frames = np.empty((len(u.trajectory), len(ag), 3), dtype=np.float32)
    for i, _ts in enumerate(u.trajectory):
        frames[i] = ag.positions
    return frames


def export_rollout_data(
    job,
    workspace_dir: str | Path,
    out_path: str | Path,
    *,
    segment_index: int = 0,
    dna_only: bool = False,
    frame_stride: int = 1,
    system_meta: Optional[dict] = None,
) -> dict:
    """Export ONE continuous captured segment as consecutive frames for autoregressive
    rollout: positions + velocities over a FIXED atom set (all atoms incl. water/ions
    by default — the full-atomistic requirement).

    Rollout needs a fixed atom set and a continuous time series, so it takes a single
    production segment (not the concatenation). No forces (rollout predicts Δx, Δv and
    supervises on the next frame directly)."""
    from backend.ml.propagator.local_run import captured_outputs  # noqa: PLC0415

    ws = Path(workspace_dir)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pkg = job.package_dir(ws)
    psf = str(pkg / f"{job.name_stem}.psf")
    cap = captured_outputs(job, ws)
    seg_names = [s.name for s in job.segments if s.name in cap]
    sel = ("resname " + " ".join(_dna_resnames())) if dna_only else "all"

    # segment_index=None → concatenate ALL captured segments. The unrestrained MGHH
    # chunks are NAMD continuations (pos+vel carried over), so the concatenation is one
    # continuous trajectory bar a ~1-frame gap at each boundary (negligible: 2/N pairs).
    chunk_names = seg_names if segment_index is None else [seg_names[segment_index]]
    name = chunk_names[0]
    pos_chunks, vel_chunks = [], []
    for nm in chunk_names:
        p = _read_values(psf, [cap[nm]["dcd"]], sel)[::frame_stride]
        v = _read_values(psf, [cap[nm]["veldcd"]], sel)[::frame_stride]
        k = min(len(p), len(v))
        pos_chunks.append(p[:k]); vel_chunks.append(v[:k])
    pos = np.concatenate(pos_chunks).astype(np.float32)
    vel = np.concatenate(vel_chunks).astype(np.float32)
    n = len(pos)

    import MDAnalysis as mda  # noqa: PLC0415
    u = mda.Universe(psf)
    ag = u.select_atoms(sel)
    z = np.array([_ELEMENT_Z.get(_element_of(a), 0) for a in ag], dtype=np.int16)
    mass = np.array(ag.masses, dtype=np.float32)
    is_dna = np.array(
        [1 if a.resname.strip() in set(_dna_resnames()) else 0 for a in ag], dtype=np.int8)
    manifest_in = json.loads((pkg / "manifest.json").read_text())
    box = np.array(manifest_in.get("box_ang", [0.0, 0.0, 0.0]), dtype=np.float32)
    seg_by = {m["name"]: m for m in manifest_in.get("segments", [])}
    dt_fs = float(seg_by.get(name, {}).get("dcd_freq", 10)) * PROPAGATOR_TIMESTEP_FS * frame_stride

    np.savez_compressed(out_path, positions=pos, velocities=vel, z=z, mass=mass,
                        is_dna=is_dna, box_ang=box)
    manifest = {
        "propagator_rollout_version": 1, "job_id": job.job_id, "segment": name,
        "npz": out_path.name, "n_frames": int(pos.shape[0]), "n_atoms": int(pos.shape[1]),
        "n_dna_atoms": int(is_dna.sum()), "dna_only": dna_only, "dt_fs": dt_fs,
        "frame_stride": frame_stride,
        "units": {"positions": "angstrom", "velocities": "namd_veldcd"},
        "system": system_meta or {},
    }
    (out_path.parent / (out_path.stem + "_manifest.json")).write_text(json.dumps(manifest, indent=2))
    return manifest


def export_windows(
    job,
    workspace_dir: str | Path,
    out_path: str | Path,
    *,
    system_meta: Optional[dict] = None,
    dna_only: bool = True,
) -> dict:
    """Export a finished job's captured trajectory to ``out_path`` (.npz) + manifest.

    Returns the manifest dict. ``dna_only`` restricts the exported atom set to DNA
    residues (the fluctuation target); water/ions are read but not exported.
    """
    from backend.ml.propagator.local_run import captured_outputs  # noqa: PLC0415

    ws = Path(workspace_dir)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    pkg = job.package_dir(ws)
    psf = str(pkg / f"{job.name_stem}.psf")
    cap = captured_outputs(job, ws)
    if not cap:
        raise RuntimeError(f"job {job.job_id} has no captured vel/force segments")

    # Ordered captured segments (production p10 → p50 → p100 is a continuous window).
    seg_order = [s.name for s in job.segments if s.name in cap]
    sel = ("resname " + " ".join(_dna_resnames())) if dna_only else "all"

    pos_chunks, vel_chunks, frc_chunks, seg_starts = [], [], [], []
    cursor = 0
    for name in seg_order:
        files = cap[name]
        dcd = files["dcd"]; vel = files["veldcd"]; frc = files["forcedcd"]
        if not (dcd and vel and frc):
            # partial capture (e.g. a segment that died mid-write) — skip it
            continue
        p = _read_values(psf, [dcd], sel)
        v = _read_values(psf, [vel], sel)
        f = _read_values(psf, [frc], sel)
        n = min(len(p), len(v), len(f))   # guard a torn final frame
        if n < 2:
            continue
        seg_starts.append(cursor)
        pos_chunks.append(p[:n]); vel_chunks.append(v[:n]); frc_chunks.append(f[:n])
        cursor += n

    if not pos_chunks:
        raise RuntimeError(f"job {job.job_id}: no usable captured frames")

    positions = np.concatenate(pos_chunks).astype(np.float32)
    velocities = np.concatenate(vel_chunks).astype(np.float32)
    forces = np.concatenate(frc_chunks).astype(np.float32)

    # Per-atom static features + bonds from the PSF (over the selected atoms).
    import MDAnalysis as mda  # noqa: PLC0415
    u = mda.Universe(psf)
    ag = u.select_atoms(sel)
    z = np.array([_ELEMENT_Z.get(_element_of(a), 0) for a in ag], dtype=np.int16)
    mass = np.array(ag.masses, dtype=np.float32)
    charge = np.array(ag.charges, dtype=np.float32)
    resid = np.array(ag.resids, dtype=np.int32)
    global_ix = {int(a.index): i for i, a in enumerate(ag)}
    bonds = []
    for b in getattr(ag, "bonds", []):
        i0, i1 = int(b.atoms[0].index), int(b.atoms[1].index)
        if i0 in global_ix and i1 in global_ix:
            bonds.append((global_ix[i0], global_ix[i1]))
    bonds_arr = np.array(sorted(set(bonds)), dtype=np.int32) if bonds else np.zeros((0, 2), np.int32)

    manifest_in = json.loads((pkg / "manifest.json").read_text())
    # dt between captured frames = dcd_freq × timestep.  MdSegmentStatus doesn't
    # carry dcd_freq, so read it back from the manifest the prep wrote.
    seg_by = {m["name"]: m for m in manifest_in.get("segments", [])}
    dcd_freq = next((seg_by[n].get("dcd_freq") for n in seg_order if n in seg_by), 10)
    dt_fs = float(dcd_freq) * PROPAGATOR_TIMESTEP_FS

    # Orthorhombic box (Å) for minimum-image correction of displacements: NAMD
    # wrapAll can flip a boundary atom by a full box length between frames.
    box_ang = np.array(manifest_in.get("box_ang", [0.0, 0.0, 0.0]), dtype=np.float32)

    np.savez_compressed(
        out_path,
        positions=positions, velocities=velocities, forces=forces,
        z=z, mass=mass, charge=charge, resid=resid,
        bonds=bonds_arr, segment_starts=np.array(seg_starts, dtype=np.int32),
        box_ang=box_ang,
    )

    manifest = {
        "propagator_dataset_version": 1,
        "job_id": job.job_id,
        "npz": out_path.name,
        "n_frames": int(positions.shape[0]),
        "n_atoms": int(positions.shape[1]),
        "n_bonds": int(bonds_arr.shape[0]),
        "n_segments": len(seg_starts),
        "segment_starts": [int(x) for x in seg_starts],
        "dna_only": dna_only,
        "dt_fs": dt_fs,
        "timestep_fs": PROPAGATOR_TIMESTEP_FS,
        "dcd_freq_steps": int(dcd_freq),
        "units": {
            "positions": "angstrom",
            "velocities": "namd_veldcd (x 20.45482706 -> angstrom/ps)",
            "forces": "kcal/mol/angstrom",
        },
        "namd_vel_to_A_per_ps": NAMD_VEL_TO_A_PER_PS,
        "arrays": {
            "positions": "float32 [T, N, 3]",
            "velocities": "float32 [T, N, 3]",
            "forces": "float32 [T, N, 3]",
            "z": "int16 [N] atomic number",
            "mass": "float32 [N]",
            "charge": "float32 [N]",
            "resid": "int32 [N]",
            "bonds": "int32 [B, 2] (0-indexed into N)",
            "segment_starts": "int32 [n_segments]",
        },
        "system": system_meta or {},
    }
    (out_path.parent / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest
