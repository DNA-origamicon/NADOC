"""Short local controls. Reuses completed reference probes; never reruns a prefix."""

import argparse
import json

from backend.core.namd_gold_package import build_package, verify_package
from experiments.gold_interfaces.native import run


def controls(root, binary):
    particle = {"kind": "nanoparticle", "radius_nm": .85, "solvent_padding_nm": 1.5}
    slab = {"kind": "slab", "facet": "111", "repeats": [16, 9], "layers": 5, "gap_nm": 3.}
    # Based on the 2 ps probes: ~110–130 ns/day. 100 ps <=~90 s;
    # 10 ps <=~10 s per ordinary case, plus preparation/startup.
    rows = []
    def execute(package, **kwargs):
        evidence = package/f"{kwargs['prefix']}.result.json"
        if evidence.exists():
            data = json.loads(evidence.read_text())
            if data["status"] != "passed":
                raise ValueError(f"Retained failed run requires a new explicit prefix: {evidence}")
            return data
        return run(package, binary, **kwargs)

    rows.append(json.loads((root/"slab_v3/equilibrate.result.json").read_text()))
    for name, spec in (("particle", particle), ("slab_v3", slab)):
        for mobility in ("fixed", "mobile"):
            p = root/f"{name}_{mobility}"
            if not p.exists():
                build_package(p, spec, mobility=mobility, water_loading_scale=1.22 if name == "slab_v3" else 1.)
            verify_package(p)
            rows.append(execute(p, prefix="control", minimize=200, steps=10000, timeout=60))
        for dt in (.5, 1., 2.):
            rows.append(execute(root/name, prefix=f"dt{str(dt).replace('.', '_')}",
                            restart="equilibrate",
                            steps=int(10000/dt), dt=dt, timeout=60))
    for name, spec, kwargs in (
        ("slab_v3_100", {**slab, "facet": "100", "repeats": [16, 16]}, {"water_loading_scale": 1.22}),
        ("slab_v3_wider", {**slab, "repeats": [20, 12]}, {"water_loading_scale": 1.22}),
        ("slab_v3_padding", {**slab, "vacuum_factor": 4.}, {"water_loading_scale": 1.22}),
        ("slab_v3_weaker_restraint", slab, {"restraint_k": 2., "water_loading_scale": 1.22}),
        ("particle_larger_cell", {**particle, "solvent_padding_nm": 2.}, {}),
    ):
        p = root/name
        if not p.exists():
            build_package(p, spec, **kwargs)
        verify_package(p)
        rows.append(execute(p, prefix="control", minimize=200, steps=10000, timeout=90))
    (root/"controls.json").write_text(json.dumps(rows, indent=2)+"\n")


if __name__ == "__main__":
    from pathlib import Path
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("root", type=Path)
    p.add_argument("--binary", type=Path, required=True)
    a = p.parse_args()
    controls(a.root, a.binary)
