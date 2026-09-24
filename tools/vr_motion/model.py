"""Small, dependency-free motion core. Synthetic parameters are not population fits.

Positions are metres; quaternions are XYZW. Correlated perturbations represent
combined movement variability, not a separately identified tracking-noise model.
"""
from dataclasses import asdict, dataclass
import math
import random


def vector(value, size):
    if not isinstance(value, (list, tuple)) or len(value) != size:
        raise ValueError(f"expected {size}-vector")
    if any(isinstance(x, bool) or not isinstance(x, (float, int)) or
           not math.isfinite(x) or abs(x) > 100 for x in value):
        raise ValueError("vector must be finite and within +/-100")
    return list(value)


def quaternion(value):
    q = vector(value, 4)
    norm = math.sqrt(sum(x*x for x in q))
    if not 0.99 <= norm <= 1.01:
        raise ValueError("quaternion must be normalized XYZW")
    return [x / norm for x in q]


def multiply(a, b):
    x, y, z, w = a
    X, Y, Z, W = b
    return [w*X+x*W+y*Z-z*Y, w*Y-x*Z+y*W+z*X,
            w*Z+x*Y-y*X+z*W, w*W-x*X-y*Y-z*Z]


def slerp(a, b, u):
    dot = sum(x*y for x, y in zip(a, b))
    if dot < 0:
        b, dot = [-x for x in b], -dot
    if dot > 0.9995:
        q = [(1-u)*x+u*y for x, y in zip(a, b)]
    else:
        theta = math.acos(min(1, dot))
        q = [(math.sin((1-u)*theta)*x + math.sin(u*theta)*y) / math.sin(theta)
             for x, y in zip(a, b)]
    norm = math.sqrt(sum(x*x for x in q))
    return [x/norm for x in q]


@dataclass(frozen=True)
class Profile:
    # Standard deviation per axis. Values are illustrative stress-test settings.
    position_sigma_m: float = 0.002
    rotation_sigma_deg: float = 0.4
    correlation_s: float = 0.12
    endpoint_bias_m: tuple = (0.0, 0.0, 0.0)
    overshoot_fraction: float = 0.03
    reaction_s: float = 0.15

    def validate(self):
        for name, upper in (("position_sigma_m", 0.1), ("rotation_sigma_deg", 30),
                            ("correlation_s", 10), ("overshoot_fraction", 0.5),
                            ("reaction_s", 5)):
            v = getattr(self, name)
            if isinstance(v, bool) or not math.isfinite(v) or not 0 <= v <= upper:
                raise ValueError(f"invalid profile {name}")
        if self.correlation_s == 0:
            raise ValueError("correlation_s must be positive")
        if any(abs(x) > 0.2 for x in vector(self.endpoint_bias_m, 3)):
            raise ValueError("endpoint bias exceeds 0.2 m")


def reach(start, target, *, start_q=(0, 0, 0, 1), target_q=(0, 0, 0, 1),
          duration_s=1.0, rate_hz=90, hand="right", seed=0, profile=None):
    """Minimum-jerk reach, optional overshoot/correction, persistent OU variability.

    Noise begins at zero and evolves through the reaction interval and movement.
    It is not pinned to the target at the end, so misses remain observable.
    """
    start, target = vector(start, 3), vector(target, 3)
    qa, qb = quaternion(start_q), quaternion(target_q)
    p = profile or Profile()
    p.validate()
    if hand not in ("left", "right"):
        raise ValueError("unknown hand")
    if not math.isfinite(duration_s) or not 0.05 <= duration_s <= 60:
        raise ValueError("duration must be 0.05..60 seconds")
    if isinstance(rate_hz, bool) or not isinstance(rate_hz, int) or not 10 <= rate_hz <= 240:
        raise ValueError("rate must be an integer 10..240 Hz")
    rng = random.Random(seed)
    total = duration_s + p.reaction_s
    count = math.ceil(total * rate_hz)
    noise = [0.0] * 6
    samples = []
    previous = 0.0
    smooth = lambda t: t*t*t*(10+t*(-15+6*t))
    for i in range(count+1):
        t = min(i/rate_hz, total)
        alpha = math.exp(-(t-previous)/p.correlation_s)
        previous = t
        noise = [alpha*x + math.sqrt(1-alpha*alpha)*rng.gauss(0, 1) for x in noise]
        u = max(0.0, min(1.0, (t-p.reaction_s)/duration_s))
        if p.overshoot_fraction:
            # Reach beyond the endpoint at 80%, then correct during the last 20%.
            s = ((1+p.overshoot_fraction)*smooth(u/0.8) if u <= 0.8 else
                 1+p.overshoot_fraction*(1-smooth((u-0.8)/0.2)))
        else:
            s = smooth(u)
        pos = [a+s*(b-a)+smooth(u)*bias+p.position_sigma_m*n
               for a, b, bias, n in zip(start, target, p.endpoint_bias_m, noise)]
        angle = [math.radians(p.rotation_sigma_deg)*n for n in noise[3:]]
        theta = math.sqrt(sum(x*x for x in angle))
        dq = ([x*math.sin(theta/2)/theta for x in angle]+[math.cos(theta/2)]
              if theta else [0, 0, 0, 1])
        samples.append({"t": t, "hands": {hand: {
            "position": pos, "orientation": multiply(slerp(qa, qb, smooth(u)), dq),
            "valid": True}}})
    trace = {"schema": "nadoc-motion-1", "space": "OpenXR_LOCAL", "units": "meters",
             "quaternion_order": "xyzw", "provenance": {
                 "kind": "synthetic_uncalibrated", "seed": seed, "profile": asdict(p),
                 "target": target, "duration_s": duration_s, "rate_hz": rate_hz},
             "samples": samples, "events": []}
    validate_trace(trace)
    return trace


def validate_trace(trace, *, playable=False):
    if (trace.get("schema") != "nadoc-motion-1" or trace.get("units") != "meters"
            or trace.get("quaternion_order") != "xyzw"):
        raise ValueError("unsupported motion schema/units/quaternions")
    if playable and trace.get("space") != "OpenXR_LOCAL":
        raise ValueError("source recording needs explicit registration to OpenXR_LOCAL")
    samples = trace.get("samples", [])
    if not 2 <= len(samples) <= 100000:
        raise ValueError("trace requires 2..100000 samples")
    previous = -1.0
    expected_hands = set(samples[0]["hands"])
    for sample in samples:
        t = sample["t"]
        if isinstance(t, bool) or not math.isfinite(t) or t <= previous or t > 3600:
            raise ValueError("sample times must increase, within one hour")
        if previous == -1 and t != 0:
            raise ValueError("trace must start at zero")
        previous = t
        if not sample["hands"] or set(sample["hands"]) - {"left", "right"}:
            raise ValueError("unknown/missing hands")
        if playable and set(sample["hands"]) != expected_hands:
            raise ValueError("playable traces must retain the same hands throughout")
        for pose in sample["hands"].values():
            if type(pose["valid"]) is not bool:
                raise ValueError("valid must be boolean")
            if playable and not pose["valid"]:
                raise ValueError("tracking gaps must be segmented before playback")
            if pose["valid"]:
                vector(pose["position"], 3)
                quaternion(pose["orientation"])
    event_time = -1
    for event in trace.get("events", []):
        if (isinstance(event["t"], bool) or not math.isfinite(event["t"]) or not event_time <= event["t"] <= previous
                or event["t"] < 0 or event["hand"] not in ("left", "right")
                or event["button"] not in ("menu", "grip", "trigger")
                or type(event["pressed"]) is not bool):
            raise ValueError("invalid/unsorted button event")
        if playable and event["hand"] not in expected_hands:
            raise ValueError("button events require a posed hand")
        event_time = event["t"]


def summary(trace):
    """Describe recorded motion, without mislabelling it as aiming error/noise."""
    validate_trace(trace)
    result = {"samples": len(trace["samples"]), "duration_s": trace["samples"][-1]["t"],
              "space": trace["space"], "hands": {}}
    for hand in ("left", "right"):
        speeds, angles, path, invalid = [], [], 0.0, 0
        previous = None
        for sample in trace["samples"]:
            pose = sample["hands"].get(hand)
            if not pose or not pose["valid"]:
                invalid += 1
                previous = None
                continue
            if previous:
                old_t, old = previous
                dt = sample["t"]-old_t
                distance = math.dist(pose["position"], old["position"])
                path += distance
                speeds.append(distance/dt)
                a, b = quaternion(pose["orientation"]), quaternion(old["orientation"])
                angles.append(math.degrees(2*math.acos(min(1, abs(sum(x*y for x, y in zip(a, b))))))/dt)
            previous = sample["t"], pose
        if speeds:
            percentile = lambda xs, p: sorted(xs)[round((len(xs)-1)*p)]
            result["hands"][hand] = {"path_m": path, "invalid_samples": invalid,
                "speed_m_s_p50": percentile(speeds, .5), "speed_m_s_p95": percentile(speeds, .95),
                "angular_deg_s_p95": percentile(angles, .95)}
    result["interpretation"] = "Motion statistics include tracking effects; not an error model or population calibration."
    return result
