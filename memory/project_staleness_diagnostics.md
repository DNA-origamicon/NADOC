---
name: staleness-diagnostics
description: "oxDNA/MD job \"design changed, cannot continue\" guard compares against the LIVE active design; a wrong/default loaded design (e.g. after a server restart) spuriously flags jobs"
metadata: 
  node_type: memory
  type: project
  originSessionId: 0e051a9d-7019-4210-ac0c-6cf3868969c3
---

The oxDNA + MD "cannot continue / design changed" guard (`backend/core/oxdna_staleness.py`) is a content **fingerprint** (sha256 of design fields: helices, strands, crossovers, deformations, extensions, overhangs, overhang_connections, forced_ligations, photoproduct_junctions — `_FINGERPRINT_FIELDS`). `job_out_of_date(job_fp, current_active_fp)` compares the job's stored fp against `current_active_design_fingerprint()` = **the design CURRENTLY LOADED in the backend** (`design_state.get_or_404()`), NOT the job's frozen snapshot.

**Key gotcha #1 — the guard is relative to the LIVE loaded design.** After a dev-server restart the backend can come up with a *different/default* design while the browser still shows the old one. **First check what's actually loaded**: `curl -s localhost:8000/api/design | jq '.design.metadata.name'` and compare to the job's frozen `design.json` (`workspace/{oxdna_jobs,md_jobs}/<id>/design.json`). Fingerprint IS deterministic + display-layer-agnostic (same saved .nadoc → identical fp; cluster transforms/camera/feature-log excluded). 3x6x400 sweep jobs legitimately differ (different `loop_skips` per run).

**Key gotcha #2 — MULTI-DOCUMENT doc-header desync (the REAL 2026-07-03 root cause).** NADOC is multi-document: each browser tab has a `doc_id` sent as header **`X-NADOC-Doc`** (from `frontend/src/shared/doc_id.js` `docHeaders()`; backend `doc_context.py` ContextVar + `DocContextMiddleware`; per-doc active design in `state.py` `_sessions[doc]`). The active-design fingerprint (`current_active_design_fingerprint()` → `design_state.get_or_404()`) resolves **the request's doc**. If a request omits the header it hits `__default__`. Diagnosis tooling: `GET /api/documents` lists every doc's `{doc_id, design:{id,name}}`; fetch a specific doc's design with `curl -H "X-NADOC-Doc: <id>" .../api/design`. **The bug:** `md_jobs_panel.js` used raw `fetch('/api/md/jobs…')` calls that OMITTED the header → job list + "continue production" resolved the default doc (a stale "Bundle") → false stale 409, while the design *display* (via `client.js`, which stamps it) correctly showed 3x6x200. Proof: `GET /api/md/jobs` no-header → `out_of_date=True`; with `-H "X-NADOC-Doc: <3x6x200 doc>"` → `False`. Also note e2e/test runs LEAK docs into the live dev backend (saw 50: teeth×16, metrics-popup×5, __e2e__…). **Fix (prevention):** routed ALL md panel calls through `client.js` MD functions (`_oxdnaJSON` always stamps `docHeaders()`); no raw `/api/md` fetch remains in the panel. Regression: `frontend/src/api/md_client_doc_header.test.js` pins the header on every MD endpoint. oxDNA panel was never affected (already uses `client.js`). Invariant: **never call `/api/md`|`/api/oxdna` with a bare `fetch` — use the `client.js` wrappers so the doc header can't be dropped.**

**Fix shipped 2026-07-03:** `describe_staleness(job_design, current_design, stage)` in oxdna_staleness.py now distinguishes (a) *a different design is loaded* — name/lattice/helix+strand-count mismatch → "A different design is loaded: app has 'Bundle' (honeycomb, 26 helices, 52 strands), but this job was prepared from '3x6x200_test' (square, 18 helices, 77 strands). Open '3x6x200_test'…" (rolling the feature log can't help) from (b) *same design edited* → "'X' has been edited … roll the feature log back." Wired into `_assert_md_job_current` (routes_md.py) + `_assert_job_current` (routes_oxdna.py); frontend already shows `d.detail`. Generic fallback (no snapshot design) keeps the old "design has changed" wording — hence the pre-existing oxDNA staleness tests (jobs w/o design.json) still pass. Tests: `test_md_stale_message_names_a_different_loaded_design` (different-design branch), `test_md_out_of_date_flag_and_roll_clears_it` (edited branch). See [[af25_af26_job_log_sync]] (roll/return lifecycle).

**Reference-geometry invariant (2026-08-12):** Every simulation job is prepared from
`Design.without_reference_geometry()`. The shared build fingerprint and the coarse
identity used by `describe_staleness` must apply that same projection before comparing
a live editor design with a frozen job snapshot. Hashing the full editor design makes
every fresh job from a reference-backed design immediately stale (the VoltronCoreArm
reproduction was 71 helices/436 strands live versus 9/224 simulated). The projection
belongs centrally in `oxdna_design_fingerprint`, not independently in each engine's
status route.

**Projection hardening (2026-08-12):** `Design.without_reference_geometry()` also
prunes reference-owned crossovers, deformations, extensions, overhang metadata,
connections/bindings/duplexes, ligations, nucleotide transforms, and anchored protein
attachments/assets. Cleanup also runs on already-stripped snapshots, removing orphan
records left by older projection code. Fingerprint `v3` hashes this canonical projection;
cross-version hashes degrade to unknown instead of falsely marking old jobs stale.
