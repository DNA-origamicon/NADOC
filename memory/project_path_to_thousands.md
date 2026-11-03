---
name: path-to-thousands
description: "Refactor plan to make NADOC assemblies render and bulk-create smoothly at ~2000 instances (5000 tolerable). Target: shared GPU instancing + O(N) backend + diff snapshots + .nass v2. Started 2026-05-18."
metadata: 
  node_type: memory
  type: project
  originSessionId: bbfbdeb4-f435-46e2-ae4a-d7094b347162
---

# Path to Thousands — Assembly Scale Refactor

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

**Goal:** ~2000 instances at 60 FPS, 5000 at 30 FPS. Bulk creation (polymerize/duplicate) in seconds. Static render + orbit camera fluid.
**Out of scope:** interactive joint drag at scale, per-instance pick/edit at scale, assembly-animation playback at scale.
**Compat:** Break .nass freely; ship a one-time migrator.
**Uniformity assumption:** ~5–20 unique parts, hundreds of copies each (polymer/crystal regime).

This file is the single source of truth for all subagents working on this refactor. Subagents must read this entire file before starting and update the relevant phase section when their chunk is done.

## Assembly rebuild performance correction — 2026-10-13

The shared renderer now retains unchanged source meshes and decoded nucleotide
geometry. Live backend file versions prove freshness; inline IDs and saved hash
keys alone do not. Supported Full/Beads/Cylinders/Hull Prism sources prepare Full
primitives once and change actual LOD caps/visibility without rebuilding them.
Interaction/simulation indexes are lazy. Unsupported/auxiliary sources retain
the guarded rebuild-from-cached-coordinates fallback; edits refetch affected
sources. `assembly_diff` includes source versions so source edits cannot
accidentally take the transform-only path. Prepared buffers alone never prove
that Full was drawn: validate actual close-LOD slots, frames, and triangles.

`invalidateInstance` only marks the source dirty. Callers mutate, then request
one rebuild; external part-refresh explicitly invalidates before syncing the
assembly. `assembly_rebuild_queue.js` shares duplicate in-flight work, serializes
new snapshots and suppresses stale work after disposal. Transform-only linker
refreshes remain valid. Historical descriptions of unconditional whole-assembly
refetch/dispose and invalidation-triggered rebuilds below are superseded.
See `docs/audits/benchy_full_performance_20261013.md` and source-reuse regressions.

Loading follow-up (ISSUE-80, **PARTIAL for cold-load/GPU limits; validation complete**):
native geometry negotiates lossless Float64 NDGB (`?format=ndgb1`); default JSON
reuses the compact cache and native placement authority. Both decoders bound
malformed expansion. Hidden cluster/overhang panels and readiness await versioned
renderer sources; display Designs never seed base-only selected-part authoring.
Hidden direct-open library startup defers listing. Readiness caches every authored
input except live representation, retains source stamps, and rechecks job status.
Source waits use version/membership/mode, not representation; fresh unversioned
snapshots restart. Source failures persist until explicit rebuild begin, without
auto retry. Accepted API provenance confirms equal optimistic snapshots through
synchronous clones and rejects unmarked delayed snapshots. CG choices show while
ordered saves finish; rollback/document guards and atomistic confirmation remain.
Autosave is quiet; manual Save retains progress. Inactive volumes/warnings and
hidden/lazy panel work no longer expand/rebuild per-instance UI unnecessarily.

Final release Benchy: 34.203 s navigation / 29.669 s import→paint, 33 ms first Full;
all seven sources close, 462,002 nucleotides / 91,752,688 triangles, Full FPS
21.07/21.60. Hinge500: 10.481 s navigation / 6.119 s import, 485 ms first Full;
all 500 close / 1.517 billion triangles, Full FPS 2.36/1.85, Cylinders 59.21.
Single document/browser/source-cold runs; option-click timing excludes menu
navigation and measures renderer submission/next rAF, not compositor pixels.
The hinge release first-Full screenshot has stale-looking Cylinders selectors;
a separate 500-control probe has zero mismatches every phase and a Full screenshot.
Cause not reproduced; retain anomaly. One readiness GET is pending at close,
server cancellation is absent, and the intermediate cold assessment remains
39.604 s before lifetime cleanup. Cold-load and historical scale targets are unmet.

Final frontend 8,075 passed/one skipped/697 files; smoke 23 passed. FAST 10,603
passed with unchanged 22 failures/four errors; zero individual timing violators,
aggregate 203 s > 90 s. Exact transport/hull parity and native review gate pass.
Final cleanup preserves 205 project paths/five document IDs/nine source hashes,
zero test artifacts/bridge credentials and all 109 frozen app/test hashes.
No acceptance work remains pending. Evidence, limitations and checkpoint history:
`docs/audits/assembly_loading_performance_20261013.md`.

Color updates also avoid rebuilding temporary molecular geometry.
`assembly_source_colors.js` repaints retained close/mid/overhang color textures
and curved-cylinder vertex ranges; crossover insertions and arc lines keep their
endpoint-owner coloring helper. Real helix-controller parity tests cover all four
color modes, custom/binder/scaffold colors, curved domains and alpha preservation.
The older throwaway-builder descriptions below are superseded.

<a id="where-the-code-lives-2026-07-25--assembly_rendererjs-was-split-paths-below-are-current"></a>
- [WHERE THE CODE LIVES (2026-07-25 — assembly_renderer.js was split; paths below are current)](details/project_path_to_thousands/01-where-the-code-lives-2026-07-25--assembly_rendererjs-was-split-pa.md#where-the-code-lives-2026-07-25--assembly_rendererjs-was-split-paths-below-are-current)

<a id="shared-renderer-visual-parity-audit-2026-08-28"></a>
- [Shared-renderer visual parity audit (2026-08-28)](details/project_path_to_thousands/01-where-the-code-lives-2026-07-25--assembly_rendererjs-was-split-pa.md#shared-renderer-visual-parity-audit-2026-08-28)

<a id="getassembly-returns-the-raw-v2-wire-shape--never-read-instances-off-it-2026-05-27"></a>
- [`getAssembly()` returns the RAW v2 wire shape — NEVER read `.instances` off it (2026-05-27)](details/project_path_to_thousands/01-where-the-code-lives-2026-07-25--assembly_rendererjs-was-split-pa.md#getassembly-returns-the-raw-v2-wire-shape--never-read-instances-off-it-2026-05-27)

<a id="curved-cylinder-lod-for-deformed-sources-2026-05-26"></a>
- [Curved-cylinder LOD for DEFORMED sources (2026-05-26)](details/project_path_to_thousands/01-where-the-code-lives-2026-07-25--assembly_rendererjs-was-split-pa.md#curved-cylinder-lod-for-deformed-sources-2026-05-26)

## Architectural shift in one paragraph

PartInstances stop being independent rendered objects. They become indices into a per-source geometry cache plus a packed per-instance transform table. The frontend renders one shared InstancedMesh tree per unique source, composing `world = instance_transform[i] × per_bp_transform[j]` in the vertex shader by reading from a Float32 DataTexture. Backend stops doing full Pydantic deep-copies and dual gzipped snapshots per mutation; instead it emits diff snapshots and uses an id→instance dict for O(N) resolve. The .nass format collapses redundancy into a sparse-override layout.

---

<a id="numbers-were-aiming-for-validated-by-phase-0-harness-updated-as-phases-land"></a>
- [Numbers we're aiming for (validated by Phase 0 harness, updated as phases land)](details/project_path_to_thousands/02-numbers-were-aiming-for-validated-by-phase-0-harness-updated-as-p.md#numbers-were-aiming-for-validated-by-phase-0-harness-updated-as-phases-land)

<a id="per-phase-definition-of-done"></a>
- [Per-phase Definition of Done](details/project_path_to_thousands/02-numbers-were-aiming-for-validated-by-phase-0-harness-updated-as-p.md#per-phase-definition-of-done)

<a id="coordination-protocol-read-this-if-you-are-a-subagent"></a>
- [Coordination protocol (read this if you are a subagent)](details/project_path_to_thousands/02-numbers-were-aiming-for-validated-by-phase-0-harness-updated-as-p.md#coordination-protocol-read-this-if-you-are-a-subagent)

<a id="subagent-prompt-discipline-manager-apply-this-to-every-subagent-prompt-you-draft"></a>
- [Subagent prompt discipline (manager: apply this to every subagent prompt you draft)](details/project_path_to_thousands/02-numbers-were-aiming-for-validated-by-phase-0-harness-updated-as-p.md#subagent-prompt-discipline-manager-apply-this-to-every-subagent-prompt-you-draft)

<a id="worktree-gotchas-discovered-the-hard-way-2026-05-18--confirmed-by-2-agents"></a>
- [Worktree gotchas (discovered the hard way 2026-05-18 — confirmed by 2 agents)](details/project_path_to_thousands/02-numbers-were-aiming-for-validated-by-phase-0-harness-updated-as-p.md#worktree-gotchas-discovered-the-hard-way-2026-05-18--confirmed-by-2-agents)

<a id="where-the-shared-renderer-stands-2026-05-18"></a>
- [Where the shared renderer stands (2026-05-18)](details/project_path_to_thousands/02-numbers-were-aiming-for-validated-by-phase-0-harness-updated-as-p.md#where-the-shared-renderer-stands-2026-05-18)

<a id="related"></a>
- [Related](details/project_path_to_thousands/02-numbers-were-aiming-for-validated-by-phase-0-harness-updated-as-p.md#related)

## Phase map — index (status)

12 phases. Full per-phase detail + completion reports are in the archive.

- Phase 0 — Measure baseline                      [DONE:7234d1d]
- Phase 1 — Backend cheap wins                    [DONE:af28cab,984f537]
- Phase 2 — Wire-format compaction + transform-only update path   [DONE:a98b3b0 on worktree-agent-a9276d10bcd362097]
- Phase 3 — Shared GPU instancing per source           [DONE — flag flipped 2026-05-20 (2e540e0); Phase 3 DoD met]
- Phase 4 — Backend bulk-op refactor                  [4a/4b/4e DONE on master; 4c TODO, 4d deemed unneeded]
- Phase 5 — `.nass` v2 + migrator                     [EXPAND + MIGRATE-READERS + CONTRACT all DONE on master]
- Phase 6 — Frontend orchestration polish              [6a NEVER MERGED; 6d DONE; 6b/6c TODO]
- Phase 7 — Shared-path feature parity, THEN flip the default   [DONE — 2026-05-20; flipped 2e540e0]
- Open perf gap (not a stub — a genuine unsolved bottleneck)
- LOD benchmarking tooling + N≤500 numbers (2026-05-21)
- Real-GPU sweep RESULTS (2026-05-21, user's GPU; data in `frontend/e2e/bench_results/lod_fps_realgpu.json`)
- O(N) cold-open ROOT CAUSE + FIX (2026-05-21) — it was NOT the indicators

> **History.** Per-phase detail + subagent completion reports live in [project_path_to_thousands_archive.md](project_path_to_thousands_archive.md). Read on demand only.
