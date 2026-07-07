# LAMMPS + CG-DNA Setup Guide (parallel oxDNA)

This document covers building **LAMMPS with the CG-DNA package** — NADOC's
**CPU-parallel oxDNA** engine. It runs the *same* oxDNA / oxDNA2 force field as
standalone oxDNA, but **MPI domain-decomposed** across CPU cores, which is the
only way the oxDNA model scales to very large assemblies (tens of origami,
~0.5–2 M nucleotides) that single-GPU oxDNA can't fit.

> **When you need this vs. standalone oxDNA.** For one design, single-GPU oxDNA
> (`~/oxDNA/build_cuda`) is faster — use it. Reach for LAMMPS + CG-DNA only when a
> system is too large to fit one GPU and you want to spread it over many CPU
> cores. The physics (base-pair unzipping, crossover unbinding) is identical; only
> the parallelisation differs.

The CG-DNA package (Henrich / Ouldridge / Romano / Rovigatti) provides the full
oxDNA/oxDNA2/oxRNA force field, sequence-dependent, with a Langevin thermostat
(`fix nve/dotc/langevin`).

---

## TL;DR

```bash
# 1. Prerequisites (Debian/Ubuntu):
sudo apt-get install -y build-essential cmake git libopenmpi-dev openmpi-bin

# 2. Clone + build with the three required packages (+ MPI):
git clone --depth 1 https://github.com/lammps/lammps.git ~/lammps
cd ~/lammps && mkdir -p build && cd build
cmake -D PKG_CG-DNA=on -D PKG_MOLECULE=on -D PKG_ASPHERE=on -D BUILD_MPI=on ../cmake
cmake --build . -j$(nproc)

# 3. NADOC auto-detects ~/lammps/build/lmp — restart the backend and check the
#    MD Engines panel (or: uv run python scripts/lammps_doctor.py).
```

---

## Prerequisites

| Tool | Why | Install |
|---|---|---|
| **git, cmake, make, g++** | build LAMMPS from source | `sudo apt-get install -y build-essential cmake git` |
| **MPI** (OpenMPI or MPICH) | the *parallel* speedup (domain decomposition) | `sudo apt-get install -y libopenmpi-dev openmpi-bin` |

MPI is **optional** for the build — without it LAMMPS still compiles, but as a
single-core binary, which defeats the purpose of this engine. NADOC's build adds
`-D BUILD_MPI=on` only when it sees an MPI toolchain (`mpirun`/`mpicxx`).

No GPU / CUDA is needed: the standard oxDNA styles in CG-DNA are CPU code.

---

## The build, explained

LAMMPS is built from source with three packages enabled:

| CMake flag | Package | Why |
|---|---|---|
| `-D PKG_CG-DNA=on` | **CG-DNA** | the oxDNA/oxDNA2 pair + bond styles themselves |
| `-D PKG_MOLECULE=on` | **MOLECULE** | bonded topology (FENE backbone) — a CG-DNA dependency |
| `-D PKG_ASPHERE=on` | **ASPHERE** | ellipsoidal particles (oxDNA nucleotides carry orientation) — a CG-DNA dependency |
| `-D BUILD_MPI=on` | (core) | domain-decomposed parallel run (added when MPI is present) |

Note two LAMMPS-isms that trip people up:

- The CMake **source directory is `../cmake`** (the `cmake` subfolder of the
  repo), *not* the repo root.
- The package flag keeps the **hyphen**: `PKG_CG-DNA`, not `PKG_CG_DNA`.

The resulting binary is `~/lammps/build/lmp`.

---

## How NADOC finds LAMMPS

`find_lammps()` in [backend/core/oxdna_runner.py](../backend/core/oxdna_runner.py)
resolves the binary like this:

1. **`$LAMMPS_BIN`** — explicit override (absolute path or a name on `$PATH`). Always wins.
2. Otherwise the first usable candidate among `lmp` / `lmp_mpi` / `lmp_serial`
   on `$PATH`, then `~/lammps/build/lmp`, then `~/Applications/lammps/build/lmp`.

Being *found* is not enough: only a build that included **CG-DNA** can run the
oxDNA styles. `lammps_supports_cgdna(path)` runs `lmp -h` and checks the compiled-in
styles/packages for oxDNA — the LAMMPS analog of oxDNA's CUDA-capability probe. A
LAMMPS **without** CG-DNA shows in the panel as *installed but not CG-DNA-capable*
(a "degraded" row) with a rebuild offered, exactly like a CPU-only oxDNA on a GPU box.

---

## Verify it works

Two quick checks:

```bash
# 1. Does this binary have CG-DNA?  (lists compiled-in styles)
~/lammps/build/lmp -h | grep -i oxdna        # should print oxdna2/fene, oxdna2/excv, …

# 2. Run the bundled oxDNA2 example:
cd ~/lammps/examples/PACKAGES/cgdna/examples/oxDNA2/duplex1
mpirun -np 2 ~/lammps/build/lmp -in in.duplex1
```

Or just run NADOC's doctor, which reuses the app's exact detection + build planner:

```bash
uv run python scripts/lammps_doctor.py         # diagnose
uv run python scripts/lammps_doctor.py --fix    # clone + build if missing
```

---

## Auto-install from the app

The **Help ▸ MD Engines (install / status)…** panel lists a **LAMMPS (CG-DNA /
oxDNA)** row. When it's missing (and the toolchain is present) the panel offers a
one-click **Install** that runs the clone + cmake + make above over the install
WebSocket, with a live log, and re-detects the binary — no terminal needed. If the
toolchain is incomplete it falls back to showing these copy-paste commands.

---

## MPI (the parallel speedup) needs the dev package

The build only turns on MPI domain decomposition when the MPI **developer** package
is present. If cmake reports an MPI include-path error (only the runtime is
installed), install the dev package and rebuild:

```bash
sudo apt-get install -y libopenmpi-dev
cd ~/lammps/build && cmake -D BUILD_MPI=on ../cmake && cmake --build . -j$(nproc)
```

Without it, LAMMPS still builds and runs **serial** (same physics, one core). NADOC's
runner launches serial by default and only uses `mpirun -np N` when explicitly asked
for `ranks > 1` (which requires an MPI-enabled `lmp`).

## Status in NADOC (Phases 1–3 shipped)

- **Phase 1**: detection, the engine row, install/build plan, doctor, this guide.
- **Phase 2**: a **native** oxDNA→LAMMPS transcoder
  ([backend/physics/lammps_interface.py](../backend/physics/lammps_interface.py)) that
  converts NADOC's own oxDNA `topology.top`/`conf.dat` to a LAMMPS data file + input
  script (no tacoxDNA dependency), and a runner
  ([backend/core/lammps_runner.py](../backend/core/lammps_runner.py)) that prepares a
  job and runs `lmp` to a trajectory. Verified end-to-end against a real serial LAMMPS.
- **Phase 3**: managed background **jobs + REST API** — a LAMMPS run is a persistent,
  listable, stoppable job created from the active design. Endpoints (under `/api`):
  `GET /lammps/available`, `POST /lammps/jobs`, `GET /lammps/jobs`,
  `GET /lammps/jobs/{id}`, `POST /lammps/jobs/{id}/stop`. Model
  [backend/core/lammps_job.py](../backend/core/lammps_job.py),
  routes [backend/api/routes_lammps.py](../backend/api/routes_lammps.py).
- **Phase 4**: a dedicated **"LAMMPS — parallel oxDNA" sidebar section** (between the
  oxDNA and mrDNA sections) to launch + monitor runs: a Run button (enabled when
  CG-DNA is present), an Advanced card (steps / dump / temperature / salt / ranks), a
  live-polled job list with per-row Stop. Panel
  [frontend/src/ui/lammps_jobs_panel.js](../frontend/src/ui/lammps_jobs_panel.js).
- **Phase 5**: **trajectory read-back** — the LAMMPS dump is transcoded to an oxDNA
  `.dat` and served (`GET /lammps/jobs/{id}/trajectory`) in the same payload the oxDNA
  viewer uses. Requires the design the run was made from to be loaded.
- **Phase 6**: a full **"Visualizations & processing" card** in the LAMMPS section,
  matching the oxDNA one — select a finished run, then toggle **Display** (final
  structure, + Align to design pose), **Flexibility map (RMSF)**, **Deviation map**, or
  **View trajectory** (play/scrub). It runs the *same* validated code as oxDNA: the
  backend reuses `oxdna_health` (`production_rmsf`/`geometry_deviation_map`) on the
  transcoded `.dat`, and the frontend reuses oxdna_display's pure mappers + the shared
  trajectory player. Endpoints: `GET /lammps/jobs/{id}/{display,rmsf,deviation}`.

**Not yet built** (later phases): mapping NADOC external forces (E-field, surface,
anchors) to LAMMPS `fix`es, and any torque-to-failure protocol. The
parallel (MPI) run itself is coded but not yet exercised on this machine (needs
`libopenmpi-dev`, above). See
[memory/project_lammps_oxdna.md](../memory/project_lammps_oxdna.md).

---

## References

- LAMMPS oxDNA2 pair styles: <https://docs.lammps.org/pair_oxdna2.html>
- Building LAMMPS with CMake / packages: <https://docs.lammps.org/Build_package.html>
- tacoxDNA (oxDNA ↔ LAMMPS-data converter, for a later phase):
  <https://github.com/lorenzo-rovigatti/tacoxDNA>
