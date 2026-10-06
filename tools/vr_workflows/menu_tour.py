"""Live ScryWrite tour of both desktop-mapped VR sidebars.

The command owns an isolated native viewer, never a document or browser session.
Every tab/page is inspected against the desktop catalog. Default motion is the
least steady fast preset; --validate runs steady_fast then all other presets.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from frontend.scrywrite.mcp_bridge import Bridge
from tools.vr_motion.session import LiveSession
from tools.vr_motion.metrics import target_metrics
from tools.vr_motion.presets import PRESETS
from tools.vr_workflows.profile_input import reach_target
from tools.vr_workflows.control_approach import control_approach
from tools.vr_workflows.menu_pixels import check as check_pixels


def context_catalog(catalog, state):
    """Omit the Assembly-only tab when the native session is a Part workspace.

    Other absent tabs stay in the tour and fail normally; context filtering must
    not turn a missing production control into passing reduced coverage.
    """
    visible = {(c.get("sidebar"), c["id"]) for c in state["controls"]}
    skipped = [
        {"side": t["side"], "tab": t["key"], "reason": "assembly_context_unavailable"}
        for t in catalog["tabs"]
        if t["key"] == "assembly" and (t["side"], "tab:assembly") not in visible
    ]
    excluded = {(t["side"], t["tab"]) for t in skipped}
    return {**catalog, "tabs": [t for t in catalog["tabs"]
                               if (t["side"], t["key"]) not in excluded]}, skipped


def find_control(live, hand, identifier):
    return next(
        c
        for c in live.state["controls"]
        if c.get("sidebar") == ("left" if hand == 0 else "right")
        and c.get("id") == identifier
    )


def acquired(state, hand, identifier):
    control = next(
        (
            c
            for c in state["controls"]
            if c.get("sidebar") == ("left" if hand == 0 else "right")
            and c.get("id") == identifier
        ),
        None,
    )
    return bool(
        control
        and state["sidebars"][hand]["hover_id"] == identifier
        and target_metrics(control, state["hands"][1])["predicted_hit"]
    )


def click(live, hand, identifier, preset, trials):
    for attempt in range(3):
        control = find_control(live, hand, identifier)
        trial = reach_target(
            live,
            control["position"],
            preset,
            4200 + len(trials),
            acquired=lambda s: acquired(s, hand, identifier),
            target_position=control_approach(
                control, live.state["hands"][1]["position"]
            ),
        )
        trial.update(side=hand, control=identifier, attempt=attempt + 1)
        trial["hit"] = bool(
            trial["acquired_with_feedback"] and acquired(live.state, hand, identifier)
        )
        trials.append(trial)
        if trial["hit"]:
            live.button("trigger", hand=1)
            live.frame()
            return
    raise RuntimeError(f"Noisy reach missed {hand}/{identifier} after three attempts")


def scroll_page(live, hand, direction):
    if hand == 0:
        from .sidebar_pointer_scroll import page
        return page(live, hand, direction)
    from .menu_focus_check import pad, seek
    if live.state["sidebars"][hand]["input_mode"] != "trackpad":
        pad(live, hand)
    seek(live, hand, "scrollbar")
    for _ in range(8):
        pad(live, hand, y=-direction)
    time.sleep(.25)  # One-row touchpad steps settle before the next measured reach.
    live.frame()
    pad(live, hand)  # Explicitly restore pointing for the next noisy reach.


def check_page(live, tab):
    side = 0 if tab["side"] == "left" else 1
    state = live.state["sidebars"][side]
    assert state["open"] and state["tab"] == tab["key"], state
    assert state["layout"] == "valid", state
    if tab["key"] == "dynamics" and any(c["id"]=="sim:jobs" for c in live.state["controls"]):
        return []  # Live jobs/results have their own document-backed simulation tour.
    rows = tab["rows"][state["offset"] : state["offset"] + 8]
    actual = {
        c["id"]: c for c in live.state["controls"] if c.get("sidebar") == tab["side"]
    }
    for row in rows:
        assert row["id"] in actual, row["id"]
        # Context can disable an implemented action, but never enable a missing one.
        if not row["action"]:
            assert not actual[row["id"]]["enabled"], row["id"]
    for row in rows:
        control = actual[row["id"]]
        assert sum(x * x for x in control["hit_half_up"]) ** 0.5 / state["scale"] >= 0.045, control
    return rows


def open_sidebar_for_review(live, hand, pose):
    """Reopen through normal input at an observed, reproducible wrist pose."""
    if live.state["sidebars"][hand]["open"]:
        return
    live.send("pose", hand=hand, position=pose["position"], orientation=pose["orientation_xyzw"])
    live.frame()
    live.button("menu", hand=hand)


def run_tour(live, catalog, output, preset, hold, quick, spawn_hands=None):
    trials = []
    visited = []
    spawn_hands = spawn_hands or [dict(h) for h in live.state["hands"]]
    try:
        for tab in catalog["tabs"]:
            hand = 0 if tab["side"] == "left" else 1
            # Expanded simulation panes can occlude the opposite sidebar. Inspect
            # each page with its own menu visible, through normal menu buttons.
            if live.state["sidebars"][1-hand]["open"]:
                live.button("menu", hand=1-hand)
            open_sidebar_for_review(live, hand, spawn_hands[hand])
            click(live, hand, "tab:" + tab["key"], preset, trials)
            while live.state["sidebars"][hand]["offset"]:
                scroll_page(live, hand, -1)
            while True:
                live.frame()
                rows = check_page(live, tab)
                offset = live.state["sidebars"][hand]["offset"]
                name = f"{tab['side']}-{tab['key']}-{offset}"
                print(preset, name, flush=True)
                evidence, _ = live.capture_to(
                    output / name,
                    files=["left.png", "right.png", "mirror.png", "evidence.json"],
                    discard_source=True,
                )
                pixels = check_pixels(output / name, evidence)
                (output / name / "pixels.json").write_text(
                    json.dumps(pixels, indent=2) + "\n"
                )
                assert pixels["passed"], [
                    r for r in pixels["controls"] if not r["passed"]
                ]
                visited.append(
                    {
                        "tab": tab["key"],
                        "side": tab["side"],
                        "offset": offset,
                        "ids": [r["id"] for r in rows],
                        "capture": name,
                    }
                )
                # A real disabled click must be consumed without changing tool/style/menu.
                if offset == 0:
                    disabled = next((r for r in rows if not r["action"]), None)
                    if disabled:
                        before = {
                            k: live.state.get(k)
                            for k in (
                                "representation",
                                "coloring",
                                "tool",
                                "tool_sequence",
                                "owner_tokens",
                            )
                        }
                        click(live, hand, disabled["id"], preset, trials)
                        assert before == {k: live.state.get(k) for k in before}
                        assert live.state["sidebars"][hand]["tab"] == tab["key"]
                # Review time is outside measured human reaches.
                time.sleep(hold)
                if tab["key"] == "vr":
                    click(live, hand, "vr-desktop", preset, trials)
                    from .desktop_panel_check import run as check_desktop_panel
                    from tools.vr_motion.desktop_check import reveal_viewer
                    reveal_viewer(live, lower=True)
                    try:
                        check_desktop_panel(live, output, preset, hand, trials, spawn_hands[hand])
                    finally:
                        reveal_viewer(live)
                if quick or offset + len(rows) >= len(tab["rows"]):
                    break
                scroll_page(live, hand, 1)
        for hand in (0, 1):
            open_sidebar_for_review(live, hand, spawn_hands[hand])
        if not quick:
            expected = {
                (t["side"], t["key"], r["id"])
                for t in catalog["tabs"]
                for r in t["rows"]
            }
            found = {(p["side"], p["tab"], r) for p in visited for r in p["ids"]}
            assert found == expected, (expected - found, found - expected)
        return {
            "passed": True,
            "pages": len(visited),
            "controls": sum(len(p["ids"]) for p in visited),
        }
    finally:
        (output / "trials.json").write_text(json.dumps(trials, indent=2) + "\n")
        (output / "pages.json").write_text(json.dumps(visited, indent=2) + "\n")


def check_actions(live, output, preset):
    """Exercise sidebar actions and their dedicated tool panels with real input."""
    trials = []
    checks = {}
    try:
        for hand in (0, 1):
            if not live.state["sidebars"][hand]["open"]:
                live.button("menu", hand=hand)
        click(live, 0, "tab:vr", preset, trials)
        checks["vr_controls_use_left_sidebar"] = live.state["sidebars"][0]["tab"] == "vr"
        click(live, 1, "tab:tools", preset, trials)
        before = [(p["open"], p["tab"]) for p in live.state["sidebars"]]
        click(live, 1, "tool-inspect", preset, trials)
        checks["inspect_active"] = live.state["tool"] == "inspect"
        checks["inspect_preserves_sidebars"] = before == [(p["open"], p["tab"]) for p in live.state["sidebars"]]
        from tools.vr_workflows.menu_navigation import sidebar_click
        def activate(hand, identifier):
            def input_click(label):
                control = next(c for c in live.state["controls"] if c["label"] == label)
                click(live, hand, control["id"], preset, trials)
            sidebar_click(live, input_click, identifier, hand)
            assert live.state["menu"] in ("sidebars", "closed")
            assert not any(c.get("id") in ("tool-settings", "vr-options")
                           or c.get("id", "").startswith("menu:") for c in live.state["controls"])
        def capture(name):
            live.capture_to(output / name,
                files=["left.png", "right.png", "mirror.png", "evidence.json"], discard_source=True)
        for identifier, panel in [("tool-extrude", "extrude"), ("tool-twist", "twist"),
                                  ("tool-bend", "bend"), ("tool-move", "move")]:
            activate(1, identifier)
            checks[panel + "_uses_right_sidebar"] = (
                live.state["sidebars"][1]["open"]
                and live.state["sidebars"][1]["tab"] == panel
                and live.state["sidebars"][0]["open"]
            )
            assert checks[panel + "_uses_right_sidebar"], checks
            capture("action-" + panel)
            activate(1, panel + ":back")
            assert live.state["sidebars"][1]["tab"] == "tools"
        activate(1, "tool-inspect")
        checks["selection_menu_removed"] = not any(c['id'].startswith('select:') for c in live.state['controls'])
        assert checks["selection_menu_removed"]
        activate(1, "tab:tools")
        while live.state["sidebars"][1]["offset"]:
            scroll_page(live, 1, -1)
        capture("action-tools")
        activate(0, "tab:dynamics")
        trajectory_id = "sim:trajectory" if any(c.get("id") == "sim:trajectory" for c in live.state["controls"]) else "vr-trajectory"
        activate(0, trajectory_id)
        checks["trajectory_uses_left_sidebar"] = (
            live.state["sidebars"][0]["tab"] == "trajectory"
            and live.state["trajectory"]["panel_open"]
            and live.state["sidebars"][1]["open"]
        )
        assert checks["trajectory_uses_left_sidebar"], live.state["trajectory"]
        for action in ("play", "previous", "next"):
            control = find_control(live, 0, "trajectory:" + action)
            sequence = live.state["trajectory"]["request_sequence"]
            activate(0, "trajectory:" + action)
            checks["trajectory_" + action] = (
                (live.state["trajectory"]["request_sequence"] > sequence) == bool(control["enabled"]))
        capture("action-trajectory")
        activate(0, "trajectory:back")
        checks["trajectory_return_restores_simulations"] = live.state["sidebars"][0]["tab"] == "dynamics"
        checks["only_sidebar_menu_state"] = live.state["menu"] == "sidebars"
        assert all(checks.values()), checks
        # Put the shortcut above the columns for observation, outside timed reaches.
        from tools.vr_motion.metrics import rotate

        anchor, _ = live.capture_to(
            output / "shortcut-anchor", files=["evidence.json"], discard_source=True
        )
        eye = anchor["eyes"][0]
        offset = rotate(eye["orientation_xyzw"], [0, 0.4, -0.5])
        live.send(
            "pose",
            hand=1,
            position=[a + b for a, b in zip(eye["position"], offset)],
            orientation=eye["orientation_xyzw"],
        )
        live.frame()
        # The shortcut is available when the matching sidebar is closed.
        live.button("menu", hand=1)
        # Hold the ordinary right trackpad shortcut, then close it without a choice.
        live.send("button", hand=1, button="trackpad", pressed=True)
        live.frame()
        live.capture_to(
            output / "right-trackpad-shortcut",
            files=["left.png", "right.png", "mirror.png", "evidence.json"],
            discard_source=True,
        )
        checks["right_trackpad_owns_input"] = (
            live.state["hands"][1]["input_owner"] == "radial"
        )
        from PIL import Image
        import numpy as np

        for eye_name in ("left", "right"):
            rgb = np.asarray(
                Image.open(
                    output / "right-trackpad-shortcut" / (eye_name + ".png")
                ).convert("RGB")
            )
            cyan = (rgb[:, :, 0] < 100) & (rgb[:, :, 1] > 140) & (rgb[:, :, 2] > 180)
            checks["shortcut_visible_" + eye_name] = int(cyan.sum()) >= 50
        live.button("menu", hand=1)
        live.send("button", hand=1, button="trackpad", pressed=False)
        checks["independent_after_actions"] = all(
            s["open"] for s in live.state["sidebars"]
        )
        assert all(checks.values()), checks
        return {"passed": True, "checks": checks}
    finally:
        (output / "actions.json").write_text(
            json.dumps({"checks": checks, "trials": trials}, indent=2) + "\n"
        )


def enlarge_mirror(live):
    """Enlarge and raise only this verified viewer; no display configuration change."""
    import ctypes as c
    import ctypes.util
    import re
    from tools.vr_motion.desktop_check import viewer_window, reveal_viewer

    window = int(viewer_window(live), 16)
    monitors = subprocess.check_output(["xrandr", "--listmonitors"], text=True)
    candidates = [line for line in monitors.splitlines() if "*" in line]
    if not candidates:
        return
    geometry = re.search(r"(\d+)/\d+x(\d+)/\d+\+(\d+)\+(\d+)", candidates[0])
    if not geometry:
        return
    width, height, x, y = map(int, geometry.groups())
    lib = c.CDLL(ctypes.util.find_library("X11"))
    lib.XOpenDisplay.argtypes = [c.c_char_p]
    lib.XOpenDisplay.restype = c.c_void_p
    lib.XMoveResizeWindow.argtypes = [
        c.c_void_p,
        c.c_ulong,
        c.c_int,
        c.c_int,
        c.c_uint,
        c.c_uint,
    ]
    lib.XSync.argtypes = [c.c_void_p, c.c_int]
    lib.XCloseDisplay.argtypes = [c.c_void_p]
    display = lib.XOpenDisplay(os.environ.get("DISPLAY", ":1").encode())
    if not display:
        raise RuntimeError("Cannot open X display for tour mirror")
    try:
        lib.XMoveResizeWindow(
            display,
            window,
            x + 20,
            y + 50,
            max(640, width - 60),
            max(480, height - 130),
        )
        lib.XSync(display, 0)
    finally:
        lib.XCloseDisplay(display)
    reveal_viewer(live)
    time.sleep(0.3)
    live.frame()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--action-checks", action="store_true", help="Check current tool, selection and trajectory routes")
    mode.add_argument("--qr-checks", action="store_true", help="Check Share-tab Vive camera preview and cancellation")
    mode.add_argument("--room-checks", action="store_true", help="Check frosted menus and the calibrated SteamVR floor")
    mode.add_argument("--dimension-checks", action="store_true", help="Check live dimensions, pinning, entry controls and model transforms")
    mode.add_argument("--remote-checks", action="store_true", help="Check fixed-ray trigger movement, two-controller and double-trigger resize")
    mode.add_argument("--grip-checks", action="store_true", help="Check border grabbing, movement and two-hand resize")
    mode.add_argument(
        "--focus-checks",
        action="store_true",
        help="Check trackpad focus, trigger activation and pointer handoff",
    )
    parser.add_argument("--depth-checks", action="store_true", help="Check sharp foreground controllers and behind-menu occlusion")
    parser.add_argument("--tab", help="Tour only this side:key, e.g. right:properties")
    parser.add_argument("--socket", help="Use an existing isolated control session")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--preset", choices=PRESETS, default="variable_fast")
    parser.add_argument(
        "--validate", action="store_true", help="Run all four presets in order"
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="First page of every tab; not full coverage",
    )
    parser.add_argument("--hold", type=float, default=1.5)
    parser.add_argument(
        "--exit",
        action="store_true",
        help="Exit after tour instead of holding menus for review",
    )
    mode.add_argument("--selection-checks", action="store_true", help="Check left touchpad selection wheel, haptics and release confirmation")
    mode.add_argument("--edit-checks", action="store_true", help="Check right touchpad edit wheel and history command publication")
    args = parser.parse_args()
    if args.edit_checks and args.socket:
        parser.error("--edit-checks requires its own isolated metadata fixture")
    if not 0 <= args.hold <= 30:
        parser.error("hold must be 0..30 seconds")
    root = Path(__file__).resolve().parents[2]
    os.chdir(root)
    output = args.output or root / ".development-artifacts/vr-sidebar" / time.strftime(
        "tour-%Y%m%d-%H%M%S"
    )
    catalog = json.loads((root / "native/vr_viewer/sidebar_catalog.json").read_text())
    if args.tab:
        if args.edit_checks or args.selection_checks or args.action_checks or args.remote_checks or args.focus_checks or args.grip_checks or args.dimension_checks or args.room_checks or args.depth_checks or args.qr_checks:
            parser.error('--tab is only supported by the sidebar page tour')
        tabs = [t for t in catalog['tabs'] if f"{t['side']}:{t['key']}" == args.tab]
        if not tabs:
            parser.error('Unknown sidebar tab: '+args.tab)
        catalog = {**catalog, 'tabs': tabs}
    output.mkdir(parents=True, exist_ok=False)
    proc = None
    live = None
    with tempfile.TemporaryDirectory(prefix="nadoc-menu-") as temp:
        try:
            socket = args.socket
            if not socket:
                from backend.api.routes_vr import (
                    _build_environment,
                    _start_steamvr,
                    _ensure_viewer_built,
                )

                _ensure_viewer_built()
                _start_steamvr()
                socket = str(Path(temp) / "viewer.sock")
                command = [
                    str(root / "native/vr_viewer/build/nadoc-vr-viewer"),
                    str(root / ("native/vr_viewer/examples/scrywrite_simple_origami.nadocvr" if args.room_checks or args.depth_checks or args.qr_checks else "native/vr_viewer/examples/empty_authoring.nadocvr")),
                    "--scrywrite-live",
                    socket,
                    "--scrywrite-live-mode",
                    "control",
                    "--mirror-eye",
                    "left",
                    "--reference-grid",
                    "off",
                ]
                if args.edit_checks:
                    # Owned empty scene + metadata only; never connected to a browser document.
                    edit_events = Path(temp)/"edit-events.json"
                    edit_events.with_suffix('.json.ligation').write_text("NADOC_LIGATION_1 1 READY 0\n")
                    command[command.index("control")] = "transactions"
                    command += ["--events", str(edit_events)]
                if args.action_checks:
                    # Metadata-only fixture: no browser, molecular coordinates or saved document.
                    trajectory = Path(temp) / "trajectory.txt"
                    trajectory.write_text("NADOCVR_TRAJECTORY 1 1 1 4 10 0 1 0 1 1\n")
                    command += ["--trajectory", str(trajectory)]
                with (output / "viewer.log").open("w") as log:
                    proc = subprocess.Popen(
                        command,
                        env=_build_environment(),
                        stdout=log,
                        stderr=subprocess.STDOUT,
                    )
                (output / "launch.json").write_text(
                    json.dumps(
                        {"pid": proc.pid, "command": command, "socket": socket},
                        indent=2,
                    )
                )
            deadline = time.monotonic() + 60
            while True:
                try:
                    live = LiveSession(Bridge(socket), physical=True, allow_transactions=args.edit_checks)
                    assert live.state["mode"] == ("transactions" if args.edit_checks else "control"), (
                        "Tour requires its isolated input mode"
                    )
                    break
                except (OSError, ValueError, RuntimeError):
                    if time.monotonic() > deadline or (
                        proc and proc.poll() is not None
                    ):
                        raise
                    time.sleep(0.2)
            enlarge_mirror(live)
            # Observe the real tracked view; place wrists so controller-spawned
            # panels remain visible without replacing physical headset tracking.
            from tools.vr_motion.metrics import rotate
            anchor, _ = live.capture_to(output / "spawn-anchor", files=["evidence.json"], discard_source=True)
            eye = anchor["eyes"][0]
            head, orientation = eye["position"], eye["orientation_xyzw"]
            for hand in (0, 1):
                offset = rotate(orientation, [-.30 if hand == 0 else .30, -.10, -.40])
                live.send("pose", hand=hand,
                          position=[a+b for a,b in zip(head, offset)], orientation=orientation)
                live.frame()
                if not live.state["sidebars"][hand]["open"]:
                    live.button("menu", hand=hand)
            live.frame()
            assert all(s["open"] for s in live.state["sidebars"])
            catalog, skipped = context_catalog(catalog, live.state)
            (output / "context-skips.json").write_text(json.dumps(skipped, indent=2) + "\n")
            if not catalog["tabs"]:
                raise RuntimeError("Requested tab is unavailable in this document context: " + str(skipped))
            # Independent toggling is checked through real controller input.
            live.button("menu", hand=0)
            assert (
                not live.state["sidebars"][0]["open"]
                and live.state["sidebars"][1]["open"]
            )
            live.button("menu", hand=0)
            spawn_hands = [dict(h) for h in live.state["hands"]]
            results = []
            if args.edit_checks:
                from .edit_wheel_check import run as edit_run
                focus_run = lambda live, catalog, destination, preset: edit_run(live, catalog, destination, preset, edit_events)
            elif args.selection_checks:
                from .selection_wheel_check import run as focus_run
            elif args.action_checks:
                focus_run = lambda live, _catalog, destination, preset: check_actions(live, destination, preset)
            elif args.remote_checks:
                from tools.vr_workflows.remote_border_check import run as focus_run
            elif args.depth_checks:
                from tools.vr_workflows.menu_depth_check import run as focus_run
            elif args.qr_checks:
                from tools.vr_workflows.qr_calibration_check import run as focus_run
            elif args.room_checks:
                from tools.vr_workflows.room_ui_check import run as focus_run
            elif args.dimension_checks:
                from tools.vr_workflows.dimensions_check import run as focus_run
            elif args.grip_checks:
                from tools.vr_workflows.menu_grip_check import run as focus_run
            elif args.focus_checks:
                from tools.vr_workflows.menu_focus_check import run as focus_run
            for preset in list(PRESETS) if args.validate else [args.preset]:
                destination = output / preset
                destination.mkdir()
                results.append(
                    {
                        "preset": preset,
                        **(
                            focus_run(live, catalog, destination, preset)
                            if args.edit_checks or args.selection_checks or args.action_checks or args.remote_checks or args.focus_checks or args.grip_checks or args.dimension_checks or args.room_checks or args.depth_checks or args.qr_checks
                            else run_tour(
                                live,
                                catalog,
                                destination,
                                preset,
                                args.hold,
                                args.quick,
                                spawn_hands,
                            )
                        ),
                    }
                )
                (output / "result.json").write_text(
                    json.dumps(results, indent=2) + "\n"
                )
            if not args.edit_checks and not args.selection_checks and not args.action_checks and not args.remote_checks and not args.tab and not args.room_checks and not args.depth_checks and not args.qr_checks:
                check_actions(live, output, args.preset)
            from tools.vr_motion.desktop_check import run as check_desktop

            desktop = check_desktop(socket, output / "desktop", live=live, reveal=True)
            if desktop["passed"]:
                print("Tour complete. Evidence:", output, flush=True)
            else:
                print(
                    "Menu interaction checks passed, but desktop verification FAILED. "
                    "The mirror may have moved or been obscured during capture. "
                    f"Details: {output / 'desktop' / 'desktop-check.json'}",
                    flush=True,
                )
            if args.exit or not (args.selection_checks or args.edit_checks):
                live.release()
            if not args.exit:
                print(
                    "Touchpad wheel remains open for review. Ctrl+C closes this tour viewer." if args.selection_checks or args.edit_checks
                    else "Menus remain open for review. Ctrl+C closes this tour viewer.",
                    flush=True,
                )
                try:
                    if args.edit_checks or args.selection_checks:
                        if args.edit_checks:
                            from .edit_wheel_check import review
                        else:
                            from .selection_wheel_check import review
                        review(live, lambda: proc is None or proc.poll() is None)
                    else:
                        while proc is None or proc.poll() is None:
                            time.sleep(0.5)
                except KeyboardInterrupt:
                    pass
            if not desktop["passed"]:
                raise SystemExit(1)
        finally:
            if live:
                try:
                    live.release()
                except (OSError, RuntimeError):
                    pass
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()


if __name__ == "__main__":
    main()
