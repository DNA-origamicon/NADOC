"""Bounded Alpine patch-grid recovery; stdlib-only and Python 3.6 compatible.

Only called after the exact cell-shrink fatal. Never changes atom selections,
restraint references, force constants, timestep, or the requested ensemble.
"""

import argparse
import json
import math
import re
import shutil
import struct
from pathlib import Path

try:
    from nadoc_resume_conf import build_resume_conf, restart_step_of
except ImportError:
    from backend.core.remote_resume_conf import build_resume_conf, restart_step_of


def directive(text, key):
    matches = re.findall(r"^\s*" + key + r"\s+([^#\n]+)", text, re.M | re.I)
    return matches[-1].strip() if matches else None


def volume(path):
    rows = [
        line.split()
        for line in path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    row = rows[-1]
    value = float(row[1]) * float(row[5]) * float(row[9])
    if not math.isfinite(value) or value <= 0:
        raise ValueError("invalid checkpoint cell volume")
    return value


def recover(package, segment, source, total, attempt):
    """Write a retry conf, rejecting incomplete/stale checkpoints and cell collapse."""
    original = (package / (source + ".conf")).read_text()
    if directive(original, "langevinPiston") not in ("on", "yes"):
        raise ValueError("cell recovery requires an NPT dynamics stage")
    if not 1 <= attempt <= 4 or total <= 0:
        raise ValueError("cell recovery retry limit or invalid segment length")
    out = package / "output"
    state_path = out / (segment + ".cell_recovery.json")
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    baseline = state.get("initial_volume")
    if baseline is None:
        baseline = volume(package / directive(original, "extendedSystem"))
    checkpoint = out / (segment + ".restart.xsc")
    step = 0
    if checkpoint.exists():
        step = restart_step_of(checkpoint.read_text())
        counts = []
        for suffix in ("coor", "vel"):
            path = out / (segment + ".restart." + suffix)
            with path.open("rb") as stream:
                count = struct.unpack("<i", stream.read(4))[0]
            if count <= 0 or path.stat().st_size != 4 + 24 * count:
                raise ValueError("incomplete restart " + suffix)
            counts.append(count)
        if counts[0] != counts[1]:
            raise ValueError("checkpoint coordinate/velocity atom counts differ")
        fraction = volume(checkpoint) / baseline
        if fraction < 0.85:
            raise ValueError(
                "cell collapsed below 85% of its initial volume; refusing retry"
            )
        if step <= max(0, state.get("step", -1)):
            raise ValueError("checkpoint made no progress since the previous retry")
        text = build_resume_conf(original, segment, step, total)
    else:
        # small_plate failed before restartfreq=5000. One fresh restart with the
        # local runner's gentler piston and dense checkpoints can establish a restart.
        # Repeating the same checkpoint-free retry would hide a persistent defect.
        if attempt != 1 or state or directive(original, "firsttimestep"):
            raise ValueError("no complete checkpoint for cell recovery")
        text = original

    # Soften ONCE relative to the original conf, never exponentially per retry.
    for key in ("langevinPistonPeriod", "langevinPistonDecay"):
        value = directive(original, key)
        if value:
            text = re.sub(
                r"^\s*" + key + r"\s+[^\n]+",
                key + " " + str(float(value) * 10),
                text,
                flags=re.M | re.I,
            )
    cadence = min(100, int(directive(text, "restartfreq") or 100))
    text = re.sub(
        r"^\s*restartfreq\s+[^\n]+",
        "restartfreq " + str(cadence),
        text,
        flags=re.M | re.I,
    )

    # Keep the canonical trajectory current for node health/early-stop. Preserve
    # every partial as a separate archive, outside the contN trajectory chain (whose
    # chronology is base-first). Downloads include all files in output/.
    index = 1
    while list(out.glob(segment + ".cell_archive" + str(index) + ".*")):
        index += 1
    for key in ("dcdFile", "xstFile", "velDCDfile", "forceDCDfile"):
        name = directive(text, key)
        if name:
            path = package / name
            if path.exists():
                suffix = (
                    ".vel.dcd"
                    if key.lower() == "veldcdfile"
                    else ".force.dcd"
                    if key.lower() == "forcedcdfile"
                    else path.suffix
                )
                shutil.copy2(
                    str(path),
                    str(out / (segment + ".cell_archive" + str(index) + suffix)),
                )
    retry = segment + ".cell_retry"
    (package / (retry + ".conf")).write_text(text)
    state.update(initial_volume=baseline, step=step, attempt=attempt)
    state_path.write_text(json.dumps(state))
    return retry


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--segment", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--total", required=True, type=int)
    parser.add_argument("--attempt", required=True, type=int)
    args = parser.parse_args()
    recover(Path("."), args.segment, args.source, args.total, args.attempt)


if __name__ == "__main__":
    main()
