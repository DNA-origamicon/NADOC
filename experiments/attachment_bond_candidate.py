"""Unapproved diagnostic: minimize the native root bond over clear grid poses.

No new coordinates, thresholds, chemistry, or pose samples are introduced.
The caller-frame lookup is diagnostic instrumentation, not an application API.
"""

from __future__ import annotations

import inspect
from dataclasses import replace
from types import SimpleNamespace

import numpy as np


def fit_shortest_root_bond(*args, **kwargs):
    from backend.core import nanoparticle_attachment_fit as fitting
    from backend.core.atomistic import AtomisticModel, build_atomistic_model
    from backend.core.atomistic_validation import _find_clashes, CLASH_NM
    from backend.core.nanoparticle_atomistic import LINKER_ATOM_NAMES, append_nanoparticle_linkers
    from backend.core.protein import _rotation_between

    native_fit = fitting.fit_swing
    root, _, _, _, _, geometry, version = args[:7]
    angles = args[9] if len(args) > 9 else kwargs.get("angles")
    if angles:
        return native_fit(*args, **kwargs)
    scores = []

    class RecordScores:
        def __getattr__(self, name):
            return getattr(np, name)

        def argmax(self, values, *a, **kw):
            scores.append(np.array(values))
            return np.argmax(values, *a, **kw)

    original_numpy = fitting.np
    try:
        fitting.np = RecordScores()
        original = native_fit(*args, **kwargs)
    finally:
        fitting.np = original_numpy
    caller = inspect.currentframe().f_back.f_locals
    if not caller["place_new_graft"]:
        raise ValueError("This diagnostic fit policy is limited to generated new grafts")
    design = caller["out"]
    rows = [n for n in geometry if n.get("strand_id") == version.strand_id
            or n.get("overhang_id") == version.overhang_id]
    sites = {(n["strand_id"], n["helix_id"], n["bp_index"], n["direction"]) for n in rows}
    strand_ids = {n["strand_id"] for n in rows}
    helix_ids = {d.helix_id for s in design.strands if s.id in strand_ids for d in s.domains}
    model = build_atomistic_model(design, fast_bridges=True,
                                 exclude_helix_ids={h.id for h in design.helices} - helix_ids)
    xyz = np.array([[a.x, a.y, a.z] for a in model.atoms])
    moving = np.array([(a.strand_id, a.helix_id, a.bp_index, a.direction) in sites
                       and a.name not in LINKER_ATOM_NAMES for a in model.atoms])
    boundary = [(i, j) for i, j in model.bonds if moving[i] != moving[j]
                and model.atoms[i].name not in LINKER_ATOM_NAMES
                and model.atoms[j].name not in LINKER_ATOM_NAMES]
    if not boundary:
        return original
    owner, record = fitting._surface_owner(design, version.nanoparticle_id, version.strand_id)
    particle = next(p for p in design.nanoparticles if p.id == version.nanoparticle_id)
    terminal_seq = (1 if owner.attach_end == "5p" else
                    max(a.seq_num for a in model.atoms if a.strand_id == version.strand_id))
    terminal_indices = [i for i, a in enumerate(model.atoms)
                        if a.strand_id == version.strand_id and a.seq_num == terminal_seq
                        and a.name not in LINKER_ATOM_NAMES]
    remap = {old: new for new, old in enumerate(terminal_indices)}
    terminal_bonds = [(remap[i], remap[j]) for i, j in model.bonds if i in remap and j in remap]
    particle_pose = particle.pose.to_array()

    def linker_model(trial):
        target, rotation, _ = trial
        positions = (xyz[terminal_indices] - root) @ rotation.T + root
        atoms = [replace(model.atoms[old], serial=new, x=p[0], y=p[1], z=p[2])
                 for (old, new), p in zip(remap.items(), positions)]
        # The exact existing graft rotation and native linker builder. This
        # predicts their emitted atoms; it does not fit new linker coordinates.
        graft_rotation = _rotation_between(
            particle_pose[:3, :3] @ np.asarray(record.backbone_attachment_local_nm),
            target - particle_pose[:3, 3],
        )
        local_rotation = particle_pose[:3, :3].T @ graft_rotation @ particle_pose[:3, :3]
        moved_record = record.model_copy(update={
            key: tuple(local_rotation @ np.asarray(getattr(record, key)))
            for key in ("site_local", "sulfur_local_nm", "backbone_attachment_local_nm")
        })
        local_design = SimpleNamespace(nanoparticles=[particle], nanoparticle_conjugations=[
            owner.model_copy(update={"surface_strands": [moved_record]})])
        return append_nanoparticle_linkers(AtomisticModel(atoms, terminal_bonds), local_design)

    phase_count = kwargs.get("phase_samples", 16)
    roll_count = kwargs.get("roll_samples", 24)
    assert len(scores) == phase_count and all(len(row) == roll_count for row in scores)
    best = None
    linker_refusals = 0
    for phase, values in enumerate(scores):
        for roll in np.flatnonzero(values >= 0):
            explicit = {"phase_deg": phase * 360 / phase_count,
                        "duplex_roll_deg": int(roll) * 360 / roll_count}
            trial = native_fit(*args[:9], explicit, **kwargs)
            rotation = trial[1]
            lengths = [np.linalg.norm(
                (rotation @ (xyz[i] - root) + root if moving[i] else xyz[i])
                - (rotation @ (xyz[j] - root) + root if moving[j] else xyz[j])
            ) for i, j in boundary]
            key = (max(lengths), -values[roll])
            if best is None or key < best[0]:
                terminal = linker_model(trial)
                terminal_xyz = np.array([[a.x, a.y, a.z] for a in terminal.atoms])
                if _find_clashes(terminal_xyz, np.isfinite(terminal_xyz).all(axis=1),
                                 terminal.bonds, CLASH_NM, 1):
                    linker_refusals += 1
                    continue
                best = (key, trial, terminal)
    if best is None:
        raise ValueError("No clear grid pose avoids native terminal linker clashes")
    predicted_linkers = getattr(fit_shortest_root_bond, "predicted_linkers", {})
    predicted_linkers[version.strand_id] = {
        a.name: [a.x, a.y, a.z] for a in best[2].atoms if a.name in LINKER_ATOM_NAMES
    }
    fit_shortest_root_bond.predicted_linkers = predicted_linkers
    print({"root_bond_candidate": version.overhang_id, "max_boundary_bond_nm": best[0][0],
           "angles": best[1][2], "linker_refusals_during_ranking": linker_refusals,
           "eligible_poses": sum(int(np.sum(row >= 0)) for row in scores)}, flush=True)
    return best[1]
