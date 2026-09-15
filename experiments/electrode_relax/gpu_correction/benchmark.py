"""Longer matched timing and post-migration force audit on a prepared checkpoint."""

import argparse
import json
import re
from pathlib import Path

import numpy as np

from experiments.electrode_relax.gpu_correction.validate import (
    parameters,
    prepare,
    render,
    run,
    save_parameters,
)


def audit(path, p, s):
    values = np.loadtxt(path, skiprows=1)
    x, actual = values[:, :3], values[:, 3:]
    axis = int(s[0])
    moment = np.dot(p[:, 0], x[:, axis])
    d = (x[:, axis] - np.clip(x[:, axis], s[2], s[3])) * p[:, 1]
    delta = x - p[:, 2:5]
    expected = -p[:, 5, None] * delta
    expected[:, axis] -= 2 * s[1] * p[:, 0] * moment + s[4] * d
    energy = (
        s[1] * moment**2
        + 0.5 * s[4] * np.dot(d, d)
        + 0.5 * np.sum(p[:, 5, None] * delta**2)
    )
    actual_e = float(path.read_text().splitlines()[0])
    force_error = float(abs(expected - actual).max())
    energy_error = abs(energy - actual_e)
    assert np.isfinite(values).all() and force_error < 1e-8
    assert energy_error < 1e-8 + 1e-12 * abs(energy)
    return dict(
        force_error=force_error,
        energy_error=energy_error,
        max_wall_penetration_A=float(abs(d).max()),
    )


def main():
    ap = argparse.ArgumentParser()
    for key in ("package", "plugin", "binary", "cpu-binary", "output"):
        ap.add_argument("--" + key, type=Path, required=True)
    a = ap.parse_args()
    out = a.output.resolve()
    base = prepare(a.package.resolve(), out)
    p, s = parameters(a.package.resolve())
    save_parameters(out / "electrode.params", p, s)
    rows = []
    cases = [
        ("cpu_bridge", "cpu", "", 20000),
        ("gpu_default", "gpu", "", 60000),
        ("gpu_migration_twoaway", "gpu", "GPUAtomMigration on\ntwoAwayZ on", 60000),
        (
            "gpu_migration_twoaway_margin0",
            "gpu",
            "GPUAtomMigration on\ntwoAwayZ on\nmargin 0",
            60000,
        ),
        (
            "gpu_migration_twoaway_repeat",
            "gpu",
            "GPUAtomMigration on\ntwoAwayZ on",
            60000,
        ),
    ]
    for name, kind, options, steps in cases:
        extra = (
            f"gpuGlobalUpdateClient electrode audit {{{out / name}.audit}}\n"
            if kind == "gpu"
            else ""
        )
        conf = render(
            base, name, a.plugin.resolve(), out / "electrode.params", steps, kind, extra
        )
        conf = conf.replace("gpuGlobal on", options + "\ngpuGlobal on")
        (out / f"{name}.conf").write_text(conf)
        row = run((a.binary if kind == "gpu" else a.cpu_binary).resolve(), out, name)
        log = (out / f"{name}.log").read_text()
        times = [
            float(x) for x in re.findall(r"TIMING:.*?Wall:.*?, ([\d.e+-]+)/step", log)
        ]
        median = float(np.median(times[len(times) // 2 :]))
        row.update(
            steps=steps,
            median_ms=median * 1000,
            ns_per_day=0.1728 / median,
            options=options,
        )
        energy_lines = [
            line.split()[1:] for line in log.splitlines() if line.startswith("ENERGY:")
        ]
        assert energy_lines and all(
            np.isfinite(np.array(line, dtype=float)).all() for line in energy_lines
        )
        row["finite_energy_records"] = len(energy_lines)
        if kind == "gpu":
            row.update(audit(out / f"{name}.audit", p, s))
        rows.append(row)
        (out / "results.json").write_text(json.dumps(rows, indent=2) + "\n")
        print(row, flush=True)


if __name__ == "__main__":
    main()
