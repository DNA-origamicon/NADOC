"""Adapters to existing Witness and live MCP bridge; no new mutation pathway."""
import math
import time

from .model import validate_trace
from .session import LiveSession


def timeline(trace):
    # At equal timestamps, pose updates precede button transitions.
    items = [(s["t"], 0, s) for s in trace["samples"]]
    items += [(e["t"], 1, e) for e in trace.get("events", [])]
    return sorted(items, key=lambda x: (x[0], x[1]))


def witness(trace, rate_hz=90):
    validate_trace(trace, playable=True)
    if type(rate_hz) is not int or not 10 <= rate_hz <= 240:
        raise ValueError("invalid Witness rate")
    lines = ["SCRYWRITE_WITNESS 1", "# Generated motion; steps are runtime frames, not a wall-clock guarantee."]
    last_frame = 0
    button_frames = set()
    for t, kind, value in timeline(trace):
        frame = round(t*rate_hz)
        if frame > last_frame:
            lines.append(f"step {frame-last_frame}")
        last_frame = frame
        if kind:
            key = frame, value['hand'], value['button']
            if key in button_frames:
                raise ValueError("button edges collapse into one Witness frame; increase rate")
            button_frames.add(key)
            lines.append(f"button {value['hand']} {value['button']} {'down' if value['pressed'] else 'up'}")
        else:
            for hand, pose in value["hands"].items():
                x, y, z, w = pose["orientation"]
                numbers = [*pose["position"], w, x, y, z]
                lines.append(f"pose {hand} " + " ".join(format(n, '.10g') for n in numbers))
    # Process the final pose/button state for a frame before neutralizing inputs.
    lines.append("step 1")
    for hand in ("left", "right"):
        for button in ("menu", "grip", "trigger"):
            lines.append(f"button {hand} {button} up")
    lines.append("step 1")
    if len(lines)-2 > 10000:
        raise ValueError("Witness limit exceeded; export a shorter motion segment")
    return "\n".join(lines)+"\n"


def play_live(trace, bridge, *, allow_transactions=False, max_lag_s=0.15,
              clock=time.monotonic, sleep=time.sleep):
    """Paced inputs with session/sequence checks, frame barriers and final release.

    The live socket is not an atomic trajectory scheduler. Abort when deadlines
    slip rather than replaying a burst of stale poses. Never control the HMD.
    """
    validate_trace(trace, playable=True)
    if not math.isfinite(max_lag_s) or not 0 < max_lag_s <= 1:
        raise ValueError("invalid lag budget")
    if any(b["t"]-a["t"] > 0.5 for a, b in zip(trace["samples"], trace["samples"][1:])):
        raise ValueError("live samples must be <=0.5s apart to maintain the input lease")
    live = LiveSession(bridge, allow_transactions=allow_transactions)
    session = live.session
    if live.state['mode'] == 'inspect':
        raise ValueError('live playback requires control/transactions viewer')
    def send(name, args):
        return live.send(name, **args)
    barrier = live.frame

    maximum_lag = 0.0
    count = 0
    failure = None
    try:
        send("release", {})
        started = clock()
        for t, kind, value in timeline(trace):
            delay = started+t-clock()
            if delay > 0:
                sleep(delay)
            lag = clock()-started-t
            maximum_lag = max(maximum_lag, lag)
            if lag > max_lag_s:
                raise TimeoutError(f"motion deadline missed by {lag:.3f}s")
            if kind:
                send("button", {"hand": int(value["hand"] == "right"),
                    "button": value["button"], "pressed": value["pressed"]})
                # Acknowledge application of each edge before a following release.
                barrier()
            else:
                for hand, pose in value["hands"].items():
                    send("pose", {"hand": int(hand == "right"),
                        "position": pose["position"], "orientation": pose["orientation"]})
            count += 1
        barrier()
    except BaseException as error:
        failure = error
        raise
    finally:
        # A timed-out command may have been accepted. Observe its sequence before
        # release, but never resume the motion or release a replacement session.
        try:
            live.release()
        except Exception as cleanup_error:
            if failure is not None:
                failure.add_note("Input release failed: " + str(cleanup_error))
            else:
                raise
    return {"session": session, "items_sent": count, "max_lag_s": maximum_lag,
            "released": True, "evidence": "input delivery only; not design persistence or visual correctness"}
