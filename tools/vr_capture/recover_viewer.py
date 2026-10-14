#!/usr/bin/env python3
"""Recover a saved viewer into private files, with explicitly separate stages.

prepare copies verified baseline assets and writes a launch plan; it never starts
VR. launch starts the backed-up viewer or explicitly supplied recovery build,
without inherited capture-layer environment. A recovery build restores saved
presentation at startup and keeps normal physical input in inspect mode.
restore-presentation is an alternative diagnostic using ScryWrite grips: the
original binary's control/transactions modes do not return physical hand input.
No head tracking changes, saved design writes, or runtime restarts are made.

The cached representation can have a different normalization from the original
lazy-loaded scene. We restore source-nanometer -> tracking-meter placement, not
blindly the old model matrix in a different normalized coordinate system.
Physical registration across an OpenXR runtime restart is not established here.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import tempfile
import time


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def saved_option(argv, option):
    return argv[argv.index(option) + 1] if option in argv else None


def prepare(args):
    baseline = args.baseline.resolve()
    records = read_json(baseline / "processes.json")
    candidates = [p for p in records if Path(p["executable"]).name == "nadoc-vr-viewer"]
    if len(candidates) != 1:
        raise ValueError("Expected one backed-up NADOC viewer")
    process = candidates[0]
    argv = process["argv"]
    event = saved_option(argv, "--events")
    if not event:
        raise ValueError("Baseline viewer has no event sidecars")
    manifest = {row["source"]: row for row in read_json(baseline / "file-manifest.json")}

    def backup(source):
        row = manifest[source]
        path = baseline / row["backup"]
        if sha256(path) != row["sha256_backup"]:
            raise ValueError("Baseline backup hash mismatch: " + source)
        return path

    avatar = read_json(backup(event + ".avatar"))
    visualization_source = saved_option(argv, "--visualization")
    with backup(visualization_source).open() as stream:
        visualization_header = stream.readline().strip()
    fields = visualization_header.split()
    if len(fields) < 7 or fields[0] != "NADOCVR_VISUALIZATION":
        raise ValueError("Unsupported visualization header")
    representation = fields[4]
    # The ready representation is a complete gzip scene, even without .gz.
    status = backup(event + ".repr-status").read_text().splitlines()[0].split()
    if len(status) < 7 or status[0] != "NADOCVR_REP_STATUS" or status[5] != "ready" or status[4] != representation:
        raise ValueError("No matching completed cached representation")
    cached_source = event + ".repr-" + status[2]
    cached = backup(cached_source)
    with gzip.open(cached, "rt") as stream:
        scene_header = stream.readline().strip()
    if scene_header.split()[2] != representation:
        raise ValueError("Cached scene representation disagrees with visualization")
    executable_backup = backup(f"/proc/{process['pid']}/exe")
    if sha256(executable_backup) != process["executable_sha256"]:
        raise ValueError("Executable differs from active baseline process")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    output.chmod(0o700)
    assets = output / "assets"
    assets.mkdir(mode=0o700)
    copied = {}
    sources = {a for a in argv[1:] if a.startswith("/tmp/nadoc-vr-")}
    sources.update(s for s in manifest if s.startswith(event))
    for source in sorted(sources):
        path = backup(source)
        destination = assets / Path(source).name
        shutil.copy2(path, destination)
        destination.chmod(0o600)
        copied[source] = str(destination)
    original_executable = output / "nadoc-vr-viewer.original"
    shutil.copy2(executable_backup, original_executable)
    original_executable.chmod(0o700)
    executable = output / "nadoc-vr-viewer"
    shutil.copy2(args.viewer_binary.resolve() if args.viewer_binary else executable_backup, executable)
    executable.chmod(0o700)
    command = [str(executable), copied[cached_source]]
    changes = [{"option": "scene", "from": argv[1], "to": copied[cached_source],
                "reason": "Complete cached active representation, with saved Flex visualization"}]
    # Completed cache is loaded directly: startup's lazy initial-Full protocol
    # would otherwise attempt to publish Full after loading the Stick snapshot.
    omitted = {"--loading-status", "--scrywrite-live", "--scrywrite-live-mode", "--presentation-state"}
    if args.live_mode == "control":
        omitted.add("--events")
    for index in range(2, len(argv), 2):
        option, value = argv[index:index + 2]
        if option in omitted:
            changes.append({"option": option, "from": value, "to": None})
        else:
            command.extend([option, copied.get(value, value)])
    presentation_file = None
    if args.viewer_binary:
        saved = avatar["presentation"]
        similarity_scale(saved["model_to_tracking_rows"])
        normalization(saved)
        presentation_file = output / "saved-presentation.txt"
        rows = ["NADOCVR_PRESENTATION 1"]
        rows += [" ".join(format(v, ".9g") for v in row) for row in saved["model_to_tracking_rows"]]
        rows += [" ".join(format(v, ".9g") for v in saved["source_center_nm"]),
                 format(saved["normalization_model_per_nm"], ".9g"),
                 " ".join(format(v, ".9g") for v in saved["normalized_offset_model"])]
        presentation_file.write_text("\n".join(rows) + "\n")
        presentation_file.chmod(0o600)
        command.extend(["--presentation-state", str(presentation_file)])
    socket_path = None
    if args.live_mode != "off":
        socket_dir = Path(tempfile.mkdtemp(prefix="nadoc-vr-recover-", dir="/tmp"))
        socket_dir.chmod(0o700)
        socket_path = str(socket_dir / "viewer.sock")
        command.extend(["--scrywrite-live", socket_path, "--scrywrite-live-mode", args.live_mode])
    identity = pwd.getpwuid(os.getuid())
    # No os.environ.copy(): compositor instrumentation must not leak into viewer.
    environment = {"HOME": identity.pw_dir, "USER": identity.pw_name,
                   "LOGNAME": identity.pw_name, "LANG": "C.UTF-8"}
    environment.update(process["environment_whitelist"])
    plan = {
        "schema": "nadoc-viewer-recovery-1", "baseline": str(baseline),
        "baseline_pid": process["pid"], "baseline_executable_sha256": process["executable_sha256"],
        "executable_sha256": sha256(executable),
        "recovery_binary_source": str(args.viewer_binary.resolve()) if args.viewer_binary else None,
        "original_binary_copy": str(original_executable),
        "presentation_state": str(presentation_file) if presentation_file else None,
        "presentation_state_sha256": sha256(presentation_file) if presentation_file else None,
        "argv": command, "cwd": process["cwd"], "environment": environment,
        "socket": socket_path, "live_mode": args.live_mode, "argument_changes": changes,
        "copied_assets": [{"source": s, "copy": d, "sha256": sha256(d)} for s, d in copied.items()],
        "scene_header": scene_header, "visualization_header": visualization_header,
        "target_avatar": avatar, "viewer_started": False,
        "limitations": [
            "Private sidecars preserve snapshot presentation; the browser does not poll these private paths.",
            "Only the cached representation is resident; switching to absent styles requires a new export.",
            "Menu visibility/placement was not fully saved; those are not reconstructed.",
            ("Startup restores presentation; verify-presentation checks resulting coordinates."
             if presentation_file else "Original binary needs diagnostic grip recovery or manual pose placement."),
            "Control/transactions modes substitute simulated hands; inspect/off retain physical controllers.",
            "OpenXR LOCAL registration across runtime restart needs physical verification.",
        ],
    }
    write_json(output / "recovery-plan.json", plan)
    return {"plan": str(output / "recovery-plan.json"), "socket": socket_path,
            "prepared": True, "viewer_started": False}


def running_viewers():
    found = []
    for process in Path("/proc").iterdir():
        if not process.name.isdigit():
            continue
        try:
            command = (process / "cmdline").read_bytes().split(b"\0")
            if command and Path(os.fsdecode(command[0])).name == "nadoc-vr-viewer":
                found.append(int(process.name))
        except (OSError, ValueError):
            pass
    return found


def launch(args):
    plan_path = args.plan.resolve()
    plan = read_json(plan_path)
    existing = running_viewers()
    if existing:
        raise RuntimeError(f"Viewer already running, refusing a second session: {existing}")
    if (plan_path.parent / "launch.json").exists():
        raise RuntimeError("This recovery plan was already launched; prepare a new private plan")
    if sha256(plan["argv"][0]) != plan.get("executable_sha256", plan["baseline_executable_sha256"]):
        raise RuntimeError("Recovery executable hash changed")
    if plan.get("presentation_state") and sha256(plan["presentation_state"]) != plan["presentation_state_sha256"]:
        raise RuntimeError("Saved presentation state changed")
    for row in plan["copied_assets"]:
        if sha256(row["copy"]) != row["sha256"]:
            raise RuntimeError("Prepared asset changed: " + row["copy"])
    with (plan_path.parent / "viewer.log").open("ab", buffering=0) as log:
        process = subprocess.Popen(plan["argv"], cwd=plan["cwd"], env=plan["environment"],
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                   start_new_session=True)
    result = {"pid": process.pid, "started_unix": time.time(), "plan": str(plan_path),
              "socket": plan["socket"], "startup_success_verified": False}
    write_json(plan_path.parent / "launch.json", result)
    return result


def normalization(presentation):
    import numpy as np
    matrix = np.eye(4)
    scale = float(presentation["normalization_model_per_nm"])
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("Invalid scene normalization")
    matrix[:3, :3] *= scale
    matrix[:3, 3] = (np.array(presentation["normalized_offset_model"])
                     - scale * np.array(presentation["source_center_nm"]))
    return matrix


def similarity_scale(matrix):
    import numpy as np
    matrix = np.asarray(matrix, dtype=float)
    scale = float(np.linalg.norm(matrix[:3, 0]))
    rotation = matrix[:3, :3] / scale
    if (matrix.shape != (4, 4) or not np.isfinite(matrix).all() or scale <= 0
            or not np.allclose(matrix[3], [0, 0, 0, 1], atol=1e-6)
            or not np.allclose(rotation.T @ rotation, np.eye(3), atol=2e-5)
            or not np.isclose(np.linalg.det(rotation), 1, atol=2e-5)):
        raise ValueError("Expected a proper uniform presentation transform")
    return scale


def rotation_quaternion(rotation):
    """Rotation to quaternion, in OpenXR/ScryWrite XYZW order."""
    import numpy as np
    r = np.asarray(rotation)
    # Symmetric eigenproblem remains stable at rotations close to 180 degrees.
    k = np.array([
        [r[0,0]-r[1,1]-r[2,2], r[1,0]+r[0,1], r[2,0]+r[0,2], r[2,1]-r[1,2]],
        [r[1,0]+r[0,1], r[1,1]-r[0,0]-r[2,2], r[2,1]+r[1,2], r[0,2]-r[2,0]],
        [r[2,0]+r[0,2], r[2,1]+r[1,2], r[2,2]-r[0,0]-r[1,1], r[1,0]-r[0,1]],
        [r[2,1]-r[1,2], r[0,2]-r[2,0], r[1,0]-r[0,1], r.trace()],
    ]) / 3
    _, vectors = np.linalg.eigh(k)
    q = vectors[:, -1]
    return (q if q[3] >= 0 else -q).tolist()


def restore_presentation(args):
    import numpy as np
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root))
    from frontend.scrywrite.mcp_bridge import Bridge
    from tools.vr_motion.session import LiveSession

    plan_path = args.plan.resolve()
    plan = read_json(plan_path)
    launch_info = read_json(plan_path.parent / "launch.json")
    if plan["live_mode"] not in ("control", "transactions"):
        raise ValueError("Prepare with control or transactions for presentation recovery")
    if launch_info["pid"] not in running_viewers():
        raise RuntimeError("The planned recovery viewer is no longer running")
    report_path = plan_path.parent / "presentation-restore.json"
    if report_path.exists():
        raise RuntimeError("Presentation attempt already recorded; inspect before any retry")
    live = LiveSession(Bridge(socket_path=plan["socket"]), physical=True, allow_transactions=True)
    before = live.state
    target_saved = plan["target_avatar"]["presentation"]
    current_normalization = normalization(before["presentation"])
    target_source_to_tracking = np.array(target_saved["model_to_tracking_rows"]) @ normalization(target_saved)
    target = target_source_to_tracking @ np.linalg.inv(current_normalization)
    target_scale = similarity_scale(target)
    if not .05 <= target_scale <= 20:
        raise ValueError("Recovered scale exceeds ordinary grip limits")
    if before["representation"] != plan["scene_header"].split()[2]:
        raise RuntimeError("The expected active representation is not ready")
    if before.get("controller_prompt_open") or any(s["open"] for s in before.get("sidebars", [])):
        raise RuntimeError("A prompt or menu is open; inspect it before restoring the model")
    if before.get("tool") not in (None, "inspect"):
        raise RuntimeError("A design tool is active; model-only grip recovery refused")
    report = {"status": "in_progress", "before": before, "target_model_to_tracking_rows": target.tolist(),
              "method": "ordinary two-hand scale followed by one-hand rigid grip",
              "head_override": False, "physical_registration_verified": False,
              "normalization_compensated": not bool(np.allclose(normalization(target_saved), current_normalization, atol=1e-8))}
    write_json(report_path, report)

    def pose(hand, position, orientation=(0, 0, 0, 1)):
        live.send("pose", hand=hand, position=np.asarray(position).tolist(), orientation=list(orientation))
        live.frame()

    def grip(hand, pressed):
        live.send("button", hand=hand, button="grip", pressed=pressed)
        live.frame()

    try:
        live.release()
        live.frame()
        current = np.array(live.state["presentation"]["model_to_tracking_rows"])
        factor = target_scale / similarity_scale(current)
        anchor = np.array(live.state["head_position"]) + [0, -1, 0]
        if abs(factor - 1) > 1e-6:
            for hand, sign in ((0, -1), (1, 1)):
                pose(hand, anchor + [sign * .1, 0, 0])
            grip(0, True)
            grip(1, True)
            for hand, sign in ((0, -1), (1, 1)):
                pose(hand, anchor + [sign * .1 * factor, 0, 0])
            grip(0, False)
            grip(1, False)
        current = np.array(live.state["presentation"]["model_to_tracking_rows"])
        if not np.isclose(similarity_scale(current), target_scale, atol=2e-5):
            raise RuntimeError("Ordinary two-hand grip did not establish the requested scale")
        delta = target @ np.linalg.inv(current)
        quaternion = rotation_quaternion(delta[:3, :3])
        destination = delta[:3, :3] @ anchor + delta[:3, 3]
        pose(1, anchor)
        grip(1, True)
        pose(1, destination, quaternion)
        grip(1, False)
        actual = np.array(live.state["presentation"]["model_to_tracking_rows"])
        actual_source = actual @ normalization(live.state["presentation"])
        # Validate representative source points, not coefficient error alone.
        center = np.array(target_saved["source_center_nm"])
        points = np.column_stack((np.vstack([center, center + np.eye(3)*100, center - np.eye(3)*100]), np.ones(7)))
        errors = np.linalg.norm((actual_source @ points.T - target_source_to_tracking @ points.T)[:3], axis=0)
        report["max_reference_point_error_m"] = float(errors.max())
        report["raw_saved_model_matrix_max_abs_difference"] = float(np.max(np.abs(actual - np.array(target_saved["model_to_tracking_rows"]))))
        for key in ("scene_revision", "tool_sequence", "config_sequence", "committed_feature_id", "visualization_sequence"):
            if live.state.get(key) != before.get(key):
                raise RuntimeError("Non-presentation state changed: " + key)
        if float(errors.max()) > .0001:
            raise RuntimeError("Restored placement exceeds the 0.1 mm reference-point tolerance")
        report["status"] = "coordinate_placement_restored"
    except Exception as error:
        report["status"] = "failed"
        report["error"] = str(error)
        raise
    finally:
        try:
            live.release()
            live.frame()
            report["input_released"] = True
        except Exception as release_error:
            report["input_released"] = False
            report["release_error"] = str(release_error)
        report["after"] = live.state
        write_json(report_path, report)
    return {"report": str(report_path), "status": report["status"],
            "max_reference_point_error_m": report["max_reference_point_error_m"],
            "physical_registration_verified": False}


def verify_presentation(args):
    """Read-only numerical verification of native startup restoration."""
    import numpy as np
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from frontend.scrywrite.mcp_bridge import Bridge
    plan_path = args.plan.resolve()
    plan = read_json(plan_path)
    launch_info = read_json(plan_path.parent / "launch.json")
    if launch_info["pid"] not in running_viewers():
        raise RuntimeError("The planned recovery viewer is no longer running")
    state = Bridge(socket_path=plan["socket"]).call("scrywrite_observe", {})
    if "error" in state:
        raise RuntimeError(str(state))
    if not state.get("presentation_restore", {}).get("applied"):
        raise RuntimeError("Native presentation restoration has not yet applied")
    saved = plan["target_avatar"]["presentation"]
    expected = np.array(saved["model_to_tracking_rows"]) @ normalization(saved)
    actual = np.array(state["presentation"]["model_to_tracking_rows"]) @ normalization(state["presentation"])
    center = np.array(saved["source_center_nm"])
    points = np.column_stack((np.vstack([center, center+np.eye(3)*100, center-np.eye(3)*100]), np.ones(7)))
    errors = np.linalg.norm((actual @ points.T - expected @ points.T)[:3], axis=0)
    report = {"state": state, "max_reference_point_error_m": float(errors.max()),
              "physical_controllers_enabled": state.get("mode") == "inspect",
              "head_override": False, "physical_registration_verified": False,
              "representation_matches": state["representation"] == plan["scene_header"].split()[2]}
    report["passed"] = (report["max_reference_point_error_m"] <= .0001
                        and report["physical_controllers_enabled"] and report["representation_matches"])
    report_path = plan_path.parent / "presentation-verification.json"
    write_json(report_path, report)
    if not report["passed"]:
        raise RuntimeError("Recovered presentation verification failed: " + str(report_path))
    return {key: report[key] for key in ("passed", "max_reference_point_error_m", "physical_controllers_enabled", "physical_registration_verified")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare", help="Copy baseline into a new private recovery plan; no launch")
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--live-mode", choices=("off", "inspect", "control", "transactions"), default="inspect")
    p.add_argument("--viewer-binary", type=Path, help="Isolated build with --presentation-state support; original executable remains backed up")
    p.set_defaults(function=prepare)
    for command, function in (("launch", launch), ("restore-presentation", restore_presentation), ("verify-presentation", verify_presentation)):
        p = sub.add_parser(command)
        p.add_argument("--plan", type=Path, required=True)
        p.set_defaults(function=function)
    args = parser.parse_args()
    try:
        print(json.dumps(args.function(args), indent=2))
    except Exception as error:
        parser.exit(1, f"Recovery stopped: {error}\n")


if __name__ == "__main__":
    main()
