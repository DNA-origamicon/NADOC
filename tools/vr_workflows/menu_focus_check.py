"""ScryWrite focus navigation and pointer handoff through production input."""

import json
import time
import numpy as np
from PIL import Image
from .menu_pixels import check as check_pixels


def pad(live, hand, x=0, y=0):
    live.send("trackpad_axis", hand=hand, x=x, y=y)
    live.button("trackpad", hand=hand)
    live.frame()


def seek(live, hand, identifier):
    """Use physical columns, never a flattened list or a wraparound shortcut."""
    side = "left" if hand == 0 else "right"
    def column(key):
        if key.startswith("tab:"):
            return 0 if hand == 0 else 2
        if key == "scrollbar":
            return 1
        return 2 if hand == 0 else 0
    if live.state["sidebars"][hand]["input_mode"] != "trackpad":
        pad(live, hand)
    for _ in range(40):
        current = live.state["sidebars"][hand]["focus_id"]
        if current == identifier:
            return
        controls = {c["id"]: c for c in live.state["controls"]
                    if c.get("sidebar") == side}
        if current not in controls:
            # Focus can advance before the 200 ms row reveal exports its hit box.
            hold(live, .25)
            controls = {c["id"]: c for c in live.state["controls"]
                        if c.get("sidebar") == side}
        source, target = controls[current], controls[identifier]
        delta = column(identifier) - column(current)
        if delta:
            pad(live, hand, x=1 if delta > 0 else -1)
        else:
            displacement = np.asarray(target["position"]) - source["position"]
            up = np.asarray(source["hit_half_up"])
            right = np.asarray(source["hit_half_right"])
            y = float(displacement @ up / np.linalg.norm(up))
            x = float(displacement @ right / np.linalg.norm(right))
            if abs(y) > 0.015:
                pad(live, hand, y=1 if y > 0 else -1)
            else:
                pad(live, hand, x=1 if x > 0 else -1)
    raise AssertionError("Unreachable focus target: " + identifier)


def hold(live, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        live.frame()
        time.sleep(0.015)


def capture(live, output, name):
    hold(live, .25)  # Let the 200 ms row animation settle before pixel evidence.
    evidence, _ = live.capture_to(
        output / name,
        files=["left.png", "right.png", "mirror.png", "evidence.json"],
        discard_source=True,
    )
    pixels = check_pixels(output / name, evidence)
    assert pixels["passed"], [p for p in pixels["controls"] if not p["passed"]]
    # Amber exists only on the focus ring/mode label, never on an ordinary tab.
    for eye in ("left", "right"):
        rgb = np.asarray(Image.open(output / name / (eye + ".png")).convert("RGB"))
        amber = (rgb[:, :, 0] > 200) & (rgb[:, :, 1] > 150) & (rgb[:, :, 2] < 140)
        assert amber.sum() > 40, f"Focus missing in {eye}"
    (output / name / "pixels.json").write_text(json.dumps(pixels, indent=2) + "\n")


def run(live, catalog, output, preset):
    from .menu_tour import click

    checks = {}
    trials = []
    try:
        from .menu_section_check import run as section_checks
        checks.update(section_checks(live, catalog, output, preset, trials))
        head = live.state["head_position"]
        for hand in (1,):
            # Ray points away from both panels. All navigation/activation below
            # must work through pad/trigger, without aim_menu or pose snapping.
            live.send(
                "pose",
                hand=hand,
                position=[head[0], head[1] - 0.2, head[2]],
                orientation=[0, 1, 0, 0],
            )
            if live.state["sidebars"][hand]["input_mode"] == "trackpad":
                pad(live, hand)
            other = dict(live.state["sidebars"][1 - hand])
            pad(live, hand)
            assert live.state["sidebars"][hand]["input_mode"] == "trackpad"
            hold(live, 0.6)
            assert live.state["sidebars"][hand]["input_mode"] == "trackpad"
            # Explicitly choose a long tab with unavailable rows.
            available_tabs = {c["id"] for c in live.state["controls"]
                              if c.get("sidebar") == ("left" if hand == 0 else "right")}
            target_tab = "dynamics" if hand == 0 else (
                "assembly" if "tab:assembly" in available_tabs else "properties")
            seek(live, hand, "tab:" + target_tab)
            live.button("trigger", hand=hand)
            tab = next(
                t
                for t in catalog["tabs"]
                if t["side"] == ("left" if hand == 0 else "right")
                and t["key"] == live.state["sidebars"][hand]["tab"]
            )
            while live.state["sidebars"][hand]["offset"]:
                seek(live, hand, "scrollbar")
                pad(live, hand, y=1)
            # Down/up cannot leave the tab column or activate a different tab.
            tabs = [c["id"] for c in live.state["controls"]
                    if c.get("sidebar") == ("left" if hand == 0 else "right")
                    and c["id"].startswith("tab:")]
            seek(live, hand, tabs[-1])
            pad(live, hand, y=-1)
            assert live.state["sidebars"][hand]["focus_id"] == tabs[-1]
            seek(live, hand, tabs[0])
            pad(live, hand, y=1)
            assert live.state["sidebars"][hand]["focus_id"] == tabs[0]
            assert live.state["sidebars"][hand]["tab"] == tab["key"]
            inward = 1 if hand == 0 else -1
            pad(live, hand, x=inward)
            assert live.state["sidebars"][hand]["focus_id"] == "scrollbar"
            pad(live, hand, x=inward)
            assert not live.state["sidebars"][hand]["focus_id"].startswith("tab:")
            # Content now scrolls one row at its visible edge. Traverse the
            # actual full column before testing that its final row is bounded.
            for _ in range(len(tab["rows"]) + 2):
                previous = live.state["sidebars"][hand]["focus_id"]
                pad(live, hand, y=-1)
                if previous == live.state["sidebars"][hand]["focus_id"]:
                    break
            hold(live, 0.25)
            bottom = live.state["sidebars"][hand]["focus_id"]
            pad(live, hand, y=-1)
            assert live.state["sidebars"][hand]["focus_id"] == bottom
            assert bottom != "scrollbar" and not bottom.startswith("tab:")
            capture(live, output, f"{hand}-bounded-content")
            checks[f"{hand}_bounded_columns"] = True
            seek(live, hand, "scrollbar")
            while live.state["sidebars"][hand]["offset"]:
                pad(live, hand, y=1)
            hold(live, 0.25)
            disabled = next(r for r in tab["rows"][:8] if not r["action"])
            seek(live, hand, disabled["id"])
            capture(live, output, f"{hand}-disabled-focus")
            before = {
                k: live.state.get(k)
                for k in (
                    "tool_sequence",
                    "owner_tokens",
                    "representation",
                    "scene_revision",
                )
            }
            live.button("trigger", hand=hand)
            assert before == {k: live.state.get(k) for k in before}
            assert live.state["sidebars"][1 - hand]["tab"] == other["tab"]
            checks[f"{hand}_disabled_inert_independent"] = True
            seek(live, hand, "scrollbar")
            old = live.state["sidebars"][hand]["offset"]
            pad(live, hand, y=-1)
            assert live.state["sidebars"][hand]["offset"] == old + 1
            assert live.state["sidebars"][hand]["focus_id"] == "scrollbar"
            pad(live, hand, y=1)
            assert live.state["sidebars"][hand]["offset"] == old
            pad(live, hand, y=-1)
            capture(live, output, f"{hand}-scroll-focus")
            pad(live, hand)
            assert live.state["sidebars"][hand]["input_mode"] == "pointer"
            checks[f"{hand}_scroll_and_explicit_pointer"] = True
            # Acquire the narrow rail using this profile's noisy pointer, then
            # trigger at its middle to move the thumb through production input.
            click(live, hand, "scrollbar", preset, trials)
            assert 0 < live.state["sidebars"][hand]["offset"] < len(tab["rows"])
            checks[f"{hand}_pointer_scrollbar"] = True
        # A resting ray on the opposite sidebar must not cancel pad navigation.
        left_target = next(
            c for c in live.state["controls"] if c.get("sidebar") == "left"
        )
        live.send("aim_menu", hand=1, label=left_target["label"])
        live.frame()
        pad(live, 1)
        hold(live, 0.7)
        assert live.state["sidebars"][1]["input_mode"] == "trackpad"
        checks["opposite_resting_ray_cannot_steal"] = True
        pad(live, 1)
        # Deliberate noisy ray acquisition must restore pointing, without a click
        # activating the old focus. The helper clicks only after native hover agrees.
        pad(live, 1)
        target = next(
            c
            for c in live.state["controls"]
            if c.get("sidebar") == "right"
            and not c["enabled"]
            and not c["id"].startswith("scroll:")
        )
        click(live, 1, target["id"], preset, trials)
        assert live.state["sidebars"][1]["input_mode"] == "pointer"
        checks["dwell_handoff"] = True
        # A ray left resting on that same control cannot steal focus back.
        pad(live, 1)
        hold(live, 0.7)
        assert live.state["sidebars"][1]["input_mode"] == "trackpad"
        checks["resting_ray_cannot_steal"] = True
        # Enter Tools and activate actions entirely through sidebar pad focus.
        seek(live, 1, "tab:tools")
        live.button("trigger", hand=1)
        assert live.state["sidebars"][1]["tab"] == "tools"
        assert live.state["sidebars"][0]["open"]
        assert live.state["sidebars"][1]["input_mode"] == "trackpad"
        live.button("menu", hand=0)
        live.button("menu", hand=0)
        assert live.state["sidebars"][1]["input_mode"] == "trackpad"
        checks["opposite_menu_toggle_preserves_focus"] = True
        seek(live, 1, "tool-extrude")
        live.button("trigger", hand=1)
        seek(live, 1, "extrude:confirm")
        unsupported = next(c for c in live.state["controls"] if c.get("id") == "extrude:confirm")
        assert not unsupported["enabled"]
        before = (live.state["tool"], live.state["tool_sequence"])
        live.button("trigger", hand=1)
        assert before == (live.state["tool"], live.state["tool_sequence"])
        checks["sidebar_disabled_inert"] = True
        seek(live, 1, "extrude:back")
        live.button("trigger", hand=1)
        seek(live, 1, "tool-inspect")
        # The text-button oracle applies to Tools. Extrude's raised wheels and
        # painter overlap have their own renderer/interaction pixel checks.
        capture(live, output, "tools-focus")
        before = [(s["open"], s["tab"]) for s in live.state["sidebars"]]
        live.button("trigger", hand=1)
        assert live.state["tool"] == "inspect"
        assert before == [(s["open"], s["tab"]) for s in live.state["sidebars"]]
        checks["sidebar_tool_trigger_preserves_panels"] = True
        pad(live, 1)
        assert live.state["sidebars"][1]["input_mode"] == "pointer"
        checks["passed"] = True
        return checks
    finally:
        (output / "focus-checks.json").write_text(
            json.dumps({"checks": checks, "trials": trials}, indent=2) + "\n"
        )
