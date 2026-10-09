"""Authoritative native Full slab poses, transported with each nucleotide.

The accepted rectangle registration is derived once from FULL_REP's chemical
landmarks. Consumers receive a center and quaternion; they never solve against
a possibly independently moved partner or retain a previous render's offset.
"""
from functools import lru_cache

import numpy as np
from scipy.spatial.transform import Rotation

from backend.core.measured_positioning import FULL_REP
from backend.core.native_full_placement import SOURCE, NativePlacementError

SLAB_DIMENSIONS = (0.30, 0.06, 0.70)
SLABLESS_SOURCES = frozenset({"native-full-extension-v1", "chemical-modification-v1"})
AUTHORED_SOURCES = frozenset({"authored-residue-c1-v1", "authored-residue-o5-v1"})


def _vector(record, field):
    try:
        value = np.asarray(record.get(field), dtype=float)
    except (TypeError, ValueError, OverflowError) as error:
        raise NativePlacementError(f"Nonnumeric {field} for native Full nucleotide.",
            details={"identity": _identity(record), "field": field, "actual": record.get(field)}) from error
    if value.shape != (3,) or not np.all(np.isfinite(value)):
        raise NativePlacementError(f"Invalid {field} for native Full nucleotide.",
            details={"identity": _identity(record), "field": field, "actual": record.get(field)})
    return value


def _identity(record):
    return {k: record.get(k) for k in ("helix_id", "bp_index", "direction", "copy_k", "strand_id")}


def _frame(normal, tangent):
    length = np.linalg.norm(tangent)
    if not np.isfinite(length) or length < 1e-12:
        raise NativePlacementError("Native Full slab has a zero axis tangent.")
    tangent = tangent / length
    normal = normal - tangent * np.dot(normal, tangent)
    length = np.linalg.norm(normal)
    if not np.isfinite(length) or length < 1e-12:
        raise NativePlacementError("Native Full slab has a degenerate base frame.")
    normal = normal / length
    return np.column_stack((np.cross(tangent, normal), tangent, normal))


def _contact_center(bead, base, frame):
    """Accepted rectangle registration, used only at the authority boundary."""
    radial = bead - base
    radial -= frame[:, 1] * np.dot(radial, frame[:, 1])
    distance = np.linalg.norm(radial)
    if distance < 1e-12:
        raise NativePlacementError("Native Full slab has coincident bead and base centers.")
    radial /= distance
    support = (abs(np.dot(radial, frame[:, 0])) * (SLAB_DIMENSIONS[0] / 2)
               + abs(np.dot(radial, frame[:, 2])) * (SLAB_DIMENSIONS[2] / 2))
    return base + radial * max(0., distance - support + 0.02)


@lru_cache(maxsize=1)
def _native_registration():
    def xyz(site):
        return np.array([site.radius_nm * np.cos(site.azimuth_rad()),
                         site.radius_nm * np.sin(site.azimuth_rad()), site.axial_nm])
    beads = [xyz(FULL_REP.backbone_fwd), xyz(FULL_REP.backbone_rev)]
    bases = [xyz(FULL_REP.base_fwd), xyz(FULL_REP.base_rev)]
    offsets = {}
    for index, direction in enumerate(("FORWARD", "REVERSE")):
        frame = _frame(bases[1-index] - bases[index], np.array([0., 0., 1.]))
        base = bases[index].copy()
        base[2] = (bases[0][2] + bases[1][2]) * .5
        offset = frame.T @ (_contact_center(beads[index], base, frame) - beads[index])
        offset.setflags(write=False)
        base_offset = frame.T @ (bases[index] - beads[index])
        base_offset.setflags(write=False)
        offsets[direction] = (offset, base_offset)
    return offsets


def _expected_slab_pose(record):
    """Evaluate the one authority for production and validation; never mutate."""
    source = record.get("placement_source")
    if not isinstance(source, str):
        raise NativePlacementError("Native Full placement source must be an explicit authority identifier.",
            details={"identity": _identity(record), "field": "placement_source", "actual": source})
    if source in SLABLESS_SOURCES:
        is_modification = source == "chemical-modification-v1"
        if (not isinstance(record.get("extension_id"), str) or not record["extension_id"]
                or not isinstance(record.get("strand_id"), str) or not record["strand_id"]
                or record.get("is_modification") is not is_modification
                or (is_modification and (not isinstance(record.get("modification"), str) or not record["modification"]))):
            raise NativePlacementError("Slabless placement authority requires an explicit extension or chemical modification.",
                details={"identity": _identity(record), "placement_source": source,
                         **{key: record.get(key) for key in ("extension_id", "is_modification", "modification")}})
        for field in ("backbone_position", "base_position", "base_normal", "axis_tangent"):
            _vector(record, field)
        return None
    if source != SOURCE and source not in AUTHORED_SOURCES:
        raise NativePlacementError("Native Full record has no recognized placement authority.",
            details={"identity": _identity(record), "actual": source, "expected": SOURCE})
    bead = _vector(record, "backbone_position")
    try:
        frame = _frame(_vector(record, "base_normal"), _vector(record, "axis_tangent"))
    except NativePlacementError as error:
        error.details.setdefault("identity", _identity(record))
        raise
    if source == SOURCE:
        direction = record.get("direction")
        if not isinstance(direction, str) or direction not in _native_registration():
            raise NativePlacementError(f"Invalid native Full direction: {direction!r}.",
                details={"identity": _identity(record)})
        slab_offset, base_offset = _native_registration()[direction]
        actual_base_offset = frame.T @ (_vector(record, "base_position") - bead)
        if not np.allclose(actual_base_offset, base_offset, rtol=0, atol=1e-7):
            raise NativePlacementError("Native bead/base registration disagrees with its chemical template.",
                details={"identity": _identity(record), "expected_local_base_nm": base_offset.tolist(),
                         "actual_local_base_nm": actual_base_offset.tolist(),
                         "max_error_nm": float(np.max(abs(actual_base_offset - base_offset)))})
        center = bead + frame @ slab_offset
    else:
        # Deposited chemical conformations have their own actual landmarks.
        # They are never a fallback for an unplaceable native helical site.
        try:
            center = _contact_center(bead, _vector(record, "base_position"), frame)
        except NativePlacementError as error:
            error.details.setdefault("identity", _identity(record))
            raise
    return center, frame


def _expected_slab_poses(records):
    """Batch the native authority's arithmetic; retain its scalar error oracle.

    Authored chemical conformations and slabless records keep their existing
    paths. Any invalid native input is rechecked by the scalar authority, so
    batching cannot weaken registration checks or lose per-site diagnostics.
    """
    result = [None] * len(records)
    indices = [i for i, record in enumerate(records) if record.get("placement_source") == SOURCE]
    native = [records[i] for i in indices]
    try:
        arrays = [np.asarray([r.get(field) for r in native], dtype=float)
                  for field in ("backbone_position", "base_position", "base_normal", "axis_tangent")]
        valid = all(a.shape == (len(native), 3) and np.all(np.isfinite(a)) for a in arrays)
        valid = valid and all(r.get("direction") in _native_registration() for r in native)
    except (TypeError, ValueError, OverflowError):
        valid = False
    if native and valid:
        beads, bases, normals, tangents = arrays
        lengths = np.linalg.norm(tangents, axis=1, keepdims=True)
        valid = bool(np.all(lengths >= 1e-12) and np.all(np.isfinite(lengths)))
        if valid:
            tangents = tangents / lengths
            normals = normals - tangents * np.sum(normals * tangents, axis=1, keepdims=True)
            lengths = np.linalg.norm(normals, axis=1, keepdims=True)
            valid = bool(np.all(lengths >= 1e-12) and np.all(np.isfinite(lengths)))
        if valid:
            normals = normals / lengths
            frames = np.stack((np.cross(tangents, normals), tangents, normals), axis=2)
            slab_offsets, base_offsets = map(np.asarray, zip(*(_native_registration()[r['direction']] for r in native)))
            actual_offsets = np.einsum('nji,nj->ni', frames, bases - beads)
            valid = bool(np.allclose(actual_offsets, base_offsets, rtol=0, atol=1e-7))
        if valid:
            centers = beads + np.einsum('nij,nj->ni', frames, slab_offsets)
            for i, center, frame in zip(indices, centers, frames):
                result[i] = center, frame
    if not valid:
        return [_expected_slab_pose(record) for record in records]
    for i, record in enumerate(records):
        if record.get("placement_source") != SOURCE:
            result[i] = _expected_slab_pose(record)
    return result


def attach_native_slab_poses(records):
    """Attach the only slab pose to final authoritative bead/base records."""
    # The same native authority and integrity checks, evaluated in arrays.
    posed_records = []
    frames = []
    for record, pose in zip(records, _expected_slab_poses(records)):
        if pose is None:
            record["slab_position"] = None
            record["slab_quaternion"] = None
            continue
        center, frame = pose
        record["slab_position"] = center.tolist()
        posed_records.append(record)
        frames.append(frame)
    if frames:
        quaternions = Rotation.from_matrix(np.asarray(frames)).as_quat().tolist()
        for record, quaternion in zip(posed_records, quaternions):
            record["slab_quaternion"] = quaternion
    return records


def authoritative_slab_pose(record):
    """Verify and consume a supplied authoritative pose; never repair a payload.

    A source label alone cannot bless malformed or retired coordinates. Producer
    and validator share the same definition, so caches or intermediate transforms
    cannot substitute finite but inconsistent bead/base/slab coordinates.
    """
    expected = _expected_slab_pose(record)
    if expected is None:
        if record.get("slab_position") is not None or record.get("slab_quaternion") is not None:
            raise NativePlacementError("Slabless chemical records cannot supply a slab pose.", details={"identity": _identity(record)})
        return None
    expected_center, expected_frame = expected
    center = _vector(record, "slab_position")
    try:
        quaternion = np.asarray(record.get("slab_quaternion"), dtype=float)
    except (TypeError, ValueError, OverflowError) as error:
        raise NativePlacementError("Nonnumeric authoritative native slab quaternion.",
            details={"identity": _identity(record), "field": "slab_quaternion",
                     "actual": record.get("slab_quaternion")}) from error
    if (quaternion.shape != (4,) or not np.all(np.isfinite(quaternion))
            or abs(np.linalg.norm(quaternion) - 1.) > 1e-6):
        raise NativePlacementError("Invalid authoritative native slab quaternion.", details=_identity(record))
    frame = Rotation.from_quat(quaternion).as_matrix()
    if not np.allclose(center, expected_center, rtol=0, atol=1e-7):
        raise NativePlacementError("Supplied native slab center disagrees with its authoritative nucleotide pose.",
            details={"identity": _identity(record), "expected_center_nm": expected_center.tolist(),
                     "actual_center_nm": center.tolist(),
                     "max_error_nm": float(np.max(abs(center - expected_center)))})
    if not np.allclose(frame, expected_frame, rtol=0, atol=1e-7):
        raise NativePlacementError("Supplied native slab orientation disagrees with its authoritative nucleotide frame.",
            details={"identity": _identity(record), "expected_frame": expected_frame.tolist(),
                     "actual_frame": frame.tolist(),
                     "max_component_error": float(np.max(abs(frame - expected_frame)))})
    return center, frame


def authoritative_slab_poses(records):
    """Consume the supplied poses with batched, unchanged authority checks."""
    expected = _expected_slab_poses(records)
    indices = [i for i, pose in enumerate(expected) if pose is not None]
    if not indices:
        return [authoritative_slab_pose(record) for record in records]
    try:
        centers = np.asarray([records[i].get('slab_position') for i in indices], dtype=float)
        quaternions = np.asarray([records[i].get('slab_quaternion') for i in indices], dtype=float)
        valid = (centers.shape == (len(indices), 3) and quaternions.shape == (len(indices), 4)
                 and np.all(np.isfinite(centers)) and np.all(np.isfinite(quaternions))
                 and np.all(abs(np.linalg.norm(quaternions, axis=1) - 1.) <= 1e-6))
        if valid:
            frames = Rotation.from_quat(quaternions).as_matrix()
            valid = (np.allclose(centers, [expected[i][0] for i in indices], rtol=0, atol=1e-7)
                     and np.allclose(frames, [expected[i][1] for i in indices], rtol=0, atol=1e-7))
    except (TypeError, ValueError, OverflowError):
        valid = False
    if not valid:
        return [authoritative_slab_pose(record) for record in records]
    result = [None] * len(records)
    for i, center, frame in zip(indices, centers, frames):
        result[i] = center, frame
    for i, pose in enumerate(expected):
        if pose is None:
            result[i] = authoritative_slab_pose(records[i])
    return result
