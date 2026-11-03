# Numbers we're aiming for (validated by Phase 0 harness, updated as phases land) — supporting detail

[Topic head](../../project_path_to_thousands.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Numbers we're aiming for (validated by Phase 0 harness, updated as phases land)

| Metric @ N=2000 | Today | Target |
|---|---|---|
| Polymerize 64 | ~60 s | ≤2 s |
| Full resolve | ~30 s | ≤0.2 s |
| Steady-state FPS | ~1 | ≥60 |
| `.nass` size | ~7 MB | ≤2 MB |
| Open-from-disk time | >30 s | ≤5 s |

---

## Per-phase Definition of Done

Each phase chunk is "done" when ALL of these are true:

1. **Tests run green.** Subagent must execute `just test-smart` (cite its decision + pass count; a fresh worktree has no watermark → it runs FULL, which is what these broad chunks want anyway). Cite any new tests added.
2. **No file outside the chunk's declared scope was touched** (the chunk's PR adds files OR modifies the files named in this plan; if it touched something else, justify in the report).
3. **Frontend chunks include a `NOT VERIFIED IN APP` caveat in the report** unless the subagent confirmed it in `just frontend` against `workspace/hinge_test.nass`.
4. **Three-Layer Law preserved** (no topology mutation from rendering or display state).
5. **Worktree branch name + tip commit** are reported back.
6. **No regression in benchmark harness numbers** for already-shipped phases.

After a chunk lands, the manager spawns an **evaluator agent** that:
- Reads the chunk's diff (`git diff <base>..<branch>`).
- Re-runs `just test`.
- Re-runs `python scripts/bench_assembly.py` and diffs against the prior baseline.
- Reads this file's relevant phase section for the contract.
- Reports PASS/FAIL with specifics.

---

## Coordination protocol (read this if you are a subagent)

- **You work in a git worktree** (`isolation: worktree`). Your CWD is your own copy. Other agents have their own worktrees. Do not touch master.
- **Pull the plan from this file before starting.** Find your assigned chunk in the Phase map above. Read its checklist, then dive in.
- **Read CLAUDE.md** at the project root and obey its risky-action policy + git defaults.
- **Run `just test-smart` before claiming done** (cite its decision; fresh worktree → FULL). No exceptions.
- **Update your phase's status line** in this file when you start (`IN_PROGRESS:<branch>`) and when you finish (`DONE:<commit>`).
- **Write a short completion report** in the section below: branch name, commit sha, files touched, test count, benchmark deltas if applicable, and anything surprising.
- **Do not push or open PRs.** The manager merges to master after evaluator approval.
- **If you discover the chunk needs to extend out of scope to be correct, stop and report — do not just expand.** The manager re-plans.

### Subagent prompt discipline (manager: apply this to every subagent prompt you draft)

Lessons absorbed from multi-agent failure-mode literature (MAST taxonomy, Anthropic multi-agent research notes, Augment Code, MindStudio playbooks):

1. **Write the task as a diff-in-words, not a feature.** Tell the subagent which functions to modify, which signatures to change, and what to leave alone. "Make assemblies fast" → silent gold-plating. "Add `inst_by_id` param to `_fk_*`, replace 3 linear scans, no other changes" → success.
2. **Pre-declare files touched.** Every subagent prompt lists the exact files/functions in scope. Out-of-scope edits require a STOP-and-report.
3. **Define "done" externally to the subagent.** The Done checklist in this doc is the contract — subagents don't get to relax it.
4. **Cap concurrency at 4.** Above that, coordination overhead exceeds parallel speedup. Wave Cs that need >4 subagents get split into back-to-back sub-waves.
5. **Dependency-aware dispatch.** Don't put a verification-blocked chunk in the same wave as the chunk it depends on. Verification-deferred is acceptable; verification-impossible is not.
6. **Stop them from continuing past sufficient.** Explicit "if X is done, stop and report; do NOT also do Y" clauses. The expensive failure mode is agents that succeed at the task and then keep going.

### Worktree gotchas (discovered the hard way 2026-05-18 — confirmed by 2 agents)

- **Edit tool absolute-path hazard.** Inside a worktree at `/home/joshua/NADOC/.claude/worktrees/agent-<id>/`, the Edit tool resolves an absolute path like `/home/joshua/NADOC/backend/api/foo.py` to the *parent* working directory (master), NOT the worktree's own copy. `cd` in Bash calls doesn't persist across tool invocations, so even after `cd <worktree>`, the next Edit may target the parent. **Mitigation in subagent prompts:** edit via paths relative to the worktree CWD (`backend/api/foo.py`), OR use the full worktree path (`/home/joshua/NADOC/.claude/worktrees/agent-<id>/backend/api/foo.py`). Verify with `git -C <worktree> status` before committing. If you slipped: `git -C <main-repo> checkout -- <files>` reverts the parent, then re-apply inside the worktree.
- **Pre-existing transient router-suite flakes.** Multiple order-dependent flakes exist in the router suite:
  - `tests/test_seamless_router.py::test_teeth_closing_zig`
  - `tests/test_seamed_router.py::test_advanced_seamed_clears_existing_auto_route_before_teeth_reroute`
  Both pass in isolation, both fail under specific parallel-run orderings. Not caused by this refactor (proven: Phase 3e is frontend-only and triggered the second one). Future agents: when `just test` reports a router-suite failure as the ONLY failure, re-run the specific test in isolation; if it passes, it's the same flake family. Don't try to fix.
- **Bench-environment hazard (2026-05-18, discovered after Phase 4e).** Worktrees do NOT inherit master's `workspace/` (it's gitignored). The bench script's `_resolve_workspace_root` falls back through several candidates, but if the source `.nadoc` referenced by the .nass isn't in any candidate dir, the backend's `_load_design_from_source` raises 400, `_design_for(inst)` swallows the exception and returns `None`, and the per-joint slow path is silently skipped. The bench then reports impressively fast resolve numbers that are MEANINGLESS. **Subagent prompts that run benches MUST:** (a) explicitly require `export NADOC_WORKSPACE=/home/joshua/NADOC/workspace` before running, AND (b) sanity-check `/assembly/geometry` response — if `errors` is non-empty or `sources` is missing the expected source key, the bench is invalid and the agent must report that, not the timing.

- **`git reset --hard HEAD` destroyed unstaged work (2026-05-18).** During Phase 4e validation the manager ran `git cherry-pick --no-commit <sha>` to test the diff in-place, then `git reset --hard HEAD` to revert. The user had 5 unstaged frontend modifications (the WASD + Save As + UX overhaul follow-ups). `git reset --hard` discards the working tree, INCLUDING unrelated unstaged changes that weren't part of the cherry-pick. Those modifications were lost (not recoverable via `git fsck` because they were never staged or committed). **Rule for future manager + subagents:** before any `git reset --hard`, `git checkout --`, `git stash drop`, or `cherry-pick --no-commit` followed by reset, run `git status` first. If anything is unstaged or untracked AND it's not yours, stop and confirm. The safe in-place test pattern is `cp original.py /tmp/backup && cp new.py original.py && bench && cp /tmp/backup original.py` — no git ops, no risk to user state.

- **mesh.visible matters, and it's set to FALSE by default by `buildHelixObjects` for LOD meshes (2026-05-18, the bp-invisibility saga).** `buildHelixObjects` allocates multiple LOD-specific InstancedMeshes (backboneSpheres / strandCones / baseSlabs for full; helixCylinders / overhangCylinders for cylinders rep) and starts ALL of them with `mesh.visible = false`. A downstream `setDetailLevel(rep)` call is what flips the right ones to `visible = true` per the requested LOD. The OLD per-instance renderer ran setDetailLevel implicitly via its update path; the SHARED renderer never did. Result: every count>0 mesh in the shared path was hidden. **For ~10 turns we chased symptoms (shader patches, cache keys, hardcoded offsets) while `obj.visible = false` was sitting plainly visible in a probe we never ran.** JS-side probes don't catch `mesh.visible = false` unless explicitly checked. Track-B per-frame onBeforeRender counters finally surfaced it: zero hits = mesh never drew = mesh not visible. **Rule for future subagents touching the shared renderer or any LOD-multiplexed InstancedMesh:** after any `_patchSharedMeshes`-like step that resizes count or replaces attributes, EXPLICITLY set `obj.visible = true` on every mesh whose `count > 0`. Don't rely on `buildHelixObjects` to leave visibility correct — it won't.

### Where the shared renderer stands (2026-05-18)

After commits a2d71b6 (Track-B instrumentation) + d8a7526 (visibility fix) + 1ceec55 (per-bp color texture), the shared-instancing path renders correctly:
- 200 hinges visible at correct world positions on `?shared=1`.
- Strand colors restored via per-source `u_bpColor` DataTexture (parallel pattern to `u_bpXform`).
- Memory profile: ~36 MB per source (bp meshes), ~32 KB transforms texture, ~14 KB bp-color texture. Well under Chrome's per-tab budget.

**Known follow-ups (not blocking baseline):**
- Live strand-color UI changes don't yet propagate into the per-source `bpColorTex`. User can SEE the initial palette; changing strand color in UI is a no-op until Phase 3d wires the update path. Track in Phase 3d-A.
- 18 stub methods on the shared renderer no-op gracefully (`pickInstance`, `setLiveTransform`, etc.); per-instance pick + live drag deferred per scope.
- Debug scaffolding still active: `NADOC_DBG_FIXED_OFFSET`, `NADOC_DBG_RENDER_TRACE`, the diagnostic console warnings, `__NADOC_DBG__.traceFrame`. Strip after Phase 3e/3d land.
- Joint indicators still use the OLD per-instance path (~6000 Three.js Meshes for 200 joints × ~3 indicator parts × ~10 sub-meshes). Phase 3e collapses them.

- **Stub-coverage audit gap (2026-05-18, Phase 3b/3c).** The Phase 3b/3c subagent picked which 25 methods to implement vs stub-throw based on its read of "static render + bulk creation" scope. It missed that `nav_controller.js` calls `getInstanceCenters()` **every frame** via the fly-mode `_checkThreshold` → `_nearestPart` → `_getParts` chain. With the flag ON, the rAF loop threw a stack trace per frame the moment the user tried it. Adversarial evaluator also missed it — they checked code correctness in isolation, not call-site coverage. **Rule for future subagents touching the shared renderer's stub list:** before stubbing a method, `grep -rn "assemblyRenderer\.<name>" frontend/src/` AND `grep -rn "<name>" frontend/src/scene/nav_controller.js frontend/src/scene/selection_manager.js frontend/src/main.js`. Any call site in the rAF loop or a tight UI event handler MUST be implemented, not stubbed. The stub-throw message must remain clear so when an inevitable miss happens, the stack trace tells the user exactly which method needs implementing. Fix landed at `d0d8d03` — `getInstanceCenters` mirrors `getBoundingBox`'s per-instance matrix iteration.

---

## Related

- `[[polymerize-origami]]` — current polymerize impl, shipped 2026-05-15. Contains the deferred-work list this plan formalizes.
- `[[assembly-overhaul]]` — original assembly architecture decision doc.
- `/home/joshua/.claude/plans/resilient-growing-sparrow.md` — Phase 1–3 of the previous rendering-memory plan (cheap LOD, compact wire, source dedup); we build on top.
