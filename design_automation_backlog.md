# design-automation backlog — UI-only / API-less operations → programmatic + validated

**Purpose.** NADOC has many operations a user can *only* perform with the mouse, and many more that
have a REST route but **no programmatic/headless entry point**. That gap blocks two goals at once:
**(1) automated correctness validation** (you can't pin what you can't drive headlessly) and
**(2) eventual text-to-DNA-origami** (an AI/script can only build what's reachable without a canvas).
This loop closes those gaps **one feature per session**, the same disciplined way the god-file carve-ups
(`backend_router_carveup.md`, `main_js_carveup.md`) and the fix loop (`issues_ledger.md`) work:
a ranked backlog, a per-session protocol, a metrics row in `design_automation_log.md`, a living handoff,
and **cross-loop intake** into the bug ledger + manual-validation debt.

It is a *feature-development* loop, so it is governed by **`FEATURE_DEVELOPMENT.md`** (the module-first
anti-backslip law). The carve-ups *shrink* god-files; this loop must not *re-grow* them. Read that file
before writing any feature.

> **⚠ THIS MAP IS SEQUENCING-ONLY.** Line numbers and route names drift. The audit below was taken
> 2026-06-16; before claiming any item, **re-derive its real surface** — does the REST route still exist,
> is it still UI-wired, what's the actual coupling. Fix the entry you touched on your way out.

---

## The two goals, and why validation comes first

The user chose **validation-first ranking**: rank by which missing API most unblocks *automated
correctness checks*, with text-to-DNA enablement as the tiebreaker. The logic: every headless wrapper we
add is only trustworthy if it ships with a way to *prove* it does the right thing. The validation harness
(Tier 0) and the per-feature oracles are therefore the spine — text-to-DNA (Tier 4) is built *on top of*
a validated wrapper library, not before it. A wrapper with no oracle is a liability, not an asset.

Tiers 0–4 pin the **topological + geometric** layers (deterministic — exact fingerprints, analytic
geometry). **Tier 5** extends the spine to the **physical layer**: drive oxDNA headlessly, *measure*
properties of the relaxed structure, and eventually iterate the design until a user constraint is met
("make these two ends 50 nm ± 5 nm apart"). That introduces a new, *stochastic* oracle class — a measured
property within tolerance, **gated by the confidence metric** (frames pooled / RMSF SE), not exact
equality — and is the concrete bridge from Tier 4's text-to-DNA grammar to *constraint-driven* design.

**Tier 6** extends Tier 5's physical-layer spine from *static* relaxed-structure properties to **time-resolved
electric-field response**: build a design end-to-end (route + sequence + overhang + anchor), subject it to an
E-field, and *measure how it aligns over time* — extracting an **equilibration timeline** (τ to plateau) and a
**non-destructive operating window** (aligns without melting), then **automatically sweeping field intensity ×
direction across many origami designs**. Same stochastic, confidence-gated oracle class as Tier 5, now over a
*trajectory* not a single mean structure. The capstone (AF-23) is the user's stated goal: automated cross-design
exploration of which fields align which structures, on what timescale, without ripping them apart. A parallel
sub-track (AF-21/22, gated on an **oxpy rebuild**, `-DPython=ON`) adds a persistent in-process engine for *live*
field steering — the "play with it in real time" capability — proven equivalent to the validated batch engine.

---

## Target shape (where new code lands — NOT the god-files)

Three shapes, and deciding which one an item wants is the first move:

1. **Headless wrapper** — a REST-backed design operation that has no programmatic entry → a thin function
   in **`backend/api/headless_build.py`** (the existing mouse-free construction module — the seed for
   AI-driven design). Mirror its existing wrappers (`create_bundle`, `extrude`, `auto_scaffold`,
   `overhang_extrude`, `full_autostaple`). It runs the *same* service the route runs; it does **not**
   duplicate logic. **Never** add the logic to `crud.py`/`assembly.py`.

2. **New headless module** — when a whole subsystem has no programmatic builder. The flagship case:
   **assembly has no headless builder** → a NEW `backend/api/headless_assembly_build.py` mirroring
   `headless_build.py` (scratch-session context manager + fluent ops). New module, not a god-file block.

3. **Service + oracle push** — when the operation's *logic* (not just its HTTP shell) belongs in a pure,
   testable place → a pure HTTP-free fn in **`backend/core/<area>.py`** + a **validation oracle** that
   pins its contract. `backend/core` may import nothing from `backend/api`.

Whichever shape: the **mandatory deliverable is a validation augment** (next section). A wrapper without
one does not ship.

---

## Improvement metric — the anti-shovel contract (this is the point)

The carve-up's failure mode was *LOC-shoveling*. This loop's failure mode is **passthrough-shipping:**
adding a `headless_build.foo()` that just forwards to `POST /design/foo` and calling it done — when it
added *no new validation power* and can't be trusted by an automated builder. That is not closing the
automation gap; it's lengthening the call chain.

So **"a wrapper exists" is never the pass criterion.** The pass criterion is:

### Primary metric — a reusable **validation augment** shipped with the feature
Every AF item ships **≥1 new automated oracle/pin** that proves the operation is correct, and that is
**reusable** by later items. Acceptable forms (mirror an existing pattern — see `design_automation_log.md`
"Oracle catalog"):
- **Round-trip equality** — build via the new wrapper → export `.nadoc`/`.nass` → import → assert
  `_canonical_topology` equal (the id/order-independent fingerprint from `test_section_router.py`).
- **Inverse-pair invariant** — op then its inverse → topology unchanged (e.g. nick→ligate, add→delete).
- **Geometric oracle** — the result's geometry matches an analytic expectation (mirror
  `derive_periodic_delta`, the circle circularity oracle, the section-router gap-clearance metrics).
- **`validate_design` gate** — the built design passes the topological validator (no unresolved nicks,
  consistent strand positions, correct domain count).
- **JS↔Python parity** — if the op has a frontend preview, its JS logic and the Python build pin to the
  same numeric oracle (mirror `circle_primitive_logic.js` ↔ `core/circle_primitive.py`).

### Secondary metrics (log the ones that moved)
- **Headless coverage** — REST design/assembly routes that now have a headless wrapper, before→after.
  (Tier 0 builds the automated coverage report so this number can't go stale.)
- **God-file LOC Δ** — `crud.py` / `assembly.py` / `main.js` must end **flat or lower**. A rise means
  logic crept into a god-file instead of `headless_build`/`backend/core` — extract before committing.
- **Cohesion** — the new wrapper/module's *one reason to change* in a sentence.

### The required justification line
Every metrics row ends with: **"Validation gained, not just a passthrough: ___"** naming the oracle
shipped and what it now proves that nothing proved before. If you can't write it honestly, you shipped a
passthrough — add the oracle or revert.

---

## Per-session loop protocol

A fresh session keeps token cost low. Per session:

1. **Read** this map (start with the ≤8-line `## Next-session handoff`) + `design_automation_log.md`
   (conventions + oracle catalog + lessons + difficulties). Read `FEATURE_DEVELOPMENT.md` (module-first law).
   Skim the relevant `memory/project_*.md` for the area (e.g. `headless_build`, `assembly_overhaul`). Do NOT
   read `design_automation_harness.md` / `design_automation_metrics.md` wholesale — open only the harness
   block / metrics row for the item you're extending (the handoff names it).
2. **Pick ONE item** — the handoff's `▶ NEXT`, or the topmost unchecked backlog entry, or one the user
   names. One AF item (or one phase of a multi-phase item) per session.
3. **Re-derive the surface (cheap, do it):** confirm the REST route still exists and what it expects
   (`rg "<url-fragment>" backend/api/`), and that it's still UI-wired (`rg "<fn>" frontend/src/api/`).
   A dead route is a *delete* candidate, not a wrap candidate — route it to `issues_ledger.md`.
4. **Decide the shape** (wrapper / new module / service+oracle push) and **pick the validation form**
   from the primary-metric list BEFORE writing code. The oracle is the acceptance test — write it first
   where practical (it should fail until the wrapper works).
5. **Build:** the wrapper in `headless_build.py` (or the new headless module / `backend/core` fn) +
   the validation augment (a direct unit/integration test in `tests/`). No god-file growth.
6. **Gate:** `just test` green — cite pass count, flag any *drop*. `just lint` clean on touched files.
   A feature without its validation augment does not ship.
7. **One item per commit** (`feat(automation): headless <op> + <oracle>`). Commit only when the user asks.
8. **Update the ledgers:** check the box here; add a metrics row to **`design_automation_metrics.md`** **with
   the mandatory justification line**; if you shipped a reusable wrapper, add ONE block to
   **`design_automation_harness.md`** (+ its one-line index entry) and a row to the log's oracle catalog;
   bank any new lesson in the log. **Overwrite** `## Next-session handoff` (≤8 lines) — never append harness
   blocks to it; that regression is exactly what the 2026-06-25 split undid.
9. **Route what you found:** a bug → `issues_ledger.md` dossier. A genuinely UI-only op that can't be
   headless'd (pure pixel-gesture, no coord route) → push an `MV-N` row to `manual_validation_debt.md`
   (it's validated by hand, not automated). A stuck item → the log's difficulties ledger with *why*.

**Don't:** add operation logic to `crud.py`/`assembly.py`/`main.js`. Touch `_PHASE_*` or the mutation
contract (`mutate_and_validate`/`set_design_silent`/`snapshot`). Reason geometrically about crossover
placement (mechanical rules only — `feedback_crossover_no_reasoning`). Change a route URL.

---

## Single-line invocation

- **Slash command:** `/automate-feature` (optionally `/automate-feature AF-3` to name an item).
  Skill at `.claude/skills/automate-feature/SKILL.md` — loads this map + the log, picks the handoff's
  next item, re-derives its surface, and runs the protocol.
- **Plain prompt:** *"Run a design-automation feature loop"* / *"Work the next AF item."*

---

## Next-session handoff

_Living pointer — OVERWRITE this each session (protocol step 8). Keep it ≤8 lines. Do NOT append harness blocks here — those live in `design_automation_harness.md`._

**▶ STATE (2026-08-25):** named assembly interfaces now carry position, orientation, typed chemistry, and clearance; `hab.add_linear_attachment_layout` materializes deterministic mixed-composition tracks through the existing connector route. Oracle count **61 → 62** (`assert_attachment_layout`: geometry + composition + clearance + real `.nass` round-trip). `main.js` unchanged.
**▶ NEXT:** generalize the same pure layout service to grid/radial/path layouts and mixed composition, without adding another connector abstraction. Add collision/clearance-between-sites measurement before automatic mating.
**▶ STILL PICKABLE:** AF-40/41 headless constrained-drag/movable-link solvers. AF-27 hinge composition remains ASK-FIRST on linker endpoint, ss/ds choice, and bridge length. AF-37 partial sub-domain bindings remain ASK-FIRST because Duplex Phase 6 plans to retire that path. AF-24 P2/P3 remain OTHER COMPUTER.
**▶ WATCH-OUT:** interface normals are explicit declarations; do not infer DNA polarity or overhang tip orientation in the layout core. Use `blunt_end_connectors.js` for geometry-derived blunt ends.
**▶ REFERENCE:** signatures/gotchas in `design_automation_harness.md`; metrics in `design_automation_metrics.md`; oracle catalog/lessons in `design_automation_log.md`.

## Backlog — open items (ranked). Full rows + all SHIPPED items live in the archive.

_The verbose full rows (open + shipped) moved to `design_automation_backlog_archive.md` for context economy._
_These are the still-open/actionable `AF-N`; click through for the full audited row._

- **AF-27** — overhang-linker create + linker/bond relax — hinge-confinement keystone; P1+P2 shipped, parent open. [detail](design_automation_backlog_archive.md#af-27)
- **AF-37** — direct overhang-binding + sub-domain wrappers — **root-to-root CREATION DONE 2026-07-16** (5 wrappers: create/patch/delete binding + sub-domain split/patch; oracle `assert_bind_unbind_inverse`; coverage 56→61; end-to-root shipped earlier). **Still open:** *sub-domain* (partial) bindings — but see the ⚠ steering note: Proposal-B Phase 6 demotes sub-domains + retires `OverhangBinding`, so ASK before investing. Joint-lock deliberately NOT built (already route-pinned; would be a redundant oracle — see the log's AF-37 lesson). [detail](design_automation_backlog_archive.md#af-37)
- ~~**AF-39**~~ — **DONE 2026-07-16** — ss-linker relax headless test (AF-38 gap G1); pins bin → chord geometry, no new wrapper/oracle. [detail](design_automation_backlog_archive.md#af-39)
- ~~**AF-42**~~ — **DONE 2026-07-16** — ds linker-relax pin re-anchored to the real `__lnk__` complement (was silently exercising the synthetic fallback); degenerate origin re-derived `[2.5,0,0]`→`[2.0,0,0]`, default `length_bp` 24→16 so the ds span is reachable and the relax lands ON it. Fixture-only, no new wrapper/oracle, coverage FLAT. Row in `design_automation_metrics.md`.
- **AF-40** — headless constrained-drag solver (free-until-taut + ds rigid-strut) + tether oracle. [detail](design_automation_backlog_archive.md#af-40)
- **AF-41** — headless movable-link chain solve + oracle — depends on AF-40. [detail](design_automation_backlog_archive.md#af-41)
- **AF-28** — hinge-angle linker designer: overhang-placement optimizer — open question, depends on AF-27. [detail](design_automation_backlog_archive.md#af-28)
- **AF-24 P2/P3** — real-engine field-sweep + cross-design campaign — OTHER COMPUTER, don't pick up. [detail](design_automation_backlog_archive.md#af-24)
- **AF-ATOM P3** — per-atom sphere coverage oracle (Tier F). [detail](design_automation_backlog_archive.md#af-atom-p3)

> **History.** Shipped AF items live in [design_automation_backlog_archive.md](design_automation_backlog_archive.md). Read on demand only — never in a routine loop.
