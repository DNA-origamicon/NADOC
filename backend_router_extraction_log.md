# backend router extraction log

Tracks the incremental decomposition of `backend/api/crud.py` (≈15.6k ln, 190 routes) and
`backend/api/assembly.py` (≈7.8k ln, 112 routes) via the loop in `backend_router_carveup.md`.
**One row per extraction, one commit per extraction.** Sibling of `main_js_extraction_log.md`, adapted for
the backend's two target shapes (FastAPI sub-routers + `backend/core` service helpers) instead of frontend
factories.

**Why this exists:** the in-repo precedent (`routes_loop_skip.py` = Refactor 10-F, `routes_camera_poses.py`
= 13-B) proved a route cluster *can* be lifted cleanly — but those were one-offs with no measured contract,
and crud.py kept growing anyway. This log measures whether each move is a *real* decoupling or just LOC
shoveling (see the carve-up's "anti-shovel contract"). A row that can't fill its justification column is a
shovel and gets reverted.

## Baselines (2026-06-08, framework bootstrap)

- `backend/api/crud.py`: **15612 LOC, 190 routes, 131 module-level private helpers**
- `backend/api/assembly.py`: **7822 LOC, 112 routes**
- Already-lifted routers (predate this loop): `routes_loop_skip.py` (291 ln), `routes_camera_poses.py` (135 ln)
- Backend test count at bootstrap: **1753 passed, 58 skipped** (recorded first extraction, 2026-06-08)
- Shared kernel helpers (stay in crud.py, imported back — these count toward B but never block):
  `_design_response`, `_design_response_with_geometry`, `_helix_label`

---

## Conventions — how to read the columns

- **`B` (back-import surface) is the headline number.** It is the count of distinct private (`_foo`) symbols
  the new `routes_<area>.py` imports back from its god-file. **Log before-B → after-B.** The shipped exemplars
  sit at B = 1–2. A router extraction ships only at **B ≤ 3**; above that, co-extract the helpers to
  `backend/core` or pick a cleaner cluster (carve-up → high-B playbook). `_design_response`-family imports
  count toward B but are the accepted shared kernel — they don't block.
- **LOC Δ is narrative, NOT the pass criterion.** A big crud.py LOC drop with B unchanged only *relocated* the
  problem. The pass criterion is **coupling (B) down OR business-logic-into-a-tested-core-fn up.** Report LOC
  as story.
- **"routes remaining in god-file"** is the LOC-correlated metric that actually means something (fewer
  concerns in the kernel) — track it instead of raw lines.
- **Verbatim vs adapted.** A router lift with **byte-identical handler bodies** is behavior-preserving by
  construction; the existing route tests + green `just test` are sufficient proof. **A service extraction**
  (logic moved into a `backend/core` fn) is *adapted* code — it MUST add a direct unit test for the new pure
  fn (no `TestClient`; assert input→output). Say which in the row.
- **The justification column is mandatory.** One sentence: *which* metric moved and why this wasn't a shovel.
  Empty justification = reverted row.

## Coupling probe (run before every extraction — this is the gate's instrument)

Paste the region's line range; get its back-import surface against the god-file's private helpers:

```bash
cd /home/joshua/NADOC
FILE=backend/api/crud.py        # or backend/api/assembly.py
START=13144; END=13383          # the candidate region's banner-to-banner range
mapfile -t HELPERS < <(grep -nE '^(def|async def) _' "$FILE" | sed -E 's/.*(def|async def) (_[a-zA-Z0-9_]+).*/\2/' | sort -u)
body=$(sed -n "${START},${END}p" "$FILE")
for h in "${HELPERS[@]}"; do
  c=$(echo "$body" | grep -cE "\b${h}\b")
  defin=$(echo "$body" | grep -cE "^(def|async def) ${h}\b")   # defined inside range? then internal
  [ "$c" -gt 0 ] && [ "$defin" -eq 0 ] && echo "  ${h}(${c})"
done
```

`B` = number of lines this prints. Each printed `_helper(n)` is a symbol you'll either import back (counts
toward B) or co-extract. The `(n)` is how many call sites — high `n` on a kernel helper (`_design_response`)
is fine; high `n` on a bespoke helper means real entanglement.

**Bootstrap probe results (2026-06-08, crud.py):**

| Region | range | back-imports (B) |
|---|---|---|
| Animations | 13144–13383 | `_design_response`(7) → **B=1** |
| Strand extensions | 14178–14440 | `_design_response`(9) → **B=1** |
| Deformation + debug | 12690–13139 | `_design_response`(3) → **B=1** |
| Flexible ssDNA segments | 13521–13723 | `_design_response_with_geometry`(2) → **B=1** |
| Protein import+library+attachments | 3278–3596 | `_design_for_export`, `_design_response`, `_find_ovhg_or_404`, `_geometry_for_helices` → **B=4** (co-move 2) |

---

## Lessons learned (append as the loop teaches them — the durable payoff)

_Seeded at bootstrap from the carve-up design + the two existing exemplars. Add a numbered lesson whenever a
session discovers something a future session would otherwise re-learn the hard way._

- **L1 — B, not LOC, is the win.** The whole loop exists because "crud.py got shorter" is a lie if the new
  router imports 25 helpers back. Always probe before, log before→after B, and write the justification line.
- **L2 — The shared kernel helpers are SUPPOSED to be imported back.** `_design_response` &c. live in crud.py
  and are imported by `routes_loop_skip.py` / `routes_camera_poses.py` on purpose (100+ callers; moving them
  would be the bigger coupling). Don't "fix" this by duplicating them. Count them toward B, then ignore them.
- **L3 — URLs never change.** The router carries the same paths; mounting in `main.py` with `prefix="/api"`
  reproduces them. If a frontend `client.js` call breaks, you changed a path — you didn't.
- **L4 — `backend/core` must not import `backend/api`.** The dependency arrow is api→core. A service
  extraction that needs a request model or `state.py` is a sign the logic isn't actually pure yet — pass the
  data in as plain args, keep `state.mutate_and_validate` on the api side.
- **L5 — Verbatim router lift = behavior preserved by construction; service push = needs a real unit test.**
  Don't write a `TestClient` test to "prove" a verbatim move (the green suite already does). DO write a direct
  input→output unit test for any logic you pull into core — that's the adapted code whose pin must be earned.
- **L6 — Respect the mutation contract.** Every handler you move keeps its exact `state.mutate_and_validate` /
  `set_design_silent` / `snapshot` usage (api-and-state.md). Moving a handler must not change which one it
  calls — that silently breaks undo/redo. Verbatim means verbatim.
- **L7 — Stale-server trap.** After moving routes, if a `curl` looks wrong but `just test` is green, it's the
  `--reload` server holding stale in-memory `design_state` — ask the user to restart, don't debug Python
  (api-and-state.md). Tests are the source of truth, not a live curl.
- **L8 — A `# ──` banner groups by adjacency, NOT cohesion (now bitten twice).** #1's "Animations" banner held
  a binding model used elsewhere; #2's "Strand extensions" banner held 4 plate-layout / representation-override
  routes interleaved *between* the extension handlers. Always READ the whole banner-to-banner span and cut on
  the *concept* the new router owns — move only the routes/models that share its one reason to change, leave
  the rest under a retitled banner. The route count you commit to (#2: 5, not 9) is the cohesion check.
- **L9 — Baseline a flake before you trust the count.** The framework's "1753 green" baseline was optimistic:
  `test_seamless_router.py::test_teeth_closing_zig` *appeared* to be a cross-test leak (failed in full suite,
  passed in isolation). When `just test` shows ONE failure after a verbatim router lift, **stash-and-rerun on
  clean HEAD** before assuming you caused it; a verbatim move of routes unrelated to the failing test's domain
  almost never is the cause. **UPDATE (2026-06-08, ISSUE-6):** the "leak" was a misdiagnosis — it was
  hash-seed nondeterminism in the shared `_hamiltonian_path` (no lexicographic tiebreaker), now FIXED; the test
  was re-pinned to the closing-zig topological event. True full-suite green is now **1753 / 0**. The lesson
  still stands (stash-and-rerun to attribute a failure), but the order-dependence was hash-order, not state
  residue — a single-test fresh-process re-run varying pass/fail is the tell for hash nondeterminism, not a leak.

- **L10 — Region-internal helpers can be imported CROSS-FILE; grep the whole `backend/`, not just the god-file.**
  #3's `_parse_params` / `_resolve_cluster_scope` lived under the deformation banner in crud.py but were imported
  by `routes_loop_skip.py`'s `/design/deformation/validate` route. The in-file grep ("used elsewhere in crud.py?")
  found the edit-feature caller but MISSED the cross-file one; the full suite caught it as an `ImportError` after
  the helpers were deleted. **Rule:** before moving/deleting ANY helper, `grep -rn "\b_helper\b" backend/api/`
  (whole dir). If 2+ callers across files, that's the signal to do a **service push to `backend/core` first** —
  which is precisely what turned #3 from a B=3 umbilical-cord lift into a B=1 clean one (all 3 callers now import
  the pure fn from core; none import each other). A shared-across-files api helper is core logic wearing an api hat.

- **L11 — assembly.py is NOT prefix-clean like crud.py; the back-import surface is bimodal.** crud.py's clusters
  almost all sit at B=1 (`_design_response`). assembly.py splits sharply: the *display/metadata* clusters
  (Animation CRUD, Assembly camera poses) are clean B=1 on `_assembly_response` (the assembly-side twin of
  `_design_response` — same shared-kernel status, counts toward B, never blocks), but the *kinematics* clusters
  (Gear relations, Belt paths, PartGroup routes) are all **B=4–5**, entangled with a shared revolute-drive helper
  web (`_apply_assembly_mutation_with_feature_log`, `_resolve_gear_endpoint`, `_gear_endpoint_side`,
  `_build_inst_by_id`, `_propagate_gear_relations_from`, `_sync_revolute_values_*`). **Rule:** drain the B=1
  display clusters first; tackle the kinematics clusters only after a `backend/core` service push of that shared
  helper web (it's FK/gear math wearing an api hat — exactly the L10 pattern). Always probe B on the LIVE range —
  assembly.py's adjacency-grouped banners hide this entanglement.

- **L12 — Folding two adjacent clusters into ONE router is valid (the inverse of L8) when BOTH conditions hold:
  each probes B=1 *independently* AND they share one reason to change.** #5 folded `# ── Assembly configurations`
  (4 routes) + `# ── Assembly camera poses` (4 routes) into `routes_assembly_configs.py` — both are *saved
  assembly view/state presets* persisting list fields on `Assembly` and returning `_assembly_response`, so a
  change to the preset-persistence pattern or the response shape touches both. L8 says a banner can hide
  *non*-cohesive routes (split them out); L12 is the dual — two *separate* banners can be cohesive enough to
  share a module. The test is the same in both directions: **cut on the one-reason-to-change, not the banner.**
  Probe each candidate's B separately before folding (don't assume the second is clean because the first is).

- **L13 — When a region's compute helper depends on an api-layer helper AND is shared cross-region, leave it
  behind and import it back — don't move it (the L4 corollary, the inverse of L10).** #6's
  `_linker_geometry_for_assembly` looked like a service-push candidate (pure-ish, takes the assembly
  explicitly) — but it imports `crud._geometry_for_design` (api layer), so pushing it to `backend/core` would
  invert the api→core arrow (L4). It was also called from the overhang-connections region (~3022/3057) + the
  relax test suite, i.e. **cross-region** (the L10 signal). L10 says "2+ cross-file callers → service push to
  core first" — but that move is only available when the helper is *core-pure*. When it has an api dependency,
  the service push is blocked, so the right call flips: **keep the helper in the god-file as shared
  infrastructure and import it back into the new router** (counts toward B). Moving it would have forced 3+
  *reverse* imports (assembly.py ← routes_assembly_linkers.py) — strictly worse coupling than the one
  back-import. The tell: if a candidate-for-core helper `grep`s an `import` from `backend.api`, it is NOT
  core-ready; probe its callers and decide leave-and-import-back vs. (bigger job) push its api dep to core too.

- **L14 — A fat banner can yield a CLEAN service push of its PURE sub-kernel even when the rest is L4-blocked;
  don't reject the whole region because half of it is entangled.** #7's `# ── Forward kinematics helpers`
  banner (~660 ln, 20 helpers) was earmarked as one big service extraction. But probing the bodies split it
  cleanly in two: (a) a **pure graph-propagation kernel** (5 helpers) whose only deps are numpy + `Mat4x4`
  (core) — zero api dependency, B=0, directly testable; and (b) the connector-resolution + cluster-inference
  helpers, which transitively pull `_design_with_instance_overrides` (→ `_load_design_from_source`: file IO +
  `HTTPException`) and `_mat4_from_model`, i.e. L4-blocked from core. **The right move is to push (a) and leave
  (b)** — a B=0 service extraction with real unit tests beats forcing the whole banner and either inverting the
  api→core arrow or shipping an untestable blob. The tell for the pure sub-kernel: grep each helper's body for
  api-layer symbols / file-IO / `HTTPException`; the ones that touch only numpy + core models are the core-ready
  set. (Method twin of L8/L12: cut on cohesion+dependency-direction, not the banner span.) Verbatim lift keeps
  the helper names underscore-prefixed in core so the ~50 call sites import them back unchanged — a clean public
  rename is an optional later cosmetic, not required when the bodies are byte-identical.

## Difficulties ledger (extraction dead-ends — NOT user-facing bugs)

_A region that turned out un-extractable, and why. (User-facing bugs go to `issues_ledger.md`; un-hand-checked
shipped behavior goes to `manual_validation_debt.md` — route findings, don't bury them here.)_

- _(none yet)_

---

## Metrics per extraction

| # | Date | File | Move type | What (cluster → module) | routes moved | LOC Δ (god-file) | B before→after | core fn + unit tests | `just test` | Real improvement, not a shovel: |
|---|------|------|-----------|--------------------------|--------------|------------------|----------------|----------------------|-------------|----------------------------------|
| — | 2026-06-08 | — | — | **Framework bootstrap** (this log + `backend_router_carveup.md` + `/carve-router` skill). No code moved. | 0 | 0 | — | — | not run | n/a — scaffolding only; first real row lands next session (Animations, probed B=1) |
| 1 | 2026-06-08 | crud | router | Animations + keyframes → `routes_animations.py` | 7 | −222 | 1→1 | none (verbatim lift; existing route tests cover) | 1753/1753 green | Real improvement, not a shovel: 7 cohesive route concerns left the kernel (190→183 routes) at the exemplar's floor B=1 (`_design_response` only) — coupling did not rise. `BindingDisplayPoseBody` correctly left behind in crud.py (used by 2 non-animation handlers), proving the cut respected actual cohesion not adjacency. |
| 2 | 2026-06-08 | crud | router | Strand extensions (single CRUD + batch upsert/delete) → `routes_extensions.py` | 5 | ≈−200 | 1→1 | none (verbatim lift; existing route tests cover) | 1752 passed / 1 pre-existing failure (`test_teeth_closing_zig`, fails on clean HEAD too — unrelated) | Real improvement, not a shovel: 5 cohesive extension routes + their 5 request models left the kernel (183→178 routes) at floor B=1 (`_design_response`); the 4 *plate-layout/representation-override* routes physically nested under the same banner were correctly left in crud.py (different concern) — the cut followed cohesion, not the banner. Dead `_EXT_SEQ_RE` regex removed; 2 orphaned `core.models` imports cleaned. |
| 3 | 2026-06-08 | crud | both | Deformation endpoints+debug → `routes_deformation.py` (router) **+** shared `parse_deformation_params`/`resolve_cluster_scope` → `backend/core/deformation.py` (service) | 4 | −315 | 1→1 | `parse_deformation_params` + `resolve_cluster_scope` + 9 unit tests (`test_deformation_params_core.py`) | 1762 passed / 0 failed (baseline 1753 + 9 new) | Real improvement, not a shovel: the two shared helpers had **3 callers across 2 files** (deformation routes, crud's edit-feature branch, AND `routes_loop_skip.py`'s validate route) — pushing them to a tested `backend/core` fn dropped a cross-file back-import AND let the router land at floor B=1 instead of B=3. 4 cohesive routes left the kernel (178→174); `_rollback_last_feature` correctly stayed (feature-log revert, not a deformation route). 3 orphaned `core.models` imports cleaned. |
| 4 | 2026-06-08 | assembly | router | Animation CRUD (animation + keyframe CRUD + reorder) → `routes_assembly_animations.py` | 7 | −200 | 1→1 | none (verbatim lift; existing `test_assembly_api.py` route tests cover) | 1762 passed / 0 failed (unchanged) | Real improvement, not a shovel: **first assembly.py extraction** — 7 cohesive animation routes + their 5 request models + region-internal `_find_animation` left the kernel at floor B=1 (`_assembly_response`, the assembly-side `_design_response` twin, the only back-import). Probed the gear/belt/group alternatives and correctly **rejected** them (B=4–5, revolute-drive helper web) — the cut followed cohesion and the cleanest available coupling, not adjacency. Orphaned `DesignAnimation`/`AnimationKeyframe` `core.models` imports cleaned; silent-vs-undo mutation contract (`set_assembly_silent` on keyframe patch) preserved verbatim per L6. |

| 5 | 2026-06-08 | assembly | router | Configurations + camera poses → `routes_assembly_configs.py` | 8 | −268 | 1→1 | none (verbatim lift; existing `test_assembly_api.py` route tests cover, 20 refs) | 1762 passed / 0 failed (unchanged) | Real improvement, not a shovel: two independently-probed B=1 display-preset clusters (4 config-CRUD + 4 camera-pose routes) + their 5 request models + region-internal `_capture_assembly_configuration` left the kernel (105→97 routes) at floor B=1 (`_assembly_response` only). Folded per handoff — both are saved assembly view/state presets persisting list fields on `Assembly`, one reason to change. Silent-vs-undo contract preserved verbatim (restore + patch → `set_assembly_silent`, create/delete → `set_assembly`); 5 orphaned `core.models` imports cleaned. |

| 6 | 2026-06-08 | assembly | router | Linker helices/strands/geometry → `routes_assembly_linkers.py` | 5 | ≈−100 | (n/a)→2 | none (verbatim lift; existing `test_assembly_*`/`test_assembly_linker_relax.py` route+helper tests cover) | 1762 passed / 0 failed (unchanged) | Real improvement, not a shovel: 5 cohesive linker routes (helix/strand CRUD + GET linker-geometry) + their 2 request models left the kernel (97→92 routes) at B=2. The bespoke back-import `_linker_geometry_for_assembly` is *forced down* coupling, not a shovel: that compute helper imports api-layer `crud._geometry_for_design` (L4-blocked from `backend/core`) and is called from the overhang region + relax tests — leaving it in assembly.py and importing it back is strictly less coupling than moving it (which would create 3+ reverse imports). New lesson L13 records the L4-corollary decision. Orphaned `Helix`/`Strand` `core.models` imports cleaned; silent-vs-undo contract (`set_assembly_silent` + `snapshot` on all 4 mutators) preserved verbatim. |

| 7 | 2026-06-08 | assembly | service | Pure FK graph-propagation kernel (5 helpers: apply-delta-to-joint, build-inst-by-id, expand-rigid-group, propagate-fk, move-instance-with-fk-delta) → `backend/core/assembly_fk.py` | 0 (routes unchanged, 92) | −83 | (n/a)→**0** | the 5 FK fns + 12 unit tests (`test_assembly_fk_core.py`) | 1774 passed / 0 failed (1762 + 12 new) | Real improvement, not a shovel: ~95 ln of pure kinematic graph/matrix math that was marooned in the api file is now in a **dependency-free** `backend/core` module (imports only numpy + `Mat4x4`; **B=0** — back-imports NOTHING from assembly.py) with direct input→output unit tests pinning the FK rules (rigid groups move as one body, non-rigid children ride the parent delta, fixed/visited skipped). Verbatim lift → behavior preserved by construction; the 12 tests are the durable pins. The other ~565 ln under the same banner correctly STAYED (L4-blocked: they depend on api-layer `_design_with_instance_overrides`→file-IO+`HTTPException` and `_mat4_from_model`) — moving them would invert the api→core arrow. |
| 8 | 2026-06-08 | assembly | service | Pure assembly-validation report (`_validate_assembly`) → `backend/core/assembly_validate.py::validate_assembly_report` | 0 (routes unchanged, 92) | −76 | (n/a)→**0** | `validate_assembly_report` + 8 unit tests (`test_assembly_validate_core.py`) | 1782 passed / 0 failed (1774 + 8 new) | Real improvement, not a shovel: ~75 ln of pure validation logic (file-source / joint-ref / joint-limit / id-uniqueness / flattened-id checks + ok-dedup) that was marooned in the api file is now in a **dependency-free** `backend/core` module (imports only `Assembly` + delegates to `assembly_flatten`; **B=0** — back-imports NOTHING from assembly.py) with 8 direct input→output unit tests pinning each check + the dedup rule. The `GET /assembly/validate` handler shrank from ~84 ln to 4 (parse→delegate→respond). Body moved byte-identical → behavior preserved by construction; the 8 tests are the durable pins (the only adaptation was the public rename + import-site move, both exercised by the green route tests + the new unit tests). |

_Row template (copy for each extraction):_
`| N | YYYY-MM-DD | crud/assembly | router/service/both | <cluster> → routes_<area>.py | <k> | −<n> | <b0>→<b1> | <core fn> + <t> tests | <pass>/<pass> green | <one sentence> |`
