---
name: LESSONS — past struggles, failed approaches, anti-patterns
description: Categorized log of what didn't work and why. Read before debugging similar symptoms or proposing changes in these areas. Categorized by failure mode, not by date.
type: project
originSessionId: beb97b30-62be-44e6-bb7b-8879314d2566
---
# LESSONS

A categorized log of past struggles. Categorize by **failure mode**, not by date — patterns repeat. When a new lesson is learned, add it to the matching category or create a new one.

Format per entry: short title → one-paragraph what-went-wrong → "How to avoid" line. Keep entries tight; if it grows past ~10 lines, link out to a project file.

---

**This file is now an INDEX.** Full entries live in [LESSONS_archive.md](LESSONS_archive.md). Scan the symptom hooks below; open the archive only for the entry that matches your symptom. IDs (A1, D11, …) are stable and cited elsewhere (CLAUDE.md's Done checklist). Add a new lesson by writing the full entry in the archive under its ID heading and adding a one-line hook here.

> Note: two IDs appear twice in history — **C7** (`workspace` E2E corruption vs autosave/SSE clobber) and **D11** (loop-`copy` overlay vs cluster-move snap-back). Both are preserved; their second occurrences anchor to `#c7-2` / `#d11-2`.

## A. DNA topology / geometry reasoning
- **A1** — Geometric crossover-placement reasoning always wrong — inventing where crossovers "should" go from geometry; reverted every time. [detail](LESSONS_archive.md#a1)
- **A2** — Strand polarity / direction confusion — guessing strand direction from helix orientation instead of the topology graph. [detail](LESSONS_archive.md#a2)
- **A3** — Helical phase constants are locked — tweaking `_PHASE_*` to fix one thing breaks every downstream system. [detail](LESSONS_archive.md#a3)
- **A4** — `_frame_from_helix_axis` not rotation-equivariant — world-aliasing a tilted helix renders overhang/complement at wrong roll. [detail](LESSONS_archive.md#a4)
- **A5** — Periodic repeat transform leaks twist into bend — a straight periodic part shows a spurious per-copy bend / spiral. [detail](LESSONS_archive.md#a5)
- **A6** — Steer twist correction on SIGNED local twist — unsigned deviation field can't tell over/under-wound, places skips wrong. [detail](LESSONS_archive.md#a6)
- **A7** — Don't drive a per-segment skip controller off the twist profile — MIMO secant divides by noise, diverges/oscillates. [detail](LESSONS_archive.md#a7)
- **A8** — oxDNA long-bundle twist scatter is an equilibration transient — twist "slow mode" is really ~8M-step burn-in drift. [detail](LESSONS_archive.md#a8)
- **A10** — **The scaffold is route OUTPUT; the STAPLES are the design.** Autoscaffold read its own previous output as the face to extend from → every re-route ratcheted the helices outward (a plain 4HB bundle: 168→189→199→210 bp), persisted to `.nadoc`. Any mutation whose input is derived from its own prior output is non-idempotent by construction — normalise the input against something the mutation *cannot* touch (here: staple spans). [detail](LESSONS_archive.md#a10)
- **A9** — mrDNA `simulate(coarse_steps=)` silently skips the fine stage — CG curvature comes out ~straight; use `multiresolution_simulation`. [detail](LESSONS_archive.md#a9)

### A10. NAMD Flexibility-map leaves 21 bases unmoved/uncoloured on an ENSEMBLE-REPLICA job — the replica package was missing `charge_audit.json`, forcing the reference-PDB P-order that can't recover 5'-termini (2026-07-09)
Symptom: toggle Flexibility map (RMSF) on a NAMD **production replica** (child of an equilibration parent, e.g. prod job `6d7c2e38e455` under parent `07c05aaecc12`) → a handful of bases stay at design positions in the strand palette, never repositioned/recoloured. Same design toggled on the **parent** job looked fine — which is the trap: the parent's package HAS `charge_audit.json`, the child's does not.

ROOT CAUSE: `md_ensemble.build_replica_package` builds a production-only child package by hardlinking only the immutable structure files (PSF/PDB/hmr/forcefield) — it did **not** copy `charge_audit.json` (the psfgen segid→NADOC-chain map). Without it, `load_segid_chain_map(pkg)` returns `None`, so `_select_p_order` falls back to the **reference-PDB** P-order (`p_order_source="reference-pdb"`). That path maps the phosphate-bearing nucleotides fine, but `build_termini_specs` needs the segid map → returns `[]` → the **21 phosphate-less 5'-termini** (one per strand; pdb2gmx strips the 5' P) are never recovered → RMSF returns **1307/1328** keys. The renderer moves/colours strictly by `(helix_id, bp_index, direction)` key; the 21 render keys with no map entry stay put in default colour = the symptom. **The PSF/PDB are byte-identical hardlinks between parent and child — only the standalone `charge_audit.json` differed.**

FIX (two layers): (A) `build_replica_package` now `_link_or_copy`s `charge_audit.json` from parent → child (immutable, shareable). (B) `load_segid_chain_map` falls back to `manifest.json`'s embedded `charge_audit` field when the standalone file is absent — the replica's child manifest already carries the identical `topology_metadata.segments`, so this fixes replicas ALREADY on disk with no data migration. Verified on `6d7c2e38e455`: live RMSF route 1307→**1328**, 0 render keys unmapped.

**How to avoid**: when a code path reads a file straight from a package dir (`load_segid_chain_map`, etc.), audit EVERY package builder — full-prep AND the replica/reseed/child builders in `md_ensemble.py` — to confirm they emit that file. A fallback that reads the same data from the manifest makes the loader resilient to a builder that forgets. And **verify the actual job the user clicks**, not a sibling: parent vs. child jobs can have different package contents even for the same design. See [[project_alpine_cluster_submission]], [[project_md_viz_tools]].

### A11. NAMD metrics say "no NAMD trajectory yet" on a finished production run — the production child never inherited the parent's `design.json` snapshot (SAME failure mode as A10) (2026-07-10)
Symptom: 20 ns production run for `6hbx100_noT` (child job `892ad3d12d4f`) completes, a 1.9 GB DCD sits in `output/`, but clicking Generate for twist/curvature/base-pairing returns **"no NAMD trajectory yet for the selected job(s)"** — a lie: the trajectory is fine.

ROOT CAUSE: `md_ensemble.build_replica_package` copied PSF/PDB/forcefield/`charge_audit.json` into the child but **not `design.json`** (the frozen topology snapshot). `routes_md_metrics._job_inputs` needs it to map P atoms → base pairs; when absent it falls back to the *active* design, and when no design is loaded (`GET /api/design` → 404) that fallback raises → `_job_inputs` returns `None` for every job → the code hits its blanket "no trajectory" branch, misattributing a **missing-snapshot** failure to a missing trajectory. Only the relaxation-prep path ([routes_md.py](../backend/api/routes_md.py) ~L1287) writes `design.json`; the `spawn_md_production` / `stage_md_ensemble` child paths (both via `build_replica_package`) forgot it — while **oxDNA's child spawn already `shutil.copy`s it** (engine-parity drift).

FIX (both layers): (A) write side — `build_replica_package` now copies `parent.job_dir/design.json` → child (mirrors oxDNA). (B) read side — `_md_snapshot_design` **walks up `parent_job_id`** to the nearest ancestor with a snapshot (self-heals existing children + robust vs a legacy parent that also lacks one), and `_job_inputs` returns a **str reason** so a missing snapshot no longer masquerades as "no trajectory". Backfilled the two stuck jobs by copying the relaxation root's snapshot down. Verified: live metrics run on `892ad3d12d4f` → `ready=True`, 520 frames.

**How to avoid**: this is A10 again — **any per-child MD package builder must propagate EVERY parent artifact a downstream reader expects.** When oxDNA and NAMD have parallel child-spawn paths, diff them: if oxDNA copies a file into children and NAMD doesn't, that's the bug. And never let a resolver report the FIRST thing it couldn't find ("no trajectory") when it actually failed on the SECOND ("no topology") — return the specific reason. See [[project_oxdna_metrics_card]], [[project_md_job_system]].

---

## B. Three-Layer Law violations
- **B1** — Physics writing back to topology — relaxed positions written into the design corrupt it invisibly. [detail](LESSONS_archive.md#b1)
- **B2** — Re-centering native `.nadoc` on load — `/design/load` silently moved everyone's saved positions. [detail](LESSONS_archive.md#b2)

## C. Stale state / API misuse
- **C1** — uvicorn `--reload` keeps stale server state — Python test passes but the API returns wrong output; restart first. [detail](LESSONS_archive.md#c1)
- **C2** — Wrong mutation path — `set_design_silent` doesn't push undo; the op becomes wrongly (non-)undoable. [detail](LESSONS_archive.md#c2)
- **C3** — Wrong undo response shape — cluster-only vs full-geometry seek responses; don't invent a third shape. [detail](LESSONS_archive.md#c3)
- **C4** — E2E build-cycles wedge the shared dev backend (41% CPU is a red herring) — endpoints hang mid-E2E (HTTP 000). [detail](LESSONS_archive.md#c4)
- **C7** — Never load a real `workspace/*.nadoc` in a mutating E2E — the app autosaves back and corrupts the user fixture. [detail](LESSONS_archive.md#c7)
- **C5** — Rapid edits → out-of-order response clobber — fast successive edits "disappear a moment later". [detail](LESSONS_archive.md#c5)
- **C6** — The cadnano EDITOR has a separate API client — editor feature-log revert fails ("index out of range") while 3D works. [detail](LESSONS_archive.md#c6)
- **C7** — Autosave→SSE→sibling-tab reload clobbers edits — only the last edit of each type survives; reverts ~1s later. [detail](LESSONS_archive.md#c7-2)
- **C8** — Fingerprint write skipping the feature log breaks seek/staleness — oxDNA out-of-date ⚠ won't clear after seeking back. [detail](LESSONS_archive.md#c8)
- **C9** — A long IN-PROCESS solve run as a daemon thread "stops on its own" — `uvicorn --reload` (a save under `backend/`/`scripts/`, a concurrent session, a manual restart) kills the thread mid-solve → the job reconciles to `stopped`. Bites any solve > a few seconds: SNUPI "Fine" on a big design (VoltronCore, ~7k nodes, 5–7 min). Fix: run the solve in a DETACHED subprocess (`start_new_session=True` → own session, unreachable by the reloader's group signal); recover via `reconcile` on the persisted pid + `display.json`. `snupi_runner`/`snupi_worker` do this; **`cando_runner` still uses the vulnerable in-process thread** (fast/small solves, so lower risk). See [[snupi-frontend-tab]].
- **C9** — `glob("*.psf")[0]` picks the derived `_hmr.psf` sibling — prep intermittently fails on a phantom `{stem}_hmr.pdb`. [detail](LESSONS_archive.md#c9)
- **C10** — Deleting a 3D crossover via NICK only leaves the record behind → arc redrawn from it ("colors change but connection stays"). [detail](LESSONS_archive.md#c10)
- **C11** — E2E: a design loaded via Playwright's `request` fixture is INVISIBLE to the page. Backend design state is **per-document**, keyed by the `X-NADOC-Doc` header that `client.js` stamps on every call; `request.post()` sends none → lands in the `__default__` doc. Symptom: `design/load` returns 200, `GET /api/design` (raw fetch, also headerless) returns 200, yet the panel's own calls 404 with *"No active design."* — an impossible-looking split. Fix: load through the page — `await import('/src/api/client.js'); api.loadDesign(path)`. Also: e2e runs a THROWAWAY backend on `:8002`, not the dev `:8000` (several existing specs hardcode 8000 and only pass because they never need the design). Found building the ⚡ Optimize e2e (2026-07-12).

## D. Rendering / scene state
- **D1** — Beads flash to 3D after a cadnano/unfold mutation — a late subscriber overwrites cadnano positions for one frame. [detail](LESSONS_archive.md#d1)
- **D2** — Hiding the design touches all four scene modules — no single visibility toggle; arcs/beads need explicit handling. [detail](LESSONS_archive.md#d2)
- **D11** — Overlays must emit a loop-`copy` index — loop-insert extra bases strand uncoloured at their native position. [detail](LESSONS_archive.md#d11)
- **D3** — Plan B fast paths skip backend geometry — anchor-derived bridges stuck at old positions after a cluster commit. [detail](LESSONS_archive.md#d3)
- **D4** — Bounding box inflated by zero-count InstancedMesh + hidden subtrees — selection box / gizmo centroid pulled far past the part. [detail](LESSONS_archive.md#d4)
- **D6** — Crossover arc visibility driven by two decoupled concerns — arcs poke through gaps after re-showing CG in cylinder rep. [detail](LESSONS_archive.md#d6)
- **D7** — Curved-helix TubeGeometry is uncapped — bent-helix tips read as dark holes / disappear at angles. [detail](LESSONS_archive.md#d7)
- **D8** — opacity-0 depthWrite:true mesh is an invisible occluder — bent-cylinder portions disappear at certain angles (voids). [detail](LESSONS_archive.md#d8)
- **D5** — Shader-chunk variable redefinition via onBeforeCompile — `geometryNormal redefinition`; impostor beads don't render. [detail](LESSONS_archive.md#d5)
- **D9** — Selection box from mid-LOD chords collapses for bent parts — box is too THIN, doesn't bound a bent/curved part. [detail](LESSONS_archive.md#d9)
- **D10** — Blunt-end rings float past a bent-helix tip — far-end ring extrapolates ~26nm past the real bent tip. [detail](LESSONS_archive.md#d10)
- **D11** — Cluster move: axis follows but beads/slabs snap back — an inactive display overlay's `stopAndRestore` reverts on design-changed. [detail](LESSONS_archive.md#d11-2)
- **D12** — Live Display-MD: a few crossover extra bases render a full box away — the design-eq PBC snap reused `rigid_mask`, which excludes extra bases (correct for Kabsch, wrong for the wrap-snap). [detail](LESSONS_archive.md#d12)
- **D13** — SNUPI/CanDo FEM "completed" but renders NOTHING (just axis lines) = the nonlinear solve DIVERGED to mm-scale coords, blowing the scene bbox so the real structure is a sub-pixel dot. Cause: the duplex-core mesh split into ≥2 disconnected bodies (a sub-block joined to the body only by the SCAFFOLD threading through unpaired ssDNA STUB helices, which the duplex FEM can't bridge). The single centroid pin leaves the extra body a FREE rigid body → runs away under ES repulsion; the free-free NMA also gains 6 extra rigid modes → µm RMSF. FIXED generally (2026-07-13): `_add_ssdna_hops` (WLC-spring every meshed→ssDNA→meshed cross-helix hop, ALL strand types) tethers ssDNA-connected blocks; `_ensure_components_pinned` + `n_rigid=6·n_components` backstop any residual disconnection. Diagnose via `connected_components` over elements+rigid_links+springs; a huge coord span or rmsf_max ≫ a few nm is the tell. See [[project_cando_fem]].

## E. Cluster / deformation edge cases
- **E1** — Restricting arm-helices to a cluster broke deformation — tests pass, visuals break; deformation planes at wrong bp. [detail](LESSONS_archive.md#e1)
- **E2** — ds-linker bridge offset disagreement — `_BRIDGE_PHASE_OFFSET` must match in both sites. [detail](LESSONS_archive.md#e2)
- **E3** — Relax loss with bridge offset → degenerate minima — a chord≈0 minimum is preferred over the real solution. [detail](LESSONS_archive.md#e3)
- **E4** — Overhang rotation missed the linker complement domain — bridge appears at the pre-rotation location, no console error. [detail](LESSONS_archive.md#e4)
- **E5** — patch_overhang extrude resize assumed +Z helices — −Z extrude grows the junction side; doubled-crossover symptom. [detail](LESSONS_archive.md#e5)
- **E6** — Free-posed `h_XY` helix gets grid_pos back-filled → canonicalised — primitive on a bent end collapses to a 45° sheet. [detail](LESSONS_archive.md#e6)
- **E7** — Direct-overhang relax is under-constrained (null-space hinge) — relax over-rotates the hinge and isn't idempotent. [detail](LESSONS_archive.md#e7)

## F. Length / index conventions
- **F1** — caDNAno `length_bp` is NOT physical extent — dividing/indexing by `length_bp` overshoots the axis end hundreds of bp. **Recurred 2026-07-13** in the FEM display: `rise_geom = |axis_end−axis_start| / length_bp` collapsed to ~½ on ssDNA-tail helices (axis_end = paired end, length_bp counts the tail) → 20 nm stretched overhang↔staple bonds. Fix = the true bead rise `BDNA_RISE_PER_BP`, not any ratio over `length_bp`. See [[project_snupi_gaps]]. [detail](LESSONS_archive.md#f1)
- **F2** — bp_start has three conventions — inline conversion math is error-prone; use `bp_indexing.py`. [detail](LESSONS_archive.md#f2)
- **F3** — `OverhangSpec.sequence` shorter than the strand domain — linker complement rendered all-N despite a bound sequence. [detail](LESSONS_archive.md#f3)
- **F4** — Overhang autodetect per-HELIX coverage misses crossover tails — a crossover free tail is never tagged as an overhang. [detail](LESSONS_archive.md#f4)
- **F5** — Negative bp: a `\d+` regex drops negative-bp elements — delete/edit "nothing happens" on fully-negative-bp elements. [detail](LESSONS_archive.md#f5)
- **F6** — `+1` loop bases don't move after NAMD relax/production — a loop insertion shares `(helix,bp,dir)` with its base, so any readback/display keyed by that bare 3-tuple collapses the two. Disambiguate with a `copy` key (like crossover extra-bases' `__xb__`); oxDNA already did, the NAMD/MD path didn't. See [[md-viz-tools]] (2026-07-12 entry).

## I. Assembly FK propagation in resolve / multi-mate chains
- **I1** — Rigid-group BFS preempts per-joint snap in a chain — Resolve snaps only the first mate of a rigid chain. [detail](LESSONS_archive.md#i1)

## G. Disabled / deferred functionality
- **G1** — Advanced staple router is disabled — falls back to nicks; don't delete `staple_routing.py` as dead code. [detail](LESSONS_archive.md#g1)

## H. Anti-patterns I've fallen into
- **H11** — Don't reflexively relegate a test the fast-suite guard flags — **check its STANDALONE time first.** The guard's per-test `seconds` is measured under `-n auto` at nice-10, so it's contended wall-clock, ~4–5× the test's intrinsic cost; the 5s budget is really a ~1.2s standalone bar. Tests oscillate across the line run-to-run with no code change, so triage-on-sight is an infinite ratchet that quietly strips real coverage. `pytest <nodeid> -p no:xdist -p no:randomly --durations=5` settles it in seconds. Under ~2s standalone → it's the guard, not the test → see **ISSUE-20** in `issues_ledger.md`. (Never raise the budget or force the guard — those stay forbidden.) Found 2026-07-16.
- **H1** — Guessing user intent without asking — on an ambiguous request, ask one question, don't implement. [detail](LESSONS_archive.md#h1)
- **H5** — Don't screenshot-guess camera angles for render bugs — use Help→Debug toggles + Copy Camera, not blind orbiting. [detail](LESSONS_archive.md#h5)
- **H2** — Searching the codebase for ages instead of asking — breadth-first exploration burns context, misses the cause. [detail](LESSONS_archive.md#h2)
- **H3** — Restating diffs after editing — the user can read the diff; keep the summary to a sentence. [detail](LESSONS_archive.md#h3)
- **H4** — Blur-commits race click-handlers — clicking Generate before Tab-out uses a stale overhang sequence. [detail](LESSONS_archive.md#h4)
- **H6** — Async list rebuild steals focus from a number box — digit hotkeys fire during keyframe number entry. [detail](LESSONS_archive.md#h6)
- **H7** — Don't verify 3D pointer-selection via simulated canvas clicks — Playwright can't raycast-hit beads headlessly. [detail](LESSONS_archive.md#h7)
- **H8** — New autoscaffold return-path regressed the seamed contract — "Seamed" produced a seamless raster; no seams/end-extension. [detail](LESSONS_archive.md#h8)
- **H10** — A test that loads a real `workspace/*.nadoc` fixture fails on the OTHER computer (workspace/ is gitignored, not synced) with `FileNotFoundError`. Rebuild the design deterministically in `conftest.py` (`make_6hb_curved_design`, `make_deposition_chain_design`) — never bind a test to a workspace file. Second occurrence (6hb_curved, then the 6 `test_chain_completion_e2e` failures on 6hbx100_1xT, fixed 2026-07-10).
- **H11** — 1-nt strand end-select fix landed in ONE of THREE parallel "which end is 5′/3′" code paths — claimed done, user still stuck. [detail](LESSONS_archive.md#h11)
- **H14** — **Two independent samplers agreed — and both were wrong.** A polymer's ⟨R_ee²⟩ is a slow long-wavelength mode; MD *and* local-move MC converge the local bond angles first and then report a confidently wrong, too-extended answer. Tell: tangent correlation **plateaus** instead of decaying to zero. Agreement between samplers is not convergence. [detail](LESSONS_archive.md#h14)
- **H15** — **A last-ULP "identical" speedup silently moved backbone geometry 0.8 Å — because it feeds an optimizer.** Batching the atomistic per-atom stamp (`origin + R @ local` → `local_stack @ R.T`) changed floats only at ~1e-16, but those atoms seed an L-BFGS-B backbone-bridge minimiser with near-degenerate minima that amplified it to 0.1–0.8 Å at crossover/skip junctions. Also: the stamp wasn't even the bottleneck (profiling: the bridge minimiser is 86%). Profile before optimising; never assume a downstream numerical solver is ULP-stable. [detail](LESSONS_archive.md#h15)
- **H13** — Believing a failing spec's NAME instead of reading its error — ISSUE-14 sat open a week as "console error on assembly teardown"; there was no console error and the teardown was fine (the spec died in the e2e *harness*, during setup). [detail](LESSONS_archive.md#h13)
- **H12** — Removing a DOM element that a factory reads-then-guards-on silently kills the WHOLE factory. Deleting the per-engine `<h2>` headers made `heading` null; all 4 `*_jobs_panel.js` factories do `if (!panel || !heading || !body) return` up top → they early-returned and wired NOTHING (dead buttons/toggles/availability). Symptom the user reported was narrow ("oxDNA Advanced card won't expand") but the panel was fully inert. DOM presence + moved-node checks (main.js appendChild) all passed and hid it — only *exercising an in-panel toggle* exposed it. Before deleting an element referenced in a factory, grep the factory's guard/`getElementById`; verify by clicking a real in-panel control, not by asserting DOM presence. Fixed 2026-07-10 (guard → `if (!panel || !body)`; heading now optional). See [[project_simulate_panel_overhaul]].

### H9. A bare `export { x } from './y'` re-export does NOT create a local binding — using `x` in the same module throws a SILENT ReferenceError in an async handler ("greyed/dead button") (2026-07-09)
Symptom the user reported: "can't delete the chain-simulator's completed oxDNA jobs in 6hbx100_1xT" — the Delete button looked present but greyed/did nothing. **The backend delete route was 100% fine** (verified over HTTP: `DELETE /api/oxdna/jobs/{id}` → 200, dir removed, even without a doc header). The bug was entirely frontend and NOT job/design-specific. Root cause in [oxdna_jobs_panel.js](frontend/src/ui/oxdna_jobs_panel.js): the module did `export { flattenJobTree, descendantIds } from './job_tree.js'` — a **re-export**, which forwards the names to *importers* but does NOT bind them in the module's own scope. The delete click handler calls `descendantIds(_jobs, _selectedId)` locally → `ReferenceError: descendantIds is not defined`. Because the handler is an **async arrow**, the throw became a silently-rejected promise: no confirm modal, no network request, no console error the user notices → "button does nothing." Fix: add a real `import { flattenJobTree, descendantIds } from './job_tree.js'` and keep a separate `export { … }` for back-compat (one line each).

**What cost the cycle** (why static analysis kept saying "the button should work"): the render/enable logic WAS correct — the button shows + is enabled for a completed job — so reading the code never revealed the fault; the fault only exists at the moment the handler *executes*. Traps that hid it: (1) unit tests imported `descendantIds` FROM the panel and passed — a re-export resolves fine for an external importer, so `descendantIds` tests were green while the panel's *internal* use was broken; the tests never drove the delete handler. (2) `console`-error capture showed nothing; only `page.on('pageerror')` surfaced the `ReferenceError` (an unhandled promise rejection from the async handler is a pageerror, not a console.error).

**How to avoid**: (1) If a module both *uses* a symbol and wants to *re-expose* it, you need BOTH `import { x } from …` AND `export { x }` (or `export { x }` + a local `import`) — a lone `export … from` is re-export-only. ESLint `no-undef` catches this if enabled on the file; grep suspicion: any `export { … } from './…'` in a module that also *calls* one of those names. (2) Debugging a "dead"/silent UI control: reproduce in a real browser and listen for `pageerror` (not just console) — async event handlers swallow throws into unhandled rejections. (3) A regression test for a UI action must DRIVE THE HANDLER (mount panel → select → click the button → assert the API/modal fired), not just import+call the helper the handler uses. RED-verified: reverting to the bare re-export makes the new `oxdna_jobs_panel.test.js` delete test fail (no modal). See [[project_simulate_panel_overhaul]].

## J. Algorithmic search hangs
- **J1** — Unbudgeted Hamiltonian-path DFS hangs on large bundles — autoscaffold never completes, no error, spinner forever. [detail](LESSONS_archive.md#j1)
- **J2** — "No complete legal breakpoint path" 422 is crossover-break gating — full-autostaple 422s on large/dense designs. [detail](LESSONS_archive.md#j2)
- **J3** — Auto-crossover edge margin was 21nt, should be min SEGMENT — ~14–20bp at each helix end left uncrossed. [detail](LESSONS_archive.md#j3)
- **J4** — Staple breaks must clear interior scaffold crossovers — nicks land 1–6bp from scaffold seam crossovers. [detail](LESSONS_archive.md#j4)
- **J5** — Scaffold-router test flap is hash-seed order, not a state leak — a test flaps pass/fail across PYTHONHASHSEED. [detail](LESSONS_archive.md#j5)
- **J6** — Autostaple starves crossovers at INTERIOR ssDNA loops (comb/"teeth") — unstapled scaffold is the design, not a hole; a staple's global coverage *span* is not a terminus test. Also: a manual crossover must not LOCK its staple (location = user intent, connectivity = autostaple's job). [detail](LESSONS_archive.md#j6)

## K. Environment / GPU / toolchain
- **K1** — CUDA jobs segfault after a LAMMPS/CUDA apt install — `rc=-11` at first force step; native driver shadows WSL passthrough. [detail](LESSONS_archive.md#k1)
- **K2** — NAMD-GPU `buildTileLists` illegal-memory-access = **a one-line NAMD bug, FIXED.** The host counts tiles `(n-1)/32+1` but the GPU uses `(n+31)/32`; they differ ONLY for an **EMPTY patch** (host says 1, GPU says 0), so every compute with an empty i-patch leaves an uninitialised tile-list entry that the kernel reads and turns into a wild `boundingBoxes[]` index. Empty patches = **vacuum at the box corners** of a solvent-carved origami. FIXED by a patched NAMD build (`tools/namd_tilelist_fix/`, auto-preferred as `NAMD_3.0.2p1_*`); 13/13 crashers now run. NOT VRAM/atoms/water/clashes, NOT the patch grid, and NOT the CUDA toolkit version. [detail](LESSONS_archive.md#k2)
- **K2b** — ⚠️ **the p1 patch does NOT make `GPUresident` safe on a carved cell.** The *crash* is gone but the same empty-patch pathology still corrupts the exclusion accounting: NAMD dies at step 0 with **"Low global CUDA exclusion count!"** (a `Controller.C` checksum: exclusions actually evaluated on the GPU vs `numCalcFullExclusions`). Measured on the 12 Å-carved 6hbx100_90deg: 241926 vs 276956 — and the structure is *healthy* (all 377919 exclusions ≤ 4.24 Å), so the missing pairs would have been summed **without** their exclusion ⇒ wrong forces. NAMD is right to refuse; **do not force it through.** Deficit tracks water fill, not coordinates: 22%→fail, 32%→fail, 52%→fail, **80%→still fail**, ~90%+→pass. Identical on the official 3.0.2 binary, with/without HMR, with/without the ENM, `wrapAll on/off`, and from minimised coords — only fill fraction moves it. **Rule: a water-shell carve and `GPUresident` are mutually exclusive** (md_protocols now enforces this). **The empty-patch mechanism (K2's) is REFUTED for this bug** — `twoAwayX/Y/Z yes` makes patches *smaller* (⇒ MORE empty patches) yet the deficit *collapses* 35030→4779; shrinking `margin` shrinks it further (39×11×39 grid → 1646). The deficit is a smooth monotonic function of **atoms-per-patch**, asymptotic to but never reaching 0, i.e. a capacity/indexing bug in the tile-list build under high patch occupancy — not empty patches. **Do NOT tune it to "nearly zero" and ship it:** under PME the reciprocal sum includes excluded pairs, so a pair that never lands in a tile list never gets its real-space correction subtracted ⇒ silently wrong electrostatics between bonded atoms. Fatal-by-design; the only safe answer is offload. See [[water-shell-carve]].
- **K3** — NAMD-seed "Duplicate bond" / ~N× explosion of a copy-pasted/rotated origami = `build_atomistic_model` re-applying the design's `cluster_transforms`/deformations ON TOP of an oxDNA override that already has them (DOUBLE transform). FIXED: seed passes `apply_design_geometry=False`. [detail](LESSONS_archive.md#k3)
- **K4** — GBIS implicit solvent crashes in `buildTileLists` on the NAMD 3 **CUDA** build EVEN at low atom count (log: "Always using force tables … unsupported config parameters") — GBIS is a CPU-only feature on NAMD 3; confirms K2's "not VRAM". FIXED: the runner auto-routes `implicit_gbis_namd` to the non-CUDA `-multicore` build (`find_namd(prefer_cpu=True)`, no `+devices`). [detail](LESSONS_archive.md#k4)
- **K5** — Heavy tests fail on GPU/pinned-host contention (`cudaHostAlloc` in `reallocate_host_T`) *while a production sim runs* = **the sim-guard silently never fired**. A live NAMD renames its comm to `NAMD masterPe` (CAPITALS + a space), and the guard's `pgrep -l` matched process names case-SENSITIVELY. Looks like a code bug; isn't. FIXED: `pgrep -il` (`hardware._SIM_PROC_PATTERN`) — and never `-f`, which self-matches pytest's own argv. [detail](LESSONS_archive.md#k5)
- **K6** — NAMD dies at segment START with `cudaMallocHost` / `cudaHostAlloc` (`CudaUtils.C`, `allocate_host_T`) = **GPU-resident mode ran out of PINNED host memory**, NOT VRAM and NOT RAM (this WSL box pins only **1.0 GB** with 15 GB free). Hits `GPUresident on` fast segments above ~800k atoms (756k OK, 971k fails). Dropping GPUresident ALONE then blows up RATTLE — 4 fs only survives under its GPU constraint solver. FIXED: `gpu_resident_probe()` + `downgrade_gpu_resident()` (GPUresident off, 4→2 fs, steps/freqs ×2 → same ns, same frames). [detail](LESSONS_archive.md#k6)

## L. Rented-GPU runs / cost safety (RunPod)

> **Read [REFERENCE_RUNPOD_RUNBOOK](REFERENCE_RUNPOD_RUNBOOK.md) BEFORE renting anything, and run
> `experiments/exp43_runpod_bench/preflight.py <job>` — it mechanically refuses every failure below.**
> The 3x6x400 run (1.94M atoms, $13/$15) found **11 bugs; 9 of them produced NO error of any kind.**
> A passing 6hb e2e (225k atoms, 5 min, $0.03) reached **none** of them. **Scale, duration and money each
> expose a disjoint class of failure.**

- **L1** — ⚠️ **THE META-LESSON: on a rented pod, "fails safe" can mean "fails expensive."** The relaxation
  early-stop evaluator fails safe to **HOLD** (run everything) — correct for the science, ruinous for the
  wallet (~4x). Two subsystems were *documented* as fail-safe and both did, into the most expensive possible
  behaviour. **Always ask: safe for whom — the science, or the bill?** [detail](LESSONS_archive.md#l1)
- **L2** — **`fast=True` SILENTLY disabled relaxation early-stop (a 4x cost bug, zero errors).**
  `outputEnergies` was a hardcoded **9600 STEPS**; chunk step-counts derive from a target simulated *TIME*, so
  4 fs HALVES the steps for identical physics while a step-denominated cadence fires half as often *per ns*.
  Frames/chunk fell **25 → 12**, under the evaluator's `min_frames=20`; every `p10` reported HOLD forever and
  no chunk could bridge. The accelerator still ran, still answered — always "no". **General rule: any
  step-denominated cadence is a latent bug the moment the timestep becomes a variable.** (Bit us TWICE — a
  late `cell_shrink` resume runs `total-restart_step` and starves the same way.) [detail](LESSONS_archive.md#l2)
- **L3** — **`cell_shrink` was NOT self-healing; "bounded retry" meant "fails 4x".** The retry re-ran the
  ORIGINAL conf, whose `extendedSystem` points at the *previous* segment's `.xsc` — the ORIGINAL cell. NAMD
  rebuilt the same patch grid and shrank into the same wall, identically, four times. Measured:
  156.6x89.1x1436.2 → 152.0x86.5x1393.4 (-3.0%). FIXED: `remote_resume_conf.py` resumes from the segment's
  OWN restart files. **A documented "self-healing" behaviour is worthless until something has watched it
  heal.** [detail](LESSONS_archive.md#l3)
- **L4** — **A DNS blip orphaned a billing pod — and its id had never been persisted.** A transient
  `Temporary failure in name resolution` on a routine poll became a fatal error, killed the launcher, and the
  launcher's `finally` is the ONLY thing that destroys a pod. NAMD (setsid-detached, output on the volume)
  carried on happily, so nothing looked wrong. Worse: `runpod_executor` never called `job.save()`, so the
  orphan could not even be **named**, let alone reaped. **The on-pod kill-switch has no API key: it can stop
  NAMD, never the billing.** [detail](LESSONS_archive.md#l4)
- **L5** — **The spend ledger FROZE while a real GPU billed on.** It deduped pod rows by keeping the FIRST
  seen — which was the *closed* row written by the dying launcher — so the live row was discarded and
  `spent()` stuck at $0.95 while the true figure was $1.35. The budget guard reads that number; it could never
  have fired. **A safety net can have the same hole as the thing it protects** (the ledger existed *because*
  the kill-switch had no memory). **A ledger that under-reports is worse than no ledger, because it is
  trusted.** [detail](LESSONS_archive.md#l5)
- **L7** — **PRODUCTION IS NOT AS FAST AS THE RELAXATION — sizing it off the relaxation's rate mis-sized this
  run 2x.** `build_production_conf` DELIBERATELY runs a more expensive integrator: `fullElectFrequency 1`
  (vs 2 — PME every step; at 4 fs that is PME every 4 fs, matching the Aksimentiev reference, and
  `fullElect 2` here would be PME every **8 fs**, past the r-RESPA resonance limit) and `stepspercycle 10`
  (vs 20). **Measured on the same card and system: relaxation 26.4 ms/step, production 35.5.** Always cost
  production from a PRODUCTION measurement. ⚠️ **Separately, `outputEnergies 100` + `restartfreq 1000` were
  hardcoded** — fine for a 250k-atom local job, ruinous for 1.9M atoms GPU-resident: an energy reduction
  pulled off the GPU every 100 steps, and **90 MB of restart files written to a NETWORK filesystem every
  1000 steps**. Pure overhead, ZERO effect on the trajectory: **50.0 → 35.5 ms/step (29%) just by scaling
  them to the run.** [detail](LESSONS_archive.md#l7)
- **L10** — 🛑 **NEVER attach `supervise.py` to a healthy launcher — it destroys your own pod.**
  The runbook's §2 said to (now fixed). During STAGING NAMD hasn't started, so the pod reports
  `alive=False, segment=None, stale=True`; the supervisor reads that as "ladder finished" and
  terminates the pod mid-upload (measured: 62 s after creation). It is a **RE-ATTACH** tool —
  for a pod whose launcher already DIED. **A done-test that can't tell NOT-STARTED from
  FINISHED, whose false-positive branch is destructive, is a destroy-your-own-work bug.**
  Also: `spend_ledger.HARD_CAP_USD` was a stale $15 against a ~$70 run — it silently truncates
  production (`launch_production` sizes off `ledger.remaining()`) and makes `supervise` reap on
  sight. [detail](LESSONS_archive.md#l10)
- **L8** — ⚠️ **Extra crossover bases silently VETO the fast integrator, so every 0xT-vs-NxT MD
  comparison is CONFOUNDED and costs 4x.** `design_has_extra_bases()` auto-routes any such design
  to the declash protocol, which forces `fast=False` (1 fs, `rigidBonds none`, no HMR) in BOTH the
  ladder *and* production. The 0xT control then samples at 4 fs+HMR while 1xT/2xT sample at 1 fs —
  any stiffness difference is part integrator, part extra-base. Measured (24hb, 50 ns): $87/1.8 d
  for 0xT vs **$348/7.3 d each** for 1xT/2xT; budget said $196-262, truth ~$784. `preflight.py`
  catches the cost half; **nothing catches the confound half but a cross-variant CONF diff.**
  [detail](LESSONS_archive.md#l8)
- **L9** — **A RunPod GraphQL 403 with body `error code: 1010` is CLOUDFLARE blocking urllib, NOT a
  bad key.** Reading the status code instead of the body produced a confident, false "your key is
  scoped REST-only" diagnosis — and defended a **$7.96** balance figure that was really **$207.53**
  (26x). Use `httpx`; **read the body of a 403 before believing it.** [detail](LESSONS_archive.md#l9)
- **L6** — **You pay GPU rates to DOWNLOAD your results, and the price table lied.** The network volume is
  reachable only *through a live pod*, so fetching 5.2 GB burned ~100 min (~$1.20) with the card idle — a
  quarter of what the science cost. Fetch selectively: the final checkpoint is ~140 MB and is all production
  needs; DCDs persist on the volume. Separately, `GPU_TYPES` carried **COMMUNITY** prices while Community
  cloud is excluded in code — every estimate was **~2.2x low**. And the per-Matom throughput fit does **not**
  transfer across GPU architectures (4090 fit predicted 20.9 ms/step; the Blackwell did **26.4**).
  [detail](LESSONS_archive.md#l6)

> **Detail.** Full entries live in [LESSONS_archive.md](LESSONS_archive.md). Open only the entry that matches your symptom.
