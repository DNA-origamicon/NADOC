# NADOC dev task runner
# Usage: just <target>

# One-time full setup: install tools + all deps (see setup.sh)
setup:
    ./setup.sh

# Start backend + frontend together (Ctrl-C to stop). Run `just setup` first.
start *ARGS:
    ./start.sh {{ARGS}}

# Start FastAPI backend with hot reload.
# --timeout-graceful-shutdown: the status websockets (/ws/md-jobs) are long-lived
# and never close on their own, so a --reload or stop used to wedge uvicorn forever
# in "Waiting for connections to close" — freezing every job (prep heartbeat dies,
# HTTP hangs). Cap the wait so a reload always force-closes within a few seconds.
dev:
    uv run uvicorn backend.api.main:app --reload --timeout-graceful-shutdown 5 --reload-dir backend --reload-dir scripts --reload-exclude 'workspace/**' --reload-exclude 'experiments/**' --reload-exclude 'runs/**' --reload-exclude 'bp_health_runs/**' --reload-exclude 'gromacs_run/**' --reload-exclude 'memory/**' --host 127.0.0.1 --port 8000

# ── TEST POLICY ───────────────────────────────────────────────────────────────
# THE LAW: heavy (`slow`) tests — real oxDNA/NAMD/mrdna sims, CanDo-FEM solves,
# trajectory benchmarks — run ONLY inside a TEST-DEDICATED SESSION, a window the
# USER opens in THEIR terminal (`just test-session`, TTY-only). Everything an agent
# runs during ordinary coding is fast-only and must finish in under 60s.
#
# Every pytest recipe is wrapped by scripts/test_guard.sh <label> <gate> <slow>:
#   slow=1  can run slow tests -> REFUSES unless a test-dedicated session is open
#   slow=0  fast-only          -> free to run, but the 60s wall-clock BUDGET applies;
#                                 over budget prints a banner demanding a triage
#                                 subagent (.claude/skills/triage-slow-tests) that
#                                 relegates the offenders to the slow suite
#   gate=1  extra "is this really necessary?" confirm (agents: NADOC_TEST_CONFIRM=1)
# A lock (.nadoc-test.lock/) still blocks overlapping runs in every case.
# Escape hatch: NADOC_TEST_FORCE=1 bypasses everything — NOT for agents.
#
#   just test-session          # user, interactive: open a 4h heavy-test window
#   just test-session status   # is one open?   `just test-session off` closes it

# Open/close/inspect the test-dedicated session window that unlocks the slow suites.
# TTY-only, by design: an agent can fake an env var, it cannot fake a human.
test-session *ARGS:
    @scripts/test_session.sh {{ARGS}}

# What do the tests think the world looks like? Session window + heavy groups owed.
test-status:
    @scripts/test_session.sh status || true
    @echo "watermark: $(cat .nadoc-test-watermark 2>/dev/null | cut -c1-12 || echo 'none — full suite owed')"
    @echo "slow groups owed (deferred by fast-only sessions): $(cat .nadoc-slow-pending 2>/dev/null | tr '\n' ' ' || echo 'none')"

# FULL suite incl. every heavy sim (minutes). TEST-DEDICATED SESSION ONLY.
# The pre-push gate — never the per-change loop.
# --dist loadfile keeps each file's tests on one worker: tests share a module-level
# TestClient(app) over global per-doc backend state, so a file's tests must stay
# in-process and in-order. A green run bumps .nadoc-test-watermark (machine-local
# last-full-pass SHA) and clears the deferred-heavy-group debt.
test:
    scripts/test_guard.sh "test" 1 1 -- bash -c 'uv run pytest tests/ -n auto --dist loadfile && git rev-parse HEAD > .nadoc-test-watermark && rm -f .nadoc-slow-pending'

# ONLY the heavy tests (`-m slow`). TEST-DEDICATED SESSION ONLY. This is how you pay
# off the debt `just test-status` shows after a stretch of fast-only coding sessions.
# Forward pytest args: `just test-slow -k oxdna`.
test-slow *ARGS:
    scripts/test_guard.sh "test-slow" 1 1 -- bash -c 'uv run pytest tests/ -n auto --dist loadfile -m slow {{ARGS}} && rm -f .nadoc-slow-pending'

# The fast suite, nothing else (~20s): skips every `slow`-marked test. Always allowed.
# If this ever creeps over the 60s budget the guard says so and the slowest unmarked
# tests land in .nadoc-slow-candidates.json — triage them, don't raise the budget.
test-fast:
    scripts/test_guard.sh "test-fast" 0 0 -- uv run pytest tests/ -n auto --dist loadfile -m "not slow"

# DEFAULT per-change test loop. Always allowed, always fast (<60s).
# Runs the fast suite and works out which HEAVY groups your changes have made stale
# (vs .nadoc-test-watermark, the last full pass here). Outside a test-dedicated session
# it does NOT run them — it parks them in .nadoc-slow-pending and tells you. Inside one,
# it runs the owed groups too and clears the debt.
# `just test-smart --dry-run` shows the decision without running; `--base origin/master`
# overrides the watermark; forward pytest args after `--`.
test-smart *ARGS:
    scripts/test_guard.sh "test-smart" 0 0 -- uv run python scripts/select_tests.py --since-last-full {{ARGS}}

# Tightest inner loop: point pytest at the area you're editing. Pass file paths
# and/or `-k pattern`; heavy solves are dropped (`-m 'not slow'`) so it stays
# snappy. Examples:
#   just test-affected tests/test_cando_deviation.py
#   just test-affected tests/test_fem_solver.py -k rmsf
#   just test-affected tests/test_overhang_geometry.py --lf   # only last failures
# (True change-based impact analysis — pytest-testmon — is currently broken
#  against pytest 9.x; see memory/project_test_parallelization.md.)
test-affected *ARGS:
    scripts/test_guard.sh "test-affected" 0 0 -- uv run pytest -m "not slow" {{ARGS}}

# Run frontend unit tests (Vitest), single pass
test-frontend:
    cd frontend && npm test

# Build and run the headless native + Playwright ScryWrite proof of concept.
test-scrywrite:
    env -u CFLAGS -u CXXFLAGS -u CPPFLAGS -u LDFLAGS CC=/usr/bin/gcc CXX=/usr/bin/g++ cmake -S native/vr_viewer -B native/vr_viewer/build -G Ninja -DCMAKE_BUILD_TYPE=Release
    env PATH=/usr/bin:/bin cmake --build native/vr_viewer/build --target nadoc-vr-viewer nadoc-vr-scrywrite nadoc-vr-scrywrite-export nadoc-vr-interaction-test nadoc-vr-menu-layout-test nadoc-vr-scrywrite-test nadoc-vr-scrywrite-witness-test nadoc-vr-scrywrite-visual-test nadoc-vr-scrywrite-evidence-test nadoc-vr-spectator-mirror-test nadoc-vr-spectator-diagnostics-test nadoc-vr-reference-grid-test
    env PATH=/usr/bin:/bin ctest --test-dir native/vr_viewer/build --output-on-failure -R '^(nadoc-vr-interaction|nadoc-vr-menu-layout|nadoc-vr-scrywrite|nadoc-vr-spectator-mirror|nadoc-vr-spectator-diagnostics|nadoc-vr-reference-grid)'
    cd frontend && npm run test:scrywrite

# Launch the safe live VR observer replay. Override SCENE/SCRIPT as needed.
scrywrite-witness SCENE="native/vr_viewer/examples/triangle.nadocvr" SCRIPT="native/vr_viewer/examples/scrywrite_witness_menu.scry" EYE="left" GRID="room":
    env -u CFLAGS -u CXXFLAGS -u CPPFLAGS -u LDFLAGS CC=/usr/bin/gcc CXX=/usr/bin/g++ cmake -S native/vr_viewer -B native/vr_viewer/build -G Ninja -DCMAKE_BUILD_TYPE=Release
    env PATH=/usr/bin:/bin cmake --build native/vr_viewer/build --target nadoc-vr-viewer
    env XR_RUNTIME_JSON="$HOME/.local/share/Steam/steamapps/common/SteamVR/steamxr_linux64.json" native/vr_viewer/build/nadoc-vr-viewer {{SCENE}} --mirror-eye {{EYE}} --reference-grid {{GRID}} --scrywrite-witness {{SCRIPT}}

# Capture and validate the five-state live menu timeline, then attach it in Playwright.
scrywrite-menu-trace CAPTURES="/tmp/nadoc-scry-menu-trace" SCENE="native/vr_viewer/examples/triangle.nadocvr" EYE="left":
    env -u CFLAGS -u CXXFLAGS -u CPPFLAGS -u LDFLAGS CC=/usr/bin/gcc CXX=/usr/bin/g++ cmake -S native/vr_viewer -B native/vr_viewer/build -G Ninja -DCMAKE_BUILD_TYPE=Release
    env PATH=/usr/bin:/bin cmake --build native/vr_viewer/build --target nadoc-vr-viewer
    env -u LD_LIBRARY_PATH XR_RUNTIME_JSON="$HOME/.local/share/Steam/steamapps/common/SteamVR/steamxr_linux64.json" native/vr_viewer/build/nadoc-vr-viewer {{SCENE}} --mirror-eye {{EYE}} --reference-grid off --scrywrite-witness native/vr_viewer/examples/scrywrite_witness_menu_capture.scry --witness-captures {{CAPTURES}} --witness-visual-expect native/vr_viewer/examples/visual --witness-exit on
    cd frontend && SCRYWRITE_WITNESS_CAPTURE_DIR={{CAPTURES}} npx playwright test --config playwright.scrywrite.config.js witness_artifacts.spec.js --trace on

# Report locally available API layers/profilers/frame debuggers.
vr-diagnostics-check:
    scripts/vr_diagnostics.sh check

# Check host headroom and capture the latest downloaded 24hb_2xT Alpine frame.
vr-atomistic-system:
    uv run python scripts/vr_atomistic_diagnostics.py system

vr-atomistic-capture:
    uv run python scripts/vr_atomistic_diagnostics.py capture-md

# Exercise every atomistic representation exposed by the native VR menu against a
# supplied full scene snapshot and the captured real MD frame. Witness Mode is
# read-only and exits on its own after semantic representation assertions pass.
scrywrite-atomistic-24hb SCENE VISUALIZATION="/tmp/24hb_2xT-latest.visualization.txt" CAPTURES="/tmp/nadoc-scry-24hb":
    env -u CFLAGS -u CXXFLAGS -u CPPFLAGS -u LDFLAGS CC=/usr/bin/gcc CXX=/usr/bin/g++ cmake -S native/vr_viewer -B native/vr_viewer/build -G Ninja -DCMAKE_BUILD_TYPE=Release
    env PATH=/usr/bin:/bin cmake --build native/vr_viewer/build --target nadoc-vr-viewer
    mkdir -p {{CAPTURES}}
    env -u LD_LIBRARY_PATH XR_RUNTIME_JSON="$HOME/.local/share/Steam/steamapps/common/SteamVR/steamxr_linux64.json" native/vr_viewer/build/nadoc-vr-viewer {{SCENE}} --visualization {{VISUALIZATION}} --mirror-eye left --reference-grid off --place-scene-in-view on --scene-view mirror --scene-orientation front --scene-distance 0.90 --scene-scale 2.1 --scrywrite-witness native/vr_viewer/examples/scrywrite_witness_atomistic_24hb.scry --witness-captures {{CAPTURES}} --witness-exit on

# Run while the HMD is active/worn; inactive-headset samples fail closed.
vr-atomistic-steamvr-stats:
    uv run python scripts/vr_atomistic_diagnostics.py steamvr-stats

# Launch a local fixture with a read-only desktop mirror of the physical HMD eye.
vr-hmd-mirror SCENE="native/vr_viewer/examples/scrywrite_chiral_perspective.nadocvr" EYE="left" GRID="room" PLACE="on" VIEW="mirror" ORIENT="front" DISTANCE="1.30" SCALE="2.0" YAW="0" PITCH="0" ROLL="0" DIAGNOSTICS="/tmp/scrywrite_mirror_diagnostics.jsonl":
    env -u CFLAGS -u CXXFLAGS -u CPPFLAGS -u LDFLAGS CC=/usr/bin/gcc CXX=/usr/bin/g++ cmake -S native/vr_viewer -B native/vr_viewer/build -G Ninja -DCMAKE_BUILD_TYPE=Release
    env PATH=/usr/bin:/bin cmake --build native/vr_viewer/build --target nadoc-vr-viewer
    env XR_RUNTIME_JSON="$HOME/.local/share/Steam/steamapps/common/SteamVR/steamxr_linux64.json" native/vr_viewer/build/nadoc-vr-viewer {{SCENE}} --mirror-eye {{EYE}} --reference-grid {{GRID}} --place-scene-in-view {{PLACE}} --scene-view {{VIEW}} --scene-orientation {{ORIENT}} --scene-distance {{DISTANCE}} --scene-scale {{SCALE}} --scene-yaw {{YAW}} --scene-pitch {{PITCH}} --scene-roll {{ROLL}} --mirror-diagnostics {{DIAGNOSTICS}}

# Canonical one-command ScryWrite framing workflow. Override only the desired view.
scrywrite-frame ORIENT="front" VIEW="mirror" EYE="left" SCENE="native/vr_viewer/examples/scrywrite_chiral_perspective.nadocvr" GRID="room" DISTANCE="1.30" SCALE="2.0" YAW="0" PITCH="0" ROLL="0" DIAGNOSTICS="/tmp/scrywrite_mirror_diagnostics.jsonl":
    env -u CFLAGS -u CXXFLAGS -u CPPFLAGS -u LDFLAGS CC=/usr/bin/gcc CXX=/usr/bin/g++ cmake -S native/vr_viewer -B native/vr_viewer/build -G Ninja -DCMAKE_BUILD_TYPE=Release
    env PATH=/usr/bin:/bin cmake --build native/vr_viewer/build --target nadoc-vr-viewer
    env XR_RUNTIME_JSON="$HOME/.local/share/Steam/steamapps/common/SteamVR/steamxr_linux64.json" native/vr_viewer/build/nadoc-vr-viewer {{SCENE}} --mirror-eye {{EYE}} --reference-grid {{GRID}} --place-scene-in-view on --scene-view {{VIEW}} --scene-orientation {{ORIENT}} --scene-distance {{DISTANCE}} --scene-scale {{SCALE}} --scene-yaw {{YAW}} --scene-pitch {{PITCH}} --scene-roll {{ROLL}} --mirror-diagnostics {{DIAGNOSTICS}}

# Export headset-free POV, top-down orientation, and numeric evidence artifacts.
scrywrite-evidence SCENE="native/vr_viewer/examples/scrywrite_chiral_perspective.nadocvr" SCRIPT="native/vr_viewer/examples/scrywrite_witness_chiral.scry" EXPECT="native/vr_viewer/examples/scrywrite_chiral_perspective.scry-evidence" OUTPUT="docs/generated/scrywrite/chiral_perspective":
    env -u CFLAGS -u CXXFLAGS -u CPPFLAGS -u LDFLAGS CC=/usr/bin/gcc CXX=/usr/bin/g++ cmake -S native/vr_viewer -B native/vr_viewer/build -G Ninja -DCMAKE_BUILD_TYPE=Release
    env PATH=/usr/bin:/bin cmake --build native/vr_viewer/build --target nadoc-vr-scrywrite-export
    mkdir -p docs/generated/scrywrite
    native/vr_viewer/build/nadoc-vr-scrywrite-export {{SCENE}} {{SCRIPT}} {{OUTPUT}} --expect {{EXPECT}}
    node frontend/scrywrite/render_evidence.mjs {{OUTPUT}}

# Tight loop: Vitest in watch mode — re-runs affected tests on save (sub-second)
test-frontend-watch:
    cd frontend && npx vitest

# Backend FULL suite + frontend unit tests ("is everything green?").
# TEST-DEDICATED SESSION ONLY (it runs the heavy sims). Day to day: `just test-smart`
# for the backend, `just test-frontend` for the JS.
test-all:
    scripts/test_guard.sh "test-all" 1 1 -- bash -c 'uv run pytest tests/ -n auto --dist loadfile && git rev-parse HEAD > .nadoc-test-watermark && rm -f .nadoc-slow-pending'
    cd frontend && npm test

# Commit gate for main.js refactor work: the full smoke suite — app boot, the
# File>New dialog flow, command palette, API, the console-error render gate, and
# the teardown gate (design close-session in smoke.spec.js + assembly-mode exit
# in assembly_exit_cleanup.spec.js — teardown is where #34's const-reassignment
# bug escaped, so it's now in the gate) (~1.5 min, NOT per-iteration).
#
# Guarded: a production NAMD/oxDNA/ARBD job starves the browser specs into timing
# out, so the gate would go red about the CPU rather than the code. It REFUSES to
# run rather than skipping — this is a commit gate, and a silent skip is no gate.
# Override with NADOC_IGNORE_SIM_GUARD=1.
smoke:
    @uv run python scripts/sim_guard.py smoke
    cd frontend && npx playwright test --config playwright.smoke.config.js smoke.spec.js assembly_exit_cleanup.spec.js

# Diagnose oxDNA GPU setup (add --fix to auto-build a CUDA-enabled oxDNA)
oxdna-doctor *ARGS:
    uv run python scripts/oxdna_doctor.py {{ARGS}}

# mrdna round-trip benchmarks: forward-translation traceability + back-map +
# no-explosion guards across a few designs. --fast = Phase A only (no GPU).
# Run ./scripts/setup-mrdna.sh first. (e.g. `just bench-mrdna --fast`)
bench-mrdna *ARGS:
    uv run python scripts/benchmark_mrdna_roundtrip.py {{ARGS}}

# Audit the atomistic ball-and-stick display of an oxDNA job's relaxed frame (default 6hb_sim_tests, latest job)
audit-atomistic *ARGS:
    uv run python scripts/audit_atomistic.py {{ARGS}}

# Audit a sampling of the View-trajectory frames (whole lineage) — per-frame invariants, not just frame 0
audit-trajectory *ARGS:
    uv run python scripts/audit_atomistic.py --trajectory {{ARGS}}

# Start Vite frontend dev server (requires FastAPI running separately)
frontend:
    cd frontend && npm run dev -- --host 127.0.0.1

# Build frontend for production (output to frontend/dist)
build-frontend:
    cd frontend && npm run build

# Bake hover-preview GIFs + posters for workspace/Primitives/*.nadoc (needs `just dev` + `just frontend` running)
build-primitives:
    cd frontend && node scripts/build-primitives.mjs

# Run a specific test file (fast tests only — any `slow` test in it is skipped, per
# the test policy at the top. To run that file's heavy tests, the user opens a
# test-dedicated session and runs `just test-slow -k <pattern>`).
test-file FILE:
    scripts/test_guard.sh "test-file" 0 0 -- uv run pytest -m "not slow" {{FILE}} -v

# Format code
fmt:
    uv run ruff format backend/ tests/

# Lint code
lint:
    uv run ruff check backend/ tests/

# Check agent-memory size, indexing, and link integrity without changing files.
lint-memory:
    scripts/lint_memory.sh
