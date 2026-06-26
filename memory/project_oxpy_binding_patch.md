---
name: oxpy-binding-patch
description: "The user's ~/oxDNA oxpy build is locally patched to expose BaseForce.F0/.dir read-write (needed for NADOC live-field steering); reapply after any clean rebuild."
metadata: 
  node_type: memory
  type: project
  originSessionId: e4528887-ebff-427d-83cc-f00bd959c679
---

NADOC's live oxDNA engine (`backend/physics/oxdna_live.py`, AF-21, shipped 2026-06-23) re-aims a uniform electric field LIVE between simulation bursts by mutating `force.F0` / `force.dir` on the field's `ConstantRateForce` handle. Stock oxpy does **not** expose those — only `stiff`/`rate`/`pos0` are bound on `BaseForce`, and `dir` only on `MovingTrap`. (The earlier idea of `ConfigInfo.subscribe("end_of_step", cb)` + `particle.force` injection does NOT work: oxDNA's MD backend fires no per-step event, so the callback never runs.)

**The patch (git-untracked in the user's `~/oxDNA` tree — reapply after any clean clone/rebuild):** two lines added in `~/oxDNA/src/oxpy/bindings_includes/Forces/BaseForce.h`, beside the existing `stiff`/`rate`/`pos0` bindings:
```cpp
force.def_readwrite("F0", &BaseForce::_F0, "...");
force.def_readwrite("dir", &BaseForce::_direction, "...");
```
then `cd ~/oxDNA/build && make -j12` (the venv editable-install of `~/oxDNA/build/python` auto-picks-up the refreshed `core.so` — no reinstall).

Without it, `LiveOxdnaSession` / `hox.run_live_field`'s real-oxpy path dies with `AttributeError` on `force.F0`; the gated real-oxpy tests (`pytest.importorskip("oxpy")`) would error rather than skip. The GPU-free path (mock stepper) is unaffected.

oxpy itself was built 2026-06-23 (`-DPython=ON`, CUDA reused) and editable-installed into `.venv`; `import oxpy` works with no PYTHONPATH. See the design-automation loop's `design_automation_backlog.md` Tier-6 as-built note + the AF-21 handoff. Related: [[ssdna-flexible-segments]] is unrelated; physics lives under `oxdna_*`.


---

# Detailed build notes (merged from repo topic file)

# oxpy build + field-steering binding patch (oxDNA LIVE)

The oxDNA **LIVE** field feature (`backend/physics/oxdna_live.py`,
`backend/api/routes_oxdna_live.py`) needs an importable **oxpy** whose
`oxpy.forces.BaseForce` exposes read-write `F0` and `dir`. Stock oxpy only binds
`stiff`/`rate`/`pos0`, so a live session can't re-aim/rescale the uniform `string`
field mid-run. The probe `routes_oxdna_live.oxpy_live_available()` gates the whole
feature on those two attrs.

## Two local source edits to ~/oxDNA (not upstream)

1. **Field-steering bindings** — `src/oxpy/bindings_includes/Forces/BaseForce.h`,
   after the `pos0` `def_readwrite`, add:
   ```cpp
   force.def_readwrite("F0",  &BaseForce::_F0);
   force.def_readwrite("dir", &BaseForce::_direction);
   ```
   (`_F0` is `number`; `_direction` is `LR_vector`. The LR_vector type_caster in
   `src/oxpy/vector_matrix_casters.h` force-casts a Python `[x,y,z]` list, so
   `field.dir = [0,0,1]` works.)

2. **tinyexpr link fix** — `src/oxpy/CMakeLists.txt`, the `core` target links
   `oxdna_common` but NOT `tinyexpr`. In CPU mode `oxdna_common` is a *static* lib
   and tinyexpr is only linked into the executables, so the module fails to import
   with `undefined symbol: te_interp`. Add `tinyexpr` to both `target_link_libraries(core ...)`
   branches (APPLE + non-APPLE).

## CUDA superset build (INSTALLED — what the venv oxpy now is)

The venv oxpy is the **CUDA build**, which is a *superset*: one library runs
`backend = CPU` AND `backend = CUDA`, chosen per run by the input file. Live
sessions auto-pick CUDA when a GPU is present (see "Live backend autodetect"
below). Stage-2 benchmark: CUDA wins at every size ≥250 nt (oxDNA CPU is
single-threaded) — 5.7× at 252 nt up to 125× at 10k nt on the RTX 3080 Ti.

Build dir `~/oxDNA/build_oxpy_cuda` (do NOT delete — `core.so` rpaths to its
`src/liboxdna_common.so` + miniforge libcudart). Two CUDA-specific gotchas beyond
the CPU ones:
- **`-DCUDA_COMMON_ARCH=OFF`** is mandatory. The default (ON) compiles for all
  "common" arches incl. compute_100/120 (Blackwell), whose CCCL headers hit a
  `_CCCL_PP_SPLICE_WITH_IMPL1` preprocessor bug. OFF → `-arch=native` = sm_86 only
  (the 3080 Ti) → dodges the bug AND ~19× less device code to compile.
- System g++ works as the nvcc host compiler (the CCCL failure was the future
  arches, NOT gcc-13) — keep system g++ for the Python-binding `.cpp`.

```bash
export PATH="$HOME/.local/bin:$PATH"
cd ~/oxDNA && rm -rf build_oxpy_cuda && mkdir build_oxpy_cuda && cd build_oxpy_cuda
cmake .. -DPython=ON -DOxpySystemInstall=ON -DCUDA=ON -DCUDA_COMMON_ARCH=OFF \
  -DDEFAULT_PYTHON=/usr/bin/python3.12 \
  -DCMAKE_C_COMPILER=/usr/bin/gcc -DCMAKE_CXX_COMPILER=/usr/bin/g++ \
  -DCMAKE_CUDA_HOST_COMPILER=/usr/bin/g++ -DCMAKE_BUILD_TYPE=Release
make -j"$(nproc)" core          # ~12 s on this box (native arch only)
cd /home/jojo/Work/NADOC && uv pip install --reinstall ~/oxDNA/build_oxpy_cuda/python
```

## Live backend autodetect (CPU vs CUDA)

`backend/core/oxdna_live_backend.py` — `preferred_backend()` returns "CUDA" when
`engines.gpu_info()["present"]` (cached machine probe), else "CPU". Live rundirs
(`routes_oxdna_live._prepare_live_rundir`) stage the chosen-backend `input` AND a
CPU `input_cpu`; `_OxpyStepper` (physics/oxdna_live.py) tries CUDA and, on a
GPU-init/out-of-memory failure, reopens `input_cpu`, sets `fell_back`/`active_backend`.
The frame payload carries `backend`/`backend_fell_back`/`backend_reason`; the
frontend (`oxdna_live_controller.js`) shows the engine in the status and pops a
one-shot toast on GPU→CPU fallback. Tests: `tests/test_oxdna_live_backend.py`,
`tests/test_oxdna_live_session.py`, `oxdna_live_controller.test.js`.

## CPU-only build (alternative — LIVE input uses `backend = CPU`, no CUDA needed)

Target the **NADOC venv interpreter** (`/usr/bin/python3.12`, what the backend runs
on). The uv venv has no pip, so install with `uv pip`, NOT cmake's `make install`
(its `pip install --user` would miss the venv).

Two gotchas the cmake auto-detect gets wrong on this host:
- CMake's `find_program(python)` grabs **miniforge 3.13** → force `-DDEFAULT_PYTHON=/usr/bin/python3.12`.
- The **conda g++** can't find Debian multiarch python headers
  (`x86_64-linux-gnu/python3.12/pyconfig.h`) → force the system compiler.

```bash
export PATH="$HOME/.local/bin:$PATH"           # uv
cd ~/oxDNA && rm -rf build_oxpy && mkdir build_oxpy && cd build_oxpy
cmake .. -DPython=ON -DOxpySystemInstall=ON \
  -DDEFAULT_PYTHON=/usr/bin/python3.12 \
  -DCMAKE_C_COMPILER=/usr/bin/gcc -DCMAKE_CXX_COMPILER=/usr/bin/g++ \
  -DCMAKE_BUILD_TYPE=Release
make -j"$(nproc)" core                          # builds python/oxpy/core.so
cd /home/jojo/Work/NADOC
uv pip install --reinstall ~/oxDNA/build_oxpy/python   # staged package → venv
```

## Verify
```bash
.venv/bin/python -c "import oxpy; b=oxpy.forces.BaseForce; print('F0' in dir(b), 'dir' in dir(b))"  # True True
.venv/bin/python -c "from backend.api.routes_oxdna_live import oxpy_live_available as a; print(a())"  # available: True
.venv/bin/python -m pytest tests/test_headless_oxdna_build.py -k "real_oxpy or steers" -q
```

Built & validated 2026-06-23 (oxpy 3.7, py3.12, gcc-13). All real-engine
field-steering tests pass; full `just test` 3082 passed.
