"""Fixture resolution and native oxDNA forces for a DNA-only torsion test."""

from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal

import numpy as np

from backend.core.constants import OXDNA_LENGTH_UNIT
from backend.physics.oxdna_interface import (
    OXDNA_FORCE_PN, _strand_nucleotide_order, resolve_anchor_particles, unwrap_align_to_reference,
)

TORQUE_UNIT = OXDNA_FORCE_PN * OXDNA_LENGTH_UNIT
SETUP_FILE = "torsion_setup.json"
FORCES_FILE = "torsion_forces.txt"


@dataclass(frozen=True)
class TorsionFixture:
    mode: Literal["rotation", "tangential"]
    steps: int
    target: float
    clamp_stiffness: float
    drive_stiffness: float
    checkpoint_sha256: str
    axis: list[float]
    center: list[float]
    box: list[float]
    clamp_indices: list[int]
    drive_indices: list[int]
    clamp_positions: list[list[float]]
    drive_positions: list[list[float]]
    clamp_images: list[list[float]]
    drive_images: list[list[float]]
    drive_forces: list[list[float]]

    @property
    def rate(self):
        return np.deg2rad(self.target) / self.steps if self.mode == "rotation" else 0.0

    def summary(self):
        return {
            "mode": self.mode, "target": self.target, "axis": self.axis,
            "center_nm": (np.asarray(self.center) * OXDNA_LENGTH_UNIT).tolist(),
            "clamp_particles": len(self.clamp_indices), "drive_particles": len(self.drive_indices),
            "checkpoint_sha256": self.checkpoint_sha256,
            "largest_site_force_pn": (
                float(np.linalg.norm(self.drive_forces, axis=1).max() * OXDNA_FORCE_PN)
                if self.drive_forces else None
            ),
        }


def read_configuration(stream, count):
    header = stream.readline().split()
    box_row = stream.readline().split()
    energy = stream.readline().split()
    if (len(header) != 3 or header[:2] != [b"t", b"="]
            or len(box_row) != 5 or box_row[:2] != [b"b", b"="]
            or energy[:2] != [b"E", b"="]):
        raise ValueError("The oxDNA configuration header is incomplete.")
    box = np.asarray(box_row[2:], dtype=float)
    data = np.empty((count, 9))
    for i in range(count):
        fields = stream.readline().split()
        if len(fields) < 9:
            raise ValueError("The oxDNA configuration is missing particles.")
        data[i] = fields[:9]
    if not np.isfinite(data).all() or not np.isfinite(box).all() or np.any(box <= 0):
        raise ValueError("The oxDNA configuration contains invalid coordinates or box dimensions.")
    return int(header[2]), box, data


def _selection_particles(design, refs, role, order, *, structure_anchors=False):
    indices = set()
    for ref in refs:
        descriptor = ref.model_dump(exclude_none=True)
        if ref.kind == "cluster" and not structure_anchors:
            cluster = next((c for c in design.cluster_transforms if c.id == ref.id), None)
            if cluster is None:
                raise ValueError(f"A {role} cluster is missing from the checkpoint design.")
            if cluster.base_ids:
                base_keys = {(b.helix_id, b.bp_index, b.direction.value, b.copy_k) for b in cluster.base_ids}
                selected = [i for i, key in enumerate(order)
                            if (key if len(key) == 4 else (*key, 0)) in base_keys]
            elif cluster.domain_ids:
                selected, _ = resolve_anchor_particles(design, [
                    {"kind": "domain", **domain.model_dump()} for domain in cluster.domain_ids
                ])
            else:
                selected, _ = resolve_anchor_particles(design, [descriptor])
        else:
            selected, _ = resolve_anchor_particles(design, [descriptor])
        if not selected:
            raise ValueError(f"A {role} selection ({ref.kind}) has no particles in the checkpoint.")
        indices.update(selected)
    return sorted(indices)


def _axis_line(design, selection, order, gauge, clamp_center, driven):
    if selection == "auto":
        _, s, basis = np.linalg.svd(driven - driven.mean(axis=0), full_matrices=False)
        if len(s) < 3 or s[1] < 1e-4 or s[2] > 0.5 * s[1]:
            raise ValueError("The drive selection has no clear plane. Choose an axis explicitly.")
        axis = basis[2].copy()
        return clamp_center, axis * np.sign(axis[np.argmax(np.abs(axis))])
    if isinstance(selection, str):
        return clamp_center, np.eye(3)["xyz".index(selection)]
    if selection.kind == "selections":
        start = _selection_particles(design, selection.start, "axis start", order)
        end = _selection_particles(design, selection.end, "axis end", order)
        center = gauge[start].mean(axis=0)
        direction = gauge[end].mean(axis=0) - center
        if np.max(np.abs(direction)) < 1e-4:
            raise ValueError("The axis selections have coincident centers. Choose two distinct points.")
    else:
        center = np.asarray(selection.point_nm)
        direction = np.asarray(selection.direction)
        # Keep coordinate conversion and squared lever arms within float range.
        if np.any(np.abs(center) > 1e100):
            raise ValueError("Enter a finite point in the checkpoint coordinate frame.")
        center = center / OXDNA_LENGTH_UNIT
    scale = np.max(np.abs(direction))
    if scale == 0:
        raise ValueError("Enter a nonzero direction for the axis.")
    direction = direction / scale
    return center, direction / np.linalg.norm(direction)


def _balanced_forces(relative, axis, torque):
    radial = relative - (relative @ axis)[:, None] * axis
    tangent = np.cross(axis, radial)
    lengths = np.linalg.norm(tangent, axis=1)
    tangent /= np.where(lengths > 1e-8, lengths, 1)[:, None]
    # A minimum-norm distribution with zero net force and zero off-axis moment.
    # Scale the moment equations so the force and torque rows are comparable.
    lever = max(float(lengths.max()), 1.0)
    matrix = np.vstack((tangent.T, np.cross(relative, tangent).T / lever))
    target = np.r_[np.zeros(3), axis / lever]
    weights = np.linalg.lstsq(matrix, target, rcond=1e-9)[0]
    if np.linalg.norm(matrix @ weights - target) > 1e-7:
        raise ValueError("Choose driven sites on opposite sides of the axis for a balanced load.")
    return tangent * (weights * torque / TORQUE_UNIT)[:, None]


def _pose_in_checkpoint(design, reference, selection, order, positions, box):
    from scipy.spatial.transform import Rotation

    with reference.open("rb") as stream:
        _, _, frame = read_configuration(stream, len(order))
    posed = dict(zip(order, ({"backbone_position": p} for p in positions)))
    source = frame[:, :3]
    ref = dict(zip(order, ({"backbone_position": p} for p in source)))
    whole = unwrap_align_to_reference(posed, ref, design, box, align=False)
    gauge = np.asarray([whole[key]["backbone_position"] for key in order])
    source_center, gauge_center = source.mean(axis=0), gauge.mean(axis=0)
    registration, _ = Rotation.align_vectors(gauge - gauge_center, source - source_center)
    point = np.asarray(selection.position_nm) / OXDNA_LENGTH_UNIT
    axis = Rotation.from_euler("XYZ", selection.rotation_deg, degrees=True).apply([0, 0, 1])
    return gauge, registration.apply(point - source_center) + gauge_center, registration.apply(axis)


def resolve_fixture(design, checkpoint: Path, request, steps: int, *, design_reference=None) -> TorsionFixture:
    from io import BytesIO

    order = _strand_nucleotide_order(design)
    clamp = _selection_particles(design, request.clamp, "clamp", order)
    anchors = _selection_particles(design, request.clamp_anchors, "structure anchor", order, structure_anchors=True)
    clamp = sorted(set(clamp) | set(anchors))
    drive = (_selection_particles(design, request.drive, "drive", order) if request.drive
             else sorted(set(range(len(order))) - set(clamp)))
    if set(clamp) & set(drive):
        raise ValueError("The clamp and drive selections overlap. Choose disjoint sites.")
    if len(drive) < 2:
        raise ValueError("Torque needs at least two driven particles.")
    count = len(order)
    raw = checkpoint.read_bytes()
    digest = sha256(raw).hexdigest()
    if request.checkpoint_sha256 and digest != request.checkpoint_sha256:
        raise ValueError("The parent checkpoint changed. Preview the fixture again.")
    with BytesIO(raw) as stream:
        _, box, frame = read_configuration(stream, count)
        if stream.read().strip():
            raise ValueError("Torsion tests require a full DNA-only checkpoint.")
    positions = frame[:, :3]
    if design_reference is not None:
        gauge, center, axis = _pose_in_checkpoint(design, design_reference, request.axis, order, positions, box)
    else:
        delta = positions - positions[(clamp or drive)[0]]
        gauge = positions - box * np.round(delta / box)
        clamp_center = gauge[clamp or drive].mean(axis=0)
        center, axis = _axis_line(design, request.axis, order, gauge, clamp_center, gauge[drive])
    images = positions - gauge
    held, driven = gauge[clamp], gauge[drive]
    projected = np.cross(driven - driven.mean(axis=0), axis)
    if np.linalg.norm(projected) < 1e-4:
        raise ValueError("The driven sites must span the plane perpendicular to the axis.")
    forces = (_balanced_forces(driven - center, axis, request.target)
              if request.mode == "tangential" else np.empty((0, 3)))
    return TorsionFixture(
        mode=request.mode, steps=steps, target=request.target,
        clamp_stiffness=request.clamp_stiffness, drive_stiffness=request.drive_stiffness,
        checkpoint_sha256=digest, axis=axis.tolist(), center=center.tolist(), box=box.tolist(),
        clamp_indices=clamp, drive_indices=drive, clamp_positions=held.tolist(),
        drive_positions=driven.tolist(), clamp_images=images[clamp].tolist(),
        drive_images=images[drive].tolist(), drive_forces=forces.tolist(),
    )


def _vec(values):
    return ",".join(format(value, ".16g") for value in values)


def forces_text(fixture: TorsionFixture, banked_steps=0):
    blocks = []
    held = np.asarray(fixture.clamp_positions) + fixture.clamp_images
    for i, pos in zip(fixture.clamp_indices, held):
        blocks.append(f"""type = trap
particle = {i}
pos0 = {_vec(pos)}
stiff = {fixture.clamp_stiffness:.16g}
rate = 0
dir = 1,0,0""")
    if fixture.mode == "rotation":
        for i, pos, image in zip(fixture.drive_indices, fixture.drive_positions, fixture.drive_images):
            blocks.append(f"""type = twist
particle = {i}
pos0 = {_vec(np.asarray(pos) + image)}
center = {_vec(np.asarray(fixture.center) + image)}
axis = {_vec(fixture.axis)}
stiff = {fixture.drive_stiffness:.16g}
mask = 1,1,1
base = {fixture.rate * banked_steps:.16g}
rate = {fixture.rate:.16g}""")
    else:
        for i, vector in zip(fixture.drive_indices, np.asarray(fixture.drive_forces)):
            magnitude = np.linalg.norm(vector)
            if magnitude > 0:
                blocks.append(f"""type = string
particle = {i}
F0 = {magnitude:.16g}
rate = 0
dir = {_vec(vector / magnitude)}""")
    return "".join("{\n" + block + "\n}\n" for block in blocks)


def save_fixture(directory, fixture):
    import json

    (directory / SETUP_FILE).write_text(json.dumps(asdict(fixture), indent=2) + "\n")
    (directory / FORCES_FILE).write_text(forces_text(fixture))


def load_fixture(directory):
    import json

    return TorsionFixture(**json.loads((directory / SETUP_FILE).read_text()))
