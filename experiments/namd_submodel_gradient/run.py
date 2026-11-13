"""3 nm graded shell from an existing full-model relaxed DNA checkpoint."""

import argparse
from dataclasses import replace
import hashlib
import json
import io
import zipfile
from pathlib import Path
import re
import shutil
import subprocess
import time
import psutil

import numpy as np
from backend.core.models import Design
from backend.core.namd_topology import CharmmTopologyBuild
from backend.core.namd_submodel import crop_topology, sections, canonical_bonded_lines
from backend.core.namd_submodel_charge import record_charge_policy
from backend.core.namd_solvate import build_namd_solvated_package
from backend.physics.oxdna_submodel import box_distance
from backend.core.md_shell_reprep import read_namd_coor
from backend.core.md_protocols import (
    prepare_equilibrium_aware_namd,
    SegmentSpec,
    _segment_conf,
    build_production_conf,
    write_hmr_psf,
)
from experiments.namd_submodel_damping.run import (
    marker,
    boundary_atoms,
    set_boundary,
    dump,
)

CONDITIONS = ["full", "fixed", "uniform", "gradient"]
SEEDS = [77, 177]


def run_native(binary, pkg, name, root):
    print("NATIVE", name, flush=True)
    started = time.monotonic()
    rss = 0
    gpu = []
    log = pkg / (name + ".native.log")
    with log.open("w") as output:
        process = subprocess.Popen(
            [str(binary), "+p4", "+setcpuaffinity", "+devices", "0", name + ".conf"],
            cwd=pkg,
            stdout=output,
            stderr=subprocess.STDOUT,
        )
        while process.poll() is None:
            try:
                rss = max(rss, psutil.Process(process.pid).memory_info().rss)
            except psutil.NoSuchProcess:
                pass
            query = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-compute-apps=pid,used_memory",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
            )
            for line in query.stdout.splitlines():
                parts = [part.strip() for part in line.split(",")]
                if (
                    len(parts) == 2
                    and parts[0] == str(process.pid)
                    and parts[1].isdigit()
                ):
                    gpu.append(int(parts[1]))
            time.sleep(1)
    result = dict(
        stage=name,
        package=str(pkg),
        exit_code=process.returncode,
        seconds=time.monotonic() - started,
        peak_sampled_rss_bytes=rss,
        peak_sampled_gpu_MiB=max(gpu) if gpu else None,
        memory_sample_interval_seconds=1,
        success=process.returncode == 0 and "End of program" in log.read_text(),
    )
    with (root / "execution.jsonl").open("a") as f:
        f.write(json.dumps(result) + "\n")
    if not result["success"]:
        raise RuntimeError(f"Native failure: {log}")


def ramp(distance, width=3.0, fixed_layer=0.3, maximum=0.5):
    """Static reference-distance smoothstep; values are NAMD harmonic coefficients."""
    if not 0 <= fixed_layer < width or maximum <= 0:
        raise ValueError("Invalid gradient parameters")
    t = np.clip(np.asarray(distance) / (width - fixed_layer), 0, 1)
    return maximum * t * t * (3 - 2 * t)


def atoms(path):
    return [
        s
        for s in Path(path).read_text().splitlines()
        if s.startswith(("ATOM  ", "HETATM"))
    ]


def xyz(lines):
    return np.array([[float(s[i : i + 8]) for i in (30, 38, 46)] for s in lines])


def identity(rows):
    return {tuple(row[1:3] + [row[4]]): i for i, row in enumerate(rows)}


def prepare(prior, root):
    root.mkdir(parents=True, exist_ok=False)
    for name in ["source-design.json", "source.psf", "source.pdb"]:
        shutil.copy2(prior / name, root / name)
    design = Design.from_json((root / "source-design.json").read_text())
    original = json.loads((prior / "experiment.json").read_text())
    box = {**original["box"], "shell_nm": 3.0}
    full_info = json.loads((prior / "packages.json").read_text())["full"]
    fp = Path(full_info["package"])
    stem = full_info["stem"]
    meta = json.loads((fp / "charge_audit.json").read_text())["topology_metadata"]
    source = CharmmTopologyBuild(
        (root / "source.pdb").read_text(), (root / "source.psf").read_text(), meta
    )
    cropped, receipt = crop_topology(source, box)
    receipt["charge_policy"] = record_charge_policy(source.psf_text, cropped.psf_text)
    rows = [s.split() for s in sections(source.psf_text)["NATOM"][1]]
    full_rows = [
        s.split() for s in sections((fp / f"{stem}.psf").read_text())["NATOM"][1]
    ]
    lookup = identity(full_rows)
    mapping = [lookup[tuple(row[1:3] + [row[4]])] for row in rows]
    checkpoint = fp / "output/common_relax.coor"
    start = read_namd_coor(checkpoint)[mapping]
    translation = xyz(atoms(fp / f"{stem}.pdb"))[mapping] - xyz(
        atoms(root / "source.pdb")
    )
    assert np.max(np.ptp(translation, axis=0)) < 0.002
    source_start = start - translation.mean(0)
    source_lines = atoms(root / "source.pdb")
    seeded = [
        s[:30] + "".join(f"{v:8.3f}" for v in source_start[i]) + s[54:]
        for i, s in enumerate(source_lines)
    ]
    retained = receipt["retained_source_indices"]
    n_dna = len(retained)
    # Selection remains the exact source-space box; only derived simulation coordinates change.
    cropped = replace(
        cropped, pdb_text="\n".join(seeded[i] for i in retained) + "\nEND\n"
    )

    def builder(design, **kwargs):
        data = build_namd_solvated_package(design, topology_override=cropped, **kwargs)
        output = io.BytesIO()
        with (
            zipfile.ZipFile(io.BytesIO(data)) as archive,
            zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as result,
        ):
            for name in archive.namelist():
                result.writestr(name, archive.read(name))
            prefix = next(
                name.rsplit("/", 1)[0]
                for name in archive.namelist()
                if name.endswith("/namd.conf")
            )
            result.writestr(prefix + "/submodel.json", json.dumps(receipt))
            result.writestr(prefix + "/submodel_source/full.psf", source.psf_text)
            result.writestr(prefix + "/submodel_source/full.pdb", source.pdb_text)
        return output.getvalue()

    rel, stem, _ = prepare_equilibrium_aware_namd(
        design,
        root / "crop",
        package_builder=builder,
        fixed_cell=True,
        gpu_resident_mode="off",
        padding_nm=2,
        box_mode="bbox",
        minimize_steps=4800,
        adaptive_minimization=False,
        ion_conc_mM=150,
        mg_conc_mM=0,
        salt_mode="custom",
    )
    pkg = root / "crop" / rel
    for psf in pkg.glob("*.psf"):
        psf.write_text(canonical_bonded_lines(psf.read_text()))
    lines = atoms(pkg / f"{stem}.pdb")
    out_rows = [
        s.split() for s in sections((pkg / f"{stem}.psf").read_text())["NATOM"][1]
    ]
    assert [row[1:5] for row in out_rows[:n_dna]] == [rows[i][1:5] for i in retained]
    heavy = np.array([float(row[7]) > 2 for row in out_rows])
    n = len(lines)
    core = set(receipt["mobile_output_indices"])
    distances = box_distance(xyz(source_lines) / 10, box)
    representative = {}
    for i, row in enumerate(rows):
        key = tuple(row[1:3])
        if row[4] == "P" or (key not in representative and row[4] == "C1'"):
            representative[key] = i
    d = np.array([distances[representative[tuple(rows[i][1:3])]] for i in retained])
    fixed = set(boundary_atoms(source.psf_text, receipt)) | {
        i for i in range(n_dna) if i not in core and d[i] >= 2.7
    }
    assert not fixed.intersection(core)
    buffer = sorted(set(range(n_dna)) - core - fixed)
    weights = np.zeros(n)
    weights[buffer] = ramp(d[buffer])
    weights[~heavy] = 0
    weights = np.round(weights, 2)  # Exact values serialized in the PDB B column.
    all_fixed = np.zeros(n)
    all_fixed[:n_dna] = 1
    marker(pkg / "prepare_fixed.pdb", lines, all_fixed)
    flags = np.zeros(n)
    flags[list(fixed)] = 1
    marker(pkg / "outer_fixed.pdb", lines, flags)
    all_fixed[list(core)] = 0
    marker(pkg / "all_shell_fixed.pdb", lines, all_fixed)
    dump(root / "selection.json", receipt)
    dump(pkg / "submodel.json", receipt)
    dump(
        root / "buffer.json",
        dict(
            frozen_indices=sorted(fixed),
            buffer_indices=buffer,
            core_indices=sorted(core),
            retained_atoms=n_dna,
            total_atoms=n,
            buffer_heavy_atoms=int(heavy[buffer].sum()),
            distance_nm=d.tolist(),
            gradient_k=weights[:n_dna].tolist(),
            coefficient_policy="per nucleotide P/C1 reference distance; smoothstep 0 to 0.5 over 0 to 2.7 nm; outer 0.3 nm and cut support fixed",
        ),
    )
    dump(
        root / "experiment.json",
        dict(
            source=original["source"],
            source_sha256=hashlib.sha256(
                (root / "source-design.json").read_bytes()
            ).hexdigest(),
            prior=str(prior),
            checkpoint=str(checkpoint),
            checkpoint_sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
            box=box,
            plot_title="3 nm shell: fixed, uniform and smooth restraint gradient\nShared relaxed DNA start; two 50 ps seeds; exploratory, not converged",
            conditions=CONDITIONS,
            seeds=SEEDS,
            production_steps=12500,
            timestep_fs=4,
            damping_ps_inv=1,
            gradient_maximum=0.5,
            fixed_outer_nm=0.3,
            uniform_coefficient=0.1,
            metrics=[
                "aligned core RMSD/RMSF",
                "WC contacts and angle",
                "C1 pair distances",
                "Rg",
                "core and boundary bond strain",
                "hydration",
                "temperature and pressure diagnostic",
                "shell radial displacement/RMSF/restraint force proxy",
                "DNA image clearance",
                "fixed drift",
                "runtime",
                "peak process RSS; GPU memory sampled separately",
            ],
            limits="50 ps screening, two seeds. Shared DNA checkpoint; new crop solvent. Full references reused read-only from the prior campaign. Not converged or matched solvent.",
        ),
    )
    dump(
        root / "packages.json",
        dict(full=full_info, crop=dict(package=str(pkg), stem=stem, atoms=n)),
    )
    # Record the translation and precision loss so matched DNA starts can be audited.
    delta = xyz(lines)[:n_dna] - source_start[retained]
    assert np.max(np.ptp(delta, axis=0)) < 0.003
    dump(
        root / "checkpoint-map.json",
        dict(
            source_to_full_indices=mapping,
            retained_source_indices=retained,
            solvation_translation_A=delta.mean(0).tolist(),
            max_centered_roundoff_A=float(np.abs(delta - delta.mean(0)).max()),
        ),
    )
    return pkg, stem, weights


def execute(root, prior, binary, prepared):
    packages = json.loads((root / "packages.json").read_text())
    info = packages["crop"]
    pkg = Path(info["package"])
    stem = info["stem"]
    m = json.loads((pkg / "manifest.json").read_text())
    lines = atoms(pkg / f"{stem}.pdb")
    if not prepared:
        minimum = m["minimization"]["name"]
        p = pkg / (minimum + ".conf")
        p.write_text(set_boundary(p.read_text(), "prepare_fixed.pdb"))
        run_native(binary, pkg, minimum, root)
        spec = SegmentSpec(
            name="common_relax",
            stage="20 ps solvent-only relaxation; DNA fixed",
            percent=100,
            steps=10000,
            temp=300,
            damping=1,
            scale=None,
            npt=False,
            previous=minimum,
            reinit=True,
            dcd_freq=500,
            timestep_fs=2,
        )
        (pkg / "common_relax.conf").write_text(
            set_boundary(
                _segment_conf(
                    spec,
                    stem,
                    tuple(m["box_ang"]),
                    False,
                    seed=42,
                    force_resident=False,
                ),
                "prepare_fixed.pdb",
            )
        )
        run_native(binary, pkg, "common_relax", root)
        write_hmr_psf(pkg / f"{stem}.psf", pkg / f"{stem}_hmr.psf")
    b = json.loads((root / "buffer.json").read_text())
    start = read_namd_coor(pkg / "output/common_relax.coor")
    assert (
        np.max(np.abs(start[: b["retained_atoms"]] - xyz(lines)[: b["retained_atoms"]]))
        < 1e-8
    )
    heavy = np.array(
        [
            float(s.split()[7]) > 2
            for s in sections((pkg / f"{stem}.psf").read_text())["NATOM"][1]
        ]
    )
    weights = np.zeros(len(lines))
    weights[: b["retained_atoms"]] = b["gradient_k"]
    marker(pkg / "gradient_reference.pdb", lines, weights, start)
    weights[:] = 0
    weights[b["buffer_indices"]] = 0.1
    weights[~heavy] = 0
    marker(pkg / "uniform_reference.pdb", lines, weights, start)
    trials_path = root / "trials.json"
    trials = (
        json.loads(trials_path.read_text())
        if trials_path.exists()
        else [
            t
            for t in json.loads((prior / "trials.json").read_text())
            if t["condition"] == "full"
        ]
    )
    dump(trials_path, trials)
    for seed in SEEDS:
        for condition in CONDITIONS[1:]:
            name = f"{condition}_seed{seed}"
            if any(t["name"] == name for t in trials):
                continue
            if (pkg / (name + ".conf")).exists():
                raise RuntimeError(
                    "Existing attempt: preserve and inspect before retry"
                )
            spec = SegmentSpec(
                name=name,
                stage="3 nm graded boundary pilot",
                percent=100,
                steps=12500,
                temp=300,
                damping=1,
                scale=None,
                npt=False,
                previous="common_relax",
                reinit=True,
                dcd_freq=250,
                timestep_fs=4,
            )
            text = build_production_conf(
                spec,
                stem,
                tuple(m["box_ang"]),
                False,
                seed=seed,
                fast=True,
                timestep_fs=4,
                npt=False,
                damping=1,
                force_resident=False,
            )
            text = "temperature 300\n" + re.sub(
                r"^binVelocities[^\n]*\n", "", text, flags=re.M
            )
            text = set_boundary(
                text,
                "all_shell_fixed.pdb" if condition == "fixed" else "outer_fixed.pdb",
                None if condition == "fixed" else f"{condition}_reference.pdb",
            )
            (pkg / (name + ".conf")).write_text(text)
            run_native(binary, pkg, name, root)
            trials.append(
                dict(
                    condition=condition,
                    seed=seed,
                    package=str(pkg),
                    stem=stem,
                    name=name,
                    frames_expected=50,
                )
            )
            dump(trials_path, trials)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prior", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--binary", type=Path, required=True)
    ap.add_argument("--prepare-only", action="store_true")
    ap.add_argument("--prepared", action="store_true")
    a = ap.parse_args()
    prior = a.prior.resolve()
    root = a.output.resolve()
    if not a.prepared:
        prepare(prior, root)
    if not a.prepare_only:
        execute(
            root,
            prior,
            a.binary,
            False
            if not a.prepared
            else (
                Path(
                    json.loads((root / "packages.json").read_text())["crop"]["package"]
                )
                / "output/common_relax.coor"
            ).exists(),
        )


if __name__ == "__main__":
    main()
