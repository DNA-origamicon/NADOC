# PEG Live simulations

## Use

Select a **prepared or previously run PEG job** in Simulations → oxDNA, then
click **Live**. The parent must already contain its coating particles. Live uses
that frozen DNA+PEG topology; it does not add PEG to a DNA-only job.
**Stop Live** ends the worker and restores the preview controls. Coating inputs
and the coating/surface enable toggles are locked during Live. Stop and prepare a
new job to change segment count, patch placement, seed, bead size or terminal charge.
Surface position/stiffness, anchor and field updates use the existing Live controls.

The PEG bindings were built locally on 2026-09-11. For another installation:

```sh
bash scripts/build-oxdna-peg.sh
bash scripts/build-oxdna-peg-live.sh
```

The second script builds `~/.local/share/nadoc/engines/oxdna-peg/build-live/python`.
It neither installs over the normal oxpy package nor replaces the batch engine.
`NADOC_PEG_OXPY_PATH` can select an alternate compatible bindings directory.
The capability response at `/api/oxdna/live/available` now includes a separate
`peg: {available, reason}`. A missing build disables PEG Live with build instructions.
An existing page may need reloading to refresh its initial capability check.

## Implementation and contracts

- An isolated Python subprocess keeps one PEG `OxpyManager` alive across bursts.
  JSON-line commands handle stepping and steering; native engine output goes to a
  temporary log, separate from the protocol. Stock and PEG oxpy never share a process.
- Live copies the prepared DNA+PEG topology and retains DNA2PEG parameters,
  `dt ≤ 0.001`, coating trap indices and neutral-backbone field exclusion.
  CUDA is preferred by the existing Live selector; failed CUDA initialization
  falls back to the separately staged CPU input and reports that fallback.
- Frames read the correct DNA indices despite appended PEG particles. PEG uses
  center-of-mass positions and synthetic `capN` identities. Coordinates stay in
  the simulation frame so alignment does not rotate the grafted surface.
- Physical fields (`field_V_per_m`) compose signed DNA and terminal forces.
  Neutral PEG backbone beads receive no uniform DNA force. Physical-field changes
  require `/reconfigure`, which rewrites all signed forces together; `/field` is
  the legacy DNA-force steering endpoint and rejects physical sessions.
- Reconfiguration uses the worker's current snapshot and retains the prepared
  topology. Changed coating parameters and inconsistent stored particle indices
  return a conflict instead of silently altering the coating.
- Stop kills only the owned worker if needed and removes its temporary directory.
  Staging failures remove partially written directories. Runtime errors remain
  visible in the Live status after stopping; process-exit diagnostics are retained
  in the error response before temporary logs are removed.

`main.js` LOC delta for this Live change: **0**.

## Verification and remaining barriers

- Built PEG CPU/CUDA oxpy bindings successfully; isolated import confirms both
  `BaseForce.F0` and `.dir` bindings. No stock oxpy replacement was performed.
- Fast regressions cover topology/parameter/trap preservation, DNA/PEG indexing,
  physical terminal forces, continuation validation, start/reconfigure routing,
  current-pose preservation and staging cleanup. A real subprocess with a **fake
  oxpy module** checks persistence, CUDA→CPU fallback reporting and cancellation.
- Playwright drives the real app's unified job selection → Live → PEG frame
  rendering → Stop, with mocked Live responses. It verifies the bead instance
  coordinates and control locking. This checks UI plumbing, not molecular dynamics.
- Playwright persists only the existing prefixed scratch design
  `workspace/playwright_tests/__e2e__peg-coating.nadoc`, removed in `afterAll` and
  global teardown. Live/job endpoints are intercepted, so it creates no engine
  session or job artifacts. Cleanup was verified after the run.
- Real CPU/CUDA stepping tests are present as
  `test_real_peg_worker_bursts_and_stops` in `tests/test_peg_live.py`, marked `slow`.
  They have **not been run**: no user-opened test session is active. Run them after
  opening `just test-session` in your terminal. This remains the execution-validation
  barrier; successful compilation/import does not prove force or sampling validity.
- `just smoke` remains blocked by the repository guard while the existing oxDNA
  simulation is running. No guard override or simulation interruption was used.
- The broad fast suite still fails on missing unrelated `BigO.nadoc`,
  `BigO-poly.nass` and `smallO-poly.nass` workspace fixtures.
- NAMD Live mapping, chemical calibration, electrode/solvent physics, and the
  earlier setup/persistence gaps remain in [PEG setup barriers](peg_coating_setup.md).
- The shared field card currently emits legacy force-per-nucleotide settings.
  Physical V/m mode is supported by the Live API but still needs a dedicated UI
  control; legacy force mode does not drive PEG terminal charges.
- Live retains the existing Live run-stage thermostat, temperature and salt
  defaults; complete inheritance of a parent's thermodynamic protocol is a separate
  configuration task. Reconfiguration currently restarts engine/thermostat state
  from a coordinate snapshot, as in stock Live; it is not an uninterrupted production
  trajectory for kinetic or equilibrium measurements.

Build barrier resolved: the first attempt inherited Conda compiler flags and failed
on a system Python header include. The script now explicitly uses `/usr/bin/gcc`
and `/usr/bin/g++` with clean compiler flags, in its own build directory.

Latest verification: **37 focused tests passed** (2 real-engine cases deselected),
**6,255 frontend tests passed**, and **3 Playwright tests passed**, including PEG
Live visibility, CM instance transforms, control locking and stop. Changed Python
files pass Ruff and `git diff --check` is clean. Repository-wide Ruff retains the
two existing unused-name errors in `routes_oxdna.py` and `test_oxdna_peg.py`.

`just test-smart` selected **FAST**: **8,171 passed, 109 skipped, 11 failed**;
all failures are the missing unrelated workspace fixtures listed above. Its
slow-suite deferral was:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
Ask the user to run `just test-session` (their terminal), then `just test-slow`.
```
