"""All directed native representation switches on a read-only design snapshot.

Uses physical OpenXR, ScryWrite controller input and the production visualization
feed. A private responder acknowledges style requests; browser polling latency is
not included. Never modifies the source design or attaches to a user's viewer.
"""

import argparse
import hashlib
import itertools
import json
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

import numpy as np
from backend.api import routes_vr as vr, state
from backend.api.doc_context import set_current_doc, reset_current_doc
from backend.core.models import Design
from frontend.scrywrite.mcp_bridge import Bridge
from tools.vr_motion.session import LiveSession
from tools.vr_motion.presets import PRESETS
from tools.vr_workflows.menu_tour import click, scroll_page, enlarge_mirror

REPS = {
    "cylinders": "menu-view-detail-cylinders",
    "full": "menu-view-detail-full",
    "ballstick": "menu-view-atomistic-ballstick",
    "stick": "menu-view-atomistic-stick",
}
ROOT = Path(__file__).resolve().parents[2]


def transitions():
    return list(itertools.permutations(REPS, 2))


def _produce_snapshot(raw, destination):
    doc = "__test_vr_representations_" + uuid.uuid4().hex
    token = set_current_doc(doc)
    try:
        state.set_design(Design.from_json(raw.decode()))
        with destination.open("w", buffering=1024 * 1024) as stream:
            vr._snapshot(
                vr.VRLaunchRequest(), line_writer=lambda line: stream.write(line + "\n")
            )
    finally:
        state.drop_doc(doc)
        reset_current_doc(token)


def export_design(source, destination, *, use_cache=True):
    from tools.vr_workflows.snapshot_cache import prepare

    raw = source.read_bytes()
    result = prepare(raw, destination, _produce_snapshot, enabled=use_cache)
    return dict(source=str(source), sha256=hashlib.sha256(raw).hexdigest(),
                snapshot_bytes=destination.stat().st_size, **result)



def check_framing(evidence, directory):
    """Require visible, unclipped design pixels separate from the sidebar."""
    assert not evidence["state"]["sidebars"][0]["open"]
    result = {}
    for eye in evidence["eyes"]:
        pixels = np.fromfile(directory / (eye["eye"] + ".classes.u8"), dtype=np.uint8).reshape(eye["height"], eye["width"])
        y, x = np.where(pixels == 1)
        assert len(x) > 100, "Design is not visible"
        assert x.min() > 0 and x.max() < eye["width"] - 1
        assert y.min() > 0 and y.max() < eye["height"] - 1
        menu_y, menu_x = np.where(pixels == 3)
        assert len(menu_x), "Right menu is not visible"
        assert x.max() < menu_x.min(), "Right menu overlaps the design's view"
        result[eye["eye"]] = dict(design_pixels=len(x), design_bounds=[int(x.min()), int(y.min()), int(x.max()), int(y.max())], menu_gap_px=int(menu_x.min() - x.max()))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--design", type=Path, default=ROOT / "workspace/24hb_0xT.nadoc"
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        help="Reuse an already exported snapshot for paired renderer comparisons",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT
        / ".development-artifacts/vr-representations"
        / ("tour-" + uuid.uuid4().hex[:12]),
    )
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--no-cache", action="store_true", help="Measure a fresh design export without reading or populating the cache")
    parser.add_argument("--repeats", type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 10:
        parser.error("--repeats must be 1..10")
    from backend.api.routes_vr_tours import _viewer_active

    if _viewer_active():
        raise RuntimeError("Close the active native viewer before this isolated tour.")
    startup_started = time.perf_counter()
    args.output.mkdir(parents=True, exist_ok=False)
    snapshot = args.snapshot or args.output / "scene.nadocvr"
    if not args.snapshot:
        print("Preparing VR design snapshot…", flush=True)
        exported = export_design(args.design, snapshot, use_cache=not args.no_cache)
        (args.output / "export.json").write_text(json.dumps(exported, indent=2))
        print("VR_EXPORT " + json.dumps(exported), flush=True)
    vr._ensure_viewer_built()
    if _viewer_active():
        raise RuntimeError("A native viewer started during export/build; refusing to replace it.")
    vr._start_steamvr()
    live = None
    process = None
    stopping = threading.Event()
    trials = []
    results = []
    errors = []
    with tempfile.TemporaryDirectory(prefix="nadoc-representations-") as temporary:
        root = Path(temporary)
        events = root / "events.json"
        visual = root / "visualization.txt"
        socket = root / "viewer.sock"

        def publish(seq, representation, coloring="strand"):
            pending = visual.with_suffix(".tmp")
            pending.write_text(
                vr._visualization_snapshot_record(
                    [],
                    sequence=seq,
                    mode="design",
                    view_rotation=np.eye(3),
                    representation=representation,
                    coloring=coloring,
                )
            )
            pending.replace(visual)

        publish(1, "full")

        def respond():
            last = 0
            while not stopping.wait(0.01):
                try:
                    if not events.exists():
                        continue
                    event = json.loads(events.read_text())
                    seq = event.get("style_sequence", 0)
                    if seq > last:
                        publish(seq + 1, event["representation"], event["coloring"])
                        last = seq
                except (FileNotFoundError, json.JSONDecodeError):
                    # Native event publication can be observed during replacement.
                    # Retry the next poll, as the desktop event reader does.
                    continue
                except Exception as error:
                    errors.append(str(error))
                    return

        responder = threading.Thread(target=respond, daemon=True)
        responder.start()
        command = [
            str(ROOT / "native/vr_viewer/build/nadoc-vr-viewer"),
            str(snapshot.resolve()),
            "--events",
            str(events),
            "--visualization",
            str(visual),
            "--scrywrite-live",
            str(socket),
            "--scrywrite-live-mode",
            "transactions",
            "--mirror-eye",
            "left",
            "--reference-grid",
            "off",
            "--place-scene-in-view",
            "on",
            "--scene-view",
            "mirror",
            "--scene-orientation",
            "isometric",
            "--scene-distance",
            "1.30",
            "--scene-scale",
            "3.0",
            "--mirror-diagnostics",
            str((args.output / "mirror.jsonl").resolve()),
        ]
        try:
            if _viewer_active():
                raise RuntimeError("A native viewer is now active; refusing to launch over it.")
            launched_at = time.perf_counter()
            with (args.output / "viewer.log").open("w") as log:
                process = subprocess.Popen(
                    command,
                    env=vr._build_environment(),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            (args.output / "launch.json").write_text(
                json.dumps({"pid": process.pid, "command": command}, indent=2)
            )
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("Viewer exited; inspect viewer.log")
                try:
                    live = LiveSession(
                        Bridge(str(socket)), physical=True, allow_transactions=True
                    )
                    break
                except (RuntimeError, ValueError, OSError):
                    time.sleep(0.2)
            if live is None:
                raise RuntimeError("Viewer did not become ready")
            (args.output / "loading.json").write_text(
                json.dumps(
                    {
                        "launch_to_live_ready_s": time.perf_counter() - launched_at,
                        "startup_to_live_ready_s": time.perf_counter() - startup_started,
                        "snapshot_bytes": snapshot.stat().st_size,
                        "reused_snapshot": bool(args.snapshot),
                    },
                    indent=2,
                )
            )
            enlarge_mirror(live)
            placement_deadline = time.monotonic() + 30
            while "ScryWrite placement applied:" not in (args.output / "viewer.log").read_text():
                if time.monotonic() >= placement_deadline:
                    raise RuntimeError("Scene framing did not acquire a stable tracked-eye pose")
                live.frame()
                time.sleep(0.1)
            live.frame()
            head = live.state["head_position"]
            live.send(
                "pose",
                hand=1,
                position=[head[0] + 0.60, head[1] - 0.28, head[2] - 0.35],
                orientation=[0, 0, 0, 1],
            )
            if live.state["sidebars"][0]["open"]:
                live.button("menu", hand=0)
            if not live.state["sidebars"][1]["open"]:
                live.button("menu", hand=1)
            # Default sidebar opening is head-anchored; move its real grip frame
            # aside so the model and controls remain independently observable.
            from tools.vr_workflows.menu_grip_check import acquire, move

            placement_trials = []
            acquire(live, 1, 1, 1, "steady_fast", placement_trials)
            live.send("button", hand=1, button="grip", pressed=True)
            live.frame()
            assert live.state["sidebars"][1]["grip_state"] == "moving"
            left, right, *_ = map(np.asarray, live.state["sidebars"][1]["grip_targets"])
            delta = (right - left) / np.linalg.norm(right - left) * 0.35
            move(
                live,
                {1: (np.asarray(live.state["hands"][1]["position"]) + delta).tolist()},
                "steady_fast",
                placement_trials,
            )
            live.send("button", hand=1, button="grip", pressed=False)
            live.frame()
            (args.output / "observation-placement.json").write_text(
                json.dumps(placement_trials, indent=2)
            )
            click(live, 1, "tab:visualization", "steady_fast", trials)
            initial, _ = live.capture_to(args.output / "initial-view", files=["left.png", "right.png", "mirror.png", "left.classes.u8", "right.classes.u8", "evidence.json"], discard_source=True)
            (args.output / "framing.json").write_text(json.dumps(check_framing(initial, args.output / "initial-view"), indent=2))

            def switch(rep, preset):
                if live.state["representation"] == rep:
                    return
                identifier = REPS[rep]
                for _ in range(20):
                    if any(
                        c.get("id") == identifier and c.get("sidebar") == "right"
                        for c in live.state["controls"]
                    ):
                        break
                    scroll_page(live, 1, -1 if rep != "stick" else 1)
                started = time.perf_counter()
                click(live, 1, identifier, preset, trials)
                deadline = time.monotonic() + 20
                while (
                    live.state["representation"] != rep and time.monotonic() < deadline
                ):
                    live.frame()
                assert not errors, errors
                assert live.state["representation"] == rep, live.state["representation"]
                return (time.perf_counter() - started) * 1000

            for preset in PRESETS if args.validate else ["steady_fast"]:
                for repeat in range(args.repeats):
                    for source, target in transitions():
                        switch(source, preset)
                        start_size = (args.output / "viewer.log").stat().st_size
                        elapsed = switch(target, preset)
                        with (args.output / "viewer.log").open() as log:
                            log.seek(start_size)
                            metrics = [
                                line.strip()
                                for line in log
                                if "phase=style_apply " in line
                            ]
                        assert metrics, "Missing renderer style measurement"
                        name = f"{preset}-{repeat}-{source}-to-{target}"
                        evidence, _ = live.capture_to(
                            args.output / name,
                            files=[
                                "left.png",
                                "right.png",
                                "mirror.png",
                                "left.classes.u8",
                                "right.classes.u8",
                                "evidence.json",
                            ],
                            discard_source=True,
                        )
                        assert evidence["state"]["representation"] == target
                        coverage = {
                            eye["eye"]: int(
                                np.count_nonzero(
                                    np.fromfile(
                                        args.output
                                        / name
                                        / (eye["eye"] + ".classes.u8"),
                                        dtype=np.uint8,
                                    )
                                    == 1
                                )
                            )
                            for eye in evidence["eyes"]
                        }
                        framing = check_framing(evidence, args.output / name)
                        record = dict(
                            design_pixels=coverage,
                            framing=framing,
                            source=source,
                            target=target,
                            preset=preset,
                            repeat=repeat,
                            interaction_ms=elapsed,
                            style_metrics=metrics,
                            capture=name,
                        )
                        results.append(record)
                        (args.output / "result.json").write_text(
                            json.dumps(
                                {"transitions": results, "passed": False}, indent=2
                            )
                        )
                        print(name, metrics[-1], flush=True)
            from tools.vr_motion.desktop_check import run as desktop_check

            desktop = desktop_check(
                str(socket), args.output / "desktop", live=live, reveal=True
            )
            assert desktop["passed"], desktop
            (args.output / "result.json").write_text(
                json.dumps(
                    {"transitions": results, "passed": True, "desktop": desktop},
                    indent=2,
                )
            )
        finally:
            stopping.set()
            responder.join(timeout=2)
            (args.output / "trials.json").write_text(json.dumps(trials, indent=2))
            if live:
                try:
                    live.release()
                except (RuntimeError, OSError):
                    pass
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    main()
