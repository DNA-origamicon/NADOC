---
name: project_md_engines_panel
description: MD Engines install/status feature — Help-menu panel + sidebar install gates + auto-build orchestration for oxDNA/NAMD/GROMACS
metadata: 
  node_type: memory
  type: project
  originSessionId: 8f79cde3-99de-41fa-89b1-04a109194b76
---

# MD Engines panel (install / status)

Shipped 2026-06-19. Goal: a zero-expertise user can get full MD on their own
machine. Closes the gap between "engine not installed" and "running a sim".

## What it does
- **Help ▸ MD Engines (install / status)…** → modal listing every engine
  (oxDNA, NAMD, GROMACS, ANM-fork, psfgen, DNAnalysis) with a red/amber/green
  dot, GPU summary, path, and a per-engine action button.
- **Sidebar install gates**: an amber banner is prepended to `#oxdna-jobs-body`
  and `#md-panel-body`; shown while that section's required engine is missing
  ("Set up engines…" → opens the modal), hidden once installed.
- **Install flow** (user chose "try auto, fall back to popup"):
  - `auto` (oxDNA, ANM-fork) → build over `/ws/engines/install` with a live
    progress bar + streamed log; on failure → command popup.
  - `download` (NAMD, license-gated) → popup with the NAMD-site link + extract cmd + Copy.
  - `guided` (GROMACS; or auto blocked by missing prereqs) → command popup.
- **GPU-aware, by design**: a CUDA GPU → plan **always targets the CUDA build**,
  never a silent CPU build. GPU present but no `nvcc` → auto is **blocked** and
  the CUDA toolkit is surfaced as a prereq (the "don't unwittingly get CPU" rule).

## Where the code lives
- Backend keystone: [backend/core/engines.py](backend/core/engines.py) —
  `engines_status()` (per-engine + GPU + toolchain + per-section readiness) and
  the pure `(gpu, toolchain) → install-plan` builders. GPU arch via
  `nvidia-smi --query-gpu=compute_cap` (pure `parse_compute_cap`).
- Build runner: [backend/core/engine_install.py](backend/core/engine_install.py)
  — pure `install_steps()` + async `run_install(engine, send)` (subprocess stream).
  Only oxDNA/ANM are auto-buildable (`installable_engine_keys()`); they build into
  the **conventional `~/oxDNA/build/`** path so `find_oxdna()` re-detects them.
- Routes: `GET /api/engines/status` in [routes_engines.py](backend/api/routes_engines.py);
  WebSocket `/ws/engines/install` in [ws.py](backend/api/ws.py) (thin → run_install).
- Frontend: [ui/md_engines.js](frontend/src/ui/md_engines.js) (factory:
  `initMdEngines({api})` → refresh/getStatus/showStatusModal/mountSidebarGates) +
  pure [ui/md_engines_logic.js](frontend/src/ui/md_engines_logic.js). Client:
  `api.enginesStatus()`. main.js wiring = +7 LOC (import + init + Help handler).

## Phase 2 — simulation switch (2026-06-19)
`NADOC_ENGINES_FORCE_MISSING=oxdna,namd,…` makes listed engines REPORT missing on
any machine, so the whole install UX renders/runs without a fresh VM or
uninstalling. `engines.forced_missing_engines()`/`is_forced_missing()`;
`engine_install.run_install` short-circuits to `_simulate_install` (streams fake
progress → declines → frontend falls back to the command popup; NO real
clone/compile). Each engine status carries a `simulated` flag.
**Answering "how to test the real build on a clean box": Docker / CI runner — NOT
git** (git is version control, never makes a clean machine). See the "Testing the
install UX" section in docs/external_tools.md.

## Phase 3 — finish a downloaded package (2026-06-19)
NAMD is license-gated (can't auto-download), so after the user downloads, the
**Download…** popup offers **"Check download & install"**:
`GET /api/engines/namd/scan-download` finds candidates in `~/Downloads`;
`engine_artifact.validate_namd_archive` verifies the file is the right package
(filename + a tar-peek for `namd3`, GPU-aware CPU-on-GPU warning);
`install_namd_archive` extracts to `~/Applications` (3.12 `filter='data'`) over the
same `/ws/engines/install` WS (extended to accept `{engine:'namd',archive_path}`)
and confirms detection. Module: [engine_artifact.py](backend/core/engine_artifact.py).
Frontend: `_downloadFinishBlock`/`_installFromArchive` in md_engines.js (+ shared
`_wsInstall` extracted from the build path); `namdScanSummary` logic helper;
`api.scanNamdDownload()`.
**KEYSTONE bug fixed**: `find_namd`/`find_psfgen` globbed `~/Applications` at
IMPORT time → a NAMD installed after server start was invisible until restart.
Now `_namd_candidates()`/`_psfgen_candidates()` glob at CALL time (namd_runner.py,
namd_topology.py; test_namd_discovery.py monkeypatches the functions). Verified
live: install round-trip now flips namd+psfgen to detected with no restart.

## Tests
`test_engines.py` (20), `test_engine_install.py` (10), `test_engine_artifact.py`
(13 — real fabricated tarballs), `test_engines_ws.py` (7 — TestClient WS: sim-switch
build round-trip + the NAMD archive verify→extract→detect round-trip + scan
endpoint), `md_engines_logic` (18), `md_engines` (5 jsdom). Backend suite 2804.
Status panel + scan endpoint + the NAMD archive round-trip all hand-verified live
(the last in a sandboxed `HOME`); the missing-engine browser UI is reproducible via
the sim switch — **[[manual_validation_debt]] MV-ENGINES**.

## Deferred / next
- GROMACS auto-install (conda `gmx` won't land on the backend's uv-venv PATH).
- Real auto-build on a clean box (Docker/CI) — the *round-trip* is WS-tested; the
  actual compile isn't run in CI yet.
- Fully hiding (vs disabling+bannering) the sidebar controls when gated.
Sibling features: [[project_oxdna_relaxation]], [[project_benchmark_tuning]],
[[project_proteins_in_simulation]]. Setup docs: docs/external_tools.md +
docs/{oxdna,namd,mrdna}_setup.md.
