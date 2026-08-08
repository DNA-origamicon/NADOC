"""RunPod-side in-flight MD health collector.

The trajectory already lives beside NAMD on the network volume.  Pulling it home just to
compute C1'/WC pairing, broken base pairs and ion-shell charge is both slow and wasteful;
run the canonical staged ``md_health`` module on the pod and publish one atomic JSON blob
instead.  Monitoring is advisory and total: no analysis failure may disturb NAMD.
"""

from __future__ import annotations

import dataclasses
import glob
import json
import os
import sys
import time
from pathlib import Path


def _load_health():
    try:
        import md_health  # staged sibling on the pod

        return md_health
    except ImportError:
        from backend.core import md_health

        return md_health


_DROP = {"wc_per_frame", "broken_bp_per_frame", "charge_per_frame"}


def _active_segment(work: Path) -> str | None:
    """Newest simulation log, excluding this collector and other service logs."""
    names = None
    try:
        manifest = json.loads((work / "manifest.json").read_text())
        names = {
            str(item["name"])
            for item in manifest.get("segments", [])
            if item.get("name")
        }
    except (OSError, ValueError, TypeError):
        pass
    logs = [
        path
        for path in glob.glob(str(work / "*.log"))
        if not Path(path).name.startswith("nadoc_")
        and (names is None or Path(path).stem in names)
    ]
    logs.sort(key=os.path.getmtime)
    return Path(logs[-1]).stem if logs else None


def _thresholds(work: Path, segment: str) -> tuple[float, float, str]:
    try:
        raw = json.loads((work / "manifest.json").read_text())
        for item in raw.get("segments", []):
            if item.get("name") == segment:
                return (
                    float(item.get("min_c1_paired", 0.90)),
                    float(item.get("min_wc_ref_relative", 0.85)),
                    str(item.get("stage") or segment),
                )
    except (OSError, ValueError, TypeError):
        pass
    return 0.90, 0.85, segment


def collect(work_dir: str, name_stem: str) -> dict:
    work = Path(work_dir)
    now = time.time()
    segment = _active_segment(work)
    base = {"schema": 1, "collected_at": now, "segment": segment}
    if not segment:
        return {**base, "ready": False, "reason": "waiting for a segment log"}
    c1, wc, stage = _thresholds(work, segment)
    base["stage"] = stage
    try:
        health = _load_health()
        result = health.run_health_check(
            work,
            segment,
            name_stem,
            min_c1_paired=c1,
            min_wc_ref_relative=wc,
            safe_back=1,
            per_frame=False,
        )
        values = {
            k: v for k, v in dataclasses.asdict(result).items() if k not in _DROP
        }
        return {
            **base,
            "ready": not bool(result.not_ready or result.error),
            "reason": (
                "waiting for two complete trajectory frames"
                if result.not_ready
                else result.error
            ),
            "health": values,
        }
    except Exception as exc:  # monitoring must never stop a paid run
        return {
            **base,
            "ready": False,
            "reason": f"{type(exc).__name__}: {exc}",
        }


def _write_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":")))
    os.replace(str(tmp), str(path))


def main(argv: list[str]) -> int:
    work = argv[1] if len(argv) > 1 else "."
    interval = float(argv[2]) if len(argv) > 2 else 0.0
    stem = argv[3] if len(argv) > 3 else ""
    out = Path(work) / "output" / "live_health.json"
    while True:
        payload = None
        try:
            payload = collect(work, stem)
            _write_atomic(out, payload)
        except Exception as exc:
            print(f"live-health: {exc}", file=sys.stderr)
        if interval <= 0:
            return 0
        # At segment start there may be fewer than safe_back+1 complete DCD frames. Do
        # not turn that ordinary seconds-long state into a five-minute blank Health card.
        time.sleep(min(30.0, interval) if not (payload or {}).get("ready") else interval)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
