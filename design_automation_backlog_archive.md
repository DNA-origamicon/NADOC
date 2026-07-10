# design-automation backlog — archive (shipped items)

> Split out of `design_automation_backlog.md` on 2026-07-09 for context economy. Holds every SHIPPED/DONE `AF-N` item and its historical narrative, plus the full verbatim rows of the still-open items (indexed one-line in the HEAD file). **Read on demand only — never in a routine loop.**

## Backlog (ranked, validation-first). Probed status is the 2026-06-16 audit; verify before claiming.

### Tier 0 — validation foundation (everything leans on it)

- [x] **AF-1 — Headless round-trip validation harness + coverage report.** SHIPPED 2026-06-16.
  `tests/automation_harness.py`: `canonical_topology` (promoted from `test_section_router.py`),
  `roundtrip_nadoc` (real `to_json` → `POST /design/import`, scratch-isolated), `assert_roundtrip_stable`
  (validate → round-trip → validate + fingerprint-equal; injectable `roundtrip` seam),
  `headless_coverage_report` (route-vs-wrapper by **function-object identity** → never stale). 8 meta-tests
  in `tests/test_automation_harness.py`, incl. the load-bearing "oracle fires on a corrupted round-trip".
  Coverage at ship: **11 / 239** design+assembly mutation routes wrapped.

- [x] **AF-FIXTURES — headless regeneration of every test fixture (drift-proof provenance). SHIPPED 2026-07-01.**
  AUDIT: a fixture whose only provenance is a hand-saved `.nadoc` silently drifts when the builder evolves.
  Found exactly that — the `2x6_triple_hinge_link` golden had been overwritten with a *routed* design
  (1 merged scaffold + 36 staples) while `build_hinge_primitive` builds the *unrouted* primitive (18
  scaffolds + 24 staples, 2x2→2x4→2x6 = 6→12→18), so `test_build_2x6_matches_golden` failed (42 vs 37
  strands). **DELIVERED:**
  - `scripts/regen_test_fixtures.py` — regenerates every buildable fixture (`--write`), reports the gaps.
    Regenerated the stale 2x6 golden → 3 golden tests green.
  - **`build_applied_2x2_binding(*, close_bond=False)`** in `headless_hinge_build.py` — regenerates
    `relax_2x2_binding.nadoc` + `relax_2x2_closebond.nadoc` (the 6-test-dependency gap) fully headless:
    `build_hinge(2,2)` → `auto_scaffold` (NO auto_crossover — build_hinge's bp-8 staple termini collide
    with the "basic" crossover placer → non-physical nick-at-crossover; the duplex tests need no
    crossovers) → extrude 2 rail overhangs (leaf-A row1→gap row2 = duplex helix; leaf-B row4→gap row3,
    relocated on apply) → `create_connection_version(end-to-root)` → `apply` → derive Duplex graph
    (`synthesize_duplexes_from_bindings` — the load path does this, a raw `model_validate` in a test does
    not) → add revolute hinge joint on the driven leaf. `close_bond` relaxes then translates the driven
    leaf `_CLOSEBOND_COMPRESS_NM=0.3` along the bond → over-compressed ~0.37 nm (the joint-arc MINIMUM is
    the 0.67 target, so <target needs a translation OFF the arc, not a rotation — banked lesson). Both
    outputs VALID (`validate_design.passed`); all 6 dependent files green against the regenerated fixtures;
    builder itself pinned by `test_build_applied_2x2_binding_*` (valid applied duplex + close-bond<0.67).
  - Portability hardening (kept): `skipif(fixture missing)` guards on the 5 previously-unguarded
    `relax_2x2` test files (per-test on `test_duplex_relax` so its 422/404 in-memory tests still run).
  - **Remaining LOW gaps:** `tests/fixtures/{test343,10-6-10hb_seamed}.nadoc` — tracked (portable) but
    hand-saved, no builder. Not worth a generator (low value, already portable).
  - **Have builders (OK):** `18hb_fixture` (`make_18hb_design`), `teeth`/`teeth_unrouted`
    (`make_teeth_design`), hinge goldens + relax_2x2 via `regen_test_fixtures.py`.
  - **Deferred augment idea:** a meta-test asserting every `tests/fixtures/*.nadoc` a test reads is
    git-tracked OR has a `regen_test_fixtures.py` entry — so a new unbuildable/untracked fixture can't
    sneak in. (The relax_2x2 fixtures remain UNTRACKED but are now regenerable — commit-or-regen is the
    user's call.)

### Tier 1 — design-op headless wrappers (REST exists, wrapper missing; small, high validation value)

- [x] **AF-2 — nick / ligate / delete-strand wrappers** in `headless_build.py` (routes `/design/nick`,
  `/design/ligate`, `DELETE /design/strands/{id}`). SHIPPED 2026-06-16. **Augment:** `assert_inverse_pair`
  (new reusable oracle in `automation_harness.py`) — `nick(h,bp,d)` then `ligate(h,bp,d)` → canonical
  topology unchanged, with a built-in "forward must mutate" guard so it can go red; delete pinned by
  canonical strand-set subtraction + round-trip stable. Coverage 11→14.
- [x] **AF-3 — loop/skip insert + apply-all-deformations wrappers** (routes `/design/loop-skip/insert`,
  `/design/loop-skip/apply-deformations`). SHIPPED 2026-06-16. `hb.loop_skip(h,bp,delta)` +
  `hb.apply_loop_skip_deformations()`. **Augment:** `assert_geometric_length_delta` (new reusable oracle in
  `automation_harness.py`) — pins the topology→geometry conservation law: a loop +1 adds 1 bp of geometry
  (1 nuc/strand), a skip −1 removes 1, delta=0 restores; per-helix scoping proves bulk apply honours each
  helix's marks one-for-one even when the global net cancels. Also pins loop survives `.nadoc` round-trip
  (canonical_topology is blind to loop/skips, so the geometric count is what proves persistence). Coverage 14→16.
- [x] **AF-4 — parametric circle (`circle-segment`) wrapper** (route `POST /design/circle-segment`).
  SHIPPED 2026-06-17. `hb.circle_segment(radius_nm, *, plane, offset_nm, …)` — takes the *radius*, runs the
  same `circle_footprint` analytic the UI mirror uses, drives `add_circle_segment`. **Augment:**
  `assert_circular_disc` (new reusable oracle in `automation_harness.py`) — reads the *placed* helices' axis
  spans (not a stored field) so it pins the full path radius→footprint→route→builder→geometry: `circularity_spread
  < 0.5 nm` + `fit_radius` within 0.5 nm of the requested R. Coverage 16→17.
- [x] **AF-5 — deformed-continuation wrapper** (route `/design/bundle-deformed-continuation`).
  SHIPPED 2026-06-17. `hb.bundle_deformed_continuation(cells, length_bp, *, source_bp, ref_helix_id, plane)`
  — samples the deformed frame via `get_deformed_frame` then POSTs *with* `source_bp` (the replayable path,
  mirrors the UI). **Augment:** `assert_on_deformed_frame` (new reusable oracle in `automation_harness.py`) —
  asserts each appended helix's `axis_start` lies on the independently re-derived deformed cross-section frame
  at `source_bp` AND is displaced > 0.5 nm from where a straight extrude would land (the can-go-red guard).
  Coverage 17→18.

<a id="af-27"></a>
- [ ] **AF-27 — overhang-LINKER creation + linker/bond RELAXATION wrappers (the hinge-confinement keystone).**
  The design-layer linker routes EXIST but have **no headless wrapper** (only the *assembly*-layer overhang
  bindings are wrapped, in `headless_assembly_build.py`; `headless_build.py` wraps only `overhang_extrude`).
  Audited 2026-06-25: routes `POST /design/overhang-connections` (`create_overhang_connection`,
  `OverhangConnectionCreateRequest`), `POST /design/overhang-connections/{id}/relax`
  (`relax_overhang_connection`, `RelaxLinkerRequest`), and the generic `POST /design/relax-bond`
  (`relax_bond_endpoint`, `RelaxBondRequest`). This item is the blocker for **everything hinge-angle**: a
  script can build two leaves + extrude overhangs on each, but **cannot tie them together with a
  length-defined linker** — and the linker's contour length is precisely what confines the hinge angle.
  See `memory/project_overhang_connections.md` (ss+ds linkers, bridge nucs), `project_ssdna_linker_relax.md`
  (FJC slab+SAW), `project_bond_relax.md` (0/1/N-DOF generic bond relax). **One phase per session.**

  **Three-layer note (VERIFY before building — re-derive the real surface).** Creating an overhang
  *connection* likely adds bridge nucleotides/strands → a **topological** write (an allowed edit, but NOT a
  pure display pose). The *relax* step is the suspicious one: per `project_bond_relax.md` / `ssdna_linker_relax`
  it should produce a **geometric/display pose** of the linker (and a `display-pose` PATCH sibling exists),
  NEVER written back to topology — confirm the relax route doesn't mutate the strand graph (mirrors the
  cluster-transform three-layer guard). If `relax_overhang_connection` edits topology, that's a finding to log,
  not to wrap silently. **ASK-FIRST:** *which* overhang nucleotide is the linker's attachment endpoint, and the
  ss-vs-ds / bridge-length choice for a given gap, are directionality/topology questions
  (`feedback_crossover_no_reasoning`, `overhang_definition`) — do not infer; surface them.

  - [x] **Phase 1 — `hb.connect_overhangs(...)` creation wrapper. SHIPPED 2026-06-25.** Imports
    `create_overhang_connection` + `OverhangConnectionCreateRequest` (covered by function identity →
    coverage **41 → 42**). Signature mirrors the body (exposes `length_value`/`length_unit` — the
    user-meaningful contour-length knob — not a pre-chewed bridge payload):
    `connect_overhangs(overhang_a_id, overhang_b_id, *, overhang_*_attach, linker_type="ds", length_value,
    length_unit="bp", name, bridge_sequence) → Design`. **Augment:** `assert_linker_connects(design, conn_id,
    *, overhang_a, overhang_b, bridge_bp=None)` (new reusable oracle in `automation_harness.py`) — the
    connection exists, joins the two named overhangs (order-independent set), carries the requested bridge
    length (`length_value`/`length_unit` lowered via the route's own `_length_value_to_bp`), and survives
    `roundtrip_nadoc` (the load-bearing pin — `canonical_topology` does NOT fingerprint `overhang_connections`,
    so only re-reading after export→import proves the wiring persisted). 3 can-go-red guards (no connection /
    wrong partner / wrong bridge_bp). Fixture: two real extruded-overhang leaves (mirrors
    `_seed_with_real_oh_domains`; the 3 hinge primitives carry NO overhangs yet — they'd need
    `overhang_extrude` first). Tests: 3 in `test_headless_build.py` + 4 in `test_automation_harness.py`; 3
    coverage-count meta-tests bumped 41→42. Full suite **3189 passed / 60 skipped**.
  - [x] **Phase 2 — `hb.relax_overhang_connection(...)` + `hb.relax_bond(...)` relax wrappers. SHIPPED 2026-06-27.**
    Imports `relax_overhang_connection`/`RelaxLinkerRequest` + `relax_bond_endpoint`/`RelaxBondRequest`/
    `RelaxBondEndpoint` (covered by function identity → coverage **48 → 50**). **VERIFIED display-pose** — both
    routes mutate only `cluster_transforms` (+ a `ClusterOpLogEntry`), never the strand graph, so
    `canonical_topology` is unchanged (the load-bearing Three-Layer pin). **Augments (2, both NEW reusable):**
    `assert_linker_relaxed_pose(before, after, conn_id)` — STRAIN-REDUCTION (user choice 2026-06-27, not raw
    chord-within-contour): `strain = |anchor_chord − natural_span|` re-measured on the POSED geometry
    (`_anchor_pos_and_normal`, the relax's own anchor lookup — NOT its optimiser) must FALL + a pose moved +
    topology unchanged; and `assert_bond_relaxed_pose(before, after, *, side_a, side_b, target_nm)` — the
    generic-bond analog (`strain = |bond_chord − target_nm|`). **GOTCHA found:** the natural relax fixture is
    DEGENERATE — the moving overhang's anchor sits ON the hinge axis (`joint_origin=[2.5,0,0]`), so rotation
    can't change the chord and strain is flat; moving the joint origin OFF the overhang (`[0,0,0]`) makes the
    relax drive the chord exactly to the natural span. That degenerate case is the oracle's load-bearing
    can-go-red. Tests: 5 in `test_headless_build.py` (linker pass/degenerate/pose-only + bond 0-DOF/1-DOF) + 5
    in `test_automation_harness.py` (pass + 2 linker red + bond pass + bond red) + coverage meta bumped 48→50
    in 3 files. Full suite **3341 passed / 61 skipped**.

- [x] **AF-29 — hinge ssDNA flexible-segment RELAX, headless + JS↔Python parity (the hinge rest-pose keystone).
  SHIPPED 2026-06-25 (user request, sibling of AF-27).** The in-app "Relax flexible segments" command pulls a
  hinge's rigid leaves together until every unpaired-ssDNA scaffold tether is taut at its contour length
  ("free until taut") — the geometric rest pose that sets the hinge angle. But the **PBD minimisation solver was
  JS-ONLY** (`cluster_gizmo.js` `relaxSsdna`/`_projectSsdnaConstraints`/`_maxSsViolation`); `POST
  /design/flexible-relax` only *applies* pre-computed transforms, so a headless script could not COMPUTE a relax.
  **Faithfully ported** the solver to pure `backend/core/flexible_relax.py` (`relax_cluster_pose` + the orchestration
  `compute_relax_transforms` mirroring `flex_relax.js relaxFlexible`: group by cluster pair → move the smaller cluster
  → translate-only for a lone tether → Gauss-Seidel sweep), driven by `hb.relax_flexible_segments(*, scope, conn_id)`
  which commits via the real `flexible_relax` route (coverage **42 → 43**). **Three-Layer-clean:** moves
  `cluster_transforms` only, never the strand graph (asserted). **Augments (2):** (1) `assert_flexible_segments_relaxed`
  (new reusable oracle) — the solver-independent correctness pin: every flexible connection's anchor-to-anchor chord
  (on POSED geometry) ≤ `contour_length_nm + tol` + a pose-moved guard + `canonical_topology` unchanged; (2)
  **JS↔Python PARITY** — extracted the JS solver into pure `frontend/src/scene/flexible_relax_solver.js` (THREE-free,
  vitest-pinned) and pinned the Python port to the SAME asymmetric-fixture golden (pos+rotation to 1e-6) so headless ==
  in-app. Tests: 4 in `test_flexible_relax.py` (solver+parity) + 2 in `test_headless_build.py` (taut + no-op) + 4 oracle
  red-tests + 3 vitest. **NB cluster_gizmo.js NOT rewired** to the pure module (its live 3D drag can't be headlessly
  verified) — the module is its faithful tested copy; wiring it as the single source is a clean follow-up.

<a id="af-37"></a>
- [ ] **AF-37 — design-layer DIRECT overhang-BINDING + sub-domain headless wrappers (the WC-duplex-that-locks-a-joint).
  GAP found 2026-06-27 (user's "directly bound" hinge test).** The user asked to build a hinge whose two overhangs
  are **directly bound to each other** (a real Watson-Crick duplex between the overhangs that LOCKS the connecting
  ClusterJoint to the duplex-satisfying angle — the `OverhangBinding` system, Phase 5), in a **root** vs **free-end**
  variant. AF-27 wrapped `connect_overhangs` (the LINKER/bridge path) + the relax, but the **entire design-layer
  direct-binding surface is UNWRAPPED** (confirmed `rg` over `headless_build.py` → NONE): `create_overhang_binding`
  (`POST /design/overhang-bindings`), the bind/lock `patch_overhang_binding` (`PATCH …/{id}` — sets `bound`, which
  drives `_apply_driver_to_joint` to freeze the joint at `locked_angle_deg`), and the sub-domain ops a root-vs-free-end
  bind needs to be DISTINCT: `sub-domains/split` (`POST …/sub-domains/split`), `sub-domains/{id}` PATCH (sequence),
  `generate-binder`/`generate-random` (to make the two halves WC-complementary), and the overhang sequence PATCH
  (`PATCH /design/overhang/{id}`). **Why root-vs-free-end NEEDS the gap closed:** an extruded overhang carries ONE
  whole sub-domain, so `_sub_domain_at_attach(root)` == `_sub_domain_at_attach(free_end)` — the two variants are
  identical until the overhang is SPLIT into a root + free-end sub-domain and each pair sequenced complementary.
  **CONFIRMED completable via direct route calls (2026-06-27) — the gap is "no headless wrappers", not "impossible".**
  The true no-linker bind was built by hand-driving the unwrapped routes: `overhang_extrude` ×2 → `split_sub_domain`
  (offset 4, → root + free-end halves) → `patch_sub_domain(sequence_override=…)` to make the bound pair WC-complementary
  (`AACC`↔`GGTT`) → `create_overhang_binding(sub_domain_a, sub_domain_b, target_joint_id)` → `patch_overhang_binding(bound=True)`.
  **`bound=True` RELOCATES topology** (driven OH's domain moves onto the driver helix antiparallel, **driven helix DELETED**
  → a real duplex, `overhang_connections`==0, NO `__lnk__` bridge) but by design does **NOT** auto-lock the joint
  (`locked_angle_deg` stays None — the in-app flow is a separate right-click "Relax bond"; reverted to manual 2026-05-14).
  Closing it = `relax_bond("crossover", bond_id=<the OH→parent crossover spanning the two clusters>)`. Built both
  configs → `workspace/3x6_hinge_bound_{root_to_root,end_to_root}.nadoc` (root_to_root: ohA offset-0 ↔ ohB offset-0;
  end_to_root: ohA offset-4 ↔ ohB offset-0; both close to ~175°, the 4 bp register offset is small vs the ~38 bp lever).
  The earlier `connect_overhangs(length_value=0)` files (`3x6_hinge_direct_{root,free_end}.nadoc`) are the WRONG path —
  a zero-bridge LINKER (the "1 bp linker mediating" the user flagged), NOT the no-linker bind. **Three-layer:** creating a binding/sub-domain is a
  topological/annotation edit (allowed); the bind→joint-lock writes the joint angle window (design-layer). **One phase
  per session** (suggested split: P1 `hb.create_overhang_binding` + `hb.set_binding_bound` + an `assert_binding_locks_joint`
  oracle [the bound binding froze the joint to `locked_angle_deg`, survives round-trip — `canonical_topology` blind to
  bindings, same blind-spot as connections]; P2 the sub-domain `split`/sequence wrappers + an `assert_subdomains_tile`
  / WC-complement oracle so a root-vs-free-end bind is constructible headlessly). **ASK-FIRST** the sub-domain split
  point + which sequences (directionality/sequence choices). See `memory/project_overhang_binding_extensions.md`,
  `project_overhang_subdomains.md`, `project_oh_binder.md`.
  - [ ] **BLOCKED + REVERTED 2026-06-27.** A first headless attempt (binding wrappers `split_sub_domain` /
    `set_sub_domain_sequence` / `create_overhang_binding` / `set_binding_bound` + a composed
    `build_bound_end_to_root_hinge` generator + a crossover-constrained `overhang_placement` module + a
    full-autostaple tweak) was built and then **reverted in full** — it rested on assumptions that don't hold.
    The **actual desired manual ops are F8–F13 of `workspace/3x6_autogen_hinge.nadoc`** (the new reference;
    the old `3x6_hinge_bound_end_to_root.nadoc` is gone): on a **200 bp seamed + already-autostapled** hinge,
    extrude a **10 bp** overhang on `h_XY_2_0` bp 56→gap(3,0) AND on `h_XY_5_1` bp 40→gap(4,1) (DIFFERENT
    columns 0/1 + DIFFERENT bp), `generate-random` a rare sequence on A (`CGGACTAGGC`), set B = its revcomp
    (`GCCTAGTCCG`), create binding B1 (whole sub-domains, no split), bind.
    **Gaps to automating this (the blockers):**
    1. **Overhang positions are design decisions, not auto-derivable** — the pair is on different columns/bp,
       reaching diagonally across the gap into the end-to-root register; there is no model for choosing a
       *bindable, gap-spanning* site pair (→ janky binding UX).
    2. **Automatic overhang generation correctness** — must invoke the real rare-sequence `generate-random`
       (Johnson 5-mer, no hairpin/dimer) for one half + revcomp the other; the attempt hardcoded a placeholder.
    3. **Order is route-first** — seamed scaffold + full-autostaple run BEFORE the overhangs are extruded onto
       finished staples; the attempt extruded onto the bare bundle then routed, which is what forced the (now
       reverted) full-autostaple change. With the real order the original "protect overhang staples wholesale"
       behaviour is correct (the overhang strand was routed as a plain staple before the overhang was added).
    4. **Better overhang binding development** — `bound=True` relocates the duplex but does **NOT** lock the
       joint (`locked_angle=None`, joint stays ±180°); confining the hinge needs a separate `relax_bond`, and
       the whole bind→lock flow is manual/janky.
    Until those mature, recreating F8–F13 headlessly is out of reach. See `memory/project_overhang_binding_extensions.md`,
    `project_overhang_subdomains.md`, `project_oh_binder.md`.
  - [x] **END-TO-ROOT SHIPPED 2026-06-29 via a DIFFERENT (cleaner) path — `apply_end_to_root_binder`.** The
    janky sub-domain-split + bind-lock surface above is sidestepped: the direct end-to-root connection is now
    a ConnectionVersion **apply** (`hb.create_connection_version(connection_type="end-to-root")` →
    `hb.apply_connection_version`). Apply regenerates overhang B as A's reverse-complement binder, splicing the
    binder domain (antiparallel, on A's helix, RC of A) into B's root staple in place of B's tip, then cleans the
    relocation: adds a **`ForcedLigation`** at the root→binder junction, **drops B's stale overhang crossover**,
    and **deletes B's orphaned overhang helix** (+ scrubs cluster `helix_ids`). B is consumed (its `OverhangSpec`
    removed; a domain can't be both overhang and binder). No sub-domain split, no `OverhangBinding`, no
    `locked_angle` — it's a pure topological splice. **Augment shipped:** reusable oracle
    `assert_end_to_root_binder` (8 clauses incl. no-orphan-helix / no-stale-crossover / forced-ligation, all
    re-checked after a `.nadoc` round-trip — the load-bearing pin for the `autodetect_overhangs`
    `binds_overhang_id` skip-guard), a caDNAno-export validation test, AND an **autonomous-build composition
    gate** (`test_autonomous_build_end_to_root_binding_is_valid_and_roundtrip_stable`: full headless grammar →
    end-to-root apply → `assert_roundtrip_stable` so `validate_design` passes + topology byte-stable). Route
    coverage 50→52 (`create_connection_version` + `apply_connection_version`). Root-to-root / sub-domain
    binding / joint-lock (the blockers 1–4 above) remain open. See `memory/project_overhang_connections_panel.md`.

- [x] **AF-38 — direct-bind RELAX wrappers + minimized-bond oracles ("relax for ALL connection types"). SHIPPED 2026-06-29
  (user request, sibling of AF-27 P2).** AF-27 P2 wrapped ds/ss LINKER relax + the generic bond relax; the two DIRECT-bind
  relaxes were unwrapped + un-pinned. Added `hb.relax_overhang_binding(binding_id)` (root-to-root, wraps `POST
  /design/overhang-bindings/{id}/relax` → shared `core/bond_relax`) and `hb.relax_end_to_root(version_id)` (version-keyed,
  wraps the NEW `POST /design/connection-versions/{id}/relax-end-to-root` whose solver `backend/core/end_to_root_relax.py`
  swings A's overhang duplex 2-DOF about A's root bead [persisted as `OverhangSpec.rotation`, binder co-rotates via
  `binds_overhang_id`] + cluster kinematics [joint-rotate / rigid-translate] to close the spliced ForcedLigation chord;
  same rigid body → swing only). Coverage **52 → 54**. **Augments — 2 NEW reusable oracles:** `assert_binding_relaxed_pose`
  (strain = |sub-domain-junction chord − target| via `_sub_domain_junction_anchor`) + `assert_end_to_root_relaxed_pose`
  (strain = |FL chord − target| via `_find_binder_and_root`/`_bead_pos`; pose-moved clause accepts a cluster move OR an
  `OverhangSpec.rotation` change so the same-body swing-only relax isn't a false negative) — both strain-reduction on POSED
  geometry, `canonical_topology` unchanged. Tests: +4 `test_headless_build.py`, +5 `test_automation_harness.py`, +coverage
  meta 52→54 in 3 files; end-to-root relax solver itself pinned by `tests/test_end_to_root_relax.py` (7). **Validation
  gained, not just a passthrough:** before this nothing could relax a directly-bound overhang headlessly or prove a
  direct-bind relax minimizes its bond; now both paths are driveable + a reusable oracle proves the bound/FL chord is pulled
  to ~one backbone bond on posed geometry without editing topology. **GOTCHA:** binding-relax fixture needs a Z-axis joint
  (a Y-axis joint leaves a y-offset rotation can't close → false degenerate). **GAPS noted:** ss-LINKER relax wrapped +
  oracle-supported but no ss-specific test; direct-binding CREATION still unwrapped (AF-37 blockers).

<a id="af-39"></a>
- [ ] **AF-39 — ss-LINKER relax headless test (AF-38 gap G1, intake 2026-06-29).** The ds-linker relax path is
  pinned (`test_relax_overhang_connection_pulls_linker_toward_natural_span`) but the **ss path is unexercised**:
  `hb.relax_overhang_connection` already dispatches to `relax_ss_linker` (closes the anchor chord onto the chosen
  FJC histogram bin's R_ee, not the ds duplex span), and `assert_linker_relaxed_pose(natural_span_nm=R_ee)` already
  accepts an ss target — so this is a **test + fixture add only, NO new wrapper/oracle**. Build a 2-overhang leaf
  pair tied by an `linker_type="ss"` `OverhangConnection` (mirror `_two_overhang_leaves_with_joint` with
  `linker_type="ss"`, a bp length inside the FJC lookup range), put a joint OFF the moving overhang, relax with an
  explicit `bin_index`, and assert `assert_linker_relaxed_pose(before, after, conn_id, natural_span_nm=R_ee_of_bin)`
  reduces strain toward that bin's R_ee + a degenerate (joint-on-overhang) can-go-red. R_ee per bin via
  `backend.core.ssdna_fjc.bin_r_ee(n_bp, bin_index)`. See `project_ssdna_linker_relax.md` (FJC slab+SAW lookup).
  **Validation gained:** proves the ss-linker relax actually pulls the chord to the FJC ensemble R_ee (a *different*
  target than ds), which no test currently exercises — the ds pin says nothing about the ss bin-selection path.

#### Constrained-move solver ports (intake 2026-07-01 — gaps from the "Constrained (tethers)" + movable-link work)

The move/rotate "Constrained (tethers)" drag, the ds-linker **rigid strut** (bilateral), and the **movable-link**
duplex-swing were all shipped this session, but their SOLVERS live only in the gizmo's live drag
(`cluster_gizmo.js` `_projectSsdnaConstraints` / `_solveLinksChain`) — there is NO headless entry point that
*computes* a constrained drag, so every one of these can be validated ONLY by a human-eye WebGL drag
(`manual_validation_debt.md` MV-CONNTETHER / MV-CONNLINK / MV-MRSEL). The DESCRIPTORS are already headless +
tested (`cluster_connection_tethers` / `cluster_movable_links` / `duplex_cluster_tethers` +
`test_connection_tethers.py`); the missing augment is the SOLVE + an oracle. These mirror **AF-29** (which ported
the flexible-relax solver to `flexible_relax.py` + a JS↔Python parity golden) — do the same for the drag projector.

<a id="af-40"></a>
- [ ] **AF-40 — headless constrained-drag solver (free-until-taut + ds rigid-strut) + tether oracle (intake 2026-07-01).**
  The gizmo `_projectSsdnaConstraints` (single-body: pull a dragged cluster back so no tether exceeds its contour,
  PLUS the new `rigid` bilateral case — a ds-linker strut held at its rod length against BOTH compression and
  extension; pure predicate `ssTetherViolated` in `cluster_gizmo.js`) has no headless twin. Add: extend the pure
  `flexible_relax_solver.js` (+ its Python parity `backend/core/flexible_relax.py`) with the `rigid` (bilateral)
  tether case, and a `hb.constrain_cluster_drag(cluster_id, target_translation/rotation)` entry that arms the
  cluster's `cluster_connection_tethers` and returns the projected pose. Oracle `assert_tethers_satisfied(design,
  cluster, pose)`: every free tether chord ≤ contour+tol; every RIGID strut within tol of its length (the
  can-go-red: a compression case a free tether would allow but a strut must reject). Ports the JS `ssTetherViolated`
  bilateral into the shared golden (edit one ⇒ edit the other, like AF-29). **Validation gained:** the ds-strut
  "can't compress OR stretch" and the free-until-taut clamp become headlessly assertable — today only MV-CONNTETHER.
<a id="af-41"></a>
- [ ] **AF-41 — headless movable-link CHAIN solve (duplex swings, partner fixed) + oracle (intake 2026-07-01, depends on AF-40).**
  `_solveLinksChain` (the coupled 2-body Gauss-Seidel: drag part A → each connected duplex LINK body swings to follow
  A while the partner part B stays fixed, then A is re-clamped against the moved link) is JS-only — the entire
  duplex-swing feature is human-eye-only (MV-CONNLINK). Add a headless port that, given a dragged part + its
  `cluster_movable_links` + a target displacement, returns A's constrained pose AND each link body's swung pose
  (reusing the AF-40 solver per body + the same Gauss-Seidel coupling). Oracle `assert_link_chain_settled(before,
  after)`: each link↔part bond ≤ contour+tol on the POSED geometry, the partner part B is unmoved, and A moved but
  stayed within the chain's reach (can-go-red: B drifts, or a bond overstretches). **Validation gained:** the whole
  A↔link↔B chain kinematics gets an oracle; also unblocks automated hinge-with-duplex ROM testing (sibling of the
  AF-27 linker-hinge keystone). **GOTCHA banked:** the link solve must NOT call `relaxClusterHeadless` (clobbers the
  gizmo singletons) — the pure port sidesteps that; and multi-body live paint needs `captureClusterBase(append=true)`
  for the 2nd body (the main-cluster-freeze bug, fixed this session).

#### Fine-routing wrappers (intake 2026-06-26 — the user's "automate ALL fine routing ops" request)

These complete the fine-routing set begun by AF-2 (nick / ligate / delete-strand). Each is a GUI/cadnano-editor
op with a REST route but **no headless wrapper**, so a script can't drive it and there's no regression pin.
All three are **mechanical pass-throughs** — the request body carries explicit coordinates / strand-ids /
signed deltas, so the wrapper forwards them verbatim (it does NOT decide *where* to nick/cross/resize —
`feedback_crossover_no_reasoning`: never reason geometrically about crossover placement). No topology
ASK-FIRST blocker; the directionality is the caller's input. One item per session.

- [x] **AF-30 — strand end-resize wrapper (`hb.resize_strand_end`). SHIPPED 2026-06-26.** Route `POST /design/strand-end-resize`
  (`strand_end_resize`, `StrandEndResizeRequest` → `entries: [{strand_id, helix_id, end: "5p"|"3p",
  delta_bp}]`, `crud.py:2496`; builder `_build_strand_end_resize`). `hb.resize_strand_end(strand_id, helix_id,
  end, delta_bp)` — a single-entry mechanical pass-through (caller supplies the explicit end + signed delta).
  Imports `strand_end_resize`/`StrandEndResizeRequest`/`StrandEndResizeEntry` → covered by identity, coverage
  **47 → 48**. **Augment (NO new oracle — two proven ones REUSED):** (1) `assert_geometric_length_delta` (AF-3) —
  a `+δ` resize of a scaffold whose terminal domain DEFINES its helix extent grows that helix's emitted geometry
  by exactly `δ` bp (one nuc/strand → `δ×2`); the load-bearing pin (catches silent clamp / no-op / wrong-helix /
  dropped inline-overhang split). (2) `assert_inverse_pair` (AF-2) — `+δ` then `−δ` at the same end restores
  `canonical_topology`, with the forward-must-mutate guard. **GOTCHA found & ledgered as ISSUE-13:** the backlog
  assumed the inverse pair is clean from a raw bundle, but `resize_strand_ends`' axis re-trim uses
  `(max_index−min_index)·rise` while `create_bundle` uses `length_bp·rise` (one rise longer), so the FIRST resize
  shifts the helix `axis_end` convention and `canonical_topology` (which fingerprints axis floats) never restores
  — the test captures `start` AFTER one settling resize so both ±δ runs share the re-trim convention.
  The resize itself DOES change the nucleotide count (that is the property the oracle pins); only the ISSUE-13
  *axis-endpoint* off-by-one leaves the count untouched (it shifts where the axis line stops, not `length_bp`),
  which is why the geometric oracle stays clean while the inverse pair breaks. Tests: 3 in
  `test_headless_build.py` + 1 coverage meta-test, coverage-count assertions bumped 47→48 in 3 files. Full suite
  **3231 passed / 61 skipped**. **Validation gained, not just a passthrough:** the length-delta count proves a
  resize moves exactly the requested bp of geometry on exactly the named helix (not a clamp/no-op/wrong-end), and
  the inverse pair proves a `−δ` exactly undoes a `+δ` on the strand bp-range — neither was provable before.

- [x] **AF-31 — manual crossover-PLACE wrapper (`hb.place_crossover`) + crossover-delete inverse. SHIPPED 2026-06-26.**
  `hb.place_crossover(half_a, half_b, nick_bp_a, nick_bp_b)` + `hb.delete_crossover(id)` in `headless_build.py`
  (import the route handlers → covered by identity, coverage **43 → 45**). **Augment:** `assert_crossover_joins`
  (new reusable oracle) — record exists + joins the named half-sites (order-independent) + (ligated) a single
  strand spans both (load-bearing `_strand_spans_both`: catches a record-appended-but-ligate-failed build the
  same-strand `unligated_crossover_ids` set misses) + `validate_design` (ligated only); `expect_ligated=False`
  accepts the recorded-but-unligated cycle-avoidance outcome (validator flags terminus-on-crossover by design →
  gate skipped). PLUS `assert_inverse_pair` REUSED as **delete→place** (NOT place→delete: place adds nicks a
  desplice doesn't undo — see harness gotcha). Tests: 2 in `test_headless_build.py` + 5 in
  `test_automation_harness.py` + 3 coverage-count meta-tests bumped 43→45. Full suite **3220 passed / 61 skipped**.
  Unligated outcome via the route is fiddly to manufacture → its oracle branch is pinned with a hand-built cycle
  fixture (mirror `test_crud._cycle_design`). `place-batch` / `crossovers/move` remain a Phase-2 follow-up.
  <details><summary>original spec</summary>
  Routes
  `POST /design/crossovers/place` (`place_crossover`, `PlaceCrossoverRequest` → `half_a/half_b:
  {helix_id, index, strand}`, `nick_bp_a`, `nick_bp_b`, `crud.py:2971`) and `DELETE
  /design/crossovers/{id}` (`crud.py:3686`). The manual counterpart to the already-wrapped `auto_crossover` —
  a script can auto-route but cannot place a SINGLE named crossover. **CROSSOVER = nick + ligate + record**
  (route docstring: "If changing this, ask user first" — we are NOT changing it, only wrapping). Valid sites
  come from `GET /design/crossovers/valid`; the wrapper takes explicit half-sites (mechanical). **Edge case to
  pin:** the route may leave a crossover *recorded but unligated* (returns `placement_warnings`) when ligating
  would circularize a strand — the oracle must handle the ligated AND the unligated-to-avoid-circular outcome.
  **Augment:** NEW `assert_crossover_joins(design, xover_id, *, half_a, half_b)` — the `Crossover` record exists
  joining the two named half-sites (order-independent), and (when ligated) the strand graph now has a backbone
  crossing between the two helices (a single strand spans both at those bp — visible to `canonical_topology`).
  PLUS inverse-pair: place → delete restores `canonical_topology`. PLUS `validate_design` gate (no unresolved
  nicks). Coverage +2 (`place_crossover` + `delete_crossover`). **Validation gained:** proves the place
  actually merged the backbone at the named sites (not just appended a record), and that delete is its exact
  inverse. NB consider `place-batch` / `crossovers/move` as a Phase-2 follow-up, not this session.
  </details>

- [x] **AF-32 — forced-ligation wrapper (`hb.force_ligate`) + delete inverse. SHIPPED 2026-06-26.** Wrappers
  `hb.force_ligate(three_prime_strand_id, five_prime_strand_id, *, is_periodic_seam=False)` +
  `hb.delete_forced_ligation(fl_id)` in `headless_build.py` (import `forced_ligation`/`delete_forced_ligation` →
  covered by identity, coverage **45 → 47**), documented as the **scripted-manual** entry (NOT an autorouting
  hook). **Augment:** NEW `assert_forced_ligation(before, after, fl_id, *, three_prime_strand_id,
  five_prime_strand_id)` — FL record carries the right re-derived 3'/5' endpoints (3' = last domain of the 3'
  strand, 5' = first domain of the 5' strand → catches a swap or wrong helix/bp) + the two strands merged into one
  (count −1 + AF-31's `_strand_spans_both`) + survives a `.nadoc` round-trip (load-bearing: record lives OFF the
  strand graph, `canonical_topology` blind — same blind-spot as clusters/overhang-connections). PLUS
  `assert_inverse_pair` REUSED as **force-ligate→delete** (CLEAN forward/inverse — forced ligation adds NO nicks,
  unlike AF-31's crossover place). Tests: 2 in `test_headless_build.py` + 5 in `test_automation_harness.py` (incl.
  3 red: missing record / swapped endpoints / not-merged) + coverage meta bumped 45→47. **Unblocks AF-33** (the
  hinge builder's 2N cross-gap FL links).
  <details><summary>original spec</summary>Routes `POST
  /design/forced-ligation` (`forced_ligation`, `ForcedLigationRequest` → `three_prime_strand_id`,
  `five_prime_strand_id`, `is_periodic_seam`, `crud.py:4111`) and `DELETE /design/forced-ligations/{id}`
  (splits the merged strand back, `crud.py:4172`). Connects ANY 3′ end to ANY 5′ end bypassing the crossover
  lookup tables → ONE multi-domain strand + a `ForcedLigation` record. **Manual-only op** (route docstring:
  "must never be called by autocrossover/autobreak/any automated pipeline") — the headless wrapper is the
  *scripted-manual* entry, NOT an autorouting hook; document that in the wrapper docstring. See
  `memory/project_forced_ligation.md`. **Three-layer:** topological edit (merges two strands) — allowed.
  **Augment:** NEW `assert_forced_ligation(design, fl_id, *, three_prime_strand, five_prime_strand)` — the
  `ForcedLigation` record carries the right 3′/5′ endpoints AND the two strands merged into one
  (strand count −1, merged strand spans both domains), AND it **survives a `.nadoc` round-trip** (the
  load-bearing pin: the FL record lives on `design.forced_ligations`, OFF the strand graph — same blind-spot as
  clusters/overhang-connections, so only re-reading after export→import proves the record persisted). PLUS
  inverse-pair: force-ligate → delete splits back to `canonical_topology`. Coverage +2 (`forced_ligation` +
  `delete_forced_ligation`). **Validation gained:** proves the merge wired the named endpoints, the record
  persists across save/load (canonical_topology can't see it), and delete is the exact split-back inverse.
  </details>

### Tier 2 — deformation by constraint (gizmo-only construction → programmatic; known three-layer-bug area)

- [x] **AF-6 — `add_bend` / `add_twist` by constraint** wrapping the `addDeformation` REST path.
  SHIPPED 2026-06-17. `hb.add_bend(a, b, *, curvature_deg_per_bp, direction_deg)` +
  `hb.add_twist(a, b, *, total_degrees | degrees_per_nm)` (import `add_deformation` → covered by identity).
  **Augment:** `assert_deformation_angle` (new reusable oracle) — walks the deformed frame in 1-bp steps
  and SUMS each step's relative-rotation magnitude (unwraps past 180°/360°: a 540° twist reads 540°),
  asserting the total = κ×(b−a) for a bend / the total twist, plus a can-go-red guard (fails on an
  un-deformed design). **Direction-AGNOSTIC** (magnitude only → no ASK-FIRST sign/frame reasoning needed;
  the signed-curvature oracle the backlog floated was *not* built, deliberately). Coverage 18→19.

- [x] **AF-14 — geometry-aware revolute-joint placement on hull-prism corners/edges. ALL 3 PHASES SHIPPED (P1 2026-06-17, P2 2026-06-17, P3 2026-06-18 — see sub-items).** (route
  `POST /design/cluster/{cluster_id}/joint`, handler `add_joint` in `routes_cluster_joints.py`; currently
  gizmo-only — the user clicks a face on the cluster's hull-surface approximation, the frontend computes a
  world axis, the route converts it to the cluster's LOCAL frame). **No headless wrapper exists** → uncovered.
  Three-layer note: a `ClusterJoint` is a **topological/design-layer** intent (which rigid cluster rotates
  about what axis) — placing one is an allowed write; the hull prism, the OBB, and the range-of-motion (ROM)
  math are all **geometric reads** and never write back (clean Three-Layer; mirrors how AF-6 deformation reads
  the frame). Multi-phase — one phase per session.

  **The kinematic-design framing (this is the point — it's why "face corners" is the right primitive).**
  A revolute joint is a hinge: a rigid cluster M swings about an axis line relative to the static rest of the
  design. What a designer actually wants to pick is *which hinge gives the desired free swing without M
  colliding into a neighbouring cluster*. The hull prism **is the cluster's oriented bounding box (OBB)**, so
  its faces/edges/corners are the natural discretised anchor set, and the relevant mechanical principles are:
  - **The hinge axis belongs on the contact interface (the door-jamb principle).** Co-locating the axis with
    the *edge of M's OBB that lies against the neighbour* maximises ROM: M rotates immediately *away* from the
    obstacle instead of swinging *into* it. An axis through M's interior (or the far edge) collides almost
    at once. So the high-value candidates are the OBB **edges on the face adjacent to the obstacle**.
  - **For a revolute joint the primitive is an EDGE (a corner→corner pair); for a ball/point joint it's a
    CORNER.** "Face corners" enumerates both: the 8 corners give point pivots; corner-pairs give the 12
    candidate hinge edges. The axis *direction* is the edge's line (typically perpendicular to the helix axis
    = a fold; parallel = a barrel-roll — usually not what's wanted).
  - **ROM is a swept-collision root-find.** Rotating M about axis a sweeps every point p on a circle of radius
    `r = dist(p, a)`; first contact is driven by the point of M **farthest from a on the obstacle side** (the
    instantaneous-centre / largest-swing-radius point). Because both M and every obstacle are OBBs, the swept
    interference is exact and cheap: **bisect θ on OBB–OBB separation (SAT) to find θ⁺ and θ⁻**, and
    `ROM(a) = θ⁺ + θ⁻` (clamped to the joint's `min/max_angle_deg` limits), checked against **all** other
    clusters, not just the nearest. This is the discretised collision-free workspace of a 1-DOF joint.
  - Connects to the **AF-12 hinge-primitive / 4-bar-linkage** discussion: a multi-joint mechanism's mobility
    (Grübler) and ROM both depend on these corner/edge choices; AF-14 is the per-joint geometry the linkage
    layer will compose.

  **Feasibility blocker to settle first (do this in Phase 1):** the hull-prism OBB is currently computed in
  **JS** (`frontend/src/scene/joint_renderer.js` — `_bundleGeometry`/`_buildExtrusionBoxes`), NOT Python, so a
  headless ROM oracle needs a backend OBB. Build it from the geometry kernel (`_geometry_for_design` →
  per-cluster nucleotide positions → PCA/bundle-frame OBB), as a NEW pure `backend/core/cluster_obb.py`
  (service+oracle shape, rule 3; `backend/core` imports nothing from `backend/api`). Pin it for parity against
  the JS extents on a shared fixture so the headless corner set matches what the user sees.

  - [x] **Phase 1 — `hb.place_cluster_joint` + corner/edge resolver + on-corner oracle. SHIPPED 2026-06-17.**
    Wrapper in `headless_build.py` importing `add_joint` (covered by identity) + `AddJointBody`. The pure helper
    `hull_prism_axis(design, cluster_id, *, edge=(axis,s1,s2) | corner=(su,sv,sw)+face=(axis,sign))
    → (axis_origin, axis_direction)` in `cluster_obb.py` turns a named OBB edge/corner into the world axis the
    route expects (edge = revolute hinge ALONG the edge: origin=midpoint, dir=edge line; corner = point pivot AT
    the corner, dir=face normal). **Augment:** `assert_joint_on_hull_corner(design, joint_id, *, edge|corner,
    face, tol_nm, tol_deg)` — re-derives the joint world axis from its LOCAL storage via `_local_to_world_joint`
    + the cluster's current pose, recomputes the OBB independently, asserts the axis is collinear with the named
    edge / passes through the named corner. Direction-AGNOSTIC. Coverage **34 → 35** (`add_joint` — first flip
    since AF-15 P1). Tests: 7 in `test_cluster_obb.py` + 5 in `test_automation_harness.py` (incl. a posed-cluster
    local-frame round-trip test + 2 load-bearing red-tests).
  - [x] **Phase 2 — `cluster_range_of_motion` + `rank_joint_candidates` (the geometry-aware selector).
    SHIPPED 2026-06-17.** Pure swept OBB–OBB SAT (`_obb_intersect`, Ericson 15-axis) + per-step scan +
    bisection in `cluster_obb.py`: `obb_sweep_rom(moving, obstacles, axis_origin, axis_dir, *, min_deg,
    max_deg, pad, step_deg)` (on OBBs) → `cluster_range_of_motion(design, cluster_id, axis, *, obstacles=None,
    min_angle_deg, max_angle_deg, pad=HELIX_RADIUS, step_deg)` (anchored cluster swings, others static) →
    `rank_joint_candidates(design, cluster_id, *, target_rom_deg=None)` ranks the 12 OBB **edges** (corners are
    3-DOF ball pivots — single swing angle ill-defined — deliberately not ranked). **Augment:**
    `assert_range_of_motion(design, cluster_id, axis, expected_deg, *, tol_deg, …)` in `automation_harness.py`.
    **ASK-FIRST decisions (user, 2026-06-17):** anchored cluster is the moving body / all others static; ROM =
    **total two-sided magnitude** (θ⁺+θ⁻, each clamped to the limit) → direction-AGNOSTIC, no handedness; OBBs
    **padded by the helix radius** (~1 nm) so contact is rim-to-rim. Analytic precision proved on a SYNTHETIC
    rod+double-wall fixture (closed-form `2·(asin(Y0/√(L²+w²))−atan2(w,L))`, an independent derivation, tol 1°);
    the two can-go-red guards proved on real bars (no-obstacle → full 360°/limit; a neighbour in the path
    strictly reduces ROM, monotonic with the gap). Coverage **35 → 35** (composition over the already-covered
    `add_joint`/`update_cluster` — wraps no new route; the oracle is the deliverable). 10 new tests.
  - [x] **Phase 3 — edge-mapping joint recommender (`recommend_hinge_joints`) + corner anchoring.
    SHIPPED 2026-06-18.** `recommend_hinge_joints(design, cluster_id, *, anchor="corner", axial_tol_deg=20,
    target_rom_deg=None)` in `cluster_obb.py` ranks ALL 12 OBB edges by the user-fixed priority below
    (non-axial first → longest edge → ROM tiebreak), returning each annotated `{edge, edge_length,
    angle_to_axis_deg, is_axial, rom_deg, axis_origin, axis_direction}`; `axis_origin` is corner-anchored.
    `hull_prism_axis` + `place_cluster_joint` gained `anchor="midpoint"|"corner"` (default midpoint =
    backward-compatible; corner stores the edge's `−axis` endpoint — same hinge line). **Augment:**
    `assert_recommended_hinge` (new reusable oracle, re-measures on the independent equivariant OBB) — pins the
    #1 hinge is non-axial + the longest non-axial edge + corner-anchored, with 2 load-bearing red-tests
    (axial-on-top, midpoint-anchor). Coverage **35 → 35** (pure selector; the anchor reuses the already-covered
    `add_joint` route). Tests: 7 in `test_cluster_obb.py` + 3 harness meta-tests; full suite **2523 passed /
    55 skipped**. NB the capstone's 4-bar hinged on the axial `w`-edge (a barrel-roll); a follow-up could
    re-point `build_parallelogram` at the recommended cross-section edge.

    <details><summary>original Phase-3 spec</summary>
    Surface
    headlessly the **most-likely hinge-joint candidates** as an edge mapping: for each cluster, enumerate the OBB
    edges and rank them by the **user-fixed hinge-recommendation priority (2026-06-18, takes precedence over the
    Phase-2 ROM-only sort)**:
      1. **Hinge edge = the largest edge that is NOT parallel to the helical axis.** The OBB `w` axis IS the
         helical/bundle axis, so its 4 long edges (`("w", …)`) are *excluded* — hinging about them is a
         barrel-roll, not a fold. Among the remaining cross-section edges (`("u", …)` / `("v", …)`), prefer the
         **longest** (for a 3×6 bar the `u` edge — the wide cross-section — beats the `v` edge). ROM stays a
         secondary tiebreaker (the Phase-2 door-jamb sort), not the primary key.
      2. **Anchor joints at face corners, NOT edge midpoints.** `hull_prism_axis` edge mode currently sets
         `origin = edge midpoint`; the recommender must place the joint's anchor at a **face corner** (an edge
         endpoint) instead. The revolute axis *line* runs along the chosen edge as before — corner vs. midpoint
         only moves the stored anchor point — but the convention is corner-anchored. (Decide whether this is a new
         `anchor="corner"` option on `hull_prism_axis`/`place_cluster_joint`, or the recommender returns the
         corner explicitly; corner mode's `corner=(su,sv,sw)+face` storage may suffice with `direction` overridden
         to the edge line — settle when building.)
    **Augment:** `assert_recommended_hinge(design, cluster_id, …)` — the top recommendation is a non-axial edge
    (angle to `w` > tol), is the longest such edge, and the placed joint is corner-anchored; can-go-red on a
    design where an axial `w`-edge is (wrongly) returned first or the anchor is the midpoint. Reuses the
    equivariant OBB + `rank_joint_candidates`. **NB this revises the capstone's choice** (the 4-bar used the
    axial `w`-edge as the hinge — a barrel-roll); the new rule prefers a cross-section fold edge, so the
    parallelogram builder/oracle may want a follow-up pass to use the recommended edge.
    </details>

- [x] **AF-16 — headless cluster creation + a loggable cluster-create feature-log entry. SHIPPED 2026-06-18.**
  NEW `ClusterCreateLogEntry` Pydantic model in `backend/core/models.py` (mirrors `ClusterOpLogEntry`:
  `cluster_id`/`name`/`helix_ids`/`domain_ids`) added to the `FeatureLogEntry` union; `add_cluster` route gained an
  opt-in `log: bool = False` that appends the entry with the same cursor-truncation discipline `update_cluster`
  uses; `hb.add_cluster(..., log=False)` gained the passthrough (default off — backward-compatible, the capstone +
  all existing tests don't log). **Augment:** `assert_cluster_in_feature_log(design, cluster_id, *,
  expect_helix_ids=None)` — the `cluster_create` entry exists, names the cluster's exact helix set + name; call it
  on a `roundtrip_nadoc` result to prove the grouping survived `.nadoc` save/load (canonical_topology is blind to
  clusters — the entry is the only proof of persistence). Coverage **35 → 35** (`add_cluster` already covered since
  AF-15 P1 — this adds the log path, not a new route). Tests: 3 in `test_headless_build.py` + 3 harness meta-tests
  (incl. 2 load-bearing red-tests: unlogged build leaves no entry; wrong helix set raises). Full suite **2529
  passed / 55 skipped**. The generated 4-bar part's feature log is now completable — the cluster-creation step is
  representable. **The gap (found 2026-06-17 while generating the 4-bar part):** `add_cluster` creates the cluster in
  design state but emits **no feature-log entry** — there is no `ClusterCreateLogEntry` type (the log has
  `cluster_op` for translate/rotate, but nothing for *grouping helices into a bar*). So a design's feature log
  cannot record "create the 4 bars," and the construction history is incomplete: a user replaying the log sees the
  bundle + the transforms + the joints (minor mutations under "Fine Routing") but not the cluster creation. Closing
  this means (a) a NEW `ClusterCreateLogEntry` Pydantic model in `backend/core/models.py` added to the
  `FeatureLogEntry` union (mirror `ClusterOpLogEntry`: `cluster_id`, `name`, `helix_ids`, `domain_ids`), (b) wiring
  `add_cluster`'s route to append it (with the same `commit`/`log` discipline `update_cluster` uses), and (c) the
  `hb.add_cluster` wrapper gaining a `log=` passthrough. **Three-layer note:** creating a cluster is a
  display/geometry-layer grouping (it never touches the strand graph), exactly like `cluster_op` — clean.
  **Augment:** `assert_cluster_in_feature_log(design, cluster_id)` — after a logged `add_cluster`, the feature log
  carries a `cluster_create` entry naming that cluster + its exact helix set, and it survives a `.nadoc`
  round-trip (canonical_topology is blind to clusters, so the feature-log entry is what proves the grouping
  persisted — same shape as the AF-3 loop/skip / AF-6 deformation blind-spot lesson). Can-go-red: a build that
  creates a cluster *without* logging leaves no entry. **This is what makes the generated 4-bar part's feature log
  truly complete** (today its cluster-creation step is unrepresentable).

- [x] **AF-15 — cluster rigid-transform wrapper + OBB-edge-alignment solver. BOTH PHASES + 4-BAR CAPSTONE SHIPPED 2026-06-17 (see sub-items).** (routes `POST /design/cluster`
  = `add_cluster`, `PATCH /design/cluster/{cluster_id}` = `update_cluster` in `routes_clusters.py`; both
  uncovered). **Sequences BEFORE AF-14 Phase 2 and the linkage demo** — you arrange the rigid bars, *then*
  hinge them. This is the design-layer analog of the AF-8 assembly connector-mate, but driven by **OBB edges**
  instead of named connectors. Three-layer note (load-bearing, and clean here): a `ClusterRigidTransform` is a
  **DISPLAY/geometric pose — it never mutates topology** (stated at `routes_clusters.py:8`). So aligning two
  bars edge-to-edge *reposes rigid bodies*; the DNA strand graph of each bar is untouched. The articulated
  arrangement (poses) + AF-14 joints (kinematic intent) together describe the mechanism without ever editing
  the bars' topology — the three-layer law made concrete for a mechanism. **Shares `backend/core/cluster_obb.py`
  with AF-14** (whichever lands first builds it; the OBB corner/edge enumerator is the common foundation).

  **What the user wants automated (the parallelogram 4-bar linkage, at the part-design level):** four rigid
  bars → arranged into a parallelogram → hinged at the four corners → a working 1-DOF mechanism, all in ONE
  `Design` (4 clusters + 4 `ClusterJoint`s), no assembly layer. The pieces:
  - **Extrude the bars — ALREADY AUTOMATABLE.** `hb.create_bundle` / `hb.extrude` (and the AF-11 `bundle` /
    `extrude` build-spec ops) build the bar bundles today. AF-15 does NOT re-do this.
  - **Cluster each bar — NEW.** `hb.add_cluster(name, helix_ids, domain_ids=…)` wraps `add_cluster` (covered
    by identity).
  - **Pose each bar — NEW.** `hb.transform_cluster(cluster_id, *, translation, rotation_quat, pivot)` wraps
    `update_cluster` (covered). Low-level; takes an explicit rigid transform.
  - **Align by OBB edge — NEW, the high-value piece.** A pure solver
    `align_edge_transform(design, cluster_id, src_edge, target_edge|target_line) → (R, T, pivot)` in
    `cluster_obb.py` computes the rigid transform that brings cluster M's chosen OBB edge onto a target edge
    (another cluster's OBB edge, or a world line), then drives `transform_cluster`. Composing four of these is
    the parallelogram arrangement.

  **Augment (Phase split — one per session):**
  - [x] **Phase 1 — cluster create/transform wrappers + round-trip pin. SHIPPED 2026-06-17.**
    `hb.add_cluster(name, helix_ids, *, domain_ids=())` + `hb.transform_cluster(cluster_id, *, translation,
    rotation, pivot, commit=True, log=False)` (import `add_cluster`/`update_cluster` → covered by identity).
    **VERIFIED `canonical_topology` IS blind to the cluster pose** (it fingerprints helices by `axis_start` +
    strands; cluster_transforms aren't in it — the AF-3 loop/skip / AF-6 deformation blind-spot confirmed for a
    third overlay), so `assert_roundtrip_stable` is necessary-but-NOT-load-bearing for the pose. The load-bearing
    augment is the NEW geometric oracle `assert_cluster_translated(before, after, cluster_id, *, translation)` —
    it reads the cluster-posed helix axes via `deformed_helix_axes` and asserts (1) every cluster helix's
    `start`/`end` shifted by exactly the translation, (2) only the cluster moved (non-cluster helices unchanged),
    (3) `‖T‖ > min` can-go-red guard. **Direction-AGNOSTIC** (a pure world-space translation, no quaternion/pivot
    convention → ASK-FIRST-safe; **rotation poses deliberately out of scope** — they ARE a directionality question,
    deferred to Phase 2's edge-alignment flip/snap). Coverage **32 → 34** (`add_cluster` + `update_cluster`).
    **`cluster_obb.py` was NOT built** — Phase 1 needs no OBB (a translation oracle reads posed axes directly);
    the OBB enumerator is first needed by Phase 2's `align_edge_transform` + AF-14's ROM.
  - [x] **Phase 2 — `align_edge_transform` solver + alignment oracle. SHIPPED 2026-06-17.**
    NEW pure core `backend/core/cluster_obb.py` (the **equivariant OBB enumerator** — corners/edges keyed
    `(axis, s1, s2)` — built from posed helix axes via a PCA cross-section frame, NOT
    `_initial_cross_section_frame` which snaps to world axes and would not track a posed cluster; + the pure
    `align_edge_transform` solver) + the `hb.align_cluster_edge` wrapper driving `transform_cluster` (coverage
    UNCHANGED 34 — wraps no new route) + the reusable `assert_edges_collinear` oracle. **ASK-FIRST conventions
    confirmed with the user (2026-06-17): minimal rotation / auto-flip (≤90° onto ±target_dir) / midpoint snap
    (endpoints coincide) / roll left free.** The load-bearing pin proved equivariance
    (`OBB(g·design)=g·OBB(design)`) — the property that makes an edge key refer to the same physical edge before
    and after the solve. Tests: `tests/test_cluster_obb.py` (11) + 4 harness meta-tests. **`cluster_obb.py` is now
    the shared foundation AF-14 reuses** (the OBB enumerator + a future swept-OBB SAT for ROM).
    `assert_edges_collinear(design, cluster_id, src_edge, target_edge, *, tol_nm, tol_deg)` — after the solved
    transform the two OBB edges are **collinear** (shared line: angle between directions ≈ 0/180° AND
    perpendicular distance < tol), with a can-go-red guard (the pre-align edges are skew/separated, so a no-op
    solver fails). Collinearity is **direction-AGNOSTIC** (a line, not a ray). **The capstone integration test
    SHIPPED 2026-06-17** (`tests/test_parallelogram_linkage.py` + `grubler_mobility` in `cluster_obb.py` +
    `assert_parallelogram_linkage` in `automation_harness.py`): the **4-bar parallelogram built headlessly** —
    extrude 4 bars, cluster + edge-align into a rhombus (adjacent bars share an OBB corner), place 4 revolute
    joints on the shared side-edges — and assert it's a closed, parallel, Grübler-1-DOF linkage with every hinge
    movable. The first headless **kinematic mechanism** and the AF-12 linkage-mobility demo; the Tier-2 arc is
    complete.

### Tier 3 — headless ASSEMBLY builder (biggest construction gap; multi-phase, `headless_assembly_build.py`)

- [x] **AF-7 (Phase 1) — assembly scratch-session + `add_instance(source, transform)` + save/validate.**
  SHIPPED 2026-06-17. NEW module `backend/api/headless_assembly_build.py` mirroring `headless_build.py`:
  `assembly_scratch_session()` + `new_assembly` + `add_inline_instance` / `add_file_instance` / `add_instance`
  (imports `create_assembly` / `add_instance` / `resolve_assembly` / `import_assembly` route handlers → covered
  by function identity) + `resolve()` + `translation()` helper. **Augment:** `assert_assembly_roundtrip_stable`
  (new reusable oracle) + `canonical_assembly` fingerprint + `roundtrip_nass` in `automation_harness.py` — build
  → `.nass` export (`to_json` v2) → real `POST /assembly/import` → `validate_assembly_report` passes both sides
  AND id/order-independent fingerprint (inline source → embedded design's `canonical_topology`; file → path+sha;
  + per-instance transform/mode/rep/fixed/visible; + joints for AF-8) is unchanged. In-memory (inline parts
  travel inside the payload, no disk) — the assembly analog of `roundtrip_nadoc`'s import path, NOT file save/load.
  Coverage 19→23 (create + add-instance + resolve + import all flip). `headless_coverage_report` now scans both
  `headless_build` AND `headless_assembly_build`.
- [x] **AF-8 (Phase 2) — headless mate/joint by connector labels.** SHIPPED 2026-06-17.
  `hab.add_connector(inst, label, position, normal)` (imports `add_connector` route → covered) +
  `hab.define_mate(child, parent, *, child_label, parent_label, joint_type="rigid")` (imports `create_mate`
  → covered); the route snaps the child so its connector meets the parent's (no FK transform passed — the
  connector-derived snap aligns the parts). **Augment:** `assert_mate_coincident` (new reusable oracle) —
  the two mated connectors are coincident in world space (via the SAME `_get_connector_world` machinery
  resolve uses) within tol, plus a non-triviality guard (mated part origins must be separated, else
  coincidence is vacuous). Also enriched `canonical_assembly`'s joint key with the mated parts' source
  fingerprints (id-independent). Coverage 23→25.
- [x] **AF-9 (Phase 3) — gears / belts / overhang-bindings / polymerize wrappers. ALL 4 SUB-OPS SHIPPED 2026-06-17; only the `polymerize_periodic` straggler remains (sub-item below).** Multi-op; one sub-op
  per session. **Augment:** each resolve-invariant (gear ratio holds, belt tangent length, polymerized chain
  count + seam geometry via `derive_periodic_delta`).
  - [x] **gears — SHIPPED 2026-06-17.** `hab.define_gear(joint_a_id, joint_b_id, *, ratio, invert=…)`
    (imports `create_gear_relation`) + `hab.drive_joint(joint_id, value, *, endpoint_side=…)` (imports
    `patch_joint`; PATCH auto-propagates the gear, path 1). **Augment:** `assert_gear_ratio(before, after,
    rel_id, *, expected_ratio)` — measures the two coupled bodies' real *instance-transform* rotation
    magnitudes after driving one side, asserts driven/driver = |ratio| (NOT a re-test of `current_value`),
    with a can-go-red "driver actually moved" guard. Direction-agnostic (magnitude only). Also enriched
    `canonical_assembly` to fingerprint `gear_relations` (keyed by the coupled joints' id-independent
    fingerprints + ratio/invert/anchors) so the round-trip oracle now catches a dropped/rewired gear.
    Coverage 25→27.
  - [x] **belts — SHIPPED 2026-06-17.** `hab.define_belt(joint_a_id, joint_b_id, *, radius_a, radius_b, …)`
    (imports `create_belt_path` + `CreateBeltPathRequest`/`BeltPulleyRequest` from `routes_assembly_belts`).
    **Augment:** generalised `assert_gear_ratio` to search `_coupling_relations` (gears + belt-derived) so a
    belt pins with the SAME oracle — pass `rel_id=f"__belt__{belt.id}"` + `expected_ratio = radius_a/radius_b`;
    it proves `_belt_to_relation`'s radius→ratio synthesis actually drives the coupled pulley (NOT a hand-passed
    gear ratio). Also extended `canonical_assembly` to fingerprint `belt_paths` (now a **4-tuple**). Coverage 27→28.
  - [x] **polymerize (mate-seeded) — SHIPPED 2026-06-17.** `hab.polymerize(joint_id, count, *,
    direction="forward", additional_instance_ids=…)` (imports `polymerize_assembly` +
    `PolymerizeAssemblyRequest` from `routes_assembly_polymerize`). **Augment:**
    `assert_polymer_chain(before, after, seed_joint_id, *, count, direction)` — re-derives the seed mate's
    repeat `delta = T_B @ inv(T_A)` from the seed pair ALONE (not the route's chain helpers) and asserts
    the `count−2` new copies form the exact `delta`-power multiset (`delta^k @ T_B` fwd / `inv(delta)^k @ T_A`
    back), id-independent, within tol — plus a can-go-red guard that `delta`'s translation > 0.5 nm (stacked
    seed → vacuous). `canonical_assembly` already fingerprints instances+joints, so the round-trip oracle
    catches a dropped copy/joint with no extension needed. Coverage 28→29.
  - [x] **overhang-bindings — SHIPPED 2026-06-17.** `hab.bind_overhangs` / `hab.patch_binding` /
    `hab.unbind_overhangs` (import `create_/patch_/delete_assembly_overhang_binding` + the two request models
    from `routes_assembly_overhangs` — covered by function identity). **Augment:** `assert_binding_resolves`
    (new reusable oracle) — a cross-part binding's two endpoints each resolve to a real overhang sub-domain on
    their part design (loaded via the route's own `_load_design_from_source`), with a non-degenerate guard
    (distinct endpoints + cross-part). Genuinely new power: `canonical_topology` does NOT fingerprint a design's
    overhangs/sub-domains, so a round-trip that regenerated a sub-domain id while the binding kept its stale ref
    would slip past `canonical_assembly` — only resolving against the actual designs catches it. Also extended
    `canonical_assembly` to fingerprint `overhang_bindings` (now a **5-tuple**). Coverage 29→32.
  - [x] **periodic polymerize — SHIPPED 2026-06-22.** `hab.polymerize_periodic(instance_id, count, *,
    direction)` wraps `POST /assembly/polymerize-periodic` (flips `polymerize_periodic_assembly` → covered,
    36→37). Fixture turned out light: a 2-helix HC bundle + two `_seam_for` `is_periodic_seam` ligations
    (mirrors `test_periodic_polymer.py`). Oracle NEW `assert_periodic_chain_tiles` — the derived repeat unit
    tiles seamlessly at EVERY rigid seam junction (3p↔5p coincidence via `_get_connector_world`) AND is a
    single repeating unit (constant step length + rotation, magnitude-only → direction-agnostic) + a
    non-vacuity step>min guard. Distinct from `assert_polymer_chain` (mate-seeded, re-derives delta from two
    instances): here the delta is auto-derived from ONE part's seam geometry.
- [x] **AF-10 — instance layout helpers** (grid / ring placement) for parametric assembly gen.
  SHIPPED 2026-06-17. NEW pure core `backend/core/instance_layout.py` (`grid_translations` /
  `ring_translations` — spec→world translations, identity orientation; mirrors `circle_primitive`) +
  `hab.place_grid` / `hab.place_ring` (construction sugar over the already-covered `add_instance` — they
  wrap NO new route, so headless-coverage is unchanged at 32). **Augment:** `assert_instances_on_grid` /
  `assert_instances_on_ring` (new reusable oracles) — read the *placed* instance origins and assert the
  lattice as PROPERTIES re-derived from the user-facing params (count exact, even spacing == pitch / every
  cell filled; on-ring radius exact + angular step == 360°/n), not by re-running the placement formula, each
  with a non-degeneracy guard (the ring's `radius>0` guard is load-bearing — radius=0 stacks every part where
  `dist==radius==0` passes vacuously). Radial-facing/rotated layouts deferred (orientation convention =
  ASK-FIRST). Coverage 32→32.

### Tier 4 — text-to-DNA-origami groundwork (the eventual goal; built ON the validated wrapper library)

- [x] **AF-11 (Phase 1) — declarative build-spec interpreter.** SHIPPED 2026-06-17. Pure grammar/parser
  `backend/core/build_spec.py` (`parse_design_spec` / `parse_assembly_spec` → ordered `BuildOp` list; full
  grammar + referential-integrity validation, NO execution) + driver `backend/api/headless_spec_build.py`
  (`build_design` / `build_assembly` dispatch each parsed op to the REAL existing wrappers — re-implements
  nothing). Grammar: design `{bundle, extrude, nick, ligate}` (helices referenced by `grid_pos`), assembly
  `{add_part, place_grid, place_ring, mate}` (parts = a named library of nested design specs; instances by
  spec `ref`; nested part designs built via `build_design`). **Augment:** `assert_spec_matches_calls` (new
  reusable oracle) — a spec builds the SAME `canonical_topology`/`canonical_assembly` as the equivalent
  hand-call wrapper sequence (the faithful-façade / golden-pin guarantee), + reuse of
  `assert_roundtrip_stable` / `assert_assembly_roundtrip_stable` per spec. Coverage 32→32 (wraps no new
  route — composition sugar, like AF-10). *Phase 2 grammar growth (one cluster per session): **`bend`/`twist`
  SHIPPED 2026-06-17** (drive `hb.add_bend`/`add_twist`; pinned by `assert_deformation_angle`, NOT
  `assert_spec_matches_calls` — the canonical fingerprint is blind to a deformation overlay). **`loop_skip`
  SHIPPED 2026-06-17** (drive `hb.loop_skip`; helix by `grid_pos`; `delta ∈ {-1,0,+1}` parse gate; pinned by the
  geometric `geometric_nucleotide_count`, NOT `assert_spec_matches_calls` — canonical is blind to a loop/skip mark
  too. Sibling `apply_loop_skips` DEFERRED: its route needs crossovers the grammar can't yet produce → rides with
  the auto-scaffold cluster). **`circle_segment` SHIPPED 2026-06-17** (primordial design op — may be FIRST, builds
  its own helices; requires a `square` lattice, enforced at parse time; drives `hb.circle_segment(radius_nm)`.
  Pinned by BOTH `assert_spec_matches_calls` — LOAD-BEARING here, circle ADDS real strands so canonical_topology
  sees it — AND the geometric `assert_circular_disc` from AF-4 as the radius→geometry pin). **`gear` SHIPPED
  2026-06-17** (assembly relations cluster — first sub-op; drives `hab.define_gear` over two revolute mate-joints
  referenced by a NEW joint-`ref` namespace added to the `mate` op; pinned by BOTH `assert_spec_matches_calls` —
  load-bearing, gears ARE fingerprinted in `canonical_assembly` since AF-9 — AND the kinematic `assert_gear_ratio`,
  which catches the orthogonal failure the fingerprint can't: a gear that's structurally present but fails to
  *drive* its coupled body. Parser also rejects gear-over-rigid + dangling joint refs at parse time). **`belt`
  SHIPPED 2026-06-17** (relations cluster, second sub-op; reuses the gear's joint-`ref` namespace verbatim by
  widening the revolute-ref check to `op in ("gear","belt")`; drives `hab.define_belt`; pinned by BOTH
  `assert_spec_matches_calls` — load-bearing, belts ARE fingerprinted in `canonical_assembly` since AF-9 — AND
  `assert_gear_ratio` handed `f"__belt__{belt.id}"` + `expected_ratio = radius_a/radius_b`, passing the *radii* so it
  pins `_belt_to_relation`'s radius→ratio synthesis distinctly from the gear test). Remaining:
  polymerize/overhang-bindings (assembly, each like gear) + auto-scaffold/full-autostaple (design) — each a
  tiny dispatch entry over an existing wrapper, oracle picked by what the op changes.*

- [~] **AF-12 — build from primitives (catalog/file-backed parts in the build-spec).** **Phase 1 (`from_file`)
  SHIPPED 2026-06-22** — an assembly spec's `parts` library may now reference a saved validated `.nadoc` **by path**:
  `"parts": {"hinge": {"from_file": "<path>"}}`. The pure parser (`build_spec._parse_part`/`FilePart`) discriminates a
  file part from an inline design spec by the `from_file` key, validates it (non-empty string path, no extra keys), and
  restricts file parts to `add_part` placement (place_grid/place_ring instance an inline design per slot → rejected at
  parse time). The interpreter (`headless_spec_build._build_assembly_from_parsed`/`_run_assembly_op`) lowers a file part
  to `hab.add_file_instance(path)` (the validated design travels as a REFERENCE, not an embedded copy) — wraps no new
  route (`add_file_instance` already existed → coverage flat at 36). **Oracle = NEW `assert_part_from_file(assembly,
  instance_id, expected_topology)`** — loads the design the instance actually references (via the route's
  `_load_design_from_source`) and asserts its `canonical_topology` equals the saved primitive's. **Load-bearing because
  `canonical_assembly` keys a file source by `("file", path, sha256)` ONLY and never loads the design** — so
  `assert_spec_matches_calls` catches a dropped/wrong-path `from_file` but is BLIND to whether the path resolves to the
  INTENDED validated topology; only this oracle catches a stale/edited/wrong-path primitive silently substituting. 10
  tests (test_build_spec: 1 parse + 5 reject; test_headless_spec_build: 1 augment + 2 can-go-red + 1 roundtrip).
  **Follow-up (file-backed `place_grid`/`place_ring`) SHIPPED 2026-06-22** — a file part may now be placed by
  `place_grid`/`place_ring` (not only `add_part`): the parse-time rejection is removed, the interpreter dispatches a
  file part to NEW `hab.place_file_grid(path, rows, cols, …)` / `hab.place_file_ring(path, n, …)` (loop
  `add_file_instance` with the same per-slot `grid_translations`/`ring_translations` — so the validated `.nadoc`
  travels as one path reference per copy, not rows·cols embedded designs). **Oracle = NEW `assert_instances_from_file(
  assembly, expected_topology, *, instance_ids=None)`** — the layout-AGNOSTIC source pin: it LOADS the design behind
  EVERY selected slot and asserts each is file-backed and resolves to the saved primitive's `canonical_topology`. It
  composes with `assert_instances_on_grid`/`_on_ring` (which pin the lattice but never load the design) to fully pin a
  file-backed layout; the plural of `assert_part_from_file` (a one-slot check misses a layout that file-backed only
  slot 0 and embedded inline copies for the rest). Coverage flat (no new route). Net +9 tests (test_build_spec: 2 accept
  replacing 2 deleted rejects; test_headless_assembly_build: 3 wrapper; test_headless_spec_build: 3 spec + 3 can-go-red).
  **Phase 2
  (`from_primitive` — catalog-by-name, STATIC catalog primitives) SHIPPED 2026-06-22:** an assembly spec's `parts`
  library may reference a curated catalog primitive **by name** — `"parts": {"beam": {"from_primitive": "6hb_primitive"}}`
  — the same name the "Add Primitive" UI shows. The pure parser (`build_spec._parse_part`/`PrimitivePart` +
  `_PRIMITIVE_PART_KEYS`) discriminates a `from_primitive` part from a `from_file` part and an inline spec; the
  interpreter (`headless_spec_build._resolve_primitive_path`) resolves the NAME → the catalog primitive's `.nadoc` path
  (`primitive_catalog.design_path`, `primitives_dir` overridable, default = the live workspace `Primitives` dir) and then
  lowers it through the EXACT `from_file` machinery (one path reference per copy; placeable by `add_part`/`place_grid`/
  `place_ring`). An unknown name fails the BUILD with a clear `BuildSpecError` (the parser is catalog-agnostic). Wraps no
  new route (reuses `add_file_instance` → coverage flat at 37). **Oracle = NEW `assert_part_from_primitive(assembly,
  instance_id, primitive_name, primitives_dir)`** — independently re-resolves the catalog NAME through
  `primitive_catalog.design_path`, loads that primitive's `.nadoc`, and delegates to `assert_part_from_file`; the new
  load-bearing piece over `from_file` is the **name→catalog-path RESOLVER** (a name mapped to the wrong/renamed primitive
  is invisible to `canonical_assembly`). Net +6 tests (test_headless_spec_build: 1 augment + 2 can-go-red on the oracle +
  1 unknown-name-fails-build + 1 roundtrip + 1 place_grid layout; suite 3002→3008). Scoped to STATIC (file-backed) catalog
  primitives per the user's choice. **Phase 2b (PARAMETRIC circle disc) SHIPPED 2026-06-23:**
  `{"from_primitive": "<circle>", "params": {"radius_nm": R}}` builds the disc generatively (lower to `circle_segment` via
  `build_design`, embed INLINE) when the catalog entry is `metadata.primitive_kind="circle"`; oracle
  `assert_part_is_circular_disc` (inline guard + AF-4 circularity). **Still OPEN:** Phase 2c — parts carrying small mate
  recipes (an assembly-level hinge *template*, not just geometry; needs a concrete hinge primitive in the catalog first).
  Original assessment below.
  **The gap (assessed 2026-06-17):** there is no primitive-catalog → automation pipeline. The design-level "Add
  Primitive" catalog is **read-only + UI-only** — `routes_primitives.py` exposes only `GET /primitives` +
  `preview.gif`/`poster.png`; there is **no placement route** (the browser reads `derive_placement_spec` and composes
  the `bundle-segment`/`continuation` calls client-side), and no headless layer references the catalog at all (the
  one parametric primitive with a headless entry is the circle disc, `hb.circle_segment`). At the assembly level,
  `hab.add_file_instance(path)` CAN instance a saved validated `.nadoc` part by workspace path and mate it — but the
  declarative grammar's `add_part`/`parts` accept **inline design specs only** (`parse_design_spec` per part), so a
  spec cannot reference a saved/validated primitive **by name**. **The missing rung** = a catalog/file-backed
  `add_part` (e.g. `"parts": {"hinge": {"from_primitive": "hinge_6hb_120deg"}}` or `{"from_file": "<path>"}`) + a
  headless primitive-instantiation wrapper. **The motivating use case (user, 2026-06-17):** hand-author +
  experimentally validate a hinge's custom scaffold routing (real topology = ground truth), save it as a part, then
  let automation place/articulate copies (display-layer mates/gears — never touching the validated topology; fits the
  three-layer law). A "hinge primitive" is likely an *assembly-level template* (two leaves + a revolute mate), not
  just a design primitive — so consider a parts-library that can carry small mate recipes, not only geometry.
  **Augment (when built):** a round-trip-style oracle asserting the instanced part's `canonical_topology` equals the
  referenced catalog file's `canonical_topology` — i.e. "build from primitive X provably uses *exactly* validated X"
  (so a stale/renamed/edited primitive can't silently substitute). Builds ON AF-11 (the build-spec interpreter) and
  AF-7 (`add_file_instance`). See the chat assessment + the 4-bar/parallelogram linkage discussion for context.
  **NB (2026-06-17): the mechanism layer this item gestured at is now spec'd as AF-14 + AF-15** (Tier 2,
  geometry-aware joint placement + OBB-edge alignment, sharing `backend/core/cluster_obb.py`). The 4-bar
  parallelogram capstone there builds the linkage at the *part-design level* (4 clusters + 4 `ClusterJoint`s in
  one `Design`); AF-12's role is the complementary path — instancing a hand-validated *saved* hinge/bar primitive
  by name — so the two compose (validated primitive geometry ← AF-12; articulation/arrangement ← AF-14/AF-15).

#### Hinge auto-generation (intake 2026-06-26 — "recreate hinge primitives programmatically + close all gaps to auto-generate autoscaffold hinge designs")

**The end-to-end target.** A script (eventually a text-to-DNA request) generates a complete, autoscaffold-routed,
validated design that contains one of the standard hinge primitives — *with zero mouse*. Today the hinge primitives
are HAND-BUILT `.nadoc` files (`workspace/Primitives/{2x2_single,2x4_double,2x6_triple}_hinge_link.nadoc`) and the
generation chain has named gaps. Inspected 2026-06-26: each primitive is two rigid SQUARE leaves (rows 0–1 & 4–5,
2-row gap) + staple leaves + cross-gap **forced-ligation links**, NOT yet scaffold-routed (**0 crossovers**) — they are
the *input* to autoscaffold. **"N links" = 2N reciprocal FL records:** 2x2=8 helices/14 strands/**2 FL**, 2x4=16/28/**4
FL**, 2x6=24/42/**6 FL**; feature_log = 2 entries (bundle-create + a grouped follow-up holding the staples + FL links).
See `memory/project_hinge_autoscaffold.md` (the router + the `scaffold_invariants.py` regression gate),
`project_primitive_library.md` (the primitives), `project_forced_ligation.md` (the link op). One item per session.

**Gap map (what blocks full auto-generation, and where each gap lives):**
- **G1 — place the cross-gap FL links headlessly** → **AF-32** (forced-ligation wrapper, ledgered above). *Prereq for AF-33.*
- **G2 — build the hinge primitive geometry+links from scratch** → **AF-33** (NEW, below). *Depends on AF-32.*
- **G3 — autoscaffold the hinge + a REUSABLE routing-compliance oracle** → **AF-34** (NEW, below).
- **G4 — compose a hinge primitive INTO a larger design at a cell offset (multi-op feature-log replay placement)** →
  **AF-35** (NEW, below). The deferred "multi-op replay" gap from `project_primitive_library.md` (today only single-op
  extrude primitives place headlessly, via `bundle-segment`).
- **G5 — reference a standard hinge BY NAME in a build-spec (optionally parametric link count)** → **AF-12 P2c**
  (`primitive_kind="hinge"`, not built). Static file-backed `from_primitive` already works in ASSEMBLY specs (AF-12 P2);
  the gap is a DESIGN-spec primitive op + the parametric-hinge branch. Tracked under AF-12; not duplicated here.
- **G6 — multi-link hinge AUTOSCAFFOLD routing (2x4/2x6)** → tracked in `project_hinge_autoscaffold.md`; currently
  **xfail** in `tests/test_hinge_router.py` (single-link 2x2 routes compliantly; multi-bridge merge unsolved). This is a
  ROUTING-ALGORITHM problem, not a wrapper+oracle item — it is the standing **blocker** for full multi-link generality,
  NOT a new AF item. AF-34's hinge leg pins the 2x2 path and rides the existing xfail for 2x4/2x6.

- [x] **AF-33 — headless hinge-primitive BUILDER + golden-equality oracle (recreate the standard hinges in code).**
  **P1 (2x2_single) SHIPPED 2026-06-26; P2 (2x4_double + 2x6_triple) SHIPPED 2026-06-27.** `backend/api/headless_hinge_build.py::build_hinge_primitive(name="2x2_single_hinge_link")`
  recreates the golden FROM SCRATCH by replaying its own feature-log recipe through the shipped wrappers: `hb.create_bundle`
  (length 40, ligated) → a `_shift_duplexes(+8)` that resizes every helix's *low-bp* end (derived from live strand
  directions, no lattice-parity reasoning) into the canonical bp 8…39 span → 2 gap-bridge `hb.resize_strand_end` (AF-30) +
  `hb.force_ligate` (AF-32) links (the bridge geometry is a per-primitive constant, NOT geometrically re-derived — the
  ASK-FIRST gap-routing territory). No new route → **coverage flat (48)**. **Augment = NEW `assert_matches_primitive`** (the
  golden-equality oracle): `canonical_topology` == golden AND `_fl_endpoint_set` == golden (load-bearing — topology fingerprint
  is BLIND to `forced_ligations`) AND `roundtrip_nadoc`-stable (topology + FL-set) AND `validate_design`. Replaying
  create-at-40-then-shift (not create-at-32) is load-bearing: AF-30's ISSUE-13 axis re-trim means only the same op sequence
  reproduces the golden's axis floats. Tests: 5 in `test_headless_hinge_build.py` + 4 harness red-tests (dropped-link /
  wrong-topology / unknown-name + positive) in `test_automation_harness.py`. Full suite **3240 passed / 61 skipped / 2 xfailed**.
  **Validation gained, not just a passthrough:** proves the code-built 2x2 hinge is byte-for-byte the validated hand-built
  primitive — topology AND the off-strand-graph FL links AND save/load persistence — so a builder that drifted (wrong shift,
  dropped/mis-wired link, altered leaf) fails. **P2 (2x4/2x6) SHIPPED 2026-06-27** — added `_HingeSpec` entries for
  `2x4_double_hinge_link` (2 links, ASYMMETRIC hand-authored trims `3p −16`/`5p −2` by column parity — transcribed
  verbatim from the golden's feature log, NOT re-derived) and `2x6_triple_hinge_link` (3 links, NO trims — the golden was
  generated by `build_hinge(2,6)`'s uniform geometry). Pinned by `test_build_2x4_matches_golden` /
  `test_build_2x6_matches_golden` (`assert_matches_primitive` reused, no new oracle) + 2 shape tests; coverage flat (48).
  NB **builder only** — 2x4/2x6 multi-link routing still falls back (the `test_hinge_router` xfail / G6 blocker), so their
  AF-34-style autoscaffold validation is pending. `build_hinge(2,4)` does NOT match the 2x4 golden (lacks the hand trims);
  `build_hinge(2,6)` DOES match the 2x6 golden.
  <details><summary>original spec</summary>
  A builder (in `headless_build.py`, or a small `headless_hinge_build.py` if it grows) that constructs each standard
  hinge — `2x2_single` / `2x4_double` / `2x6_triple` — FROM SCRATCH: build the two-leaf SQUARE bundle (the gapped
  cell layout), lay the staple leaves, and place the `2N` reciprocal cross-gap forced-ligation links via the **AF-32
  `hb.force_ligate`** wrapper. Mirror the conftest pattern (`make_mini_hinge_base_design` already replays the
  bundle-create; AF-33 extends to the FULL linked primitive). **Three-layer:** pure topological construction (bundle +
  strands + FL records) — an allowed write. **Augment = NEW `assert_matches_primitive(design, primitive_name, *,
  primitives_dir)`** — the GOLDEN-EQUALITY oracle: load `workspace/Primitives/<name>.nadoc`, assert the built design's
  `canonical_topology` equals the golden's AND its forced-ligation endpoint set (3′/5′ helix+bp, order-independent)
  equals the golden's (`canonical_topology` is BLIND to FL records — same off-strand-graph blind-spot as
  clusters/connections, so the FL-set check is load-bearing) AND it survives `roundtrip_nadoc` AND passes
  `validate_design`. Can-go-red: a dropped/extra link (FL-set mismatch), a wrong leaf layout (topology mismatch), a
  primitive the import silently altered (round-trip). **Validation gained:** proves the code-built hinge is byte-for-byte
  the validated hand-built primitive (the whole point of "recreate programmatically" — a builder that drifts from the
  golden is worthless). Coverage flat-or-+1 (reuses `create_bundle` + `force_ligate`; net new route only if a staple-lay
  op isn't already wrapped — settle when building). **NB scaffold routing is NOT part of this item** — the saved
  primitives carry 0 crossovers; routing is AF-34. **Phase split:** P1 = 2x2_single (single link); P2 = 2x4/2x6
  (parametric link count) — same builder, `n_links` parameter.
  </details>

- [x] **AF-34 — reusable autoscaffold routing-COMPLIANCE oracle + headless hinge autoscaffold validation. SHIPPED 2026-06-26.**
  NEW `assert_scaffold_routing_compliant(design, *, require_seams=True)` in `automation_harness.py` wraps
  `scaffold_routing_invariants` (empty==compliant) with a **non-vacuity guard** (design HAS a non-reference scaffold) +
  the seams/seamless distinction as the caller's flag. Driven end-to-end with ZERO file dependency:
  `build_hinge_primitive("2x2_single_hinge_link")` (builds from scratch — no golden needed) → `hb.auto_scaffold()` (the
  seamed entry dispatches to `hinge_router` on `forced_ligations`) → assert single seamed invariant-clean scaffold +
  `validate_design`. Tests: 1 end-to-end in `test_headless_hinge_build.py` + 3 oracle red/green in
  `test_automation_harness.py` (seamless route green at `require_seams=False`; the load-bearing red — same seamless route
  fires at `require_seams=True`, the exact LESSONS H8 regression; no-scaffold non-vacuity guard). 2x2 GREEN; 2x4/2x6 ride
  the existing `test_hinge_router` xfail (G6, untouched). Coverage **flat at 48** (composition over the already-covered
  `auto_scaffold`; the oracle is the deliverable). Full suite **3244 passed / 61 skipped / 2 xfailed**. **Validation gained,
  not just a passthrough:** a reusable "this autoscaffold output is real routable origami, not a seamless raster with
  buried crossovers" pin — every future headless autoscaffold build can now assert it, and the first fully-headless hinge
  build→route→validate win is pinned against the regression that previously shipped green.
  <details><summary>original spec</summary>
  `auto_scaffold`
  is already wrapped (`hb.auto_scaffold`), but there is **no reusable harness oracle** that asserts a headless
  autoscaffold output is *routing-compliant* — the `scaffold_routing_invariants` gate (`backend/core/scaffold_invariants.py`:
  seams present + every non-seam scaffold crossover ≥3 bp clear of staples) is tested only INSIDE
  `test_scaffold_invariants.py` over fixed entry points, not exposed for any AF build to pin. **Augment = NEW
  `assert_scaffold_routing_compliant(design, *, require_seams)`** in `automation_harness.py` — wraps
  `scaffold_routing_invariants` (empty list == compliant), with the seams/seamless distinction as the caller's flag and a
  non-vacuity guard (the design actually HAS a scaffold). Then drive it end-to-end on the **hinge** path: take an AF-33
  hinge → `hb.auto_scaffold` (the `hinge_router` dispatches on `forced_ligations`) → assert single scaffold strand +
  compliant + `validate_design`. **2x2_single pins GREEN; 2x4/2x6 ride the existing `test_hinge_router` xfail (G6) — do
  NOT try to solve multi-link routing here** (that's the algorithm work in `project_hinge_autoscaffold.md`). **Validation
  gained:** a reusable "this autoscaffold output is actually routable origami, not a seamless raster with buried
  crossovers" pin (the exact regression LESSONS H8 records) — every future headless autoscaffold build can assert it.
  Coverage flat (composition over the covered `auto_scaffold`; the oracle is the deliverable). **MERGE RULE reminder:** if
  this adds a new autoscaffold return path, add it to `ROUTING_ENTRY_POINTS`.
  </details>

- [x] **AF-35 — headless multi-op primitive PLACEMENT + placed-substructure oracle (compose a hinge into a larger
  design). SHIPPED 2026-06-27.** User chose **preserve-verbatim** (the ASK-FIRST below) → built as a **rigid GRAFT**,
  not an op-replay: `place_primitive_into(host, primitive, *, anchor_cell, plane)` in NEW pure
  `backend/core/primitive_placement.py` copies the primitive's own helices/strands/forced_ligations/cluster_transforms,
  translates them by ONE rigid lattice vector (grid_pos + axis floats, in-plane), remaps every id (helix/strand/cluster
  + all internal refs), and appends — host content untouched. `hb.place_primitive(name, *, anchor_cell, plane, primitive)`
  sources a built-in hinge via `build_hinge_primitive` (or takes an explicit `primitive=Design`) and commits via
  `snapshot`+`set_design_silent` (one undo step). **NOT a feature-log replay** (the route-driven replay would go through
  `bundle-segment`, a different builder → AF-30 ISSUE-13 axis drift; copying the already-correct geometry is what makes
  "verbatim" literally true). **Augment: NEW `assert_primitive_placed(before, after, primitive, *, anchor_cell, plane)`**
  — additive (host portion's `canonical_topology` unchanged) + anchored (placed min-cell == `anchor_cell`) + verbatim
  (offset-corrected INDEPENDENTLY via `_lattice_position` → `canonical_topology` == primitive) + FL links survived
  (grid-keyed set, the canonical_topology blind-spot) + cluster groupings survived. Coverage **FLAT (48)** — grafts via a
  `backend/core` service, imports no new route handler. Tests: 4 in `test_headless_build.py` (empty/additive/revertable/collision)
  + 7 red in `test_automation_harness.py` (vacuous/wrong-anchor/dropped-FL/lost-cluster/distorted/mutated-host). Full suite
  **3329 passed / 61 skipped**. **Validation gained, not just a passthrough:** proves a saved multi-op primitive composes
  into a bigger design as an EXACT rigid copy at the requested cell, with its hinge FL links + leaf clusters intact and the
  host untouched — none of which `canonical_topology` alone can see (it's blind to FLs/clusters and to absolute placement).
  <details><summary>original spec</summary>
  Today only SINGLE-op extrude primitives place headlessly (one `bundle-segment`); a
  hinge is a MULTI-op primitive (bundle-create + the grouped staple/FL op) and there is **no headless way to drop it
  into an existing design at a cell offset** — the deferred "multi-op feature-log replay (hinges / pretransformed
  clusters needing id-remap + per-op cell offset)" from `project_primitive_library.md`. A wrapper
  `hb.place_primitive(primitive_name, *, anchor_cell, plane)` that replays the primitive's feature-log ops additively
  onto the current design, each op's cells translated by the anchor offset, with fresh id remapping (mirrors the GUI
  placement pipeline's `translateFootprint` + the parity-snap rules — SQUARE has no parity term, so a hinge offset is
  unconstrained). **Augment = NEW `assert_primitive_placed(design_before, design_after, primitive_name, *, anchor_cell)`**
  — the placed sub-structure's canonical topology (re-keyed by subtracting the offset) matches the primitive's, the FL
  links survived the replay (endpoint set, offset-corrected), the placement is additive (pre-existing structure
  unchanged) and revertable. **Validation gained:** proves a saved multi-op primitive can be COMPOSED into a bigger
  design without corrupting its links — the prerequisite for "an autoscaffold design WITH a hinge in it" (vs. a design
  that IS a bare hinge, which AF-33 already gives). **ASK-FIRST:** whether placement should preserve the primitive's
  pre-placed scaffold/FL routing verbatim or re-route after composition is a topology decision — surface it before
  building. Coverage +1 if it drives a distinct replay route; flat if it loops existing wrappers. **Lower priority than
  AF-33/34** — a standalone generated hinge (AF-33 → AF-34) is the first end-to-end win; AF-35 is the composability
  extension.
  </details>

### Tier 5 — physical-layer validation (oxDNA-in-the-loop) + constraint satisfaction (the eventual goal)

**What's different here.** Tiers 0–4 validate the **topological/geometric** layers and are *deterministic*
(`canonical_topology` equality, analytic geometry oracles). Tier 5 validates the **physical** layer: it
drives an oxDNA relaxation/production headlessly, *measures* a property of the relaxed structure (end-to-end
distance, R_g, inter-helix spacing, segment angle), and — the capstone — **iterates the design until a user
constraint is satisfied.** Because MD is stochastic, the oracle class is new: **a measured property within a
tolerance, GATED by the confidence metric** (`oxdna_health.rmsf_confidence` — frames pooled + RMSF standard
error, already built), NOT exact equality. A short run reports *inconclusive*, not pass/fail.

**Eventual goal (user, 2026-06-17):** *"Make sure two ends of a curved structure are 50 nm ± 5 nm apart"* →
NADOC iterates over several oxDNA simulations until the request is met.

**Three-Layer Law (load-bearing here).** The iterate loop EDITS the **topological** layer (a bend op /
loop-skip / length knob), re-derives **geometric** positions, RE-RELAXES the **physical** layer (oxDNA),
then MEASURES the physical result. The edit is topological; the measurement is physical; **oxDNA output is
never written back into `Design`** (it stays a Physical-layer artifact, exactly as the display/RMSF paths do).
Confusion about *which* nucleotide is "an end", or *which* knob bends *which* way, is an ASK-FIRST
directionality question (`feedback_crossover_no_reasoning`, the DNA-topology rule) — do not guess.

**Reuse map (durable — don't re-derive; see `memory/project_oxdna_relaxation.md`):** job lifecycle / resume /
reconcile in `backend/core/oxdna_runner.py`; routes in `backend/api/routes_oxdna.py` (`create_oxdna_job`,
`start_oxdna_job`, `append_oxdna_production`, `/rmsf`, `/trajectory`, `/display`); average-structure + per-base
RMSF in `oxdna_health.production_rmsf`; the confidence metric in `oxdna_health.rmsf_confidence`; relaxed-geometry
readers `read_configuration_unwrapped` / `read_configuration_full` / `oxdna_backbone_site` in
`backend/physics/oxdna_interface.py`. **CI-without-GPU:** the **mock oxDNA binary** (`_MOCK_OXDNA` fixture in
`tests/test_oxdna_relaxation.py`) lets the wrapper + oracles run deterministically; gate real-binary paths with
`skipif find_oxdna() is None`.

- [x] **AF-13 (Phase 1) — headless oxDNA job wrapper. SHIPPED 2026-06-18.** NEW
  `backend/api/headless_oxdna_build.py` drives the REAL routes (`create_oxdna_job` → `start_oxdna_job` → poll →
  optional `append_oxdna_production` → `get_oxdna_display`) from an isolated scratch session, against the mock
  binary (`$OXDNA_BIN`). `hox.run_relaxation(design, workspace, *, min_bp_retained=0.0, …) → terminal OxdnaJob`;
  lower-level `create_job`/`start_relaxation`/`append_production`/`read_relaxed_positions`/`wait_for_terminal`.
  **Augment:** `assert_relaxed_geometry_recovered(job, design, workspace)` — job is `completed` AND its relaxed
  `last_conf` reads back (via the display route's `read_configuration_unwrapped`) into a full per-nucleotide
  position map (exactly one finite position per design nucleotide, every key a real `(helix_id, bp, dir)`).
  Physical-layer only — never written back to topology. NEW separate `oxdna_coverage_report()` (3 `/oxdna`
  mutation routes covered) keeps the design/assembly count untouched at 35.

- [x] **AF-13 (Phase 2) — relaxed-geometry MEASUREMENT oracle (the constraint primitive). SHIPPED 2026-06-18.**
  Landmark convention (ASK-FIRST answered by user): the raw **`(helix_id, bp_index, direction)` tuple** — most
  primitive, indexes the relaxed-display + RMSF maps directly, no strand-polarity resolution. Pure
  `measure_end_to_end(positions, a, b)` in `backend/core/oxdna_health.py` (Euclidean nm between two landmark
  backbone sites; raises on empty/identical/absent). NEW read-wrapper `hox.read_flexibility_map(job_id, ws)`
  drives the REAL `GET /oxdna/jobs/{id}/rmsf` → pooled noise-averaged mean structure + `confidence`. **Augment:**
  `assert_relaxed_measurement(job, measure_spec, target_nm, tol_nm, *, workspace, min_confidence)` — the first
  STOCHASTIC-class oracle: status-completed + reads the mean structure + **confidence gate** (≥ `min_confidence`
  pooled frames else INCONCLUSIVE-raise) + measured ∈ [target±tol]. On the identity-mock 6hb the relaxed mean
  reproduces the design's own end-to-end to ~0.002 nm (pinned at tol 0.1). Coverage unchanged (rmsf is a GET).

- [x] **AF-13 (Phase 3) — declarative constraint spec + checker. SHIPPED 2026-06-18.** `parse_constraint_spec`
  (PURE validate/normalise → `ConstraintSpecError` at parse time) + `check_relaxed_constraint(constraint,
  read_flexibility_map_dict)` REPORTING `{met, status∈{met,unmet,inconclusive}, measured_nm, n_frames,
  min_confidence, confidence}` — both in `backend/core/oxdna_health.py`, reusing P2's `measure_end_to_end`.
  The REPORTER counterpart to P2's *asserter*. **Load-bearing guard pinned:** `met` is NEVER True below
  `min_confidence`, even when the value is within tolerance (the confidence gate, now a returned status). 20 pure
  tests (13 rejection cases + idempotency + tolerance bracket + the low-frame-never-met red-test) + 2 real-run
  integration tests (`_MOCK_OXDNA_TRAJ` → `read_flexibility_map` → checker). Coverage UNCHANGED (no route wrapped).
  Wired into the AF-11 grammar as a design `constraints` block by AF-13 P5 (`build_and_check_design`).

- [x] **AF-13 (Phase 4, capstone — the eventual goal) — iterate-until-met loop. SHIPPED 2026-06-19.**
  `hox.iterate_to_constraint(build_fn, adjust_fn, constraint, ws, *, initial_knob, …)` — the closed
  build→relax→production→measure→adjust loop. Branches on the AF-13 P3 verdict **status** (never the raw measured
  value): `met`→return; `unmet`→`adjust_fn(knob, verdict)` rebuild; `inconclusive`→`_pool_until_conclusive`
  appends MORE production to the SAME job (pooling frames) until the confidence gate clears, NOT a knob change.
  `tuned=True` relaxes via `run_relaxation_tuned` (AF-17 bridge). Oracle `assert_converges_to_constraint` proves
  the loop converged AND every `met` verdict was confidence-gated (≥`min_confidence` frames) AND non-vacuously
  (first attempt was off-target). Augment fixture = a **bend-curvature knob** on a 2-helix bundle (probed monotone:
  κ 0→13.74 nm, 2.5→12.04, 3→11.33; landmarks stable since topology is unchanged) + a bisection `adjust_fn`;
  identity mock reproduces the design geometry so the *bend* moves the measured end-to-end. Three-Layer-clean (knob
  edits topology, relaxed coords never written back). Composition-sugar (wraps no new route → oxDNA coverage flat).

- [x] **AF-13 (Phase 5) — design `constraints` block wired into the AF-11 grammar (attach + report, no knob).
  SHIPPED 2026-06-21.** A design spec carries an optional top-level `constraints` list (AF-13 P3 specs; landmarks
  name a helix by **grid_pos** `{helix:[r,c], bp_index, direction}`), validated at parse time by `build_spec.py` (via
  `parse_constraint_spec` — a malformed constraint raises `BuildSpecError` BEFORE any build/relax). Driver
  `hs.build_and_check_design(spec, ws, *, steps, tuned, **relax_params) → {design, verdicts}` resolves each landmark's
  grid_pos→runtime id (fail-fast), relaxes ONCE + production, then `check_relaxed_constraint` per constraint. All four
  `measure_*` kinds get the path for free. Oracle `assert_spec_constraints_reported` proves the grammar reports the
  SAME verdict a hand-driven `check_relaxed_constraint` does — load-bearing because `assert_spec_matches_calls` is
  blind to a physical-layer verdict. Composition-sugar (coverage flat, 36; god-files Δ=0). The knob-driven
  `iterate_to_constraint` grammar clause is the deferred next step.

- [x] **AF-13 (Phase 6) — design `optimize` block (knob → `iterate_to_constraint`). SHIPPED 2026-06-22.** A design
  spec carries an optional top-level `optimize` block: a parametric `knob` (`{op:<index>, param:<numeric param>, lo,
  hi, initial, response:"increasing"|"decreasing"}`) + a single AF-13 P3 `constraint`. The pure grammar
  `build_spec.py` (`_parse_optimize`/`_parse_knob`) validates it at parse time — knob index in range, param present +
  **numeric**, `lo<hi`, `initial∈[lo,hi]`, response in the enum, constraint via `parse_constraint_spec` — so a
  malformed optimize block raises `BuildSpecError` BEFORE any build/relax. Driver
  `hs.build_and_optimize_design(spec, ws, *, max_iterations, production_steps, tuned, **relax_params)` lowers it to the
  closed `hox.iterate_to_constraint` loop: synthesises `build_fn` (rebuild with the knob overriding
  `ops[op].params[param]`) + `adjust_fn` (bisection whose direction comes from the **declared** `response`, never an
  inferred bend sign) and resolves the constraint's grid_pos landmarks → runtime ids on one probe build (ids
  deterministic → stable across rebuilds). Oracle = reuse `assert_converges_to_constraint` (the AF-13 P4 capstone
  oracle): the spec converges a bend-curvature knob to the relaxed end-to-end target, confidence-gated + non-vacuous.
  Load-bearing because `assert_spec_matches_calls` is blind both to the bend overlay AND to a physical-layer
  convergence. Composition-sugar (coverage flat, 36; god-files Δ=0). NO ASK-FIRST: the knob magnitude is
  direction-agnostic, the monotone sense is a spec-author declaration the grammar lowers, never reasons about.

- [x] **AF-ATOM (Phase 1) — atomistic-display validation oracle + queryable route + `/validate-atomistic`
  skill. SHIPPED 2026-06-21.** Every element the oxDNA-display **atomistic** rep draws (each bond stick, each
  atom sphere) is now measurable, so a stretched / hidden / clashing element is queryable, not just visible.
  `backend/core/atomistic_validation.py`: `audit_bonds(design, frame)` reconstructs the model with the SAME
  `build_atomistic_model(frame_override=…)` the renderer uses (so audited bonds ARE rendered bonds — identical
  serial pairs) and classifies every bond `rigid | linker | backbone | bridge`, flagging **rigid-stamp
  violations** (frame-invariant bonds ≠ template = a placer bug; the *load-bearing* oracle), over-stretched
  bonds (the long sticks the screenshot shows), bonds the renderer **hides** (>1 nm — drawn as nothing but
  listed), clashes, and non-finite atoms.  `latest_job_for_design` / `relaxed_frame_for_job` / `audit_oxdna_job`
  give the headless entry point; route `POST /oxdna/jobs/{id}/display-atomistic-audit` makes the live app's
  displayed frame queryable; CLI `scripts/audit_atomistic.py` (`just audit-atomistic`) + the `validate-atomistic`
  skill drive it (default `workspace/6hb_sim_tests.nadoc` latest job). Tests: `tests/test_atomistic_validation.py`
  (8) — stamp-invariance, over-stretch/hidden/clash/non-finite detectors, class partition, job entry point,
  route. **Real-job finding (job c1299e0b07b5):** stamp clean (18 279 rigid bonds, max Δ 0.0000 Å, 0
  violations → placer correct), but **1005 backbone O3'→P bonds at mean 1.0 nm / max 3.16 nm** — oxDNA's
  one-bead-per-nucleotide frames don't enforce all-atom backbone continuity, so the sticks genuinely stretch
  (the screenshot). **Validation gained, not a passthrough:** first programmatic proof of which atomistic bonds
  are real vs over-stretched vs renderer-hidden, and that the rigid stamp is frame-invariant — a number no
  HTTP-200 or eyeball gives.  **Deferred → Tier F (AF-ATOM P2) + the backbone-closure feature below.**

<a id="af-28"></a>
- [ ] **AF-28 — hinge-angle linker designer: candidate overhang-placement optimizer (OPEN QUESTION, depends
  on AF-27).** *User goal (2026-06-25):* given a hinge (two leaves + a pivot) and a **desired angle**, decide
  **where to put the overhangs** that become attachment points for confining linkers, and **which linker**
  bridges each pair, so the relaxed hinge sits at the target angle. This is the design-decision layer ABOVE the
  raw AF-27 wrappers and AF-13's `segment_angle` constraint — it chooses the *placement*, not just measures the
  result. **Deliberately framed as a decision tree / algorithm, not a one-shot solver**, because the
  geometry→angle map is many-to-one and the user flagged it may not be cleanly generated.

  **The two strategy branches (settle with the user before building — this is the open part):**
  1. **Algorithmic linker generation.** Enumerate candidate overhang sites on each leaf (REUSE AF-14's OBB
     corner/edge enumerator in `cluster_obb.py` — the leaves are clusters; the faces *across the gap* are the
     natural candidate set, the same "door-jamb" interface logic as the hinge-axis recommender). For each
     candidate site-pair, the **target angle + pivot geometry fix the required leaf-to-leaf chord**, which fixes
     the linker contour length (FJC/ds) — a geometric inverse, NOT free reasoning. Rank pairs by feasibility
     (reachable contour length, no clash, ROM via `cluster_range_of_motion`), place via AF-27, then **physically
     validate** the relaxed `segment_angle` (AF-13 `iterate_to_constraint`, `segment_angle` already a wired
     constraint kind) and iterate the chosen length until the relaxed angle hits target.
  2. **Validated linker-bearing primitives (the user's preferred fallback).** Rather than synthesise a linker de
     novo, keep a **library of hand-validated hinge primitives that already CONTAIN their confining linkers**,
     indexed by the angle they relax to — the 3 new `*_hinge_link` primitives are the seed; angle-specific
     variants get added as they're validated. The "algorithm" then degrades to **selection** (pick the primitive
     whose validated angle is nearest the request, optionally interpolate linker length) + AF-12 P2c parametric
     placement. Lower risk, no inverse-geometry guesswork, but needs a populated, angle-labelled catalog.

  **Likely shape:** a decision tree that tries branch 2 first (a validated primitive within tolerance → use it),
  falls back to branch 1 (generate + iterate-validate) only when no catalogued primitive fits. **Augment (when
  scoped):** `assert_hinge_confined(job, *, target_angle_deg, tol_deg, vertex_landmark, leg_landmarks, …)` — the
  relaxed `segment_angle` ∈ [target±tol] AND can-go-red on the SAME hinge with the linker removed (the unlinked
  hinge swings free / sits at a different angle), proving the linker is *what confines* it — the missing Gap-3
  oracle from the 2026-06-25 analysis. **Dependencies:** AF-27 (linker create/relax), AF-13 (`segment_angle`
  iterate-to-constraint), AF-14 (OBB candidate enumeration + ROM), AF-12 P2c (`primitive_kind="hinge"`).
  **Three-layer + ASK-FIRST:** the placement edit is topological, the angle measurement is physical (oxDNA
  output never written back); which nucleotide is "the vertex/legs" of the angle and the linker handedness are
  ASK-FIRST directionality. **This is the AF-12 P2c text-to-DNA rung made concrete:** "give me a hinge at θ°."

### Tier 6 — time-resolved E-field response + interactive engine (the real-time field-exploration goal)

**What's different here.** Tier 5 measures a *static* property of one relaxed mean structure. Tier 6 measures a
**time course**: subject an anchored structure to an E-field and watch its helical alignment + base-pairing evolve
*frame by frame*, extracting an **equilibration time τ** and a **non-destructive window** (aligns without melting).
The oracle class is still Tier-5's stochastic/confidence-gated one, but now over a *trajectory* (per-frame
observables), not a single pooled mean. The capstone is an **automated cross-design field sweep**.

**What already exists (audited 2026-06-22 — do NOT rebuild; see `memory/project_oxdna_efield.md` + `project_oxdna_relaxation.md`).**
The *batch* field path is shipped and automatable end-to-end: `POST /oxdna/jobs/{id}/field` spawns a field **child
job** (parent's relaxed `last_conf` → single `field` stage) with composable forces (`write_field_forces` =
uniform `string` force on all beads + anchor `trap`s, `DEFAULT_ANCHOR_STIFF=1000` = immobile); anchors resolve
server-side (`resolve_anchor_particles`: overhang / cluster / domain → particle indices); the oracle
`measure_field_response(field_pos, ref_pos, field_dir, anchor_keys)` already asserts anchored-held + free-deflected-
along-field; `headless_oxdna_build.run_field` / `run_field_validation` / `field_response_from_confs` drive it
headlessly; and a **field-deflecting mock binary** (`_FIELD_MOCK_OXDNA`) shifts free beads ∝F0 along the field +
holds trapped beads → the whole pipeline + oracle run on CPU with NO GPU (deflection already pinned monotonic in
field magnitude). The field stage writes a `trajectory.dat` (the `/trajectory` route includes it; RMSF/flex-map
pools `kind in {production,field}`). **So Tier 6 builds measurement + sweep ON the existing field child-job +
mock**, not a new engine — except the AF-21/22 live sub-track.

**Physics caveats (load-bearing — keep them in every oracle's framing; from `project_oxdna_efield.md` §1).**
(1) **Quasi-static only** — no explicit ions/screening, no hydrodynamics, timestep can't reach AC fields; τ is the
*mechanical relaxation to a new DC pose*, NOT electrophoretic mobility, and the swing *trajectory* is qualitative
while the *equilibrium pose* is meaningful. (2) **Anchors are mandatory** (uniform field ⇒ net COM force ⇒ a free
structure streams across the box) AND **anchor selection matters** (pinning only a floppy ssDNA overhang holds the
overhang but lets the rigid duplex swing — pin a duplex/cluster to hold the body). (3) **τ vs throughput** —
re-equilibration is ~10⁵–10⁶ steps; interactive rates are realistic only for *small* specimens (single duplex +
overhang), batch for large origami. Frame these as documented scope, not as bugs.

**Three-Layer Law (as in Tier 5).** The field is a **Physical-layer** load; field/relaxed coords are read back as
display/measurement artifacts and **never written into `Design`**. The *anchor designation* and *overhang* are
topological/spec inputs the user (or spec) provides; the resolver is mechanical (no geometric reasoning about which
nucleotide aligns which way — that's the ASK-FIRST `feedback_crossover_no_reasoning` rule). Field direction +
magnitude are user/spec inputs; oracles measure **magnitudes** (alignment projection, |displacement|, τ) →
direction-agnostic, no sign/handedness reasoning enters the driver.

**oxpy prerequisite (AF-21+ only; AF-18/19/20/23-batch need none) — ✅ BUILT + WIRED 2026-06-23.** The interactive
engine needs oxDNA's Python binding **oxpy**, which lets a persistent Python process step the engine in bursts and
mutate the field force vector *without restarting / re-initing CUDA*. **Now built and importable from the NADOC
venv** (was `Python:BOOL=OFF`). As-built, for the AF-21 session — DO NOT re-derive:
- Rebuilt the EXISTING `~/oxDNA/build` (CUDA objects reused) with
  `cmake .. -DCUDA=ON -DPython=ON -DPython_EXECUTABLE=/home/joshua/NADOC/.venv/bin/python3 && make -j12`. Prereq was
  `sudo apt-get install -y python3-dev` (the venv runs on the *system* Python `/usr`; its dev headers were missing —
  user ran the one sudo step). pybind11 submodule was already populated at `~/oxDNA/src/oxpy/pybind11`.
- Built module: `~/oxDNA/build/python/oxpy/core.so` (+ `__init__.py`/`utils.py`), plain `setuptools` pyproject.
  **Editable-installed into the venv:** `uv pip install --python .venv/bin/python3 -e ~/oxDNA/build/python` → a future
  `make` that refreshes `core.so` is picked up automatically (no re-install). `import oxpy` works with NO PYTHONPATH.
- **API surface confirmed present** (the AF-21 substrate): `oxpy.OxpyManager` with `.run(steps)` (burst-step),
  `.current_step`/`.steps_run`, `.config_info` (live particle/position access), `.print_configuration`; top-level
  `oxpy.forces` (where the field `ConstantRateForce` is added + **mutated live** between bursts) and `oxpy.observables`
  (live alignment/bp monitoring). The standalone CLI binary (`find_oxdna` → `~/oxDNA/build/bin/oxDNA`) is unchanged, so
  the shipped *batch* field path (AF-18→20) is unaffected. Nothing in NADOC imports oxpy yet — AF-21 introduces the
  first `import oxpy` (in a NEW `backend/physics/oxdna_live.py`, NOT a god-file).
- **GOTCHA for AF-21 tests:** the parity oracle's binary half is GPU-free via `_FIELD_MOCK_OXDNA`, but the *oxpy* half
  needs the real engine — gate oxpy tests with `pytest.importorskip("oxpy")` (mirror the `skipif find_oxdna() is None`
  pattern) so CI on a machine without the build still passes.

- [x] **AF-18 — full-pipeline anchored field-specimen builder.** One headless call composing the entire
  build→field-ready chain into a single validated entry point: `hox.build_field_specimen(spec_or_design, ws, *,
  overhang, anchor, **relax_params) → {design, job, anchor_keys}` (new code in `headless_oxdna_build.py` /
  `headless_spec_build.py`, NOT a god-file) — bundle/route (`hb.auto_scaffold`+`hb.full_autostaple` or a build-spec)
  → `hb.full_sequence` → `hb.overhang_extrude` → `hox.run_relaxation` → designate the overhang/cluster as the field
  **anchor** (resolve via `resolve_anchor_particles`). **Augment = NEW `assert_field_ready_specimen(result, design,
  ws)`** — composes three proofs into "this specimen can run a field experiment": fully sequenced (reuse
  `assert_fully_sequenced`) + relaxed geometry recovered (reuse `assert_relaxed_geometry_recovered`) + **≥1 anchor
  resolves to particle indices AND a probe field holds the anchored beads while the free part deflects** (reuse
  `measure_field_response` on a short mock field run). **Load-bearing because nothing today proves an end-to-end-built
  design is field-experiment-ready** — each piece (sequence, relax, anchor) is pinned alone, but not that they
  compose into a runnable, anchorable specimen; the gap is exactly the user's "build → … → set as anchor" chain.
  Can-go-red: an unsequenced/unrelaxed/un-anchorable specimen fails the corresponding clause. No oxpy. **ASK-FIRST:**
  which nucleotides are the overhang/anchor is a spec input — do not infer it geometrically.

- [x] **AF-19 — field equilibration-timeline measurement (τ) + non-melt oracle.** The key NEW physical observable.
  Pure `measure_field_equilibration(frames, field_dir, anchor_keys, *, observable="alignment") → {tau_steps,
  plateau, aligned_final, bp_timecourse, melted}` in `backend/core/oxdna_health.py`: per-frame alignment of the free
  body's principal axis to the field (reuse the `field_response` projection) + per-frame base-pair retention (reuse
  the bp metric), fit the monotone approach to its plateau, extract τ (time to reach 1−1/e of the plateau).
  **Augment = NEW `assert_equilibration_timeline(job, ws, field_dir, anchor_keys, *, melt_floor, min_confidence)`** —
  the field trajectory shows a finite positive τ, a monotone-within-noise approach to a stable plateau, AND **bp
  retention never drops below `melt_floor` across the WHOLE timeline** (the "without ripping it apart" invariant),
  confidence-gated on frame count. **Load-bearing because `measure_field_response` is endpoint-only** (final
  aligned/displaced) — blind to the *time course* and to *transient* melting mid-swing. Reuses the `field`-stage
  trajectory + `_FIELD_MOCK_OXDNA` (its ∝F0-per-step shift gives a synthetic monotone alignment ramp for CI).
  Can-go-red: a non-converging (never-plateau) run → no finite τ; a melt during the swing → floor breach. No oxpy.

- [x] **AF-20 — field sweep driver + (|E|,direction)→response map + correlation oracle.** SHIPPED 2026-06-23
  (`hox.sweep_field_response` + `assert_field_sweep_map`; HARNESS block at the top of the handoff). `hox.sweep_field_response(
  specimen, intensities_pN, directions, ws) → {(pN,dir): {tau, aligned, bp_retained, destructive}}` — each grid cell
  a child field job off the same relaxed parent (reuse the field child-job spawn), measured by AF-19, assembled into
  a map flagging the non-destructive regime (`aligned ∧ bp_retained ≥ floor`). **Augment = NEW `assert_field_sweep_map(
  map, *, benign_range, destructive_range)`** — every cell carries a verdict (no gaps); the non-destructive regime is
  **non-empty in `benign_range` and empty in `destructive_range`** (can-go-red); AND **τ decreases monotonically with
  |E| in the responsive band** (the field-strength ↔ equilibration-timeline correlation the user wants). **Load-bearing
  as the first automated MULTI-config physical experiment with a reusable field↔τ correlation oracle** — Tier 5
  measured one structure at one condition; this measures a *response surface*. Reuses AF-19 + the mock's
  already-pinned "deflection scales with magnitude". Can-go-red: a flat (field-independent) τ, or a non-empty
  destructive window. No oxpy. **Log a `log()`/note if any cell is skipped** (no silent truncation of the sweep).

- [x] **AF-21 — oxpy persistent interactive engine + equilibrium-parity / live-mutation oracle. SHIPPED 2026-06-23**
  (`backend/physics/oxdna_live.py` `LiveOxdnaSession`/`_OxpyStepper` + `hox.run_live_field` + `assert_oxpy_equilibrium_parity`;
  HARNESS block at the top of the handoff). [PREREQ: oxpy build
  `-DPython=ON` — DONE.]** NEW `backend/physics/oxdna_live.py` wrapping oxpy: `LiveOxdnaSession` loads
  topology+conf, steps in bursts (`run(M)` loop), **mutates the field `ConstantRateForce` vector live**, and reads CM
  positions in-process (no file round-trip, no CUDA re-init between bursts) — a cohesive module, NOT a god-file
  block. Headless `hox.run_live_field(...)` drives it. **Augment = NEW `assert_oxpy_equilibrium_parity(live_result,
  batch_result, *, tol, min_confidence)`** — an oxpy burst-stepped run reaches the **same equilibrium observables**
  (alignment, R_g, bp retention) within `tol` as a one-shot binary run of the same total steps from the same seed,
  **confidence-gated** (stochastic thermostats forbid trajectory parity → assert *equilibrium-property* parity, the
  Tier-5 stochastic-oracle class), AND **mutating the field vector mid-run shifts the measured deflection toward the
  new vector**. **Load-bearing because it proves the interactive engine is physically equivalent to the validated
  batch engine** (else "real-time" output is untrustworthy) + that live field control actually steers. The parity
  half is testable GPU-free against the binary `_FIELD_MOCK_OXDNA`; the live-mutation half needs the real oxpy build.
  Can-go-red: an oxpy run diverging from the binary beyond tol, or a field-vector change that doesn't move the body.

- [x] **AF-22 — live field-steering session + field-following oracle. SHIPPED 2026-06-23**
  (`hox.steer_field_session` + `assert_live_field_following`; HARNESS block at the top of the handoff). [builds on AF-21.]** `hox.steer_field_session(
  session, waypoints) → timeline` — set field dir d₁, run a burst, read observables; switch to d₂, run, read; … a
  steered timeline (the programmatic form of a user dragging the field gizmo). **Augment = NEW `assert_live_field_
  following(timeline, *, melt_floor)`** — after each waypoint the free body's alignment observable moves **toward the
  current field vector** (the structure follows the field), and bp retention stays above `melt_floor` across ALL
  waypoints. **Load-bearing because it proves the interactive control loop produces real field-following without
  melting** — the substance behind "playing in real time", distinct from a merely responsive UI. Reuses AF-19's
  per-frame observables + AF-21's session. Can-go-red: a body that ignores a waypoint change, or a melt during
  steering. (The frontend live-steering UI + frame-streaming WS is a separate Tier-F display item → push an `MV-`
  row when that ships; this AF item is the headless, automatable control loop.)

- [x] **AF-23 — CAPSTONE: cross-design automated field-response campaign (the user's stated goal). SHIPPED 2026-06-23**
  (`hox.run_field_campaign` + `assert_field_campaign`; HARNESS block at the top of the handoff).
  `hox.run_field_campaign(specs, intensities_pN, directions, ws) → {design_name: sweep_map}` — build each design from
  a build-spec / catalog primitive (reuse the AF-11/12 grammar + AF-18 specimen builder), run the AF-20 sweep on each,
  report **per-design non-destructive operating window + alignment-vs-field response**. **Augment = NEW
  `assert_field_campaign(campaign, *, expect_distinguishable)`** — every design yields a populated map with a reported
  non-destructive window; designs are **distinguishable** (a floppier / longer-lever design aligns at a lower |E| or
  shorter τ — proven on two specimens chosen to differ); reproducible across a re-run (deterministic mock). **Load-
  bearing as the capstone that ties text→design (grammar) + field sweep (AF-20) + equilibration (AF-19) into one
  automated study reusable for ANY origami** — "automatic exploration of E-field intensities and directions that
  correlate with DNA alignment equilibration timelines, without ripping it apart, for various designs." Runs on the
  batch path (AF-20, de-risked) now; transparently swaps to the AF-21/22 oxpy fast path once built. Can-go-red: a
  campaign where designs are indistinguishable (`expect_distinguishable` violated) or a design yields an empty map.

- [x] **AF-24 P1 — real-engine Tier-6 equilibration-τ validation. SHIPPED 2026-06-23 (committed `88e257b`).**
  Ports the AF-19 oracle to a GPU-gated real-oxDNA test (`test_field_specimen_reanneals_and_equilibrates_real_engine`,
  `NADOC_RUN_OXDNA_SLOW=1`): re-anneal retention ≥0.9 → anchored field → finite τ, not melted → PASSED on real CUDA.
  Fixed the inherited mock-tuned relax defaults (`STANDARD_RELAX_PARAMS`). See `design_automation_metrics.md` AF-24 + the
  data summary; harness/repro detail in `design_automation_harness.md`.
<a id="af-24"></a>
- [ ] **AF-24 P2/P3 — real-engine field-SWEEP (|E|↔τ law) + cross-design CAMPAIGN.** OPEN — **owned by the other
  computer; do not pick up.** P2: `sweep_field_response` over ≥2 real intensities → `assert_field_sweep_map` on real
  cells (pN≤2 benign, pN≥4 melts at 20k steps from the AF-24 session). P3: `run_field_campaign` over 6hb vs 18hb →
  `assert_field_campaign` on the real engine. Reuse one relaxed parent + `append_field` per cell; keep GPU-gated + opt-in.

### Tier 7 — design-timeline navigation + job-staleness lifecycle (the simulate→edit→roll→return loop)

> **■ MANUAL VALIDATION: currently FAILING (as of 2026-06-24).** The out-of-date-job feature still does NOT
> work end-to-end in the running app — across several fix rounds (snapshot-restore → feature-log seek →
> `_syncFromDesignResponse` on the roll → `nadoc:design-changed` refetch), each shipped with GREEN unit tests
> (`test_oxdna_staleness.py` / `test_md_staleness.py` / `roll_design_sync.test.js`) **yet the user reports the
> bug persists** (the manual feature-log seek doesn't clear the ⚠; the design/cursor don't visibly roll). That
> gap — **green piecewise tests + a broken real flow** — is the whole reason these AF items exist: the existing
> tests pin backend slices and isolated client functions, but NOTHING drives the genuine end-to-end path the
> user actually exercises, so the real failure mode is invisible to CI. The user's call (correct): **build the
> automation to detect/test/validate this rather than another manual back-and-forth.** So these oracles are NOT
> "wrap a working feature" — they are **the regression harness for a LIVE bug**, and must be written to **go red
> on the current build** (write the oracle first, confirm it FAILS, then fix until green). Because the failure
> is in the frontend wiring + DOM (refetch, rail-thumb, scene rebuild) where the backend already passes, the
> AF-26 oracle CANNOT be backend-only — it needs a real end-to-end leg (a Playwright/integration harness that
> drives the actual panel + Feature Log rail, Tier-F style), not just `headless_build` calls.

**Why now.** The 2026-06-23/24 out-of-date-job feature (a design edit after a sim run marks the job stale;
"Roll & run" SEEKS the feature-log cursor back to the run state; "Return to latest" restores it) is validated
only in **pieces** and its core primitive — the **feature-log seek** — has no headless entry point at all.
These two items close that: a navigable build timeline (text-to-design value) + the single end-to-end
regression guard for the staleness lifecycle (which originally manifested as an internal-server-error, and is
STILL not passing hand-check — see the callout above). Both ride the ALREADY-SHIPPED routes + the AF-13
mock-binary path (no GPU) for the backend legs. The browser GESTURES (the ⚠ marker, the roll-or-cancel popup,
the rail-drag visual, live-follows-the-rolled-design) are the very things failing hand-check → `MV-OXSTALE` /
`MV-OXLIVEFIELD` (both PENDING/FAILING, not validated).

- [x] **AF-25 — headless feature-log SEEK wrapper + non-destructive-scrub oracle. SHIPPED 2026-06-24.**
  `headless_build.seek_features(position, sub_position=None)` + `automation_harness.assert_feature_seek(seek_fn,
  checkpoints)` (5 scrub invariants). Coverage 37→38. **The backend oracle did NOT pass first-run** — it went RED and
  exposed a real bug: `crud._topology_substitute` never restored the `overhangs` list from the seek snapshot, so
  seeking before an overhang-extrude left a dangling overhang → wrong `design_build_fingerprint` → the roll's
  clean-path fingerprint check failed (consistent with "⚠ doesn't clear after a back-seek"). FIXED (one line:
  `overhangs=snap_design.overhangs`). Full suite green. See `design_automation_log.md` AF-25 row. Original intake below.
- [x] **AF-25 (original intake — SHIPPED; full rationale retained) — headless feature-log SEEK wrapper + non-destructive-scrub oracle.** Route
  `POST /design/features/seek {position, sub_position}` EXISTS (`routes_feature_log.py`) + is UI-wired
  (`client.seekFeatures` → `feature_log_panel` rail), but has **no headless entry point** — so the design
  timeline can't be navigated programmatically, and the oxDNA/MD job-roll (which IS a feature-log seek) can't
  be driven end-to-end. **Shape:** a thin `headless_build.seek_features(position, sub_position=None)` wrapper
  running the *same* route service mouse-free (mirror the existing wrappers — no logic in `crud.py`).
  **Augment = NEW `assert_feature_seek(...)`** on a multi-entry built design (bundle → auto-scaffold →
  assign-sequences → overhang, all now logged) asserting the scrub invariants: (1) **non-destructive** —
  `len(feature_log)` unchanged after a back-seek (unlike revert, which truncates); (2) **cursor lands** at the
  requested position; (3) **faithful reconstruction** — `design_build_fingerprint` at position P equals the
  design as captured when P was the last active op (recorded forward); (4) **reversible** — `seek(P)` then
  `seek(-1)` returns to the latest fingerprint exactly; (5) **effect removal** — seeking BEFORE a logged op
  drops its effect (the overhang's strands/helix gone; sequences cleared before `assign-scaffold-sequence`).
  **Validation gained, not a passthrough:** first programmatic proof the timeline scrub reconstructs + reverses
  faithfully and non-destructively — the missing primitive under "roll to a job's run state", and a navigable
  build history for text-to-design. Can-go-red: a seek that truncates the log, lands the cursor wrong, or whose
  fingerprint ≠ the recorded forward state.
  **MV status: the in-app seek-driven roll is currently FAILING hand-check** (the user reports the ⚠ doesn't
  clear / the cursor doesn't move). The backend seek route itself was verified to reconstruct correctly on
  `6hb_sim_tests`, so AF-25's backend oracle may well pass first-run — that's a SIGNAL the bug lives past the
  route (frontend refetch/render), so do NOT stop at a green backend oracle: it's the prerequisite primitive,
  and AF-26 is where the real-flow red must be produced.

- [x] **AF-26 — SHIPPED 2026-06-24 (backend + real e2e leg). "job/feature-log sync" COMPLETE.** The Playwright
  leg `frontend/e2e/job_log_sync.spec.js` drives the REAL oxDNA panel + a real overhang edit + a real feature-log
  seek and asserts on the rendered DOM: the seeded job shows no ⚠ initially → ⚠ appears after the overhang edit →
  **⚠ clears after the manual seek back + the model rolls (overhang gone, cursor at run position)**. Seeded GPU-free
  via `tests/e2e_seed_af26.py` (completed job + matching .nadoc into the workspace; self-cleaning). Two minimal
  panel testability hooks added (`data-job-id` on the row, `.oxdna-job-stale-warn` class). **CAN-GO-RED PROVEN in the
  browser:** reverting the `overhangs=snap_design.overhangs` line in `_topology_substitute` makes the spec fail at the
  post-seek assertion (⚠ stays) — the exact reported bug. Restored → green. smoke + panel vitest green. Also fixed:
  the running dev backend was on stale code (pre-`design_fingerprint` OxdnaJob) and silently dropped fingerprinted
  jobs — restarted it. Original intake below.
- [x] **AF-26 — BACKEND LEG + real e2e Playwright leg BOTH SHIPPED 2026-06-24 (detail retained).** Wrappers
  `headless_oxdna_build.roll_job_to_run_state(job_id, workspace)` + `headless_build.return_to_latest(loadout_id)` +
  `automation_harness.assert_roll_return_lifecycle(...)` driving the full simulate→edit→roll→return loop incl. the 409
  guard, pinned by `test_oxdna_staleness.py::test_af26_roll_return_lifecycle_overhang_edit` (overhang edit). Coverage
  38→39 (select_loadout) + oxDNA 4→5 (roll-design). **CONFIRMED the spec's prediction:** the backend oracle stays GREEN
  even with the AF-25 fix reverted — `roll_active_to_job_state`'s snapshot-overlay fallback already clears the flag
  backend-side, so the live bug is in the FRONTEND. **NEXT: the real Playwright e2e leg** over the actual oxDNA/MD
  panel + Feature Log rail (load → relax → edit → ⚠ → Roll → assert ⚠ clears + cursor moves + model reverts; and the
  manual rail-seek path), made to go RED on the running app first. NOTE: AF-25's `_topology_substitute` fix repaired the
  backend half of the manual-seek path (seeked fingerprint now correct) — the e2e leg must determine whether the app's
  refetch/rail-thumb/scene-rebuild still mis-renders. See `design_automation_log.md` AF-26 row. Original intake below.
- [x] **AF-26 (original intake — SHIPPED; full rationale retained) — headless job-staleness ROLL/RETURN lifecycle wrapper + the simulate→edit→roll→return oracle.**
  The whole "run a sim → edit the design → job goes out-of-date → roll the design back to the run state → run →
  return to latest" loop is the regression guard for the out-of-date feature (which originally crashed with an
  internal-server-error), but it's only validated in PIECES, never as one driven lifecycle. Routes EXIST:
  `POST /oxdna/jobs/{id}/roll-design` + `/md/jobs/{id}/roll-design` (seek-to-run-state + a "Latest" return
  loadout) + `/design/loadouts/{id}/select?save_current=false` (return). **Shape:** headless wrappers
  `roll_job_to_run_state(job_id)` + `return_to_latest(loadout_id)` (`headless_oxdna_build.py` /
  `headless_build.py`) composing the AF-13 relax wrapper + AF-2 edit wrappers + AF-25 seek. **Augment = NEW
  `assert_roll_return_lifecycle(...)`** running the full path and asserting at each leg: after an edit the job
  is `out_of_date=True`; **a live/production attempt on the stale job is REFUSED (409)** — the guard that
  replaced the crash; after roll `out_of_date=False`, the cursor sits at `job.feature_log_position`, the full
  log is kept, the topology reverts (overhang gone) while **sequences survive** (the now-logged assign-sequence
  ops); after return-to-latest the design is back to the edited state (overhang present). **Validation gained:**
  first end-to-end automated proof of the staleness→roll→return contract incl. the 409 crash-guard — the single
  regression the feature lacked. Reuses AF-13's mock-binary path (no GPU) for the backend legs. Can-go-red: a
  stale job that runs without refusal, a roll that doesn't move the cursor / clear the flag / preserve the log,
  or a return that loses the edits.
  **MV status: this lifecycle is currently FAILING hand-check (2026-06-24) and the bug persists across multiple
  fix rounds whose unit tests all went green** — so this item's PURPOSE is to reproduce that failure
  automatically, not to bless a working feature. **Write the oracle to go RED on the current build first**, then
  fix until green (the anti-shovel contract, sharpened: a green-first-run oracle here is a FALSE PASS — it means
  the harness isn't exercising the path the user is). Because every backend slice already passes while the app
  fails, the failing leg is the **frontend** (the panels' refetch on a `nadoc:design-changed` from a manual
  rail-seek; the Feature Log rail-thumb position; the scene rebuild) — so AF-26 needs a **real end-to-end leg**
  (a Playwright/integration harness driving the actual oxDNA/MD panel + Feature Log rail and asserting the ⚠
  clears + the cursor moves + the model reverts), NOT a backend-only `headless_build` oracle. This is the
  deliverable the user explicitly asked for: automation that DETECTS this class of bug so future fixes are
  proven, ending the manual back-and-forth.

### Tier F — frontend display subsystems (no REST route; JS-controller API + vitest-oracle augment)

**What's different here.** These subsystems are driven entirely client-side (a JS controller exposed on
`window.__*`), so the augment is **vitest oracles reading real Three.js state**, NOT a `headless_build`
wrapper. The anti-shovel rule still bites: assert the setter drove the *object* (a scene-graph light, a
`material.metalness`, a `pass.enabled`, a `camera.fov`), never `getSettings()` (which just echoes stored
intent → a passthrough). Bound by `FEATURE_DEVELOPMENT.md` — lands in the subsystem module + its
`*.test.js`, never a god-file.

- [x] **AF-ATOM (Phase 2) — renderer↔audit parity. SHIPPED 2026-06-21.** `frontend/src/scene/atomistic_renderer.test.js`
  (+1, now 4): drives a bond set with known lengths through `applyPositionLerp` and asserts, by decomposing each
  bond InstancedMesh instance matrix, that the renderer zero-scales (hides) EXACTLY the >`_MAX_BOND_NM` (1 nm)
  bonds — the same set the backend audit reports as `hidden_by_renderer` (both use the 1 nm cutoff) — and draws
  every other stick at its true atom-distance (scaleY). **Validation gained:** the on-screen sticks are now tied
  to the audited model bond-for-bond, so a renderer regression (wrong cutoff/transform) is caught, not invisible.
  Original intake below.
- [ ] **AF-ATOM (Phase 2, original intake) — renderer↔audit parity.** AF-ATOM P1 validates the atomistic *model*; the *render* parity is now P2 (shipped, above).
  `atomistic_renderer.applyPositionLerp` hides bonds > `_MAX_BOND_NM` (1 nm) by zero-scaling the bond
  InstancedMesh instance. **Enabling fact:** the renderer can be built in jsdom with a real model + fake GL;
  the bond InstancedMesh `setMatrixAt` scales are readable. **Oracle:** drive a frame with N known >1 nm bonds,
  assert the renderer zero-scaled EXACTLY those N instances (the `hidden_by_renderer` set from the backend
  audit) and drew all others at a finite length spanning the correct two atom positions — closing "the stick
  you see is the bond the audit measured, and the bond you DON'T see is hidden, not lost." Anti-shovel: assert
  the InstancedMesh matrix (the real object), never a settings echo. Lands in
  `frontend/src/scene/atomistic_renderer.test.js`. **Validation gained:** first proof the render matches the
  audited model bond-for-bond — today a renderer regression (wrong cutoff, wrong transform) is invisible.
<a id="af-atom-p3"></a>
- [ ] **AF-ATOM (Phase 3) — per-atom sphere coverage oracle.** Assert every drawn atom-sphere instance's
  radius (element→VDW) + color (element→CPK) matches the model's element mapping, so no atom renders with the
  wrong size/color. Lower priority than P2 (spheres are less bug-prone than bonds). Lands in the renderer test.
- [x] **AF-ATOM-CLOSURE — display-time backbone closure (the FIX for the stretched O3'→P sticks). SHIPPED
  2026-06-21** (user-authorized the geometry fix).  Root cause (measured): the stretch is **systematic, not
  fraying** — on the real 6hb_sim_tests relaxed frame the sequential O3'→P gaps are ideal 0.166 nm but relaxed
  **median 0.91 nm / 95% > 0.6 nm**, because oxDNA's per-nucleotide CG frames don't enforce all-atom backbone
  continuity, so each rigidly-stamped O3'(i) misses P(i+1).  Fix: `atomistic._close_sequential_backbone`, gated
  on `frame_override` + `close_backbone=True` (DISPLAY path only — design/PDB/NAMD-seed byte-identical), re-seats
  only the phosphate linker (O3'/P/O5'/OP1/OP2) between the rigid C3'(i)/C5'(i+1) anchors via the validated
  `_interpolate_backbone_bridge` (linear, ~0.01 s for ~1000 bonds — 2000× faster than the L-BFGS bridge and
  slightly better; the ribose ring + base never move, so the rigid-stamp invariant holds).  **Audit-verified
  (the oracle IS the acceptance test):** backbone mean 1.005→0.185 nm, max **3.155→0.806 nm**, **hidden-by-
  renderer 266→0** (the whole backbone now draws connected — no long sticks, none silently hidden), rigid-stamp
  still 0 violations.  Residual: ~744 mild over-stretches (0.20–0.81 nm) + clashes at genuinely-frayed/tightly-
  packed regions — inherent to un-minimised CG→all-atom display, honestly surfaced by the audit (a full display
  minimisation would be the next step; out of scope).  Pins: `tests/test_atomistic_validation.py::test_backbone_
  closure_connects_and_preserves_rigid` + the P1 audit on the real job.  **Live visual is human-eye → MV-OXREPS.**

- [x] **AF-PHOTO (P-A + P-B) — photomode option-coverage + effect oracles. SHIPPED 2026-06-18.** `frontend/src/scene/photo_renderer.test.js` (39 tests): P-A drives each setter and asserts the REAL object (renderer.toneMapping/exposure, scene-graph lights, `material.metalness`, `camera.fov`, composer `pass.enabled` via the new `getComposerState()`); P-B is the automation contract (getSettings is a copy; a 21-case table proves every option is settable through the API + every key persists). Shipped alongside the R1–R5 render fixes from the audit (tone mapping + exposure, Sun-sole, env re-bake isolation, emissive bloom clamp, Reflector state isolation). Remaining: P-C GPU-truth e2e → `MV-PHOTO-1`/`MV-PHOTO-2` (manual-validation debt). Below is the original intake item.
- [x] **AF-PHOTO — photomode option-coverage + effect oracles. P-A + P-B SHIPPED 2026-06-18 (row above); only P-C (GPU-truth e2e) remains and is routed to manual-validation debt as `MV-PHOTO-1`/`MV-PHOTO-2`, NOT an active AF item.** Photo mode
  ([frontend/src/scene/photo_renderer.js](frontend/src/scene/photo_renderer.js), ~1588 ln, ~45 setters on
  `window.__photoRenderer`) has **zero test coverage**; no automated proof any option takes effect, nor that
  the full option surface is reachable + persisted programmatically. **Enabling fact:** the controller can be
  built in jsdom with a real scene/camera + fake renderer and `activate({environment:'off'})`; the
  `EffectComposer` + passes *construct* without GL (only `.render()` / PMREM baking need WebGL), so even
  `bloomPass.enabled` / inscatter uniforms are vitest-assertable. **Phases:** (P-A) table-driven per-setter
  effect oracles in a new `photo_renderer.test.js` — see catalogue in `photo_mode_audit_plan.md` Part 3;
  (P-B) automation-contract oracles — setter⇄`getSettings` completeness + full profile round-trip; (P-C,
  MV-debt) GPU-truth e2e incl. the **yellow/purple no-tint regression** that guards the R1–R3 render fixes.
  **Validation gained, not a passthrough:** first proof photomode options reach the GPU-facing objects + the
  whole surface round-trips. Plan + per-setter table + the R1–R5 render-bug remediation in
  **`photo_mode_audit_plan.md`** (repo root, from the 2026-06-18 audit). Two MV rows queued:
  `MV-PHOTO-1` (no-tint regression render), `MV-PHOTO-2` (mid-session env-change garbage-frame guard).

### Appendix — genuinely UI-only (route these to manual-validation debt, NOT here)

Operations with no coord-taking route — they can only be hand-validated. When an AF session confirms one
is un-headless-able, push an `MV-N` row to `manual_validation_debt.md` instead of an AF item:
- Instance/strand **selection + lasso multi-select** (client store state, no backend reflection).
- **Gizmo intermediate drags** (TransformControls partial states; only the *committed* transform has a route).
- Pure **view toggles** (coloring, labels, periodic-boundary view) — no design mutation, nothing to validate.
