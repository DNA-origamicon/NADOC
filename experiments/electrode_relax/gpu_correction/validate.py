"""Isolated same-coordinate CUDA force audits and matched native benchmarks."""

import argparse, json, re, shutil, subprocess, time
from pathlib import Path
import numpy as np
from backend.core.md_charge import parse_psf_atoms


def parameters(package):
    text = (package / "electrode_forces.tcl").read_text()
    atoms = parse_psf_atoms((package / "system.psf").read_text())
    p = np.zeros((len(atoms), 6))
    p[:, 0] = [a.charge for a in atoms]

    def val(name):
        return re.search(r"^set " + name + r" (.+)$", text, re.M)[1]

    ids = np.array(val("slab_mobile").strip("{}").split(), dtype=int) - 1
    p[ids, 1] = 1
    for ident, ref in re.findall(r"(\d+) \{([^}]+)\}", val("electrode_sites")):
        p[int(ident) - 1, 2:] = np.array(ref.split(), dtype=float)
    scalars = [
        float(val("slab_" + key))
        for key in ("axis", "coefficient", "low", "high", "wall_k")
    ]
    return p, scalars


def save_parameters(path, p, s):
    path.write_text(
        f"{len(p)} "
        + " ".join(format(x, ".17g") for x in s)
        + "\n"
        + "\n".join(" ".join(format(x, ".17g") for x in row) for row in p)
        + "\n"
    )


def prepare(package, out):
    out.mkdir(exist_ok=False, parents=True)
    for f in package.iterdir():
        if f.name != "output" and f.is_dir():
            (out / f.name).symlink_to(f.resolve())
        elif f.is_file() and f.suffix not in (".log", ".conf"):
            (out / f.name).symlink_to(f.resolve())
    (out / "output").mkdir()
    for ext in ("coor", "vel", "xsc"):
        shutil.copy2(
            package / "output" / f"system_validation_p3.{ext}",
            out / "output" / f"seed.{ext}",
        )
    conf = (
        (package / "system_validation_p3.conf")
        .read_text()
        .replace("system_validation_p2", "seed")
    )
    return conf


def render(base, name, plugin, param, steps, kind="gpu", extra=""):
    t = base.replace("system_validation_p3", name)
    t = re.sub(r"^run .*$", "", t, flags=re.M)
    t = re.sub(r"^outputEnergies .*$", "outputEnergies 1000", t, flags=re.M)
    t = re.sub(r"^dcdFreq .*$", "dcdFreq 1000", t, flags=re.M)
    t += "\noutputTiming 1000\n"
    if kind == "gpu":
        scripts = re.findall(r"^tclForcesScript (.+)$", base, re.M)
        if scripts != ["electrode_forces.tcl"] or re.search(r"^gpuGlobal", base, re.M):
            raise ValueError(
                "GPU conversion requires exactly the generated electrode callback and no existing GPU client"
            )
        t = re.sub(r"^tclForces(?:Script)? .*$", "", t, flags=re.M)
        t += (
            "\ngpuGlobal on\n"
            + f"gpuGlobalCreateClient {{{plugin}}} electrode {{{param}}}\n"
        )
    return t + f"run {steps}\n" + extra


def run(binary, out, name, workers=1):
    with (out / f"{name}.log").open("w") as f:
        start = time.time()
        r = subprocess.run(
            [str(binary), f"+p{workers}", "+devices", "0", f"{name}.conf"],
            cwd=out,
            stdout=f,
            stderr=subprocess.STDOUT,
            timeout=300,
        )
    text = (out / f"{name}.log").read_text()
    assert r.returncode == 0 and "End of program" in text, (
        name,
        r.returncode,
        text[-1500:],
    )
    times = re.findall(r"TIMING:.*?Wall:.*?, ([\d.e+-]+)/step", text)
    if not times:
        times = re.findall(r"Benchmark time:.*? ([\d.e+-]+) s/step", text)
    return dict(
        name=name,
        workers=workers,
        wall_seconds=time.time() - start,
        ms_per_step=1000 * float(times[-1]) if times else None,
        normal_exit=True,
    )


def reference_audit(base, pkg, out, binary, name, p, s, gpu_dump):
    script = (pkg / "electrode_forces.tcl").read_text()
    for key, value in zip(("axis", "coefficient", "low", "high", "wall_k"), s):
        script += f"\nset slab_{key} {value:.17g}\n"
    sites = " ".join(
        f"{i + 1} " + "{" + " ".join(format(x, ".17g") for x in row[2:]) + "}"
        for i, row in enumerate(p)
        if row[5]
    )
    script += "\nset electrode_sites {" + sites + "}\n"
    script += """
proc calcforces {} {
 global slab_charges slab_mobile slab_axis slab_coefficient slab_low slab_high slab_wall_k electrode_sites
 loadcoords xyz
 set result [nadoc_native_electrode $slab_charges $slab_mobile $slab_axis $slab_coefficient $slab_low $slab_high $slab_wall_k $electrode_sites true]
 set f [open AUDIT_FILE w]
 puts $f [lindex $result 0]
 foreach atom [lrange $result 1 end] {
  set id [lindex $atom 0]
  puts $f "[join $xyz($id) { }] [join [lrange $atom 1 end] { }]"
 }
 close $f
}
""".replace("AUDIT_FILE", "{" + str(out / f"{name}.audit") + "}")
    (out / f"{name}.tcl").write_text(script)
    conf = render(base, name, None, None, 0, "cpu").replace(
        "tclForcesScript electrode_forces.tcl", f"tclForcesScript {name}.tcl"
    )
    (out / f"{name}.conf").write_text(conf)
    run(binary, out, name)
    cpu = np.loadtxt(out / f"{name}.audit", skiprows=1)
    gpu = np.loadtxt(gpu_dump, skiprows=1)
    pos_error = float(abs(cpu[:, :3] - gpu[:, :3]).max())
    force_error = float(abs(cpu[:, 3:] - gpu[:, 3:]).max())
    cpu_e = float((out / f"{name}.audit").read_text().splitlines()[0])
    energy_error = abs(cpu_e - float(gpu_dump.read_text().splitlines()[0]))
    assert (
        pos_error < 1e-9
        and force_error < 1e-8
        and energy_error < 1e-8 + 1e-12 * abs(cpu_e)
    ), (pos_error, force_error, energy_error)
    return dict(
        cpu_position_error=pos_error,
        cpu_force_error=force_error,
        cpu_energy_error=energy_error,
        cpu_energy_relative_error=energy_error / max(1, abs(cpu_e)),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", type=Path, required=True)
    ap.add_argument("--plugin", type=Path, required=True)
    ap.add_argument("--binary", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    pkg = args.package.resolve()
    out = args.output.resolve()
    plugin = args.plugin.resolve()
    binary = args.binary.resolve()
    base = prepare(pkg, out)
    p, s = parameters(pkg)
    results = []
    for case, axis in enumerate((0, 1, 2, 1)):
        pa = p.copy()
        sa = s.copy()
        sa[0] = axis
        if case < 3:
            sa[2:4] = [
                35.0,
                45.0,
            ]  # Deliberately activate wall forces without editing atoms.
            pa[0, 2] += 0.125
            pa[-1, 2:] = [5.0, 10.0, 15.0, 2.0]  # exercise a generic mobile tether too
        name = f"audit_axis{axis}" if case < 3 else "audit_normal"
        param = out / f"{name}.params"
        save_parameters(param, pa, sa)
        (out / f"{name}.conf").write_text(
            render(
                base,
                name,
                plugin,
                param,
                0,
                extra=f"gpuGlobalUpdateClient electrode audit {{{out / name}.audit}}\n",
            )
        )
        result = run(binary, out, name)
        dump = out / f"{name}.audit"
        e = float(dump.read_text().splitlines()[0])
        v = np.loadtxt(dump, skiprows=1)
        x = v[:, :3]
        actual = v[:, 3:]
        moment = np.dot(pa[:, 0], x[:, axis])
        c = sa[1]
        d = (
            np.where(
                x[:, axis] < sa[2],
                x[:, axis] - sa[2],
                np.where(x[:, axis] > sa[3], x[:, axis] - sa[3], 0),
            )
            * pa[:, 1]
        )
        delta = x - pa[:, 2:5]
        expected = -pa[:, 5, None] * delta
        expected[:, axis] -= 2 * c * pa[:, 0] * moment + sa[4] * d
        expected_e = (
            c * moment**2
            + 0.5 * sa[4] * np.dot(d, d)
            + 0.5 * np.sum(pa[:, 5, None] * delta**2)
        )
        error = float(abs(expected - actual).max())
        energy_error = abs(e - expected_e)
        assert np.isfinite(v).all() and error < 1e-8 and energy_error < 1e-6, (
            error,
            energy_error,
        )
        result.update(max_force_error=error, energy_error=energy_error, atoms=len(p))
        result.update(
            reference_audit(base, pkg, out, binary, name + "_cpu", pa, sa, dump)
        )
        results.append(result)
        print(result, flush=True)
    save_parameters(out / "electrode.params", p, s)
    for name, kind, workers in [
        ("gpu_p1", "gpu", 1),
        ("cpu_bridge_p1", "cpu", 1),
        ("gpu_p2", "gpu", 2),
        ("gpu_p4", "gpu", 4),
        ("gpu_p8", "gpu", 8),
        ("gpu_p1_repeat", "gpu", 1),
    ]:
        (out / f"{name}.conf").write_text(
            render(base, name, plugin, out / "electrode.params", 5000, kind)
        )
        result = run(binary, out, name, workers)
        results.append(result)
        (out / "results.json").write_text(json.dumps(results, indent=2) + "\n")
        print(result, flush=True)


if __name__ == "__main__":
    main()
