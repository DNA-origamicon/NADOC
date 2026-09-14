"""Portable all-potential NVE control; uses only the standard library."""

from pathlib import Path
import argparse, json, math, os, re, subprocess, time, statistics, hashlib

ROOT = Path(__file__).resolve().parent
p = argparse.ArgumentParser()
p.add_argument("--index", type=int, required=True)
p.add_argument("--backend", choices=["CPU", "CUDA"], required=True)
args = p.parse_args()
c = json.loads((ROOT / "campaign.json").read_text())["cases"][args.index]
d = ROOT / ("runs_" + args.backend) / c["name"]
d.mkdir(parents=True, exist_ok=True)
s = dict(c["settings"], backend=args.backend)
stride = int(s["print_conf_interval"])
text = (
    "".join("%s = %s\n" % (k, v) for k, v in s.items())
    + """data_output_1 = {
name = precise.dat
print_every = %d
col_1 = {
type = step
}
col_2 = {
type = potential_energy
precision = 15
}
col_3 = {
type = kinetic_energy
precision = 15
}
}
"""
    % stride
)
(d / "input").write_text(text)
binary = ROOT / "engines" / c["variant"] / "bin/oxDNA"
report = dict(
    case=c["name"],
    geometry=c["geometry"],
    variant=c["variant"],
    backend=args.backend,
    dt=s["dt"],
    state="running",
    binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
    input_sha256=hashlib.sha256(text.encode()).hexdigest(),
)
status = ROOT / ("status_" + args.backend)
status.mkdir(exist_ok=True)
target = status / (str(args.index) + ".json")


def save():
    t = target.with_suffix(".json.tmp")
    t.write_text(json.dumps(report, indent=2))
    t.replace(target)


save()
try:
    start = time.monotonic()
    with (d / "run.log").open("w") as log:
        r = subprocess.run(
            [str(binary), "input"],
            cwd=d,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=dict(os.environ, OMP_NUM_THREADS="1"),
            timeout=1200,
        )
    report["wall_seconds"] = time.monotonic() - start
    if r.returncode:
        raise RuntimeError((d / "run.log").read_text()[-1200:])
    force_text = (ROOT / "fixtures" / c["geometry"] / "forces.txt").read_text()
    blocks = [
        dict(re.findall(r"^\s*(\w+)\s*=\s*(.*?)\s*$", b, re.M))
        for b in re.findall(r"\{([^{}]+)\}", force_text)
    ]
    n, protein = c["particles"], c["protein"]

    def configuration(lines):
        a = [[float(v) for v in line.split()] for line in lines[3:]]
        if len(a) != n or any(
            len(row) != 15 or not all(math.isfinite(v) for v in row) for row in a
        ):
            raise ValueError("Nonfinite or malformed configuration")
        return a

    initial = configuration(
        (ROOT / "fixtures" / c["geometry"] / "conf.dat").read_text().splitlines()
    )
    trajectory = (d / "trajectory.dat").read_text().splitlines()
    frames = [initial]
    steps = [0]
    for i in range(0, len(trajectory), n + 3):
        block = trajectory[i : i + n + 3]
        frames.append(configuration(block))
        steps.append(int(block[0].split("=")[1]))
    if (
        len(frames) != 201
        or steps[-1] != s["steps"]
        or any(b <= a for a, b in zip(steps, steps[1:]))
    ):
        raise ValueError("Incomplete trajectory")
    final_lines = (d / "last_conf.dat").read_text().splitlines()
    configuration(final_lines)
    if int(final_lines[0].split("=")[1]) != s["steps"]:
        raise ValueError("Incomplete last configuration")
    precise = [
        [float(v) for v in line.split()]
        for line in (d / "precise.dat").read_text().splitlines()
        if line.strip()
    ]
    if len(precise) != len(frames) or [int(row[0]) for row in precise] != steps:
        raise ValueError("Energy/frame alignment differs")

    def norm(v):
        return math.sqrt(sum(x * x for x in v))

    def distance(a, b):
        return norm([x - y for x, y in zip(a[:3], b[:3])])

    def external(a):
        u = 0.0
        for block in blocks:
            kind = block["type"]
            k = float(block["stiff"])
            if kind == "repulsive_sphere_moving":
                center = [float(v) for v in block["center"].split(",")]
                radius = float(block["r0"])
                for row in a:
                    gap = distance(row, center) - radius
                    if gap < math.sqrt(2):
                        if gap <= 0:
                            raise ValueError("Inside singular gold surface")
                        q = 1 / (gap * gap)
                        u += 4 * k * (q * q - q) + k
            elif kind == "trap":
                u += (
                    0.5
                    * k
                    * distance(
                        a[int(block["particle"])],
                        [float(v) for v in block["pos0"].split(",")],
                    )
                    ** 2
                )
            elif kind == "mutual_trap":
                i, j = int(block["particle"]), int(block["ref_particle"])
                if i < j:
                    u += 0.5 * k * (distance(a[i], a[j]) - float(block["r0"])) ** 2
            else:
                raise ValueError("Unsupported external energy " + kind)
        return u

    energy = [n * (e[1] + e[2]) + external(a) for e, a in zip(precise, frames)]
    if not all(math.isfinite(v) for v in energy):
        raise ValueError("Nonfinite energy")
    dof = 3 * n + 3 * (n - protein)
    scale = dof * 296 / 3000
    report.update(
        state="completed",
        frames=len(frames),
        final_step=steps[-1],
        range_kBT_per_DOF=(max(energy) - min(energy)) / scale,
        sigma=statistics.pstdev(energy),
        energy=energy,
        steps=steps,
    )
    report["conservation_pass"] = report["range_kBT_per_DOF"] <= 0.001
except Exception as exc:
    report.update(state="failed", error=str(exc) or type(exc).__name__)
finally:
    save()
print(c["name"], report["state"], report.get("range_kBT_per_DOF"), flush=True)
if report["state"] != "completed":
    raise SystemExit(1)
