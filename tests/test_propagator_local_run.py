"""Ladder-trim logic for the local propagator pilot (no GROMACS / no NAMD).

Pins that trim_ladder_for_pilot shrinks every segment's step count, enables
velocity/force capture ONLY on the unrestrained (scale=None) production chunks, and
keeps the manifest's per-segment steps/dcd_freq in sync with the rewritten confs.
"""

import json

from backend.ml.propagator import local_run as LR


def _min_manifest():
    # Minimal manifest that segments_from_manifest can reconstruct: one restrained
    # segment (scale=0.5) and one unrestrained production segment (scale=None).
    return {
        "minimization": {"name": "sys_00_min"},
        "box_ang": [60.0, 60.0, 60.0],
        "mgh_extrabonds": False,
        "segments": [
            {
                "name": "sys_01_k0p5_p100",
                "stage": "k0.5",
                "percent": 100,
                "steps": 2_400_000,
                "temp": 300.0,
                "damping": 1.0,
                "scale": 0.5,
                "npt": True,
                "previous": "sys_00_min",
                "reinit": False,
                "dcd_freq": 20000,
                "soft": False,
            },
            {
                "name": "sys_02_MGHH_only_p100",
                "stage": "MGHH",
                "percent": 100,
                "steps": 2_400_000,
                "temp": 300.0,
                "damping": 1.0,
                "scale": None,
                "npt": True,
                "previous": "sys_01_k0p5_p100",
                "reinit": False,
                "dcd_freq": 20000,
                "soft": False,
            },
        ],
    }


def test_trim_shortens_and_captures_only_unrestrained(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps(_min_manifest()))

    trimmed = LR.trim_ladder_for_pilot(
        tmp_path,
        "sys",
        restrained_steps=2000,
        production_steps=6000,
        production_dcd_freq=10,
    )

    by_name = {s.name: s for s in trimmed}
    restrained = by_name["sys_01_k0p5_p100"]
    production = by_name["sys_02_MGHH_only_p100"]

    # step counts shrunk
    assert restrained.steps == 2000
    assert production.steps == 6000
    assert production.dcd_freq == 10

    # capture only on the unrestrained production conf
    prod_conf = (tmp_path / "sys_02_MGHH_only_p100.conf").read_text().lower()
    rest_conf = (tmp_path / "sys_01_k0p5_p100.conf").read_text().lower()
    assert "veldcdfile" in prod_conf and "forcedcdfile" in prod_conf
    assert "veldcd" not in rest_conf

    # manifest kept in sync with the rewritten confs
    m = json.loads((tmp_path / "manifest.json").read_text())
    steps = {s["name"]: s["steps"] for s in m["segments"]}
    assert steps["sys_01_k0p5_p100"] == 2000
    assert steps["sys_02_MGHH_only_p100"] == 6000
