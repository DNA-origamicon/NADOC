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
    for _ in range(40):
        if live.state["sidebars"][hand]["focus_id"] == identifier:
            return
        if live.state["sidebars"][hand]["focus_id"] == "scrollbar":
            pad(live, hand, x=1)
        else:
            pad(live, hand, y=-1)
    raise AssertionError("Unreachable focus target: " + identifier)


def hold(live, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        live.frame()
        time.sleep(0.015)


def capture(live, output, name):
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
        for hand in (0, 1):
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
            pad(live, hand, x=1)
            tab = next(
                t
                for t in catalog["tabs"]
                if t["side"] == ("left" if hand == 0 else "right")
                and t["key"] == live.state["sidebars"][hand]["tab"]
            )
            while live.state["sidebars"][hand]["offset"]:
                seek(live, hand, "scrollbar")
                pad(live, hand, y=1)
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
            assert live.state["sidebars"][hand]["offset"] == old + 8
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
        # Enter Tools and detailed settings entirely through the pad.
        for _ in range(8):
            if live.state["sidebars"][1]["tab"] == "tools":
                break
            pad(live, 1, x=1)
        seek(live, 1, "tool-settings")
        live.button("trigger", hand=1)
        assert live.state["menu"] == "tools" and live.state["sidebars"][0]["open"]
        pad(live, 1)
        assert live.state["menu_input_mode"] == "trackpad"
        live.button("menu", hand=0)
        live.button("menu", hand=0)
        assert live.state["menu_input_mode"] == "trackpad"
        checks["opposite_menu_toggle_preserves_focus"] = True
        unsupported = next(
            c for c in live.state["controls"] if c["label"] == "MOVE ROTATE"
        )
        assert not unsupported["enabled"]
        for _ in range(40):
            if live.state["menu_focus_hit"] == str(unsupported["hit"]):
                break
            pad(live, 1, y=-1)
        assert live.state["menu_focus_hit"] == str(unsupported["hit"])
        before = (live.state["tool"], live.state["tool_sequence"])
        live.button("trigger", hand=1)
        assert before == (live.state["tool"], live.state["tool_sequence"])
        checks["detailed_disabled_inert"] = True
        live.capture_to(
            output / "detailed-focus",
            files=["left.png", "right.png", "mirror.png", "evidence.json"],
            discard_source=True,
        )
        target = next(c for c in live.state["controls"] if c["label"] == "INSPECT")
        for _ in range(40):
            if live.state["menu_focus_hit"] == str(target["hit"]):
                break
            pad(live, 1, y=-1)
        assert live.state["menu_focus_hit"] == str(target["hit"])
        live.button("trigger", hand=1)
        assert live.state["tool"] == "inspect"
        checks["detailed_menu_trigger"] = True
        pad(live, 1)
        assert live.state["menu_input_mode"] == "pointer"
        live.button("menu", hand=1)
        live.button("menu", hand=1)
        checks["passed"] = True
        return checks
    finally:
        (output / "focus-checks.json").write_text(
            json.dumps({"checks": checks, "trials": trials}, indent=2) + "\n"
        )
