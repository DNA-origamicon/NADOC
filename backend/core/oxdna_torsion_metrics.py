"""Torque, relative twist and failure indicators in the frozen fixture frame."""

import numpy as np
from scipy.spatial.transform import Rotation

from backend.core.constants import OXDNA_LENGTH_UNIT
from backend.core.oxdna_frame_index import trajectory_offsets
from backend.core.oxdna_health import BP_FORMED_CUTOFF_NM, FENE_RMAX_UNITS
from backend.core.oxdna_torsion import TORQUE_UNIT, load_fixture, read_configuration
from backend.physics.oxdna_interface import _strand_nucleotide_order, oxdna_backbone_sites

MAX_FRAMES = 240


def projected_rotation(reference, observed, axis):
    first = reference - reference.mean(axis=0)
    second = observed - observed.mean(axis=0)
    first -= (first @ axis)[:, None] * axis
    second -= (second @ axis)[:, None] * axis
    cross = np.cross(first, second).sum(axis=0) @ axis
    dot = np.sum(first * second)
    if np.hypot(cross, dot) < 1e-10:
        return None
    return float(np.arctan2(cross, dot))


def measure_frame(fixture, step, raw):
    axis = np.asarray(fixture.axis)
    center = np.asarray(fixture.center)
    has_clamp = bool(fixture.clamp_indices)
    fixed = np.asarray(fixture.clamp_positions).reshape((-1, 3))
    initial_drive = np.asarray(fixture.drive_positions)
    clamp = raw[fixture.clamp_indices] - np.asarray(fixture.clamp_images).reshape((-1, 3))
    drive = raw[fixture.drive_indices] - fixture.drive_images
    reaction = (clamp - fixed) * fixture.clamp_stiffness
    if fixture.mode == "rotation":
        angle = fixture.rate * step
        target_pos = Rotation.from_rotvec(axis * angle).apply(initial_drive - center) + center
        force = (target_pos - drive) * fixture.drive_stiffness
        command = float(np.rad2deg(angle))
    else:
        force = np.asarray(fixture.drive_forces)
        command = fixture.target
    drive_torque = float(np.cross(drive - center, force).sum(axis=0) @ axis * TORQUE_UNIT)
    fixture_torque = float(np.cross(clamp - center, reaction).sum(axis=0) @ axis * TORQUE_UNIT)
    drive_angle = projected_rotation(initial_drive, drive, axis)
    clamp_angle = projected_rotation(fixed, clamp, axis) if has_clamp else 0
    twist = None if drive_angle is None or clamp_angle is None else float(
        np.rad2deg(np.arctan2(np.sin(drive_angle-clamp_angle), np.cos(drive_angle-clamp_angle)))
    )
    return {
        "step": step, "command": command, "twist_deg": twist,
        "drive_rotation_deg": float(np.rad2deg(drive_angle)) if drive_angle is not None else None,
        "applied_torque_pn_nm": drive_torque, "clamp_reaction_pn_nm": fixture_torque if has_clamp else None,
        "clamp_max_displacement_nm": (
            float(np.linalg.norm(clamp-fixed, axis=1).max() * OXDNA_LENGTH_UNIT) if has_clamp else None
        ),
    }


def _sample_frames(stage, count):
    path = stage / "trajectory.dat"
    if path.exists():
        offsets = trajectory_offsets(path)
        sample = np.unique(np.linspace(0, max(0, len(offsets)-1), min(len(offsets), MAX_FRAMES), dtype=int))
        with path.open("rb") as stream:
            for i in sample:
                stream.seek(offsets[i])
                try:
                    frame = read_configuration(stream, count)
                except ValueError:
                    if i == len(offsets)-1:
                        continue  # an interrupted writer may leave one partial frame
                    raise
                yield frame
    last = stage / "last_conf.dat"
    if last.exists():
        with last.open("rb") as stream:
            try:
                frame = read_configuration(stream, count)
            except ValueError:
                return
        yield frame


def _bond_lengths(frame, box, bonds):
    backbone = oxdna_backbone_sites(
        frame[:, :3] * OXDNA_LENGTH_UNIT, frame[:, 3:6], frame[:, 6:9]
    )
    d = (backbone[bonds[:, 0]] - backbone[bonds[:, 1]]) / OXDNA_LENGTH_UNIT
    return np.linalg.norm(d - box * np.round(d / box), axis=1)


def _paired(frame, box, pairs):
    base = frame[:, :3] + 0.4 * frame[:, 3:6]
    d = base[pairs[:, 0]] - base[pairs[:, 1]]
    return np.linalg.norm(d - box * np.round(d / box), axis=1) * OXDNA_LENGTH_UNIT <= BP_FORMED_CUTOFF_NM


def _pair_sites(design, order):
    index = {key: i for i, key in enumerate(order)}
    owner = {}
    for cluster in sorted(design.cluster_transforms, key=lambda c: (c.is_default, len(c.helix_ids))):
        for helix in cluster.helix_ids:
            owner.setdefault(helix, cluster.name)
    pairs, groups = [], []
    for i, key in enumerate(order):
        if key[2] == "FORWARD" and (j := index.get((key[0], key[1], "REVERSE", *key[3:]))) is not None:
            pairs.append((i, j))
            groups.append(owner.get(key[0], "Ungrouped DNA"))
    return np.asarray(pairs, dtype=int).reshape(-1, 2), np.asarray(groups, dtype=str)


def _worst_pair_loss(groups, baseline, tail):
    results = []
    for group in np.unique(groups):
        mask = (groups == group) & baseline
        if np.any(mask):
            lost = int(np.count_nonzero(mask & ~tail))
            results.append({"group": str(group), "lost": lost, "initially_paired": int(mask.sum())})
    return sorted(results, key=lambda rec: (-rec["lost"], rec["group"]))


def _site_label(key, labels):
    helix, bp, direction, *_ = key
    if helix in labels:
        return f"Helix {labels[helix]}, bp {bp}, {direction.lower()}"
    return "Inserted or extension nucleotide"


def analyze(directory, job, design):
    if design is None:
        raise ValueError("The frozen torsion design is unavailable.")
    setup = load_fixture(directory)
    stage = next((s for s in job.stages if s.name == "1_production"), None)
    if stage is None:
        raise ValueError("The frozen torsion stage is unavailable.")
    order = _strand_nucleotide_order(design)
    n = len(order)
    with (directory / "conf.dat").open("rb") as stream:
        _, box, seed = read_configuration(stream, n)
    topology = (directory / "topology.top").read_text().splitlines()[1:]
    if len(topology) != n:
        raise ValueError("The frozen DNA topology does not match the torsion specimen.")
    bonds = np.asarray([(i, j) for i, line in enumerate(topology)
                        if (j := int(line.split()[3])) >= 0], dtype=int).reshape(-1, 2)
    pairs, groups = _pair_sites(design, order)
    baseline = _paired(seed, box, pairs)
    samples = {}
    longest = None
    for local_step, box, data in _sample_frames(directory / stage.name, n):
        step = local_step + stage.completed_steps
        row = measure_frame(setup, step, data[:, :3])
        lengths = _bond_lengths(data, box, bonds)
        tail = _paired(data, box, pairs)
        row.update({
            "maximum_backbone_nm": float(lengths.max() * OXDNA_LENGTH_UNIT) if lengths.size else None,
            "backbone_over_limit": int(np.count_nonzero(lengths >= FENE_RMAX_UNITS)),
            "lost_seed_pairs": int(np.count_nonzero(baseline & ~tail)),
        })
        if lengths.size:
            index = int(np.argmax(lengths))
            if longest is None or lengths[index] > longest[0]:
                longest = (lengths[index], step, bonds[index])
        samples[step] = (row, tail)
    if not samples:
        raise ValueError("This test has no complete saved configuration to measure.")
    ordered = sorted(samples)
    rows = [samples[step][0] for step in ordered]
    for key in ("twist_deg", "drive_rotation_deg"):
        valid = [row for row in rows if row[key] is not None]
        for row, unwrapped in zip(valid, np.rad2deg(np.unwrap(np.deg2rad([r[key] for r in valid])))):
            row[key] = float(unwrapped)
    window = rows[-max(1, len(rows)//5):]
    input_mean = float(np.mean([row["applied_torque_pn_nm"] for row in window]))
    has_clamp = bool(setup.clamp_indices)
    reaction_mean = float(np.mean([row["clamp_reaction_pn_nm"] for row in window])) if has_clamp else None
    peak = max(rows, key=lambda row: abs(row["clamp_reaction_pn_nm"])) if has_clamp else None
    worst_loss = max(ordered, key=lambda step: samples[step][0]["lost_seed_pairs"])
    longest_bond = None
    if longest:
        distance, step, (i, j) = longest
        labels = {h.id: h.label if h.label is not None else i for i, h in enumerate(design.helices)}
        longest_bond = {"length_nm": float(distance * OXDNA_LENGTH_UNIT), "step": step,
                        "from": _site_label(order[i], labels), "to": _site_label(order[j], labels)}
    return {
        "fixture": setup.summary(), "rows": rows, "latest_attempt_from_step": stage.completed_steps,
        "job_status": job.status, "job_error": job.error, "initially_paired": int(baseline.sum()),
        "peak_clamp_reaction_pn_nm": peak["clamp_reaction_pn_nm"] if peak else None,
        "peak_clamp_step": peak["step"] if peak else None,
        "late_mean_applied_pn_nm": input_mean, "late_mean_reaction_pn_nm": reaction_mean,
        "late_window_samples": len(window),
        "late_reaction_to_applied": reaction_mean / input_mean if has_clamp and setup.target and abs(input_mean) > 1e-6 else None,
        "max_clamp_displacement_nm": max(row["clamp_max_displacement_nm"] for row in rows) if has_clamp else None,
        "max_backbone_over_limit": max(row["backbone_over_limit"] for row in rows),
        "most_stretched_backbone_bond": longest_bond,
        "peak_pair_loss_step": worst_loss,
        "pairing_loss": _worst_pair_loss(groups, baseline, samples[worst_loss][1]),
    }
