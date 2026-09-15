"""Bounded matched native performance screen; no scientific jobs are launched."""

from pathlib import Path
import argparse, re, json, numpy as np
from experiments.electrode_relax.gpu_correction.validate import (
    prepare,
    parameters,
    save_parameters,
    render,
    run,
)

p = argparse.ArgumentParser()
p.add_argument("--package", type=Path, required=True)
p.add_argument("--plugin", type=Path, required=True)
p.add_argument("--baseline-plugin", type=Path, required=True)
p.add_argument("--binary", type=Path, required=True)
p.add_argument("--output", type=Path, required=True)
a = p.parse_args()
out = a.output.resolve()
base = prepare(a.package.resolve(), out)
pa, scalars = parameters(a.package.resolve())
save_parameters(out / "electrode.params", pa, scalars)
rows = []
cases = [
    ("unfused", a.baseline_plugin, ""),
    ("fused_warp", a.plugin, ""),
    ("migration", a.plugin, "GPUAtomMigration on"),
    ("migration_twoaway", a.plugin, "GPUAtomMigration on\ntwoAwayZ on"),
    ("margin0", a.plugin, "margin 0"),
    ("margin2", a.plugin, "margin 2"),
    ("margin8", a.plugin, "margin 8"),
    ("auto_cycles", a.plugin, "AUTO_CYCLES"),
    ("fused_repeat", a.plugin, ""),
]
for name, plugin, options in cases:
    conf = render(base, name, plugin.resolve(), out / "electrode.params", 20000)
    # All immutable settings must precede gpuGlobalCreateClient, which initializes NAMD.
    conf = conf.replace("gpuGlobal on", options + "\ngpuGlobal on")
    if options == "AUTO_CYCLES":
        conf = re.sub(r"^stepspercycle .*$", "", conf, flags=re.M).replace(
            "AUTO_CYCLES", ""
        )
    (out / f"{name}.conf").write_text(conf)
    try:
        row = run(a.binary.resolve(), out, name)
        text = (out / f"{name}.log").read_text()
        timings = [
            float(x) for x in re.findall(r"TIMING:.*?Wall:.*?, ([\d.e+-]+)/step", text)
        ]
        row.update(
            median_ms=1000 * float(np.median(timings[len(timings) // 2 :])),
            ns_per_day=0.1728 / float(np.median(timings[len(timings) // 2 :])),
            options=options,
        )
    except AssertionError as e:
        row = dict(name=name, error=str(e))
    rows.append(row)
    (out / "results.json").write_text(json.dumps(rows, indent=2) + "\n")
    print(row, flush=True)
