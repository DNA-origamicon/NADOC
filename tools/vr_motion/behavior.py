"""Import raw BEHAVIOR-100 HDF5; h5py is needed only for this adapter.

Layout verified against iGibson commit 04c01e85fbb50408135729089ac11a4b1d2dd61c:
utils/ig_logging.py and simulator.py. frame_data[:,3] is last_frame_dur,
not a timestamp; metadata render_timestep is simulation time, not human time.
"""
import copy
import hashlib
import math
from pathlib import Path

from .model import multiply, quaternion, validate_trace, vector


def catalog(directory, measure=False):
    """Index raw recordings without loading images or importing a simulator."""
    import h5py

    root = Path(directory).resolve()
    files = sorted(root.rglob('*.hdf5'))
    if not files:
        raise ValueError("no HDF5 recordings found")
    records = []
    for path in files:
        with h5py.File(path, 'r') as source:
            frames = source['frame_data']
            n = frames.shape[0]
            record = {'file': str(path.relative_to(root)), 'bytes': path.stat().st_size,
                'frames': n, 'task': str(source.attrs.get('/metadata/atus_activity', 'unknown')),
                'duration_s': None, 'timing_valid': None, 'hands': {}}
            if measure:
                # Read contiguous arrays before selecting columns. Strided HDF5
                # hyperslabs create excessive small disk reads on archive HDDs.
                duration = frames[()][1:, 3]
                valid_dt = all(math.isfinite(float(x)) and x > 0 for x in duration)
                record['duration_s'] = float(sum(duration)) if valid_dt else None
                record['timing_valid'] = bool(valid_dt)
            for hand in ('left', 'right'):
                rows = source[f'vr/vr_device_data/{hand}_controller']
                if rows.shape != (n, 27):
                    raise ValueError(f"unexpected controller shape: {path}")
                record['hands'][hand] = {'tracked_samples':
                    int((rows[()][:, 0] > 0).sum()) if measure else None}
            records.append(record)
    return {'schema': 'nadoc-behavior-catalog-1', 'root': str(root),
            'recordings': len(records), 'files': records, 'measured': measure,
            'time_basis': 'recorded last_frame_dur, approximate observation intervals'}


def import_behavior(path, start=0, count=300):
    import h5py

    if type(start) is not int or type(count) is not int or start < 0 or not 2 <= count <= 100000:
        raise ValueError("invalid source slice")
    path = Path(path)
    with h5py.File(path, "r") as source:
        total = source["frame_data"].shape[0]
        if start+count > total:
            raise ValueError("source slice exceeds recording")
        frames = source["frame_data"][start:start+count]
        hands = {h: source[f"vr/vr_device_data/{h}_controller"][start:start+count]
                 for h in ("left", "right")}
        analog = {h: source[f"vr/vr_button_data/{h}_controller"][start:start+count]
                  for h in hands}
        hmd = source["vr/vr_device_data/hmd"][start:start+count]
        samples, elapsed = [], 0.0
        for i, frame in enumerate(frames):
            if i:
                if frame[0] != frames[i-1][0]+1:
                    raise ValueError("nonconsecutive source frame indices")
                dt = float(frame[3])
                if not math.isfinite(dt) or not 0 < dt <= 10:
                    raise ValueError("missing/invalid measured frame duration; do not substitute nominal 30Hz")
                elapsed += dt
            def pose(row):
                return {"valid": bool(row[0] > 0), "position": row[1:4].tolist(),
                        "orientation": row[4:8].tolist()}
            sample = {"t": elapsed, "source_frame": int(frame[0]), "hands": {}, "head": pose(hmd[i])}
            for hand, rows in hands.items():
                sample["hands"][hand] = {**pose(rows[i]),
                    "analog": {"trigger": float(analog[hand][i][0]),
                               "touchpad": analog[hand][i][1:3].tolist()}}
            samples.append(sample)
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        trace = {"schema": "nadoc-motion-1", "space": "iGibson_world_unregistered",
            "units": "meters", "quaternion_order": "xyzw", "samples": samples, "events": [],
            "provenance": {"kind": "recorded", "dataset": "BEHAVIOR-100 VR raw v0.5.0",
                "source": str(path.resolve()), "sha256": digest, "start_frame": start,
                "time_basis": "cumulative recorded last_frame_dur; approximate observation intervals",
                "task": str(source.attrs.get('/metadata/atus_activity', 'unknown')),
                "nominal_simulation_dt": float(source.attrs['/metadata/render_timestep']),
                "buttons": "analog preserved as metadata; no implicit trigger/menu/grip event mapping"}}
    validate_trace(trace)
    return trace


def register(trace, rotation, translation, controller_rotation=(0, 0, 0, 1)):
    """Explicit rigid registration, with an optional local controller-axis correction.

    p_local=R*p_source+translation; q_local=R*q_source*C. No inferred floor,
    scaling, or target alignment. Caller supplies calibration from the source rig.
    """
    validate_trace(trace)
    if trace["space"] != "iGibson_world_unregistered":
        raise ValueError("registration requires an unregistered BEHAVIOR trace")
    q, c = quaternion(rotation), quaternion(controller_rotation)
    offset = vector(translation, 3)
    inverse = [-x for x in q[:3]]+[q[3]]
    result = copy.deepcopy(trace)
    for sample in result["samples"]:
        for key, pose in [*sample["hands"].items(), ("head", sample.get("head"))]:
            if not pose or not pose["valid"]:
                continue
            rotated = multiply(multiply(q, pose["position"]+[0]), inverse)[:3]
            pose["position"] = [v+d for v, d in zip(rotated, offset)]
            pose["orientation"] = multiply(q, quaternion(pose["orientation"]))
            if key != "head":
                pose["orientation"] = multiply(pose["orientation"], c)
    result["space"] = "OpenXR_LOCAL"
    result["provenance"]["registration"] = {"rotation_xyzw": q, "translation_m": offset,
        "controller_rotation_xyzw": c, "status": "caller_supplied_not_automatically_validated"}
    validate_trace(result)
    return result
