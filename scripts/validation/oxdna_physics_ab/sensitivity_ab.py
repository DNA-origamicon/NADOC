"""Model-prior sensitivity, never an experimental-accuracy test."""

import json, re, shutil
import numpy as np
from scipy.spatial.transform import Rotation
from ab_common import ROOT, fixture, settings_for, run

rows = []
source = fixture("ads10")
for label in [
    "reference",
    "anchor_half",
    "anchor_double",
    "anm_half",
    "anm_double",
    "linker_half",
    "linker_double",
    "tilt_10deg",
]:
    d = ROOT / "sensitivity_inputs" / label
    d.mkdir(parents=True, exist_ok=True)
    for p in source.iterdir():
        shutil.copy2(p, d / p.name)
    text = (d / "forces.txt").read_text()
    if label.startswith(("anchor", "linker")):
        factor = 0.5 if label.endswith("half") else 2.0

        def change(m):
            block = m.group(0)
            if ("type = trap\n" in block and label.startswith("anchor")) or (
                "type = mutual_trap" in block and label.startswith("linker")
            ):
                block = re.sub(
                    r"(?m)^stiff = (.*)$",
                    lambda v: "stiff = " + str(float(v[1]) * factor),
                    block,
                )
            return block

        text = re.sub(r"\{[^{}]+\}", change, text)
    if label.startswith("anm"):
        factor = 0.5 if label.endswith("half") else 2.0
        lines = (d / "anm.par").read_text().splitlines()
        new = [lines[0]]
        for line in lines[1:]:
            v = line.split()
            v[4] = str(float(v[4]) * factor)
            new.append(" ".join(v))
        (d / "anm.par").write_text("\n".join(new) + "\n")
    if label == "tilt_10deg":
        a = np.loadtxt(d / "conf.dat", skiprows=3)
        center = a[:484, :3].mean(axis=0)
        rotation = Rotation.from_rotvec([0, np.pi / 18, 0])
        a[:, :3] = rotation.apply(a[:, :3] - center) + center
        # This changes the adsorption orientation prior and moves its anchor sites.
        # Minimal outward shift preserves the original minimum gold clearance.
        original = np.loadtxt(source / "conf.dat", skiprows=3)
        minimum = np.linalg.norm(original[:, :3], axis=1).min()
        radial = center / np.linalg.norm(center)
        shift = np.zeros(3)
        for _ in range(1000):
            deficit = minimum - np.linalg.norm(a[:, :3] + shift, axis=1).min()
            if deficit <= 1e-9:
                break
            shift += radial * (deficit + 1e-6)
        a[:, :3] += shift
        a[:, 3:6] = rotation.apply(a[:, 3:6])
        a[:, 6:9] = rotation.apply(a[:, 6:9])
        a[:, 9:] = 0
        a[484:, 12:] = 1e-9
        with (d / "conf.dat").open("w") as out:
            out.write("t = 0\nb = 100 100 100\nE = 0 0 0\n")
            np.savetxt(out, a, fmt="%.17g")
        text = re.sub(
            r"(?m)^pos0 = (.*)$",
            lambda m: (
                "pos0 = "
                + ",".join(
                    str(x)
                    for x in rotation.apply(np.fromstring(m[1], sep=",") - center)
                    + center
                    + shift
                )
            ),
            text,
        )
        (d / "transform.json").write_text(
            json.dumps(dict(rotation_degrees=10, outward_shift=shift.tolist()))
        )
    (d / "forces.txt").write_text(text)
    for seed in [1709, 2801, 3911]:
        s = settings_for("ads10", "CUDA", 50000, seed, "john", cadence=250)
        s.update(diff_coeff=0.1)
        for key, name in [
            ("conf_file", "conf.dat"),
            ("topology", "topology.top"),
            ("parfile", "anm.par"),
            ("external_forces_file", "forces.txt"),
        ]:
            s[key] = d / name
        r = run(f"sensitivity_{label}_{seed}", "combined_epsilon1", s)
        r.update(test="model_sensitivity", prior=label)
        rows.append(r)
        (ROOT / "sensitivity.json").write_text(json.dumps(rows, indent=2))
print("Sensitivity complete", flush=True)
