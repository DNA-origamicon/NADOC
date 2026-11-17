# oxDNA Setup Guide (incl. WSL + GPU)

This document covers getting **oxDNA** installed so NADOC's **Dynamics** sidebar
can run coarse-grained relaxation, E-field, and protein-DNA jobs. It also covers
the WSL2 + NVIDIA GPU story (shared with NAMD).

NADOC uses one pinned build of upstream `lorenzo-rovigatti/oxDNA`. Upstream merged
CUDA DNANM protein-DNA support in February 2026 (PR #192), so a separate ANM fork
is no longer required. The latest tagged release predates that merge; use NADOC's
build script instead of an older release package.

---

## TL;DR

1. **GPU under WSL2** = keep only the **Windows** NVIDIA driver; verify with
   `nvidia-smi` *inside* WSL. (Same rule as NAMD — see below.)
2. Install build tools: `sudo apt-get install -y build-essential cmake git`.
   For a GPU build, also install the CUDA toolkit (provides `nvcc`).
3. Run `scripts/build-oxdna.sh`. It pins a reviewed upstream revision, builds
   `oxDNA`, `DNAnalysis`, and the patched `oxpy` bindings required by Live, installs
   the binaries under NADOC's engine directory, and installs oxpy into NADOC's `.venv`.

---

## How NADOC finds oxDNA

`find_oxdna()` in [backend/core/oxdna_runner.py](../backend/core/oxdna_runner.py)
resolves the binary like this:

1. **`$OXDNA_BIN`** — explicit override (absolute path or a name on `$PATH`). Always wins.
2. Otherwise, among these candidates it **prefers a CUDA-capable binary**:
   - `~/.local/share/nadoc/engines/oxdna/current/bin/oxDNA`
   - `oxDNA` on `$PATH`
   - `~/oxDNA/build_cuda/bin/oxDNA`
   - `~/oxDNA/build/bin/oxDNA`
   - `~/Applications/oxDNA/build/bin/oxDNA`

**The CUDA preference is deliberate** and fixes the most common broken state: a
CPU-only `oxDNA` first on `$PATH` (a conda/apt install) silently shadowing a
perfectly good local GPU build, so every `backend = CUDA` MD stage aborts with
`ERROR: Backend 'CUDA' not supported`. NADOC now skips a CPU-only binary in
favour of a CUDA one when both are present (detected statically via `ldd` →
`libcudart`). A CUDA build also runs the CPU backend fine, so preferring it is
never wrong. So you usually do **not** need `$OXDNA_BIN` even with a CPU-only
oxDNA on `$PATH` — just build the CUDA engine into `~/oxDNA` and NADOC finds it.

> **Quick check / one-command fix:** `just oxdna-doctor` reports your GPU,
> toolchain, which binary NADOC resolves, and whether it is CUDA-capable.
> `just oxdna-doctor --fix` auto-builds the pinned CUDA-enabled upstream oxDNA.

`DNAnalysis` — the ground-truth H-bond counter used by the health check — builds
alongside oxDNA and is found **next to** the resolved oxDNA binary (or via
`$DNANALYSIS_BIN` / `$PATH`). No separate install.

See [external_tools.md](external_tools.md) for the full environment-variable
reference shared across all simulation back-ends.

`oxpy` is built from the same pinned source and installed into the interpreter that
runs NADOC. By default that is `<repo>/.venv/bin/python`; set `NADOC_OXPY_PYTHON`
only when the backend intentionally uses a different interpreter. The managed build
also applies NADOC's `BaseForce.F0`/`BaseForce.dir` steering patch required by Live.

## Surface deposition

Surface deposition is an option on a prepared continuation job. Select a completed
relaxation, use **+ New job** to create a production continuation, then select the
new queued job. Enable **Hard surface**, add the intended **Surface Anchors**, and
check **Surface deposition** in the Anchors card. Use **Send all to surface
anchors** if the selections are currently in Structure Anchors.

The toggle saves a gentle approach, main approach, contact-restraint settle, and
equilibration protocol onto that same job. It does not launch a simulation; use
the normal **Run** button after editing. Unchecking it restores ordinary production
with the chosen surface and surface anchors. Started jobs are immutable; create a
new continuation to change their protocol. Deposition uses its own normal-only
anchor forces; electric fields, Structure Anchors, and grafted capture strands
require an ordinary continuation instead.

The approach begins at 1 pN per anchor, then 5 pN, with an adaptive ceiling of
50 pN. Contact is checked every 10,000 steps during up to 40 extra approach
windows (the same 400,000-step extra budget as the previous eight windows).
Adaptive windows and contact retries retain checkpoint velocities instead of
randomizing them again. Captured anchors retain their normal-only restraints,
with stiffness 2 in oxDNA units. Each anchor must actually reach the 0.75 nm contact band; subsequent thermal
excursions do not erase an established contact or release its restraint. Lateral
motion remains free.

Protein-containing continuations inherit the parent's frozen `anm.par` and
sequence parameter file as well as its topology and relaxed configuration. A
missing required protein parameter file is reported while preparing the job,
before launching oxDNA.

## Live continuation

**Live** always starts from the currently selected completed oxDNA job, using that
job's last configuration as its initial coordinates. At launch—and whenever the
cards are changed during a Live session—NADOC composes the current enabled simulation
settings into the ephemeral run:

- the current electric-field magnitude and direction;
- the hard-surface normal, stiffness, offset, and absolute position;
- ordinary structure anchors and surface-deposition anchors; and
- inherited surface capture strands, including whether those beads participate in
  the electric field.

Changing the selected job before pressing **Live** changes the parent configuration;
the launch path re-reads that selection after any stale-job refresh. Live does not
modify the selected job or its saved output.

---

## Prerequisites

```bash
# Build toolchain (Ubuntu / WSL2)
sudo apt-get update
sudo apt-get install -y build-essential cmake git

# Check versions (oxDNA needs a C++14 compiler + CMake 3.x)
cmake --version
g++ --version
```

A **GPU build is optional** but strongly recommended for real systems — oxDNA on
the GPU is ~1–2 orders of magnitude faster. The GPU build additionally needs the
**CUDA toolkit** (`nvcc`):

```bash
nvcc --version       # only required for the CUDA build
nvidia-smi           # GPU must be visible (inside WSL too)
```

> **WSL2 + GPU — the one thing people get wrong** (identical to NAMD): install the
> NVIDIA driver on **Windows only**; never `apt install` a Linux NVIDIA driver
> inside WSL (it breaks the `/usr/lib/wsl/lib/libcuda.so` passthrough). If
> `nvidia-smi` works inside WSL, GPU access is done. The **CUDA toolkit**
> (`nvcc`), however, *is* installed inside WSL when you want to compile the CUDA
> build — that's the compiler, separate from the driver.

---

## Install mainline oxDNA (DNA-only MD)

### CPU build (always works, no GPU needed)

```bash
git clone https://github.com/lorenzo-rovigatti/oxDNA.git ~/oxDNA
cd ~/oxDNA
mkdir -p build && cd build
cmake ..
make -j$(nproc) oxDNA DNAnalysis
```

This produces:
- `~/oxDNA/build/bin/oxDNA`        ← the engine NADOC auto-detects
- `~/oxDNA/build/bin/DNAnalysis`   ← the H-bond health oracle (found next to it)

### CUDA / GPU build (recommended for real systems)

The fastest path is `just oxdna-doctor --fix`, which runs exactly the commands
below. To do it by hand, add `-DCUDA=ON` and your GPU's compute architecture.
One CUDA-built binary runs **both** the GPU and CPU backends (oxDNA picks per the
input file), so a single build into `~/oxDNA/build` is enough — NADOC's
CUDA-preferring resolver will choose it over any CPU-only `oxDNA` on `$PATH`:

```bash
cd ~/oxDNA
mkdir -p build && cd build
cmake .. -DCUDA=ON -DCMAKE_CUDA_ARCHITECTURES=86
make -j$(nproc) oxDNA DNAnalysis
```

`86` is the compute capability for an RTX 30-series (e.g. RTX 3080 Ti). Use the
value for your card (`75` for RTX 2080/2080 Super, `89` for RTX 40-series — see
https://developer.nvidia.com/cuda-gpus). `just oxdna-doctor` prints your card's
value, or read it from `nvidia-smi --query-gpu=compute_cap --format=csv`.

If you prefer to keep a separate CPU fallback, build CUDA into `~/oxDNA/build_cuda`
instead — that path is also auto-detected and **preferred** for GPU runs, so you
still don't need `$OXDNA_BIN`.

> **The conda toolchain works.** A fully conda-forge toolchain (conda's `nvcc`
> + `gcc`, no system CUDA install) builds the CUDA engine cleanly on current
> upstream oxDNA — verified on native Ubuntu with conda CUDA 12.9 + g++ 14.3,
> RTX 3080 Ti (`sm_86`). An earlier "CCCL macro conflict with conda CUDA
> headers" failure is no longer reproducible. You do **not** need a system-wide
> CUDA toolkit; `conda install -c conda-forge cuda-nvcc cuda-cudart-dev` suffices
> if `nvcc` is missing.

> **`$OXDNA_BIN` is now rarely needed.** NADOC prefers a CUDA-capable binary
> automatically, so a leftover CPU-only `oxDNA` on `$PATH` no longer shadows your
> GPU build. Set `$OXDNA_BIN` only to force a *specific* binary.

### Which GPU does oxDNA use?

By default device `0`. To pick a different GPU, set `OXDNA_DEVICE` (e.g. `1`) —
the value NADOC reports as the recommended device.

---

## Run the adaptive large-assembly build on RunPod

The first remote-submission phase is headless and targets the two GPU architectures
that match Alpine's planned deployment: H200 (`sm_90`) and RTX PRO 6000 Blackwell
(`sm_120`). Prepare an oxDNA job normally, then submit its persisted job id:

```bash
uv run python scripts/submit_runpod_oxdna.py JOB_ID --gpu rtx6000 --budget 5
```

The command uses `$RUNPOD_API_KEY` or `~/.runpod_key`, selects the account's sole
network volume by default, compiles the pinned adaptive-memory engine into that volume,
uploads a compressed prepared job, runs a restartable stage chain, fetches authoritative
stage outputs into the normal `workspace/oxdna_jobs/JOB_ID` directory, and destroys the
pod. Pass `--volume ID` when the account has multiple volumes. `--no-volume` permits any
datacenter for validation but makes the engine and checkpoints ephemeral.

The default campaign ledger is `workspace/runpod_oxdna_campaign_spend.json`. Its cap is
cumulative across failed boots and retries; the provider-owned `terminateAfter` deadline
is shortened to the affordable remainder. The CLI refuses a budget above $5. A successful
return additionally requires a fetched `last_conf.dat`, adaptive CUDA telemetry, runtime
completion timing, and no failed chain status.

The validated reference run used 32 copies of BigO (451,584 nucleotides) on an H200 and
is recorded under `workspace/runpod_oxdna_validation/`. Alpine submission remains a later
phase and must reuse this build/chain contract rather than introduce another oxDNA runner.

### Adaptive-memory validation (2026-08-27)

The adaptive build was compared with unmodified upstream oxDNA at revision
`8028cf33b3cba12992b771156085fa54879f50cd` on the same H200 and inputs.

- On the 451,584-nucleotide BigO assembly, upstream derived a global capacity of 23,486
  neighbours per particle from one dense cell. It allocated 140,997.86 MB of CUDA memory
  and completed no MD step during a 373-second observation. The adaptive build initialized
  with about 219 MB and completed a stable 100-step run at 2.56054 ms/step. This establishes
  a practical large, nonuniform-geometry capability that the fixed-capacity build did not
  provide under the benchmark constraints; it does not claim upstream could never finish.
- A 597-nucleotide, 10-strand control exercised actual adaptive growth from 8 to 110 entries
  per particle. In a deterministic one-step comparison, energies, positions, and orientations
  matched exactly. Maximum velocity and angular-momentum differences were respectively
  `2.98e-8` and `5.96e-8`, consistent with mixed-precision rounding.
- Both variants also completed a 10,000-step constant-energy smoke test. Adaptive timing was
  0.0560788 ms/step versus 0.0551406 ms/step upstream, about 1.7% overhead on this deliberately
  small system. Long mixed-precision trajectories are chaotic and are therefore treated as a
  stability test, not a pointwise equality test.

The isolated small-system campaign spent $1.14834 of its $2 cap. Its machine-readable report
is `workspace/runpod_oxdna_small_validation/validation_report.json`; RunPod workspace reports
and spend ledgers are local evidence and intentionally remain outside version control.

## Install upstream oxDNA (`DNANM` included)

The script checks out NADOC's pinned upstream revision and builds one engine for
DNA-only and protein-DNA jobs:

```bash
scripts/build-oxdna.sh
```

For the NADOC adaptive-memory CUDA flavor, which uses measured-capacity neighbor
and edge lists plus compact cell storage:

```bash
NADOC_OXDNA_ADAPTIVE_MEMORY=1 scripts/build-oxdna.sh
```

The flavors install side by side. The `current` symlink selects the most recently
built flavor, and NADOC automatically enables its guarded compact-list settings
for CUDA stages. The adaptive flavor also uses a linear histogram/scan/scatter
cell builder, defers the redundant step-zero CPU energy calculation, avoids
recomputing energy solely for restart-file headers, and changes the default
`verlet_skin = 0.20` to the measured BigO optimum of `0.40`. Explicit non-default
skin values remain untouched.

On an RTX 2080 Super, the fully sequenced 14,112-nt BigO repeat scales from 11.37
ms/step at 16 repeats to 22.04 ms/step at 32 repeats. See
[`tools/oxdna_memory/README.md`](../tools/oxdna_memory/README.md) for the benchmark
table, memory projections, and the current 22-bit CUDA particle-index ceiling.

It is idempotent and prints the installed binary and source revision. NADOC finds
the `current` symlink automatically; `OXDNA_BIN` remains an optional override.

Optional knobs for the script:
- `OXDNA_CUDA_ARCH` — optional compute capability override (for example `75`).
- `NADOC_OXDNA_ROOT` — managed install root.
- `NADOC_OXDNA_CPU_ONLY=1` — explicitly request a CPU-only build.

Validated on WSL2 Ubuntu, CUDA 13.3, g++ 13, RTX 2080 Super (`sm_75`).

---

## Verify

```bash
# Mainline — prints usage and exits non-zero with no input file (that's fine;
# you only care that it starts and reports a CUDA-enabled build if you built one)
~/oxDNA/build/bin/oxDNA 2>&1 | head

# One-shot: GPU, toolchain, resolved binary, and CUDA-capability in one report:
just oxdna-doctor

# Or the raw resolution:
uv run python -c "
from backend.core.oxdna_runner import find_oxdna, find_dnanalysis, oxdna_supports_cuda
ox = find_oxdna()
print('oxDNA     ', ox or '(not found)', '[CUDA]' if ox and oxdna_supports_cuda(ox) else '[CPU-only]')
print('DNAnalysis', find_dnanalysis() or '(not found)')
"

.venv/bin/python -c "from backend.core.engines import oxpy_live_info; print(oxpy_live_info())"
```

Then restart the NADOC backend (`just dev`) and open the **Dynamics** sidebar —
the "oxDNA missing" warning should be gone.

## Job wizard validation and headless regression

The three-tab oxDNA job wizard validates its engine build, force field, backend,
salt concentration, stage lengths, base-pair retention gate, and retry count before
enabling **Create job**. Its final configuration table supports per-stage overrides;
the resolved values and selected engine variant are preserved in the prepared-job
payload.

Browser automation should use
[`OxdnaWizardDriver`](../frontend/e2e/helpers/oxdna_wizard_driver.js), which provides
headless methods for opening the wizard, selecting Local/Alpine/RunPod, choosing an
engine, editing protocol fields and stage cells, and creating a prepared job. Run the
focused regression with:

```bash
cd frontend
npx playwright test e2e/oxdna_job_wizard_paths.spec.js --reporter=list
```

The regression generates a uniquely named two-helix design from the minimal checked-in
seed and deletes it in `afterAll`; the global Playwright teardown also removes any
`__e2e__` design artifact after an interrupted run. Job creation and RunPod APIs are
intercepted, so the test launches no oxDNA process, cluster job, or paid pod.

Local prepared-job creation is wired through the wizard. Alpine authentication,
availability, partition selection, and configuration preview are wired, as are RunPod
preflight, GPU pricing, storage, and budget preview. Remote **Create job** remains
intentionally blocked in the frontend launch handler until those submission paths are
connected to the persisted oxDNA job workflow.

---

## Surface deposition

Surface deposition is available from **Dynamics → Anchors** when the hard surface is
enabled. Structure anchors are fixed traps used during ordinary force experiments;
surface anchors are a separate designation used to bring selected nucleotides into
contact with the hard plane.

The deposition run is staged:

1. A gentle approach starts the structure moving toward the plane.
2. The full approach applies a normal attraction to surface anchors. If they do not
   arrive together, NADOC automatically continues in short adaptive windows: anchors
   already within the capture gap receive a soft normal-only restraint, while only the
   remaining anchors continue to feel the ramped attraction.
3. Settle replaces attraction with soft normal-only restraints at the plane.
4. Equilibration retains those restraints while the anchors remain free to translate
   within the plane.

The hard-floor repulsion excludes the designated surface-anchor beads, preventing it
from competing with their attraction. Contact is gated before settle; a run fails
clearly if the configured window/force limits are exhausted. The defaults use a
1.0 nm capture gap, a 0.75 nm settle gate, 50,000-step adaptive windows, a 20 pN
force ceiling, and surface-restraint stiffness 1.0 oxDNA units. These parameters are
available through the surface-deposition API for unusually large or compliant designs.

After obtaining a good deposited frame, surface anchors can be copied into Structure
Anchors before a subsequent electric-field run. Structure anchors then hold those same
elements fixed; the surface deposition designation remains independently editable.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Job fails: `ERROR: Backend 'CUDA' not supported` | The resolved oxDNA is a **CPU-only build** (commonly a conda/apt `oxDNA` on `$PATH`). Run `just oxdna-doctor` to confirm, then `just oxdna-doctor --fix` to build the CUDA engine. NADOC then prefers it automatically. Starting a CUDA job now fails fast with this guidance instead of dying mid-run. |
| Dynamics sidebar: "oxDNA not found" | No binary on any recognized path. `just oxdna-doctor --fix`, or build to `~/oxDNA/build/bin/oxDNA`, or set `$OXDNA_BIN`. Restart the backend after. |
| `cmake -DCUDA=ON` can't find CUDA | The CUDA **toolkit** (`nvcc`) isn't installed (driver alone isn't enough). Install it (`conda install -c conda-forge cuda-nvcc cuda-cudart-dev`, or a system CUDA toolkit); confirm `nvcc --version`. |
| oxDNA runs but won't use the GPU | The resolved binary is CPU-only. `just oxdna-doctor` shows which one and whether it's CUDA-capable; `--fix` builds a CUDA one. NADOC prefers a CUDA binary automatically — no `$OXDNA_BIN` needed unless you must force a specific build. |
| `nvidia-smi` fails inside WSL | Windows NVIDIA driver missing/old, or a Linux driver was installed inside WSL. Fix on the Windows side; never install a Linux GPU driver in WSL. |
| Wrong GPU selected on a multi-GPU box | Set `OXDNA_DEVICE` to the device index you want. |
| Protein job fails / "DNANM not available" | The resolved binary predates upstream PR #192. Run `scripts/build-oxdna.sh`; do not use the older v3.7.0 release package. |
| Health check shows no H-bond count | `DNAnalysis` not found. It builds with `make … DNAnalysis`; ensure it sits next to the oxDNA binary, or set `$DNANALYSIS_BIN`. |
| Live says `oxpy not built` or the engine panel reports missing Live bindings | From the NADOC repository run `scripts/build-oxdna.sh` (or `NADOC_OXDNA_ADAPTIVE_MEMORY=1 scripts/build-oxdna.sh` for the adaptive flavor), then restart the backend. This now builds and installs patched oxpy into NADOC's `.venv`; no separate package is required. |
| Surface deposition never reaches settle | Inspect the reported remaining-anchor count and maximum gap. The runner automatically captures arrivals and ramps the remaining anchors up to the configured ceiling; increase the window count or force ceiling only if the structure remains healthy. |
| Deposited anchors stretch nearby backbone bonds | Use the surface-specific normal restraint (default stiffness `1.0`), not the generic immobile structure-anchor stiffness. Restart settle from the last healthy approach checkpoint if an older run used stiff traps. |
| Override ignored | `$OXDNA_BIN` must point at an **executable** file (or PATH-resolvable name). A bad path is silently skipped and resolution falls through. |


## Detached execution and molecular attachments

Local oxDNA jobs now run the complete protocol in a separate worker process.
Closing or restarting the NADOC API server leaves that worker running, including
stage transitions and adaptive surface-contact retries. The front end reconnects
through the existing job, progress, health and frame endpoints. Stop sends a
request to the worker, which cancels its engine subprocess and saves a stopped
checkpoint. A host reboot or worker crash still requires checkpoint recovery.

Protein–DNA conjugation springs are frozen separately in `attachment_forces.txt`.
Every stage combines these molecular springs with its current protocol forces in
`effective_forces.txt`, including adaptive retries and stages without other forces.
This preserves attachments without carrying over DNA relaxation restraints or
absolute-position pins. Legacy continuations can inherit attachment evidence
from an identical-topology ancestor when creating a new continuation or copy.
Completed trajectories are not retroactively corrected. For the previously
untethered VoltronCoreArmV2 deposition, start a corrected continuation from its
attached relaxation rather than treating the drifted result as attached sampling.

Quantum dots in the current oxDNA path are display-only; their presence in the
scene does not imply a simulated body or a DNA tether. The Display status makes
this explicit. A physical QD model and an explicit functionalization/linker must
be defined before a QD connection can be simulated.

Display shows an animated Loading indicator until the selected representation
has loaded; obsolete requests cannot overwrite newer status. Hard-surface
position inputs display at most three decimals. First activation rounds the
calculated position to 0.1 nm; loading an existing saved plane preserves its
underlying precision until the user edits it.


Protein-containing surface-deposition jobs prepared before the anchor-indexing
correction must be recreated (or copied with regenerated forces), not resumed.
Deposition now resolves every selected DNA base against the frozen topology,
including its leading protein block, for placement, approach, retries and settle
contact checks. Old contact history cannot certify the newly mapped anchors.
The earlier V2 deposition completion checks used the wrong particle indices and
are not evidence that the intended anchors reached the plane.


Protein poses in trajectory playback are now fitted from the protein beads in
each saved frame and carried through the same DNA alignment. Both trajectory
transports and progressive pages include these poses. Scrubbing applies the exact
frame pose; smooth playback interpolates translation and rotation. The separate
protein renderer no longer holds the final-configuration pose during playback.
Existing trajectories already contain the required beads; reopen the trajectory
after refreshing the application. This display correction does not alter the
simulation or repair attachments in older runs.

## Temperature ramps and observable-stability gates

In **Dynamics → oxDNA → New job → Production**, select a completed relaxation
(or production continuation), then enable **Thermal ramp**. Start/end temperatures
are in °C; the positive increment works for heating or cooling and always includes
the endpoint. The Summary shows every plateau. Disable the stability checkbox for
fixed dwell, or set sampling-block steps and maximum steps per temperature for
adaptive dwell. The current implementation uses the **local, full-system runner**;
a simulation submodel box must be disabled. Ordinary CPU/CUDA physics and frozen
CPD models are inherited from the parent. CPD supports local CPU or CUDA MD with its smaller timestep; choose GPU (CUDA)
in the production wizard to continue a CPU-relaxed parent on the GPU. No authored topology or molecular geometry changes.

Thermal jobs appear as **Tm Run 1**, **Tm Run 2**, etc., using the production run
number within each design. Expand the arrow to see selectable **25C - Run 2**,
**30C - Run 2**, etc. Queued and running temperatures have spinning indicators;
completed, failed, stopped, and paused steps have their own status labels.
The parent reports the whole job's status, including an early failure while later
temperatures remain queued. Expansion and temperature selection survive polling.

Select the parent and load a trajectory to view all temperatures in that ramp.
Select a temperature child to load only that stage, including its resumed segments.
Changing between the parent and children unloads the previous trajectory. Both
trajectory radio options honor the thermal selection; the label above the controls
states which temperatures will load. Unstarted children remain selectable, but
their trajectory controls stay disabled until a stage has started.

The wizard's production-submit path now preserves `thermal_ramp`. Jobs previously
created through the faulty path were ordinary production jobs; they are not
retroactively relabeled. Re-enable the ramp in an editable queued job or recreate it.

Trajectory playback and animation timelines show temperature ticks at recorded
stage boundaries. Hover or focus a tick to see the target temperature in °C and
the following frame range (using the player's frame numbering). These are saved
thermostat setpoints, not instantaneous measured temperatures. Downsampling keeps
the ticks aligned with the displayed frames. The design-reference seed and older
archived attempts without a saved input have no temperature label. New resumed
attempts preserve their input alongside archived frames.

The optional gate compares potential energy per particle and, by default, the
geometric fraction of designed base pairs. It checks three equal-sized trailing
windows at each block boundary: the range of window means and full-window linear drift
must each lie below the selected absolute tolerance. Every window also needs the
selected effective sample count, estimated from positive autocorrelations up to
the first nonpositive lag. Each extension grows the window by its configured
initial sample count, up to 1,000 observations per window, so longer sampling
can accumulate independent evidence. Window growth depends only on completed
blocks, never on searching for a passing result. Two consecutive passing block
boundaries are required by default; their overlapping evidence is not independent.
The original short-window drift and mean-spread checks also remain active, so
larger windows cannot conceal a recent shift.
The pairing metric is a base-site distance proxy, not a native hydrogen-bond
energy measurement. Disable it for systems without designed complementary pairs.
A low pairing fraction can pass: actual melting is allowed.

Defaults: 25–85 °C in 5 °C increments, one million steps per block, ten million
maximum steps per temperature, initially 20 samples/window, ten minimum effective samples,
energy tolerance 0.02 oxDNA units/particle, pairing tolerance 0.02. Maximum dwell
must be a whole number of blocks. Output cadence is increased as necessary to
provide at least three windows per block; the preview includes that output cost.
The maximum applies to a valid sampling attempt; numerical-instability retries
have the separate existing production retry budget and reset the gate evidence.

The runner extends a plateau from its checkpoint, preserving velocities within
that temperature, and refreshes velocities when changing temperature. Each resumed
native process gets a reproducible seed derived from its job, stage, banked steps
and retry number, recorded in `thermal_attempt_<steps>_retry<N>.json`, so sampling
blocks do not repeat the same noise sequence. Stop/resume
retains sampled steps; restart reconciliation cannot treat an unchecked native
completion as a passed gate. Copies start with fresh gate evidence. Generated
plateaus are edited through `thermal_ramp`, and shared physics through
`stage_overrides.1_production`, rather than individual generated stage rows.
Queued/copied production jobs also expose the toggle in **Edit settings**.

In adaptive (gated) mode, if the maximum dwell is exhausted, the job fails with an explicit unsettled
plateau message and does **not** advance temperature. Inspect recorded settings
(`thermal_progress`), `thermal_check.json`, and the per-block
`thermal_check_<steps>.json` files for window means, drift, effective sample
counts and the decision. All trajectories and energies remain available for
analysis. An exhausted gate can be resumed without discarding outputs through
`POST /api/oxdna/jobs/{id}/start` with `{"thermal_max_steps": 20000000}`.
The new cap must exceed the previous cap and allow all required consecutive
passes. This explicit extension preserves the previous verdict in
`thermal_budget_changes`, keeps velocities/checkpoints and all sampled segments,
and starts the next block at the same temperature. It changes neither tolerances
nor the required effective sample count. Gate version 2 records growing windows;
a pass streak from version 1 is not counted toward version 2 acceptance.
Longer sampling or independent runs may be needed; loosening a gate
changes its meaning and is not evidence of physical convergence.

With **fixed dwell**, each plateau advances after its configured steps and numerical
health checks. Stability is still measured: `thermal_check.json` records
`gate_enabled: false`, the actual energy/optional-pairing metrics, and
`stability_status: passed` or `not_demonstrated`. Missing statistical evidence or
observable drift does not fail a fixed-dwell job and is never relabeled as a
convergence pass. Neither mode imposes a minimum retained-pair fraction on thermal
production or rejects expansion merely because strands dissociate. Invalid
checkpoints, nonfinite energy and overstretched covalent backbones remain errors.

`scripts/watch_oxdna_ramp.py JOB_DIRECTORY AUDIT_DIRECTORY` watches filesystem
commit events without completion polling, journals block verdicts, and alerts on
each completed temperature, numerical retry, terminal failure/completion, or a
worker that stops updating for 20 minutes. It audits this CPD GPU melt workflow
and preserves separate numerical-completion and stability results.

Observable stability is a heuristic, **not proof of global thermodynamic
equilibrium**, and a thermal ramp alone does not validate melting temperatures.
Compare independent replicas and heating/cooling histories before interpreting
relative CPD effects. Rare transitions or metastable plateaus can escape these
checks. For thermodynamic sampling context, see the upstream
[oxDNA umbrella-sampling tutorial](https://lorenzo-rovigatti.github.io/oxDNA/umbrella_sampling.html).

For explicitly authorized native workflow checks, an existing managed parent can
be used without constructing another design:

```bash
uv run python -m scripts.validate_oxdna_thermal_ramp PARENT_JOB_ID WORKSPACE \
  --config '{"start_c":25,"end_c":30,"step_c":5,"gate":false,"block_steps":10000}'
```

This tests execution; these short runs do not establish melting thermodynamics.
