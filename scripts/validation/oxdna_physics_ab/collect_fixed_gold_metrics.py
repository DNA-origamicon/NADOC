"""Collect fixed-gold validation metrics on the simulation host (Python 3.6+).

Only derived metrics are emitted. The full coordinates and trajectories remain
on their original host. ``read`` can alternatively load remote files in memory.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import statistics

NM_PER_OXDNA = 0.8518


def _distance(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a[:3], b[:3])))


def _configuration(text, expected):
    lines = text.splitlines()
    rows = [[float(x) for x in line.split()] for line in lines[3:] if line.strip()]
    if len(rows) != expected:
        raise ValueError(
            "Particle census mismatch: expected %d, found %d" % (expected, len(rows))
        )
    if any(len(row) != 15 or not all(math.isfinite(x) for x in row) for row in rows):
        raise ValueError("Malformed or nonfinite configuration")
    return rows


def _setting(text, key):
    match = re.search(r"^\s*" + re.escape(key) + r"\s*=\s*(\S+)", text, re.M)
    if match is None:
        raise ValueError("Missing input setting: " + key)
    return match.group(1)


def _forces(text):
    anchors, tethers = [], []
    for block in re.findall(r"\{(.*?)\}", text, re.S):
        settings = dict(re.findall(r"^\s*(\w+)\s*=\s*(.*?)\s*$", block, re.M))
        if settings.get("type") == "trap":
            anchors.append(
                (
                    int(settings["particle"]),
                    [float(x) for x in settings["pos0"].split(",")],
                )
            )
        if settings.get("type") == "mutual_trap":
            first, second = int(settings["particle"]), int(settings["ref_particle"])
            if first < second:
                tethers.append((first, second, float(settings["r0"])))
    if not anchors or not tethers or "repulsive_sphere_moving" not in text:
        raise ValueError("Fixed-gold exclusion/attachment forces are missing")
    return anchors, tethers


def _frame_metrics(rows, protein_count, radius, anchors, tethers, springs):
    center = [
        sum(row[k] for row in rows[:protein_count]) / protein_count for k in range(3)
    ]
    values = {
        "core_clearance_nm": min(
            _distance(row, [0, 0, 0]) * NM_PER_OXDNA for row in rows
        )
        - radius,
        "anchor_rms_nm": math.sqrt(
            sum(_distance(rows[i], pos) ** 2 for i, pos in anchors) / len(anchors)
        )
        * NM_PER_OXDNA,
        "tether_distance_nm": statistics.mean(
            _distance(rows[i], rows[j]) for i, j, _ in tethers
        )
        * NM_PER_OXDNA,
        "anm_rms_extension_nm": math.sqrt(
            sum((_distance(rows[i], rows[j]) - rest) ** 2 for i, j, rest in springs)
            / len(springs)
        )
        * NM_PER_OXDNA,
        "protein_rg_nm": math.sqrt(
            sum(_distance(row, center) ** 2 for row in rows[:protein_count])
            / protein_count
        )
        * NM_PER_OXDNA,
        "dna_rotational_per_particle": statistics.mean(
            0.5 * sum(x * x for x in row[12:15]) for row in rows[protein_count:]
        ),
        "dna_translational_per_particle": statistics.mean(
            0.5 * sum(x * x for x in row[9:12]) for row in rows[protein_count:]
        ),
        "protein_rotational_per_particle": statistics.mean(
            0.5 * sum(x * x for x in row[12:15]) for row in rows[:protein_count]
        ),
        "dna_tip_radius_nm": _distance(rows[-1], [0, 0, 0]) * NM_PER_OXDNA,
    }
    if values["core_clearance_nm"] < 0:
        raise ValueError("A saved frame penetrates the nominal gold core")
    return values


def _stage(
    read, path, particle_count, protein_count, radius, anchors, tethers, springs, md
):
    inputs = read(path + "input")
    expected = int(_setting(inputs, "steps"))
    cadence = int(_setting(inputs, "print_conf_interval"))
    last = read(path + "last_conf.dat")
    final_step = int(_setting(last, "t"))
    if final_step != expected:
        raise ValueError("Incomplete stage: %s (%d/%d)" % (path, final_step, expected))
    final_rows = _configuration(last, particle_count)
    _frame_metrics(final_rows, protein_count, radius, anchors, tethers, springs)

    lines = read(path + "trajectory.dat").splitlines()
    frame_steps, series = [], {}
    index = 0
    while index < len(lines):
        if not lines[index].strip():
            index += 1
            continue
        header = lines[index]
        frame_step = int(_setting(header, "t"))
        if frame_steps and frame_step <= frame_steps[-1]:
            raise ValueError("Repeated or unordered trajectory frames")
        frame_steps.append(frame_step)
        frame = "\n".join(lines[index : index + 3 + particle_count])
        rows = _configuration(frame, particle_count)
        index += 3 + particle_count
        for key, value in _frame_metrics(
            rows, protein_count, radius, anchors, tethers, springs
        ).items():
            series.setdefault(key, []).append(value)
    if (
        len(frame_steps) != expected // cadence
        or not frame_steps
        or frame_steps[-1] != expected
    ):
        raise ValueError("Incomplete trajectory: " + path)

    energies = [
        [float(x) for x in line.split()]
        for line in read(path + "energy.dat").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not energies or not all(math.isfinite(x) for row in energies for x in row):
        raise ValueError("Missing or nonfinite energies: " + path)
    if md:
        series["potential_per_particle"] = [
            row[1] for row in energies[len(energies) // 2 :]
        ]
        series["kinetic_per_particle"] = [
            row[2] for row in energies[len(energies) // 2 :]
        ]
    # The second half reduces the initial transient; it does not certify
    # equilibrium. Independent seeds, not frames, are compared downstream.
    means = {
        key: statistics.mean(
            values
            if key in ("potential_per_particle", "kinetic_per_particle")
            else values[len(values) // 2 :]
        )
        for key, values in series.items()
    }
    return {
        "final_step": final_step,
        "frames": len(frame_steps),
        "minimum_clearance_nm": min(series["core_clearance_nm"]),
        "means": means,
        "series": series,
    }


def collect(read, backend):
    manifest = json.loads(read("manifest.json"))
    result = {}
    for case in manifest["cases"]:
        base = "cases/" + case["name"]
        common = base + "/common/"
        count = case["particles"]
        topology = read(common + "topology.top").splitlines()[0].split()
        if int(topology[0]) != count:
            raise ValueError("Manifest/topology particle census mismatch")
        protein_count = count - int(topology[2])
        initial = _configuration(read(common + "probe.dat"), count)
        probe_text = read(base + "/" + backend + "/probe/last_conf.dat")
        if int(_setting(probe_text, "t")) != 1:
            raise ValueError("Incomplete force probe")
        probe = _configuration(probe_text, count)
        anchors, tethers = _forces(read(common + "equil_forces.txt"))
        springs = [
            (int(parts[0]), int(parts[1]), float(parts[2]))
            for parts in (
                line.split() for line in read(common + "anm.par").splitlines()[1:]
            )
            if parts
        ]
        files = [
            "topology.top",
            "anm.par",
            "probe.dat",
            "equil_forces.txt",
            "conf.dat",
            "forces.txt",
        ]
        record = {
            "particles": count,
            "inputs_sha256": {
                name: hashlib.sha256(read(common + name).encode()).hexdigest()
                for name in files
            },
            "kick": [
                [a - b for a, b in zip(p[9:15], o[9:15])]
                for p, o in zip(probe, initial)
            ],
            "stages": {},
        }
        for stage in ["1_mc_relax", "2_md_relax", "3_equil"]:
            record["stages"][stage] = _stage(
                read,
                base + "/" + backend + "/" + stage + "/",
                count,
                protein_count,
                case["diameter_nm"] / 2,
                anchors,
                tethers,
                springs,
                stage != "1_mc_relax",
            )
        result[case["name"]] = record
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", required=True, choices=["CPU", "CUDA"])
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(collect(lambda path: (args.root / path).read_text(), args.backend))
    )
