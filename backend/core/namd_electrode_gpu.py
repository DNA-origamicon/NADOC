"""Package-local, checksum-pinned GPU electrode corrections for local NAMD runs."""

import hashlib
import json
import os
import re
import shutil
from pathlib import Path

import numpy as np
from backend.core.md_charge import parse_psf_atoms

SOURCE = Path(__file__).parent / "native/electrode_gpu.cu"
REGISTRY = Path(__file__).resolve().parents[2] / "workspace/runtime/electrode_gpu"
CLIENT = "gpuGlobalCreateClient {./electrode_gpu.so} electrode {electrode_gpu.params}"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def parameter_data(package):
    """Read the generated reference callback without evaluating Tcl code."""
    package = Path(package)
    text = (package / "electrode_forces.tcl").read_text()
    atoms = parse_psf_atoms((package / "system.psf").read_text())
    p = np.zeros((len(atoms), 6))
    p[:, 0] = [a.charge for a in atoms]

    def val(name):
        matches = re.findall(r"^set " + name + r" (.+)$", text, re.M)
        if len(matches) != 1:
            raise ValueError(f"GPU electrode parameters require one generated {name}.")
        return matches[0]

    ids = np.array(val("slab_mobile").strip("{}").split(), dtype=int) - 1
    if np.any(ids < 0) or np.any(ids >= len(p)):
        raise ValueError("Invalid electrode mobile atom indices.")
    p[ids, 1] = 1
    for ident, ref in re.findall(r"(\d+) \{([^}]+)\}", val("electrode_sites")):
        index = int(ident) - 1
        if not 0 <= index < len(p):
            raise ValueError("Invalid electrode anchor atom index.")
        p[index, 2:] = np.array(ref.split(), dtype=float)
    s = [
        float(val("slab_" + key))
        for key in ("axis", "coefficient", "low", "high", "wall_k")
    ]
    if (
        not np.isfinite(p).all()
        or not np.isfinite(s).all()
        or abs(p[:, 0].sum()) > 1e-5
    ):
        raise ValueError("GPU electrodes require finite parameters and a neutral cell.")
    return p, s


def parameter_text(p, s):
    return (
        f"{len(p)} "
        + " ".join(format(x, ".17g") for x in s)
        + "\n"
        + "\n".join(" ".join(format(x, ".17g") for x in row) for row in p)
        + "\n"
    )


def order_initialization(text):
    """NAMD client creation initializes the engine; put it immediately before run."""
    lines = text.splitlines()
    clients = [
        line for line in lines if re.match(r"^\s*gpuGlobalCreateClient\b", line, re.I)
    ]
    if not clients:
        return text
    if len(clients) != 1 or clients[0].strip() != CLIENT:
        raise ValueError(
            "Unknown GPU client; cannot reorder its initialization safely."
        )
    lines = [line for line in lines if line not in clients]
    runs = [
        i for i, line in enumerate(lines) if re.match(r"^\s*run\s+\d+\s*$", line, re.I)
    ]
    if len(runs) != 1:
        raise ValueError(
            "GPU electrode configuration requires one literal run command."
        )
    lines.insert(runs[0], CLIENT)
    return "\n".join(lines) + "\n"


def convert_config(text):
    existing = CLIENT in text
    scripts = re.findall(r"^\s*tclForcesScript\s+([^\n]+)", text, re.M | re.I)
    if scripts != ([] if existing else ["electrode_forces.tcl"]):
        raise ValueError(
            "GPU electrodes cannot replace unrelated or additional Tcl forces."
        )
    if not re.search(r"^\s*GPUresident\s+on\s*$", text, re.M | re.I):
        raise ValueError("GPU electrode correction requires GPUresident on.")
    for key in (
        "langevinPiston",
        "BerendsenPressure",
        "MonteCarloPressure",
        "multigrator",
    ):
        if re.search(r"^\s*" + key + r"\s+(?:on|yes|true|1)\s*$", text, re.M | re.I):
            raise ValueError(
                "GPU electrode correction requires a fixed cell without a barostat."
            )
    if existing:
        return order_initialization(text)
    if re.search(r"^\s*gpuGlobal", text, re.M | re.I):
        raise ValueError("Unknown existing GPU client.")
    text = re.sub(r"^\s*tclForces(?:Script)?\s+[^\n]*\n", "", text, flags=re.M | re.I)
    # Tested execution options; physical timestep, output cadence and PME are preserved.
    text = re.sub(
        r"^\s*(?:GPUAtomMigration|twoAwayZ)\s+[^\n]*\n", "", text, flags=re.M | re.I
    )
    return order_initialization(
        "GPUAtomMigration on\ntwoAwayZ on\ngpuGlobal on\n" + text + "\n" + CLIENT + "\n"
    )


def install_build(build, destination=None):
    """Install an already validated ABI-specific library; compilation stays explicit."""
    build, dest = Path(build), Path(destination or REGISTRY)
    data = json.loads((build / "provenance.json").read_text())
    if (
        sha(build / "electrode.so") != data["plugin_sha256"]
        or sha(SOURCE) != data["correction_sha256"]
    ):
        raise ValueError("GPU electrode build/source checksum mismatch.")
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(build / "electrode.so", dest / "electrode.so")
    (dest / "provenance.json").write_text(json.dumps(data, indent=2) + "\n")
    return dest


def validate_package(package, binary, devices):
    package = Path(package)
    manifest = json.loads((package / "manifest.json").read_text())
    data = manifest.get("electrode_gpu")
    if not data or not data.get("enabled"):
        return
    if len(str(devices).split(",")) != 1 or str(devices).lower() in ("", "cpu"):
        raise ValueError(
            "GPU electrode package requires its validated single-GPU execution target."
        )
    if sha(binary) != data["engine_sha256"]:
        raise ValueError(
            "GPU electrode NAMD checksum changed; install a matching validated plugin before restarting."
        )
    for name, expected in data["files"].items():
        path = package / name
        if not path.is_file() or sha(path) != expected:
            raise ValueError(
                f"GPU electrode package checksum changed or file missing: {name}. Reprepare before restarting."
            )
    names = set(data["configs"]) | {
        row["name"] + ".conf"
        for row in manifest.get("segments", [])
        if re.search(
            r"^\s*GPUresident\s+on\s*$",
            (package / (row["name"] + ".conf")).read_text(),
            re.M | re.I,
        )
    }
    for name in names:
        text = (package / name).read_text()
        if CLIENT not in text or re.search(r"^\s*tclForces\s+on", text, re.M | re.I):
            raise ValueError(
                f"GPU electrode callback was removed or duplicated in {name}."
            )
        convert_config(text)


def record_cpu_backend(package, manifest, reason):
    manifest["electrode_gpu"] = dict(
        enabled=False, backend="CPU reference", reason=reason
    )
    for name in ("manifest.json", "nadoc_md_run.json"):
        (package / name).write_text(json.dumps(manifest, indent=2) + "\n")


def configure_package(package, binary, devices, *, registry=None):
    """Called by the local runner before probing/launching; saved jobs pin their library."""
    package = Path(package)
    path = package / "manifest.json"
    manifest = json.loads(path.read_text())
    if not manifest.get("two_electrodes"):
        return
    if manifest.get("electrode_gpu", {}).get("enabled"):
        validate_package(package, binary, devices)
        return
    root = Path(registry or os.environ.get("NADOC_ELECTRODE_GPU_DIR", REGISTRY))
    if not (root / "provenance.json").is_file():
        record_cpu_backend(
            package,
            manifest,
            "No validated GPU electrode plugin installed on this host.",
        )
        return
    build = json.loads((root / "provenance.json").read_text())
    if sha(binary) != build["installed_engine_sha256"]:
        record_cpu_backend(
            package,
            manifest,
            "Selected NAMD binary does not match the GPU plugin ABI checksum.",
        )
        return
    if str(devices).lower() in ("", "cpu") or len(str(devices).split(",")) != 1:
        return
    if sha(root / "electrode.so") != build["plugin_sha256"]:
        raise ValueError(
            "Installed GPU electrode plugin checksum changed; reinstall the validated build."
        )
    prepared = {}
    for row in manifest.get("segments", []):
        conf = package / f"{row['name']}.conf"
        text = conf.read_text()
        if re.search(r"^\s*GPUresident\s+on\s*$", text, re.M | re.I):
            prepared[conf.name] = convert_config(text)
    if not prepared:
        record_cpu_backend(
            package,
            manifest,
            "No GPU-resident dynamics segments; CPU correction retained.",
        )
        return
    p, s = parameter_data(package)
    params = parameter_text(p, s)
    topology_files = {"system.psf"}
    for text in prepared.values():
        structures = re.findall(r"^\s*structure\s+(\S+)\s*$", text, re.M | re.I)
        if len(structures) != 1:
            raise ValueError("GPU electrode configuration requires one explicit PSF.")
        name = structures[0]
        target = (package / name).resolve()
        if not target.is_relative_to(package.resolve()) or not target.is_file():
            raise ValueError("GPU electrode PSF must be inside its job package.")
        if name != "system.psf":
            charges = np.array([a.charge for a in parse_psf_atoms(target.read_text())])
            if charges.shape != p[:, 0].shape or not np.array_equal(charges, p[:, 0]):
                raise ValueError(
                    "GPU electrode stage PSF charges differ from the reference PSF."
                )
        topology_files.add(name)
    shutil.copy2(root / "electrode.so", package / "electrode_gpu.so")
    (package / "electrode_gpu.params").write_text(params)
    for name, text in prepared.items():
        original = package / (name + ".cpu-reference")
        if not original.exists():
            shutil.copy2(package / name, original)
        (package / name).write_text(text)
    manifest["electrode_gpu"] = dict(
        enabled=True,
        backend="CUDA fixed-cell EW3DC/walls/anchors",
        engine_sha256=sha(binary),
        source_sha256=build["correction_sha256"],
        files={
            name: sha(package / name)
            for name in {
                "electrode_gpu.so",
                "electrode_gpu.params",
                "electrode_forces.tcl",
            }
            | topology_files
        },
        configs=list(prepared),
        tuning={"GPUAtomMigration": "on", "twoAwayZ": "on"},
        scope="Single GPU, fixed cell; minimization retains reference CPU forces.",
    )
    for name in ("manifest.json", "nadoc_md_run.json"):
        temp = package / (name + ".gpu.tmp")
        temp.write_text(json.dumps(manifest, indent=2) + "\n")
        temp.replace(package / name)
    validate_package(package, binary, devices)


def restore_cpu_correction(package):
    """An explicitly accepted offload fallback must retain the electrode forces."""
    package = Path(package)
    path = package / "manifest.json"
    if not path.exists():
        return
    manifest = json.loads(path.read_text())
    data = manifest.get("electrode_gpu", {})
    if not data.get("enabled"):
        return
    for name, expected in data["files"].items():
        if not (package / name).is_file() or sha(package / name) != expected:
            raise ValueError(
                "Electrode force inputs changed; cannot safely restore the CPU correction."
            )
    from backend.core.namd_electrode_protocol import apply_electrode_forces

    prepared = {}
    for path in package.glob("*.conf"):
        text = path.read_text()
        if CLIENT not in text:
            continue
        stripped = re.sub(
            r"^\s*(?:gpuGlobalCreateClient|gpuGlobal|GPUAtomMigration|twoAwayZ)\s+[^\n]*\n",
            "",
            text,
            flags=re.M | re.I,
        )
        prepared[path] = apply_electrode_forces(stripped)
    for path, text in prepared.items():
        shutil.copy2(path, path.with_suffix(".conf.gpu-correction"))
        path.write_text(text)
    manifest.setdefault("electrode_gpu_history", []).append(data)
    manifest["electrode_gpu"] = dict(
        enabled=False,
        backend="CPU reference",
        reason="Explicit GPU-resident fallback accepted; same electrode force model retained.",
    )
    for name in ("manifest.json", "nadoc_md_run.json"):
        (package / name).write_text(json.dumps(manifest, indent=2) + "\n")
