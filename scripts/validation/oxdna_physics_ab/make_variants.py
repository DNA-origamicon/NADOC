"""Build isolated, individually attributable experimental native engines.

Never edits the managed engine or its source. Run after configuring/building
the copied baseline with CUDA and -j2. Variant libraries use relative rpaths.
"""

from pathlib import Path
import difflib
import hashlib
import json
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "source"
BUILD = ROOT / "build"
REPO = ROOT.parents[2]
FILES = [
    "src/Backends/Thermostats/BussiThermostat.cpp",
    "src/CUDA/Thermostats/CUDABussiThermostat.cu",
    "src/Interactions/DNANMInteraction.cpp",
    "src/CUDA/Interactions/CUDA_DNANM.cuh",
    "src/Backends/Thermostats/BrownianThermostat.cpp",
    "src/CUDA/Thermostats/CUDABaseThermostat.h",
    "src/CUDA/Thermostats/CUDABaseThermostat.cu",
    "src/CUDA/Thermostats/CUDABrownianThermostat.cu",
    "src/CUDA/Thermostats/CUDALangevinThermostat.cu",
    "src/CUDA/Backends/MD_CUDABackend.cu",
]
baseline_dir = ROOT / "baseline_sources"
for name in FILES:
    p = baseline_dir / name
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes((SRC / name).read_bytes())
BASE = {name: (baseline_dir / name).read_text() for name in FILES}


def replace(s, old, new, count=1):
    assert s.count(old) == count, (old, s.count(old))
    return s.replace(old, new)


def current_k(files):
    for name, kt, kr in [
        (FILES[0], "K_now_t", "K_now_r"),
        (FILES[1], "K_now_t.w", "K_now_r.w"),
    ]:
        needle = "\t_update_K(_K_t, _current_translational_degrees_of_freedom());"
        files[name] = replace(
            files[name], needle, f"\t_K_t = {kt};\n\t_K_r = {kr};\n" + needle
        )


def epsilon(files, value):
    if value == 2:
        for name in ["_pro_backbone_stiffness", "_pro_base_stiffness"]:
            files[FILES[2]] = replace(
                files[FILES[2]], name + " = 1.0f;", name + " = 2.0f;"
            )
    else:
        name = FILES[3]
        s = files[name]
        start = s.index("__forceinline__ __device__ void excluded_volume_quart(")
        end = s.index(
            "__forceinline__ __device__ void excluded_volume_quart_ang(", start
        )
        block = s[start:end]
        block = block.replace(
            "c_number rc) {", "c_number rc, c_number epsilon = EXCL_EPS) {"
        )
        block = block.replace("EXCL_EPS *", "epsilon *")
        s = s[:start] + block + s[end:]
        # Only active, non-angular DNANM call sites; protein-protein keeps EPS=2.
        for site in ["backbone", "base"]:
            old = f"        excluded_volume_quart(r{'back' if site == 'backbone' else 'base'}, Ftmp, MD_pro_{site}_sigma, MD_pro_{site}_rstar, MD_pro_{site}_b, MD_pro_{site}_rc);"
            # Comments contain indented copies: require actual line prefix.
            old = "\n" + old
            s = replace(s, old, old[:-2] + ", 1.0f);")
        files[name] = s


def rigid_mask(files):
    # CPU retains every random draw; only nonphysical point angular momentum changes.
    name = FILES[4]
    old = "\t\t\tp->L = LR_vector(Utils::gaussian(), Utils::gaussian(), Utils::gaussian()) * _rescale_factor;"
    files[name] = replace(
        files[name],
        old,
        old + "\n\t\t\tif(!p->is_rigid_body()) p->L = LR_vector(0., 0., 0.);",
    )
    # Stable original particle IDs are essential: CUDA Hilbert sorting can reorder
    # protein and DNA particles. Never index a static mask by GPU slot directly.
    name = FILES[5]
    files[name] = replace(
        files[name],
        "\tllint _seed;",
        "\tllint _seed;\n\tint _rigidity_mode = 1;\n\tint *_d_rigid_flags = nullptr;\n\tint *_thermostat_particle_ids = nullptr;\n\tvoid _setup_rigid_flags();",
    )
    files[name] = replace(
        files[name],
        "\tvirtual void set_seed(llint seed)",
        "\tvoid set_particle_ids(int *ids) { _thermostat_particle_ids = ids; }\n\tvirtual void set_seed(llint seed)",
    )
    name = FILES[6]
    files[name] = replace(
        files[name],
        '#include "CUDABaseThermostat.h"',
        '#include "CUDABaseThermostat.h"\n#include "../../Utilities/ConfigInfo.h"\n#include "../../Particles/BaseParticle.h"',
    )
    files[name] = replace(
        files[name],
        "CUDABaseThermostat::~CUDABaseThermostat() {",
        "CUDABaseThermostat::~CUDABaseThermostat() {\n\tif(_d_rigid_flags) CUDA_SAFE_CALL(cudaFree(_d_rigid_flags));",
    )
    files[name] += """
void CUDABaseThermostat::_setup_rigid_flags() {
    std::vector<int> flags(CONFIG_INFO->N());
    int n_rigid = 0;
    for(auto p: CONFIG_INFO->particles()) {
        flags[p->index] = p->is_rigid_body() ? 1 : 0;
        n_rigid += flags[p->index];
    }
    _rigidity_mode = (n_rigid == 0) ? 0 : ((n_rigid == CONFIG_INFO->N()) ? 1 : 2);
    if(_rigidity_mode == 2) {
        if(!_thermostat_particle_ids) throw oxDNAException("Rigid mask requires stable CUDA particle IDs");
        CUDA_SAFE_CALL(GpuUtils::LR_cudaMalloc<int>(&_d_rigid_flags, flags.size()*sizeof(int)));
        CUDA_SAFE_CALL(cudaMemcpy(_d_rigid_flags, flags.data(), flags.size()*sizeof(int), cudaMemcpyHostToDevice));
    }
}
"""
    name = FILES[9]
    files[name] = replace(
        files[name],
        "\t_cuda_thermostat->init();",
        "\t_cuda_thermostat->set_particle_ids(_d_particle_ids);\n\t_cuda_thermostat->init();",
    )
    for name in [FILES[7], FILES[8]]:
        s = files[name]
        s = replace(
            s,
            "int N) {",
            "int N, int rigidity_mode, const int *rigid_flags, const int *particle_ids) {",
        )
        # Draws and physical velocities remain identical to the baseline.
        marker = (
            "\t\trand_state[IND] = state;"
            if "Brownian" in name
            else "\t\tvels[IND] = v;"
        )
        if "Brownian" in name:
            clearing = "\t\tif(rigidity_mode == 0 || (rigidity_mode == 2 && !rigid_flags[particle_ids[IND]])) Ls[IND] = make_c_number4(0, 0, 0, 0);\n"
        else:
            clearing = "\t\tif(rigidity_mode == 0 || (rigidity_mode == 2 && !rigid_flags[particle_ids[IND]])) L = make_c_number4(0, 0, 0, 0);\n"
        s = replace(s, marker, clearing + marker)
        s = replace(
            s,
            "\tthis->_setup_rand(CONFIG_INFO->N());",
            "\tthis->_setup_rand(CONFIG_INFO->N());\n\tthis->_setup_rigid_flags();",
        )
        s = replace(
            s,
            "CONFIG_INFO->N());\n}",
            "CONFIG_INFO->N(), _rigidity_mode, _d_rigid_flags, _thermostat_particle_ids);\n}",
        )
        files[name] = s


def snapshot(name, files, seconds):
    out = ROOT / "engines" / name
    (out / "bin").mkdir(parents=True, exist_ok=True)
    (out / "lib").mkdir(exist_ok=True)
    shutil.copy2(BUILD / "bin/oxDNA", out / "bin/oxDNA")
    shutil.copy2(BUILD / "src/liboxdna_common.so", out / "lib/liboxdna_common.so")
    subprocess.run(
        [
            "cmake",
            "-DBINARY=" + str(out / "bin/oxDNA"),
            "-DOLD_RPATH=" + str(BUILD / "src"),
            "-P",
            str(REPO / "scripts/set-relative-rpath.cmake"),
        ],
        check=True,
        capture_output=True,
    )
    patch = "".join(
        "".join(
            difflib.unified_diff(
                BASE[p].splitlines(True),
                files[p].splitlines(True),
                fromfile="a/" + p,
                tofile="b/" + p,
            )
        )
        for p in FILES
    )
    (out / "changes.patch").write_text(patch)
    (out / "manifest.json").write_text(
        json.dumps(
            dict(
                variant=name,
                build_seconds=seconds,
                binary_sha256=hashlib.sha256(
                    (out / "bin/oxDNA").read_bytes()
                ).hexdigest(),
                library_sha256=hashlib.sha256(
                    (out / "lib/liboxdna_common.so").read_bytes()
                ).hexdigest(),
                patch_sha256=hashlib.sha256(patch.encode()).hexdigest(),
            ),
            indent=2,
        )
    )
    print("BUILT", name, round(seconds, 2), flush=True)


variants = [
    ("baseline", []),
    ("current_k", [current_k]),
    ("gpu_epsilon1", [lambda f: epsilon(f, 1)]),
    ("cpu_epsilon2", [lambda f: epsilon(f, 2)]),
    ("rigid_mask", [rigid_mask]),
    ("combined_epsilon1", [current_k, rigid_mask, lambda f: epsilon(f, 1)]),
    ("combined_epsilon2", [current_k, rigid_mask, lambda f: epsilon(f, 2)]),
]


def main():
    for name, transforms in variants:
        if (ROOT / "engines" / name / "manifest.json").exists():
            continue
        files = dict(BASE)
        for transform in transforms:
            transform(files)
        for path, text in files.items():
            if (SRC / path).read_text() != text:
                (SRC / path).write_text(text)
        start = time.monotonic()
        with (ROOT / ("build_" + name + ".log")).open("w") as log:
            proc = subprocess.run(
                ["cmake", "--build", str(BUILD), "-j2", "--target", "oxDNA"],
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        if proc.returncode:
            raise RuntimeError("Build failed: " + name)
        snapshot(name, files, time.monotonic() - start)


if __name__ == "__main__":
    main()
