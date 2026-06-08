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

_Row template (copy for each extraction):_
`| N | YYYY-MM-DD | crud/assembly | router/service/both | <cluster> → routes_<area>.py | <k> | −<n> | <b0>→<b1> | <core fn> + <t> tests | <pass>/<pass> green | <one sentence> |`
