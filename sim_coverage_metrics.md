# Sim-coverage loop — metrics + cross-engine agreement

Companion to [`SIM_COVERAGE_PLAN.md`](SIM_COVERAGE_PLAN.md). Two things live here: (1) a per-task metrics row
with the anti-shovel justification, and (2) the headline deliverable — the **cross-engine agreement table** that
fills in as milestones complete.

## Per-task metrics rows (one per shipped task)

> *Format: **`<TASK-ID>` — `<title>`** · shape (service / card / solver-change) · feature covered · engines now
> comparable · oracle shipped (fast/slow) · main.js LOC Δ · tests (pass count) ·
> **"Comparable prediction gained, not just a run: ___."**_

- **`S1` — engine-agnostic shape descriptors** · shape: new `backend/core` service (`shape_metrics.py`) +
  1 additive `oxdna_health` helper (no solver/card change) · feature: comparison-metric (the shared substrate) ·
  engines now comparable: *all four* can be fed the same descriptor set (the yardstick; actual comparison lands
  at S3) · oracle: `tests/test_shape_metrics.py` 9 tests **fast** (recover twist/arc-span, can-go-red) ·
  main.js LOC Δ = 0 · tests: 9/9 oracle, `just test-fast` 4057 passed (1 pre-existing xdist flake) ·
  **Comparable prediction gained, not just a run:** every engine's frame now maps to identical twist /
  bend-angle+radius / Rg / end-to-end numbers on the shared `(helix,bp,dir,copy)` substrate, so S3 can score
  agreement instead of comparing incommensurable per-engine metrics.

- **`S2` — unified deviation + RMSF profiles** · shape: 3 functions added to the `shape_metrics.py` service
  (no solver/card change) generalizing `cando_deviation.compute_deviation`, `oxdna_health.production_rmsf`'s
  variance core, and `fem_solver.normalize_rmsf` · feature: comparison-metric (the second shared substrate) ·
  engines now comparable: *all four* can be scored on identical per-nt deviation-from-design (+RMSD) and per-nt
  RMSF (CanDo via NMA, others via `rmsf_from_ensemble`) · oracle: `tests/test_shape_deviation_rmsf.py` 10 tests
  **fast** (rmsd 0 identical, exact non-rigid displacement recovery, Kabsch pose-removal, `A/√2` fluctuation
  round-trip, normalize round-trip) · main.js LOC Δ = 0 · tests: 10/10 oracle, `just test` 4128 passed / 66
  skipped / 1 xfailed (full suite, no drop) ·
  **Comparable prediction gained, not just a run:** any engine's frame(s) now yield the SAME per-nucleotide
  deviation (Kabsch-aligned, so pose is stripped and only real shape mismatch survives) and the SAME per-nt RMSF
  on the shared substrate — the two flexibility/shape yardsticks S3's `compare_descriptors` needs to report a
  Pearson r / signed Δ between two engines instead of comparing incommensurable per-engine numbers.

- **`S3` — cross-engine descriptor agreement** · shape: 2 entry points added to the `shape_metrics.py` service
  (`compare_descriptors` + `reference_for`; no solver/card change) composing S1's descriptors + S2's profiles ·
  feature: comparison-metric (the agreement math itself) · engines now comparable: any two engines yield a
  scored comparison — signed %Δ per shape descriptor, Pearson/Spearman on per-bp RMSF, Kabsch-aligned shape
  RMSD — with the reference picked per-observable by policy (oxDNA=shape/field, CanDo=RMSF, NAMD-override) ·
  oracle: `tests/test_shape_compare.py` 13 tests **fast** (identical→perfect, ±10° twist→±10% signed,
  scaled/reversed/constant RMSF correlation, rigid-pose-invariant shape RMSD, `reference_for` policy + override +
  missing→None, **CanDo dir-less vs oxDNA per-strand RMSF collapses to per-bp & correlates** — the review-caught
  fix) · main.js LOC Δ = 0 · tests: 13/13 oracle (32/32 S1+S2+S3), `just test` 4140 passed / 66 skipped /
  1 xfailed (1 pre-existing xdist flake, passes in isolation) ·
  **Comparable prediction gained, not just a run:** the loop's first cross-*validation* number — two engines'
  frames now reduce to an agreement score (%Δ, Pearson r, aligned RMSD) with a policy-chosen reference, so the
  question "do the quick and rigorous engines agree, and where do they diverge?" becomes computable the moment
  S5 wires it into the generate/view/export card.

- **`S4` — unified field-response descriptor** · shape: 2 entry points added to the `shape_metrics.py` service
  (`field_response_profile` + `compare_field_response`; no solver/card change) generalizing
  `oxdna_health.measure_field_response` · feature: **E-field** (the shared field-deflection substrate) · engines
  now comparable: any two engines' field responses yield a scored deflection comparison — cosine of the free-nt
  deflection fields + magnitude (compliance) ratio, plus a copy-aware per-nt deflection map + projection-along-
  field per engine · oracle: `tests/test_shape_field_response.py` 13 tests **fast** (anchors held + free deflect
  along field, monotone in |F|, fails on anchor-drift/no-deflection, copy-aware keys, cross-engine cosine
  +1/−1/0, magnitude-ratio=3.0 at 3× compliance, zero-field/no-free raise, no-shared-free→None) · main.js LOC
  Δ = 0 · tests: 13/13 oracle (45/45 S1–S4), `just test` 4155 passed / 66 skipped / 1 xfailed (full suite, no
  drop) ·
  **Comparable prediction gained, not just a run:** the E-field half of the cross-validation deliverable — two
  engines' responses to the same field now reduce to a deflection cosine + compliance ratio (does CanDo bend the
  way oxDNA does, and by how much?), the field-panel counterpart to S3's shape/RMSF agreement, ready for the S5
  card.

- **`S5` — cross-engine comparison CARD** · shape: new `backend/core` assembly service
  (`shape_compare.py::build_comparison_report`, pure) + daemon-thread route
  (`routes_shape_metrics.py`, `POST/GET /shape/compare`) + a thin frontend card
  (`shape_compare_card.js`) binding the shared `metric_graph`/`metric_export_modal` machinery (not rebuilt) ·
  feature: comparison-metric (the generate/view/export surface — closes M-METRIC-CORE) · engines now comparable:
  any set of engine source bundles renders as a scalar-delta table + RMSF overlay + agreement (RMSD/Pearson/
  Spearman) + E-field deflection panel, PNG/CSV-exportable · oracle: `tests/test_shape_compare_report.py` 14
  tests **fast** (per-observable reference incl. NAMD-override, scalar ±%Δ + zero-ref no-div0, identical RMSF→
  Pearson 1 + overlay pts, rigid-shift→shape-RMSD≈0, field cosine ±1 + mag-ratio 3, 1-engine/empty/missing-
  observable degradation, REST start→poll→404) + vitest `shape_compare_card.test.js` 9 (pure helpers + wiring) +
  one-off display-vs-oracle Playwright (displayed == backend oracle, deleted; live data → **MV-21**) · main.js
  LOC Δ = 0 (wired from `initOxdnaJobsPanel`) · tests: 15/15 backend oracle (60/60 S1–S5), 2200/2200 frontend,
  `just test` 4170 passed / 66 skipped / 1 xfailed (full suite, no drop) ·
  **Comparable prediction gained, not just a run:** the S3/S4 agreement math is now a first-class tool — one
  card GENERATES the cross-engine comparison for a design, VIEWS it (delta table + RMSF overlay + agreement +
  field panel), and EXPORTS it (PNG/CSV). M-METRIC-CORE closed; the per-engine emission tasks (O1/C5/M5/N4) now
  have a card to feed, so their cross-validation results become *reportable*, not just computable.

- **`O1` — oxDNA source bundle (first live card column)** · shape: new `backend/core` service
  (`oxdna_shape_source.py`, pure assembly) + thin route `GET /oxdna/jobs/{id}/shape-source` (routes_oxdna.py) +
  1 client fn + `getSources` wiring (no solver/card change — binds the S5 card) · feature: comparison-metric
  (oxDNA = the SHAPE + field reference column) · engines now comparable: **oxDNA is now a LIVE source** — a
  relaxed job's core-filtered descriptors + RMSF feed the card (was `getSources:()=>[]`); the moment C5 lands,
  oxDNA-vs-CanDo agreement computes with no card work · oracle: `tests/test_oxdna_shape_source.py` 7 tests
  **fast** (descriptors == `measure_bundle_twist(core)` self-consistent, core mask drops ssDNA ends, `rmsf`→
  `rmsf_nm` remap, field passthrough, drops into `build_comparison_report` as ready `oxdna` shape ref, RED empty-
  core→None) · main.js LOC Δ = 0 · tests: 7/7 oracle, `just test` 4177 passed / 66 skipped / 1 xfailed (no drop),
  vitest 2200/2200, smoke green · review-caught: descriptors are oxDNA's ABSOLUTE twist (cross-engine-comparable)
  not the differential twist the Graphs-&-Metrics card plots — docstrings + MV-21 corrected (claim, not bug) ·
  **Comparable prediction gained, not just a run:** the comparison card renders a REAL oxDNA column (a relaxed
  job's shared shape descriptors + RMSF, core-filtered to the rigid dsDNA core) instead of an empty source list —
  oxDNA is now the concrete reference every other engine's task will be scored against.

- **`C1` — CanDo FEM anchors (Dirichlet BC)** · shape: **solver-change** (`fem_solver.py`: generalized
  `apply_boundary_conditions` centroid-pin→arbitrary `fixed_nodes`; `solve_prestress_shape`/`predict_shape` thread
  anchors; new `resolve_anchor_nodes` reusing the shared `oxdna_interface.resolve_anchor_particles` scope
  resolver) · feature: **anchors** (CanDo — first of its four) · engines now comparable: CanDo can hold a resolved
  anchor exactly (u==0) under the eigenstrain — the boundary condition C2's field-deflection is measured against;
  same scope resolver as the oxDNA/mrDNA/NAMD anchor tasks (M1/N2) so "anchor scope X" = the same nucleotides
  across engines · oracle: `tests/test_cando_anchors.py` 10 tests **fast** (synthetic-beam pinned-held/free-moves,
  BC pins exactly the requested nodes / `[]`→centroid, resolver maps base+cluster & drops stale, prestress solve
  holds clamped node <1e-9 while rest deflects >1e-3, unresolved=no-op) · main.js LOC Δ = 0 · tests: 10/10 oracle,
  `just test` 4186 passed / 66 skipped / 1 xfailed (+1 known pre-existing job-archive xdist flaky, passes isolated);
  no card/UI → display-vs-oracle N/A · review-caught: none (honest note — the free-free-RMSF assertion is
  green-by-construction, consistent w/ the stated oracle; positions no-op is load-bearing) ·
  **Comparable prediction gained, not just a run:** the CanDo FEM can now clamp a tethered node and predict the
  *anchored* equilibrium shape (rest of the bundle deflects, anchor held to 1e-9) — the anchored boundary
  condition every anchored-field cross-validation needs, unblocking C2 and the M-CANDO-FIELD milestone.

- **`C2` — CanDo FEM uniform E-field** · shape: **solver-change** (`fem_solver.py`: new `assemble_field_force`
  uniform body load; `field=` threaded through `solve_prestress_shape` + `predict_shape`; `FEM_FIELD_CHARGES_PER_NODE`
  const) · feature: **E-field** (CanDo — second of its four) · engines now comparable: CanDo predicts the
  **field-deflection regime** (anchored tethered-arm, free deflects along field, monotone in |E|) from the SAME
  per-nucleotide `{field_pN, dir}` force oxDNA applies — the shared **S4** `field_response_profile` now scores both
  from one load · oracle: `tests/test_cando_field.py` 7 tests (3 `assemble_field_force` unit props **fast**;
  4 end-to-end nonlinear-solve property tests **slow**) — anchors held (drift≈0) + free proj≥0.5nm along field +
  monotone (fp 0.05→5.2nm, 0.1→10.4nm) + zero-field→no-deflection RED, measured on the **RAW clamped-solve frame**
  (not the Kabsch-reposed display frame) · main.js LOC Δ = 0 · tests: 7/7 oracle, `just test` 4194 passed / 66
  skipped / 1 xfailed (no drop); no card/UI → display-vs-oracle N/A · review-caught: none (honest note —
  `predict_shape(field=)`'s S4 verdict is proven indirectly via the shared `solve_prestress_shape(field=)`) ·
  **Comparable prediction gained, not just a run:** the cheap CanDo FEM now reproduces oxDNA's anchored
  field-deflection (along-field, monotone, same per-nt force) scored by the shared S4 descriptor — **closes
  M-CANDO-FIELD**; a real oxDNA-vs-CanDo field agreement number is one C5 field-source wiring away.

- **`C5` — CanDo source bundle (second live card column)** · shape: new `backend/core` service
  (`cando_shape_source.py`, the twin of O1's `oxdna_shape_source`) + new `GET /cando/jobs/{id}/shape-source`
  route + frontend `getSources` now merges the CanDo source with the oxDNA one (no solver/card-machinery change —
  binds the existing S5 card) · feature: comparison-metric (CanDo joins the shared card; the RMSF reference
  column) · engines now comparable: **oxDNA ↔ CanDo** — the S5 card now carries two live sources, so it emits
  the first real cross-engine agreement: CanDo's absolute shape descriptors + aligned-shape RMSD vs the oxDNA
  shape reference, and oxDNA's RMSF Pearson/Spearman vs **CanDo as the RMSF reference** (dir-less CanDo NMA RMSF
  pairs with oxDNA per-strand ensemble RMSF via the S3 per-bp collapse) · oracle:
  `tests/test_cando_shape_source.py` 7 tests (6 pure **fast** incl. the `[oxdna,cando]`→`build_comparison_report`
  integration: refs shape=oxdna/rmsf=cando, shape-RMSD≈0 on rigid shift, RMSF Pearson 1.0 n=24; 1 real-
  `predict_shape` **slow**) · main.js LOC Δ = +4 (pure wiring: lazy `getCandoJob` dep + capturing the CanDo
  panel's return) · tests: 7/7 oracle, `just test` 4206 passed / 66 skipped / 1 xfailed (no drop), vitest 2214,
  smoke green · display-vs-oracle: the two-engine card rendering was S5-scraped (synthetic); C5 wires the real
  route into that validated path → live eyeball = MV-21 (updated) ·
  **Comparable prediction gained, not just a run:** the comparison card now produces the **first real oxDNA-vs-
  CanDo agreement numbers** — two independent structure predictors (rigorous CG vs cheap FEM) cross-validate on
  the same design through one shared generate/view/export card, with per-observable references (oxDNA=shape,
  CanDo=RMSF).

- **`C3` — extra crossover bases as compliant connectors** · shape: **solver-mechanism was pre-existing** (an
  extra-base crossover meshes as a 2-node WLC ssDNA spring in `build_fem_mesh`, shipped untested in Phase-5); this
  task = the missing property **oracle**, no production change · feature: extra-bases (CanDo's 4th feature) ·
  engines now comparable: CanDo emits a measurable extra-base **flexibility** prediction (local RMSF ↑) scored
  through the shared S3 RMSF channel → an oxDNA/NAMD ensemble RMSF at the same inserts can cross-validate it ·
  oracle: `tests/test_cando_extra_bases.py` 4 tests (3 **fast**: mesh census spring-vs-rigid-link + `k∝1/L_c`
  monotone + synthetic 2-node compliance `u==F/k_trans` ≫ `F/K_PENALTY`; 1 **slow**: band-of-inserts → real
  `predict_shape`+NMA local RMSF ~1.87× up, every affected node, RED-guard self-vs-self flat) · main.js LOC Δ = 0
  (backend-only) · tests: 4/4 oracle, `just test` 4210 passed / 66 skipped / 1 xfailed (was 4206, +4, no drop),
  ruff clean; fresh-context review no gaps · display-vs-oracle: N/A (no card/UI, like C1/C2) ·
  **Comparable prediction gained, not just a run:** extra crossover bases now produce a proven, correct-sign
  CanDo prediction — inserts soften the local junction (WLC connector `~1e5×` more compliant than the rigid link)
  and the FEM predicts ~1.87× higher local per-bp RMSF there, a flexibility signal directly comparable to any
  engine's ensemble/NMA RMSF at the same ssDNA inserts. **NO twist/bend direction asserted** (softening a
  distributed load is non-monotone; geometric crossover reasoning forbidden — RMSF is the sign-safe channel).

- **`C4` — linkers / overhang connections as connector elements** (CLOSES M-CANDO-COMPLETE) · shape: two additive
  `build_fem_mesh` changes, backend-only — (1) `_duplex_bp_per_helix` now `(scaf∧stap) ∪ (fwd∧rev∧linker)` so a
  linked overhang (staple∧linker) + a ds `__lnk__` bridge (linker∧linker) are recognized as duplex, **byte-
  identical on linker-free designs** (the `∧linker` gate → zero exp36 regression); (2) `_add_linker_hops` couples
  each LINKER strand's helix-hop junctions — **ds → rigid link** (stiff duplex bridge), **ss → WLC spring**
  (`k_rot=0`, contour = ssDNA-run × `RISE_SS`) · feature: linkers (CanDo's 4th unconventional feature) · engines
  now comparable: CanDo predicts **inter-part mechanical coupling** through a linker (a ds bridge transmits a load
  stiffly, a ss tether compliantly) — a coupling any engine that meshes/beads the same generated linker topology
  (M4/N3) can cross-validate · oracle: `tests/test_cando_linkers.py` 5 **fast** (synthetic two-part coupling
  bright line: WLC linker → part B moves, no linker → exactly 0, rigid `>10×` soft; additive-no-regression dict
  equality vs legacy `scaf∧stap`; real ds duplex-bridge+rigid-hop connectivity to BOTH overhang helices; real ss
  single +1 WLC spring across the two overhang helices) · user clarification reframed the task (a linked overhang
  is DUPLEX; ask-first) · main.js LOC Δ = 0 (backend-only) · tests: 5/5 oracle, `just test` 4215 passed / 66
  skipped / 1 xfailed (was 4210, +5, no drop), FEM+exp36 calibration guards green, ruff clean; fresh-context
  review both changes correct+additive, strengthened 2 flagged oracle tests · display-vs-oracle: N/A (no card/UI,
  like C1/C2/C3) ·
  **Comparable prediction gained, not just a run:** a linker is no longer invisible to the FEM — the CanDo FEM now
  predicts how a ds vs ss overhang-connection couples two parts (stiff duplex bridge vs compliant WLC tether),
  completing CanDo's coverage of all four unconventional features and closing **M-CANDO-COMPLETE**.

- **`N2` — NAMD anchors (fixedAtoms)** (M-ALL-ANCHORS-FIELD track) · shape: backend anchor plumbing +
  request field + MD-panel picker — anchors ride NAMD `fixedAtoms` (Dirichlet hold), orthogonal to the
  slow-release `conskfile` restraint (NAMD allows only one), so they persist immobile across the ladder ·
  resolver `resolve_anchor_residue_indices` reuses the SHARED `resolve_anchor_particles` scope resolver (same
  one oxDNA + the CanDo FEM use) → `(helix,bp,dir)` keys → built-PDB residue ORDINALS via `Atom` provenance;
  `write_anchor_restraints_pdb` marks B=1 on exactly those residues' heavy atoms · feature: anchors (NAMD's
  anchor coverage; substrate for N1's anchored E-field) · engines now comparable: NAMD can hold a resolved
  region fixed with the SAME scope descriptors CanDo/oxDNA use → the anchored-field deflection descriptor is
  now expressible for NAMD too (toward M-ALL-ANCHORS-FIELD) · oracle: `tests/test_namd_anchors.py` 11 (9 fast
  + 2 slow): base→exactly-that-nucleotide / strand→all-its-residues / stale→∅; marker marks EXACTLY the
  resolved residue ordinals (heavy only, H free, HETATM never, RED empty→0); conf emits fixedAtoms only with
  anchors; SLOW real-psfgen prepare marks-exactly + wires every ladder conf + manifest; SLOW 176-strand
  `export_pdb` divergence proof · REVIEW-CAUGHT HIGH (fixed): the ordinal bridge must mirror WHICH generator
  built the package PDB — `export_pdb` (natural chain order) vs psfgen (sorted) diverge past 26 strands;
  `sort_chains`/`full_topology` selects the match, proven on 176 strands · main.js LOC Δ = +1 (getSelection
  wiring) · tests: 11/11 oracle, `just test` 4226 (was 4215, +11, no drop), ruff clean on touched, vitest 2214, smoke
  render/console-error gate green · display-vs-oracle: N/A (anchor card is an INPUT picker, not a prediction
  display) · live picker gesture NOT hand-driven (no GPU MD job) → MV row ·
  **Comparable prediction gained, not just a run:** NAMD can now hold a specific resolved region immobile
  using the same anchor scopes as CanDo/oxDNA, so an anchored region's "held vs deflected" is a comparable
  cross-engine descriptor for NAMD — the anchor half of M-ALL-ANCHORS-FIELD (with C1 done), and the substrate
  N1's anchored E-field run needs to hold against COM drift.

- **`N1` — NAMD native E-field (eFieldOn/eField)** (M-ALL-ANCHORS-FIELD track) · shape: backend field conversion
  + emission plumbing + request field + MD-panel picker (no solver/card) — `namd_efield_vector({field_pN,dir})`
  converts the SHARED per-nucleotide force descriptor to NAMD's native `eField` (`q·E`, exact: a DNA nucleotide
  carries −1 e, so no effective-charge fudge — in explicit solvent the counterions screen the field themselves);
  `external_forces_block` is the ONE emitter carrying both N2's `fixedAtoms` and the field into every conf writer
  (segment/min/both production/shell-reprep/resume) · feature: E-field (NAMD's field coverage; reuses N2's anchor
  plumbing for the anchored run) · engines now comparable: NAMD drives every nucleotide with the SAME `field_pN`
  oxDNA(S4)/CanDo(C2)/LAMMPS use → a NAMD field-deflection descriptor is now on the same tethered-arm scale as the
  others · oracle: `tests/test_namd_efield.py` 24 (fast: unit constant from 1st principles, F=q·E inversion pins
  magnitude+sign+normalisation, no-op cases, emission on all 4 writers, byte-identical zero-field, remote+local
  resume preserve field+anchors, 3 REST guards; slow: real psfgen −1 e internal + terminal-deficit measured,
  unresolvable-anchor raise, **real-NAMD differential probe** — fixed atoms move 0, free ΔCOM cosine 0.99996 along
  +field, \|ΔCOM\| within 10% of `½(F/M)t²` from `field_pN`×NAMD's-own −7 e) · REVIEW-CAUGHT HIGH (fixed): API
  guard counts anchor CHIPS → a scope that resolves to ∅ would launch the COM-drift run; prep now raises. Two
  production writers dropped anchors since N2; shell-reprep read them from an empty manifest — both fixed · main.js
  LOC Δ = 0 (card = 2nd instance of the shared `initCandoEfieldSetup`, `ids`-parameterised) · tests: 24/24 oracle,
  `just test` 4328 passed / 72 skip / 1 xfail (no drop), ruff clean on touched, vitest 2294 (+5), smoke green
  (1 pre-existing assembly_exit flake, passes isolated) · display-vs-oracle: N/A (field card is an INPUT picker) ·
  live card render+toggle+V/m-grid+ready-readout HAND-VERIFIED in the running app (throwaway spec, deleted) →
  MV row · independence RED-check: doubling `KCAL_MOL_A_IN_PN` makes REAL NAMD falsify the magnitude assertion ·
  **Comparable prediction gained, not just a run:** NAMD now applies the exact same per-nucleotide force the other
  three engines do, and a real short run's field-isolated deflection points along the field with the magnitude its
  own force-field charges predict — so NAMD's field-deflection descriptor is directly comparable to oxDNA's (the
  field reference) and CanDo's on the tethered-arm regime. Completes NAMD's anchor+field pair; M-ALL-ANCHORS-FIELD
  now needs only mrDNA M1 (anchors) + M2 (field).

- **`M1` — mrDNA anchors (ARBD RESTRAINT)** (M-ALL-ANCHORS-FIELD track) · shape: backend anchor plumbing, no
  card — `backend/core/mrdna_anchors.py` maps the SHARED `resolve_anchor_particles` scopes → per-nt keys → the
  nearest CG bead by 3D POSITION (mrDNA groups helices by base-pairing not NADOC helix id, and collapses each bp
  to one forward bead, so name/ordinal maps are unreliable — position via the input `r`-array, both in Å same
  frame), pins each with an ARBD harmonic `RESTRAINT`, and `install_anchor_restraints` wraps `generate_bead_model`
  so the restraints survive mrDNA's `clear_beads()`+regeneration between multiresolution stages · feature: anchors
  (mrDNA's anchor coverage; the substrate M2's anchored field will need against COM drift) · engines now
  comparable: mrDNA can now HOLD a resolved scope the same way CanDo (C1 Dirichlet BC) + NAMD (N2 fixedAtoms) do,
  off the same scope resolver → "anchor scope X" = the same nucleotides across all three · oracle:
  `tests/test_mrdna_anchors.py` 6 fast + 1 slow (fast: **real ARBD `.restraint.txt` via `simulate(dry_run)` carries
  a line for EXACTLY the resolved beads**, idx pinned flat==ARBD-`.idx`, stale→∅, regen-survival RED-checked 0-vs-≥1;
  slow: real ARBD coarse run holds 10/60 beads at 0.55 Å vs free 3.81 Å = **7×**) · main.js LOC Δ = 0 (backend
  only) · tests: 7/7 oracle, `just test` 4334 passed / 72 skip (+6 over 4328; lone failure was the slow test's
  output-path assumption — mrdna writes PSF to run dir, DCD under `output/` — fixed, green in isolation), ruff
  clean on touched files · display-vs-oracle: N/A (headless anchor entry point, no card) · fresh-context review:
  no gaps (frame/units, per-regen re-apply, Three-Layer, true end-to-end FAST check all verified) ·
  **Comparable prediction gained, not just a run:** a mrDNA CG run now holds a chosen scope (7× hold/move) while
  the rest relaxes — the anchored-region prediction C1/N2 already emit, on the SAME resolver — and unblocks M2's
  anchored-field cross-validation, the last piece of M-ALL-ANCHORS-FIELD.

- **`M2` — mrDNA uniform E-field (ARBD grid-potential force)** (CLOSES M-ALL-ANCHORS-FIELD) · shape: backend field
  plumbing, no card — `backend/core/mrdna_field.py` turns the SHARED `{field_pN, dir}` per-nucleotide descriptor
  into a constant per-bead force = `field_pN × (nt in bead) × (pN→kcal/mol/Å) × dir̂`, with `nt in bead =
  bead_mass/dalton_per_nucleotide` (DNA beads carry charge 0, so force is applied directly, not q·E), delivered
  through ARBD's per-`ParticleType` grid potential — a linear ramp `U=-(F·r)` via `add_grid_potential`/`gridFile`
  whose negative gradient is the uniform force (the `forceXGrid` tabulated-force path CRASHES ARBD on a constant
  grid; the ramp-potential idiom is the fix). Total applied force = `field_pN × total_nt` exactly. `install_field_force`
  wraps `generate_bead_model` so the grids re-attach to fresh `ParticleType`s after mrDNA's bead regeneration
  (idempotent). `MrdnaJob.e_field` + route `field` + guards (malformed/zero→400 incl non-numeric; field-needs-anchor
  guard REMOVED 2026-07-10 — unanchored field allowed + UI-warned, runner logs a drift warning instead of raising on 0
  held beads, see [[project_oxdna_efield]]) + runner install after anchors · feature: E-field
  (mrDNA's field coverage; needs M1's anchors to hold against drift) · engines now comparable: mrDNA now runs an
  anchored uniform-field job producing an along-field deflection descriptor the same way CanDo (C2 nodal q·E) +
  NAMD (N1 eField) do, off the SAME per-nt force descriptor · oracle: `tests/test_mrdna_field.py` 9 fast + 1 slow
  (fast: per-bead force vs **FIRST-PRINCIPLES** pN→kcal/mol/Å — not the code constant, so a wrong constant fails;
  2×mass→2×force; ramp `.dx` round-trip `-∇U==F`; per-type grid wiring; dry-run conf emits `gridFile field_*.dx`;
  regen-survival RED-checked; 2 REST guards. slow: **real ARBD, field-on vs off, one strand anchored** — anchored
  held (~0.5 Å) while free bulk deflects ALONG +field (~8.5 Å vs field-off ±2 Å wander), magnitude within
  [0.45,2.0]× the overdamped Brownian prediction `D·F·T/(k_B·T)` from the engine's OWN diffusivity/mass + field_pN
  via the first-principles constant, ~12% agreement observed) · main.js LOC Δ = 0 (backend only) · tests: 10/10
  oracle, `just test` 4345 passed / 72 skipped / 1 xfailed (fresh full suite; +11 over the M1 4334 baseline, no drop), ruff clean on touched files ·
  display-vs-oracle: N/A (headless field entry point, no card) · fresh-context review: product code correct; the
  three review findings all fixed (runner 0-held-beads guard, slow-oracle prediction made independent of the
  emission constant, malformed-type field → 400) ·
  **Comparable prediction gained, not just a run:** a mrDNA CG run now DEFLECTS a resolved free region ALONG a
  uniform field (held anchor, ~8.5 Å along-field vs ±2 Å off), at ~12% of the overdamped Brownian prediction from
  its OWN mobility — the same anchored-field deflection CanDo (C2) + NAMD (N1) emit, off the SAME per-nt force
  descriptor — closing **M-ALL-ANCHORS-FIELD**: all three job engines (CanDo, NAMD, mrDNA) now run an anchored
  E-field job with a comparable along-field deflection descriptor.

- **`M5` — mrDNA source bundle (THIRD live card column) + CG-trajectory RMSF** · shape: new `backend/core`
  service (`mrdna_shape_source.py`, the twin of O1/C5) + new `mrdna_runner.mrdna_trajectory_rmsf` (per-frame
  reconstruction → shared S2 `rmsf_from_ensemble`) + new `GET /mrdna/jobs/{id}/shape-source` route + frontend
  `getSources` now merges the mrDNA source → `[oxdna, cando, mrdna]` (no solver/card-machinery change — binds the
  S5 card) · feature: comparison-metric (mrDNA joins the shared card; a candidate for all observables) · engines
  now comparable: **oxDNA ↔ CanDo ↔ mrDNA** — a THIRD independent engine on the card: mrDNA's absolute CG-relaxed
  shape descriptors + aligned-shape RMSD vs the oxDNA shape reference + a CG-trajectory RMSF (the trajectory-
  variance source the descriptor set names for mrDNA) · **copy-key gap fix**: `_display_positions`' string-bp
  `__xb__` inserts (which crash the shared `_dev_key` `int(bp_index)`) drop out via `_core_column_key` (shape) +
  `_rmsf_profile`'s non-int skip (rmsf) · oracle: `tests/test_mrdna_shape_source.py` 8 fast + 1 slow (fast incl.
  the COPY-KEY coverage — string-bp `__xb__` inserts build a valid bundle, RED if the guard is gone; the real
  trajectory-RMSF path via monkeypatched reconstruction+fake traj length: subsamples to `max_frames`, int keys
  feed `rmsf_from_ensemble`, <2-frame→None; `[oxdna,mrdna]`→`build_comparison_report` ready, shape ref=oxdna,
  shape-RMSD≈0 on rigid shift; slow: real ARBD coarse run → trajectory RMSF n_frames≥2 → ready source) · main.js
  LOC Δ = +4 (pure wiring: lazy `getMrdnaJob` dep + capturing the mrDNA panel's return) · tests: 8 fast + 1 slow
  oracle, `just test` 4352 passed / 72 skipped / 1 xfailed **+ 1 documented xdist active-design flake**
  (`test_namd_efield::test_no_field_skips_both_guards` — reads global `design_state` another file left; passes
  isolated + alongside the new file; additive mrDNA/card code never touches `design_state`), vitest 2294, smoke
  23 green · display-vs-oracle: the multi-engine card rendering was S5-scraped (synthetic); M5 wires the real
  route into that validated path → live eyeball = MV-21 (updated) · fresh-context review: product CONFIRMED-
  CORRECT; flagged the RMSF `__xb__` guard as defending an impossible production input → addressed with the fast
  trajectory-RMSF pin + honest docstring (gap's real locus = shape column) ·
  **Comparable prediction gained, not just a run:** the comparison card now carries a THIRD independent engine —
  mrDNA's absolute CG-relaxed shape + aligned-shape RMSD scored against oxDNA, plus a CG-trajectory RMSF — so
  oxDNA, CanDo, and mrDNA cross-validate on the same design through one shared generate/view/export card.

- **`N4` — NAMD source bundle (FOURTH/LAST live card column) + gold-override reference** · shape: new
  `backend/core` service (`namd_shape_source.py`, the twin of O1/C5/M5) + new `GET /md/jobs/{id}/shape-source`
  route (`get_md_shape_source`) + frontend `getSources` now merges the NAMD source → `[oxdna, cando, mrdna,
  namd]` (no solver/card-machinery change — binds the S5 card) · feature: comparison-metric (NAMD joins the
  shared card as the GOLD-OVERRIDE reference) · engines now comparable: **oxDNA ↔ CanDo ↔ mrDNA ↔ NAMD** — the
  card's engine roster is COMPLETE, and when a NAMD job is present it becomes the reference for EVERY observable
  (shape, RMSF, field), so oxDNA/CanDo/mrDNA are scored *against* the experimentally-anchored MD engine ·
  builder is a near-clone of O1 (md_rmsf emits the same `{...,backbone_position, rmsf}` shape as production_rmsf;
  shape + RMSF from ONE Kabsch-aligned `md_rmsf` pass — time-mean structure + per-nt trajectory variance) —
  N4's value-add is the gold override, already wired in S3 (`reference_for` `_GOLD_ENGINE="namd"`), asserted here ·
  oracle: `tests/test_namd_shape_source.py` 7 fast + 1 slow (fast incl. THE HEADLINE gold-override:
  `[oxdna,cando,namd]`→`references.shape=='namd'` AND `references.rmsf=='namd'`, overriding both policy engines,
  with a negative control proving the flip is NAMD-caused; rmsf remap, core-filter drops ssDNA ends, field
  passthrough, empty-core→None RED; slow: real 2hb NAMD DCD → `md_rmsf` → ready namd source, override holds on
  real data — RAN on-machine) · main.js LOC Δ = +3 (pure wiring: lazy `getMdJob` dep + capturing the MD panel's
  return) · tests: 7 fast + 1 slow oracle, `just test` 4362 passed / 72 skipped / 1 xfailed (no drop; the prior
  xdist active-design flake `test_namd_efield` PASSED this run), vitest 2294, smoke green (pre + post), ruff
  clean on touched (19 pre-existing debt in OTHER files untouched) · display-vs-oracle: the multi-engine card
  rendering was S5-scraped (synthetic); N4 wires the real route into that validated path → live 4-engine eyeball
  = MV-21 (updated with the reference-relabel check) · fresh-context review: CONFIRMED-CORRECT, no bugs, no TDZ ·
  **Comparable prediction gained, not just a run:** the comparison card now carries all FOUR engines, and NAMD
  anchors it as the gold-override reference — oxDNA/CanDo/mrDNA's shape AND RMSF are now scored against the
  experimentally-validated MD engine on the same design through one shared generate/view/export card.

- **`M3` — mrDNA extra crossover bases PRESENT as flexible ssDNA in the BUILT ARBD model** · shape: test-only
  model-level oracle (no production code — the bridge that materializes `Crossover.extra_bases` as ssDNA beads
  shipped pre-loop in `e47edb8`; M3 was the explicit VERIFY task); new `_model_seg_stats` helper in
  `tests/test_mrdna_extra_bases.py` builds the `SegmentModel` (`mrdna_model_from_nadoc` →
  `model_from_basepair_stack_3prime`) and sums nt by segment class + bead children · feature: extra-bases
  (mrDNA feature row) · engines now comparable: mrDNA extra-base flexibility is now headlessly verifiable at the
  built-model level and mirrors CanDo's C3 signal (inserts → more local flexibility, never a bend direction) ·
  oracle: 3 mrdna-gated FAST pins (~0.8s each) — (a) built-model total nt grows by EXACTLY `n_extra` for a
  single "TT" AND all-crossovers "TT"; (b) ALL growth in `SingleStrandedSegment`, `DoubleStrandedSegment` nt
  INVARIANT (`ds_nt`=504) → inserts ssDNA/flexible/non-rigid; (c) bulk bead cloud grows 136→229; measured
  all-crossovers deltas `d_tot=106,d_ss=106,d_ds=0,d_beads=93`; strengthens the pre-loop coarse pin #6
  (`with_ss>base_ss`); can-go-red 3 ways (dropped→d_tot≠n_extra; ds-paired→ds changes; other type→ss≠n_extra) ·
  main.js LOC Δ = 0 (backend/test-only) · tests: oracle 15/15 green, `just lint` clean on file (~19 pre-existing
  ruff errors in OTHER files untouched — banked debt); full `just test` 4366 passed / 72 skip / 1 xfail + 1
  **pre-existing** non-deterministic xdist isolation flake (`test_cando_extra_bases`, unrelated slow FEM file,
  passes in isolation, different victim than the test-fast run) — no drop attributable to M3 (added 5 passing
  tests); polluter bisected & logged to `issues_ledger.md` · display-vs-oracle: N/A (headless verification, no
  new card/display; existing pin #7 slow-covers the display toggles) · fresh-context review: no real gaps ·
  **Comparable prediction gained, not just a run:** the mrDNA CG model's flexible-ssDNA content provably tracks
  extra crossover bases — one flexible ss nucleotide per inserted base in the simulated ARBD topology, a
  sign-safe cross-engine flexibility signal (vs C3).

- **`U1` — engine capability descriptor + registry** · shape: new frontend data module (`engine_capabilities.js`;
  pure data + helpers, no service/card/solver) · feature: engine-consolidation (unified-panel foundation) ·
  engines now comparable: all 5 sim engines described in ONE source of truth (5 × 8 cards) that the shared U2/U3/U4
  factories will iterate instead of the 5 bespoke `*_jobs_panel.js`; unsupported cards **present-but-disabled with
  a reason** (the absent→greyed-with-tooltip shift) · oracle (FAST, 19 tests): PARITY census — 3 tripwires
  (descriptor↔audited census field-for-field; every ENABLED anchor EXISTS in live `index.html`; every UNSUPPORTED
  probe ABSENT) + completeness (every engine carries every card). Caught a real anchor bug (LAMMPS joblist is a
  bare `lammps-jobs-list`, no `-toggle`) · main.js LOC Δ = 0 (no wiring; consumed by U2–U4) · tests: frontend
  183 files / 2331 passed (+19, no drop); backend suite not run (frontend-only, no `.py` touched) · display-vs-
  oracle: N/A (no card rendered; U4 will owe an MV row) · fresh-context review: census + oracle + helpers CLEAN,
  one LOW future-drift note (tripwire #3 guesses conventional ids) · **De-dup proven, not just wired:** the card
  matrix each shared factory needs now exists as verified data, provably matching what every bespoke panel
  renders today — the parity contract U2/U3/U4 collapse against.

- **`U2` — shared Forces (E-field) card factory** · shape: new frontend module (`forces_card.js`
  `initForcesCard({engine,ids?,gizmo?,getBaseCount?,getAnchorCount?,onChange?})`) that REPLACES two bespoke
  modules (`efield_setup.js` + `cando_efield_setup.js` DELETED) and absorbs the field third of
  `lammps_forces_setup.js` (delegated) · feature: engine-consolidation (kills the E-field triplication) ·
  engines now comparable: all 4 field-bearing panels (oxDNA/LAMMPS/CanDo/NAMD) render their Electric-field card
  from ONE factory, each emitting the SAME `{field_pN,dir,enabled}` payload; per-engine divergences (gizmo vs
  numeric, V/m sub-panel via DOM presence, +y vs +x default dir, apply-vs-lammps ready line, gizmo-visibility
  gate, job-arrow persistence) are DATA (`FORCES_FIELD_VARIANTS`/`FORCES_FIELD_IDS`), not code paths · oracle
  (FAST, 13 tests): PER-ENGINE PARITY — the ADAPTED-CODE PIN was proven by driving the LIVE old factories and the
  new one through the same input sequence on fresh DOMs and asserting byte-equal payloads (13/13 green while both
  existed); durable form pins each engine's explicit payload + gizmo-drag + applyConfig + V/m + ready lines. The
  refactored LAMMPS module still passes its 9 PRE-EXISTING tests (behaviour-preservation, tests predate the
  change). All field ids verified present in `index.html` (cards mount in the real app) · main.js LOC Δ = +1
  (import line swap `initEfieldSetup`→`initForcesCard` + `engine:'oxdna'` arg; net cohesive-logic LOC in main.js
  flat) · tests: frontend 182 files / 2315 passed (−16 = 2 deleted bespoke test files folded into
  `forces_card.test.js` + preserved LAMMPS tests; no product regression); smoke 23/23 (console-error gate green);
  backend not run (frontend-only, no `.py`) · display-vs-oracle: DOM byte-identical rewire (same ids/markup, JS
  factory swapped) → covered by parity oracle + id-presence check + smoke boot-clean; live 4-panel gesture owes
  **MV-22** · **De-dup proven, not just wired:** 3 field-card implementations → 1 factory, each engine's field
  payload machine-proven byte-identical to what its bespoke card emitted before.

- **`U3` (slice 1) — canonical job-list model + renderer** · shape: 2 new frontend modules — PURE
  `jobs_panel_model.js` (`buildJobRowModel`/`buildJobListModel`/`jobListSignature`/`runButtonEnabled`) + DOM
  `jobs_panel_render.js` (`renderJobRow`/`renderJobList`); lifts the oxDNA (CANONICAL) row/list SHAPE out of the
  bespoke panels · feature: engine-consolidation (all panels converge to the oxDNA job-list look) · engines now
  comparable: oxDNA + mrDNA job lists render from ONE model+renderer; oxDNA is byte-identical (proven), mrDNA
  UPGRADED to the canonical look (list index + spinner-while-running + legend) · oracle (FAST, 9 tests):
  BYTE-PARITY PIN — a verbatim copy of the OLD oxDNA `_jobRow`/`_renderList` (`oldOxdnaJobRow`) driven alongside
  the new model+renderer on fresh DOMs → identical `outerHTML` for every row branch (root/child/spinner/[AR]/
  archived+📦/stale-⚠/selected); flat-list convergence maps mrDNA status key + numbers rows; poll-sig stable on
  health-only change; `runButtonEnabled`=available&&!launching&&!blocked · main.js LOC Δ = 0 (panels self-rewire;
  no wiring change) · net −48 LOC across the two panels (de-dup) · tests: oracle 9/9; affected panels 112/112;
  frontend 183 files / 2325 passed (+9, no drop); smoke 23/23; ruff N/A (frontend-only; 19 pre-existing Python
  lint errors untouched) · display-vs-oracle: oxDNA DOM byte-identical (pin + 87/87 + smoke); mrDNA visual upgrade
  render-tested in jsdom, live pixels owe **MV-23** · fresh-context review: no confirmed issues, pin genuine ·
  **STATUS in_progress** (slice 1): REMAINING = converge cando/lammps/md (md = 2882-line outlier) + factor the
  stateful `initJobsPanelBase` (run-button/poll/collapse/advanced host; `runButtonEnabled` unconsumed yet) ·
  **De-dup proven, not just wired:** oxDNA's canonical job-row DOM now emitted from ONE shared model+renderer
  (byte-identical pin) and mrDNA's bespoke row rendering DELETED in favor of it.

- **`U3` (slice 2c-1) — shared STATEFUL jobs-panel base (collapse + advanced + poll)** · shape: 1 new frontend
  module `jobs_panel_base.js` (`initJobsPanelBase` factory + pure `bodyDisplay`/`arrowChar`/`shouldPoll`/`applyArrow`);
  lifts the section-collapse + advanced-drawer + REST-poll scaffold every panel repeated verbatim · feature:
  engine-consolidation (the STATE wrapper around the already-shared list renderer) · engines now comparable: mrDNA +
  CanDo run their collapse/advanced/poll through ONE factory (their bespoke `_applyCollapsed`/`_clearPoll`/
  `_scheduleNextPoll`/advToggle DELETED) · oracle (FAST, 17 tests): jsdom CONFORMANCE — the base reproduces each
  bespoke DOM effect (collapse toggles body display + arrow ▾/▸ + persists via `section_collapse_state` + fires
  onOpen/onClose; adv-drawer show/hide + arrow; poll `setTimeout(tick,pollMs)` ONLY when open&&active, cleared on
  collapse — fake timers) + pure-helper units (text/class/rotate arrow idioms, open&&active gate, null-safe) ·
  main.js LOC Δ = 0 (panels self-rewire) · net −42 LOC across the two panels (de-dup) · tests: oracle 17/17; affected
  83/83; frontend 184 files / 2356 passed (+17, no drop); smoke 23/23; lint N/A (frontend-only) · display-vs-oracle:
  behaviour-preserving (no new pixels); one-off Playwright drove mrDNA + CanDo collapse+adv gestures in-app (0
  console errors, deleted) → **no MV row owed** · fresh-context review: no behavior-preservation regressions (all 5
  checks — byte-equivalence, no lost call sites, no TDZ, per-panel behaviour kept, oracle non-superficial —
  confirmed) · **STATUS in_progress**: REMAINING = slice 2c-2 converge LAMMPS (`arrowStyle:'class'` + poll open-guard
  = adapted) / oxDNA / md (`'rotate'` + inline collapse + remote `setInterval`); then U4 selector · **De-dup proven,
  not just wired:** the stateful scaffold two panels re-implemented byte-for-byte now lives in one factory, pinned
  by a conformance oracle to behave identically.

- **`U3` (slice 2c-3a) — oxDNA section-collapse + poll converged onto `initJobsPanelBase`** · shape: rewire an
  existing panel onto the shared stateful factory (no new module) · feature: engine-consolidation (4th base
  consumer after mrDNA/CanDo/LAMMPS) · engines now comparable: oxDNA's collapse state machine + poll timer
  (`_collapsed`/`_pollTimer`/`_scheduleNextPoll` DELETED) now run through the same factory; `arrowStyle:'class'`,
  hasActive = visible-active OR selected-running · oracle (FAST, +3 tests): jsdom PARITY driving the REAL
  `initOxdnaJobsPanel` — heading-click collapse (body hidden + `is-collapsed` class), poll fires while open+active
  & STOPS on collapse (fake timers), no-poll-when-idle; the stop-on-collapse assertion FAILED pre-rewire (3 vs 2:
  bespoke let one trailing poll fire) and PASSES post-rewire = adapted-code pin, not green-by-construction · the
  ADVANCED drawer LEFT bespoke (oxDNA's `_advOpen` boolean vs the base's display-read + markup `display:none;
  display:grid`→visible ⇒ converging would flip first-click) · main.js LOC Δ = 0 · net panel LOC ≈ flat (the win
  is the deleted duplicated poll+collapse machinery, not LOC) · tests: oracle 90/90; frontend 184 files / 2362
  passed (+3, no drop); smoke 23/23; lint N/A (frontend-only; the 19 `just lint` errors are pre-existing Python) ·
  display-vs-oracle: behaviour-preserving; the one-off Playwright was blocked by unrelated left-tab-switch
  plumbing (`#tab-content-dynamics` stayed `display:none`) → live gesture deferred to **MV-26** · fresh-context
  review: all 6 adapted sites CONFIRMED equivalent, only the intended `clearPoll`-on-collapse delta, no TDZ ·
  **STATUS in_progress**: REMAINING = slice 2c-3b converge md (module-level `_collapsed` reads + 2nd remote
  `setInterval` poll + cross-panel md-collapse coordination), then U4 selector · **De-dup proven, not just wired:**
  oxDNA's bespoke collapse+poll is DELETED in favor of the shared base, pinned by a PARITY oracle that FAILS on the
  bespoke code and PASSES on the converged code.

- **`P1` — MdPipeline stage-spec data model + pure chain builder** · shape: new `backend/core` service
  (`md_pipeline.py`; pure data model + builder, no card/solver, no job submission) · feature: chaining
  (job-planner backbone) · engines now chainable: any engine's stage can be seeded from the previous stage's
  output in ONE ordered `MdPipeline` object — generalizing the 3 special-cased hops (`parent_job_id` +
  `run_kind="production"` + `seed_oxdna/mrdna_job_id`) that P2/P3/P4 build on · oracle (FAST, 9 tests):
  PARITY + CHAIN — a 3-stage plan chains each stage from its IMMEDIATE predecessor (literal-constant red guards:
  parent≠root, checkpoint≠root's, not-two-back), 1-stage plan's provenance == `spawn_md_production`'s first child
  (parent/run_kind/seed=54321/checkpoint), distinct per-stage seeds == `generate_seeds`, `cross_engine` hop
  flagged, dict round-trip; RED-verified offline (always-seed-from-root mutation fails, revert→green) ·
  main.js LOC Δ = 0 (backend-only) · tests: 9/9 oracle, `just test` 4393 passed / 110 skip / 1 xfail (+9, no drop) ·
  display-vs-oracle: N/A (no card; P4 owes the planner-UI MV) · fresh-context review: CONFIRMED-CORRECT, no bugs,
  no Three-Layer violation, oracle genuinely red-capable · **Capability proven, not just wired:** the
  deposition-chain *[field → surface → anchored field-sweep]* now resolves headlessly to a linear chain of stage
  descriptors where stage N seeds from stage N-1's output — the data backbone the unattended executor (P2) runs.

- **`U4` — engine selector + one *Simulate* section (CLOSES M-UNIFIED-PANEL)** · shape: new frontend module
  (`engine_selector.js`; pure `panelVisibility`/`selectedEngineCards` + `initEngineSelector` factory) + a
  `#simulate-panel` DOM section + segmented-control/chip CSS · feature: engine-consolidation (the selector that
  fronts the 5 stacked panels) · engines now comparable: ONE selector, driven by the U1 capability descriptor,
  shows exactly the selected engine's panel (hides the other 4) and renders the full 8-card census with
  unsupported cards **greyed-with-a-why-tooltip, not absent** · oracle (FAST, 11 tests): PURE STATE —
  `panelVisibility(e)` shows exactly `e`; `selectedEngineCards(e)` enabled subset === U1 `enabledCardKeys(e)`,
  greyed subset carries `cardReason(e,·)`; FACTORY (jsdom, 5 stub panels) — `select(x)` shows only x + hides 4 +
  marks active button, bad select is no-op, strip = 1 chip/card with greyed `title`, `onSelect` fires once, click
  selects · new logic (not a moved lift) ⇒ green-first-run valid · main.js LOC Δ = **+16** (1 import + factory
  init with 5 element lookups; ALL pure wiring, no cohesive logic — module-first law flags only a *cohesive* rise;
  routing the 5 panel inits through a loop to offset deferred as out-of-scope) · tests: oracle 11/11; frontend 185
  files / **2376 passed** (+11, no drop); smoke 23/23; lint N/A (frontend-only; the 19 `just lint` errors are
  pre-existing Python) · display-vs-oracle: one-off Playwright drove the REAL app DOM (5 buttons, per-engine panel
  show/hide, chip set == descriptor, greyed `title`s) PASSED but ran against the welcome overlay (design-load
  didn't reach the frontend view) → live-with-design gesture + hover-tooltip deferred to **MV-28**; spec deleted ·
  **De-dup/capability proven, not just wired:** a single U1 descriptor now drives per-engine card visibility
  across all 5 panels — selecting engine X yields EXACTLY X's supported cards + greys the rest, machine-pinned by
  the 11-test parity/pure-state oracle. **M-UNIFIED-PANEL CLOSED** (U1+U2+U3+U4).

- **`M4` — linkers / overhang connections into the ARBD model** · shape: VERIFY (no solver/production change —
  the mrDNA bridge `_build_nt_arrays` already threads the linker's real topology through, since it iterates
  `design.strands` + builds `helix_geom` from `design.helices`, so the `__lnk__` bridge helix + linker strands
  flow like any other) · feature: linkers (mrDNA) · engines now comparable: mrDNA joins CanDo (C4) + NAMD (N3) in
  materializing a linker's connector at the right mechanical class — mrDNA's `ds` bridge coarse-grains as a rigid
  duplex segment, its `ss` bridge as a flexible ssDNA tether, mirroring C4's rigid-link-vs-WLC-spring FEM
  distinction · oracle: `tests/test_mrdna_linkers.py` **10 fast + 2 slow** — FAST arrays (ds bridge all-paired
  `2·L`, ss bridge all-unpaired `L` threaded in-chain between the two parts, no-linker control) + FAST built
  SegmentModel (`ds.ds_nt−ss.ds_nt == L` and `ss.ss_nt−ds.ss_nt == L` for L∈{4,6,8} on the SAME overhangs — the
  ds-vs-ss diff isolates the bridge because the complement is attach-independent; bridge beads scale with bridge
  length) + SLOW real ARBD (bridge `__lnk__` positions survive the coarse run, absent unlinked; ran+passed 15 s) ·
  main.js LOC Δ = **0** (backend-only) · tests: oracle 10 fast + 2 slow green; full `just test` **4447 passed** /
  110 skipped / 1 xfailed (baseline 4435, +12 incl the 2 real-ARBD that ran+passed, no drop); ruff clean;
  backend-only ⇒ no vitest/smoke · display-vs-oracle: N/A (no card, like C1–C4/M3) · review: FAST pins CONFIRMED
  sound + bridge-drop-sensitive; the two weaker "adds particles"/SLOW `n_beads` assertions it flagged as
  complement-satisfiable were tightened to bridge-length-scaling + `__lnk__`-presence · **Comparable prediction
  gained, not just a run:** a linker's bridge now provably coarse-grains into the ARBD model with the correct
  mechanical identity — `ds` = `L` base-pairs of rigid duplex, `ss` = `L` nucleotides of flexible tether — the
  same rigid-vs-compliant call C4's CanDo FEM makes, so the two engines agree on what a linker *is*.

- **`M6` — mrDNA E-field + Anchors UI (reachability, not coverage)** · shape: frontend card-mount + a pure
  launch-body builder (no solver/backend change — M1/M2 were already done+tested) · feature: forces-ui (makes the
  DONE mrDNA field/anchors backends reachable from the unified Simulate panel) · engines now comparable: mrDNA's
  E-field + anchors are now launchable from the app exactly as oxDNA/CanDo/NAMD are, using the byte-identical
  `field:{field_pN,dir}` + `anchors:[scope dicts]` request contract — so an anchored-field mrDNA job can actually
  be *started* by a user and fed to the S5 comparison card (previously the backend was headless-only) · oracle:
  `mrdna_jobs_panel.test.js` **+7 fast** (card→launch-body PARITY: real `initForcesCard`/`initOxdnaAnchorsSetup`
  output byte-equals `body.field`/`body.anchors` with concrete pinned values; `fieldNeedsAnchor` guard; census
  flip proven against live index.html id-presence) · main.js LOC Δ = **0** (one existing init line widened by the
  `getSelection` arg — thin wiring) · tests: oracle +7 green; frontend **198 files / 2621 vitest** (no drop);
  `just test-smart` escalated to FULL **4622 passed** / 110 skipped / 1 xfailed (watermark bumped, backend
  untouched); smoke **23/23** (one flaky `assembly_exit_cleanup` self-cleared on retry + passed isolated —
  unrelated to this diff); ruff N/A (no Python) · display-vs-oracle: deferred to **MV-34** (Run button gated on a
  real mrDNA/ARBD install; payload threading + DOM-id presence are headless-pinned) · review: fresh-context
  CONFIRMED correct, no gaps (2 deltas benign — explicit `null` keys == omitted per `Optional=None`;
  whitespace-device `''→'0'` is a fix) · **Capability/de-dup proven, not just wired:** the mrDNA panel now emits
  the same anchored-field request the other three engines do, byte-for-byte, so mrDNA's already-implemented
  field/anchor physics is finally reachable — a user (and the chain planner) can launch it, closing the
  reachability gap the frontend overhaul opened.

- **`M8` — mrDNA Hard-surface UI card (reachability, CLOSES `M-MRDNA-FORCES-UI`)** · shape: frontend card-mount
  (no bespoke card — the SHARED oxDNA floor card parameterized with an `ids` bag) + surface threading in the pure
  launch-body builder + a deposition-exception guard (no backend change — M7's ARBD wall was already done+GPU-
  validated) · feature: surface-ui (makes the DONE M7 hard-surface backend reachable from the unified panel) ·
  engines now comparable: mrDNA's repulsion plane is now launchable from the app using the byte-identical
  `surface:{dir,offset_nm,stiff}` request oxDNA production uses — a deposition run (field pressing into an opposing
  surface, no anchor) can be *started* by a user and its `{dir,offset_nm,stiff}` deflection descriptor compared to
  oxDNA's floor-contact · oracle: `mrdna_jobs_panel.test.js` **+2 fast** (surface card→launch-body PARITY: real
  `initOxdnaFloorSetup` output byte-equals `body.surface` with pinned dir `[0,-1,0]`/`offset_nm 2.5`/`stiff 8`;
  null when off/zero-stiff) + **+1 deposition-guard** (`fieldNeedsAnchor` clears for a field opposed by a surface,
  still blocks a parallel one) · `oxdna_floor_setup.test.js` **+2** (custom mrDNA-ids mount emits the same spec; no
  oxDNA-ids bleed) · `engine_capabilities.test.js` census flip `off→on` proven against live index.html id-presence
  · main.js LOC Δ = **0** (untouched) · tests: frontend **198 files / 2627 vitest** (no drop); `just test-smart`→
  **FAST** (frontend-only, no Python); smoke **23/23**; ruff N/A on touched (23 pre-existing errors in untouched
  Python files = concurrent session) · display-vs-oracle: deferred to **MV-35** (Run button gated on a real
  mrDNA/ARBD install; payload threading + DOM-id presence are headless-pinned, same as M6/MV-34) · review: fresh-
  context CONFIRMED correct, no gaps (all 5 oracle requirements verified against the code) · **Capability/de-dup
  proven, not just wired:** the mrDNA panel now emits the same hard-surface request oxDNA does, byte-for-byte,
  reusing the SAME floor card rather than a new one — so M7's ARBD repulsion plane is reachable and the deposition
  chain (field-into-surface, no anchor) is launchable, closing `M-MRDNA-FORCES-UI`.

## Cross-engine agreement table (the deliverable)

Fills in as `compare_descriptors` (S3) + the card (S5) land and each engine emits descriptors. Per design ×
observable, record the reference engine and each candidate engine's agreement. This is what answers *"do the
quick and rigorous engines agree, and where do they diverge?"*

| Design (fixture) | Observable | Reference | CanDo | mrDNA | oxDNA | NAMD | Notes |
|---|---|---|---|---|---|---|---|
| _e.g. 6hb_curved_ | global twist | oxDNA | — | — | ref | — | pending S1–S5 |
| _e.g. 6hb_curved_ | bend angle / radius | oxDNA | — | — | ref | — | pending |
| _e.g. hinge fixture_ | RMSF profile (Pearson r) | CanDo | ref | — | — | — | pending |
| _e.g. tethered-arm_ | field deflection (cosine, mag ratio) | oxDNA | — | — | ref | — | **M-CANDO-FIELD headline** |

_Reference cells = `ref`; candidate cells = the agreement score (%-delta / Pearson r / cosine+ratio); `—` = not
yet emitted. Export each row's underlying data + PNG from the comparison card (per the generate/view/export
requirement)._

**C5 (2026-07-06):** the oxDNA↔CanDo rows above are now COMPUTABLE — with a completed oxDNA relaxed job + a
completed CanDo FEM job on the same design, the card emits shape %-deltas + aligned-shape RMSD (oxDNA=shape ref)
and RMSF Pearson/Spearman (CanDo=RMSF ref). The oracle proved the wiring on synthetic + real-`predict_shape`
sources; the real per-fixture numbers land from the **MV-21** live check (run both engines on one design, Generate,
read/export the agreement) or a future headless two-engine cross-run.

## Milestone status (derived from the JSON)

| Milestone | Meaning | Status |
|---|---|---|
| `M-METRIC-CORE` | comparison card generates/views/exports shared descriptors + agreement | **DONE** (S1–S5 shipped 2026-07-06) |
| `M-CANDO-FIELD` | CanDo FEM field deflection cross-validates oxDNA within tol | **DONE** (C1,C2,S4,S5,O1 shipped 2026-07-06) — FEM predicts the anchored field-deflection regime from oxDNA's per-nt force; real agreement number awaits C5 field-source |
| `M-CANDO-COMPLETE` | CanDo covers all four features + feeds the card | **DONE** (C1,C2,C3,C4,C5 shipped 2026-07-07) — anchors + E-field + extra-bases + linkers all covered, CanDo feeds the comparison card |
| `M-ALL-ANCHORS-FIELD` | every engine runs an anchored field job with a comparable descriptor | **DONE** (2026-07-08) — anchors: CanDo (C1)✓ + NAMD (N2)✓ + mrDNA (M1)✓; field: CanDo (C2)✓ + NAMD (N1)✓ + **mrDNA (M2)✓**; every engine now runs an anchored E-field job producing a comparable along-field deflection descriptor |
| `M-FULL-COVERAGE` | all engines × all four features, all feeding the card | pending — **N3 done 2026-07-08** (NAMD extra-base/linker column: atomistic model materializes inserts+linker + the shared-descriptor RMSF path made robust to string insert keys — was a real crash on any linker design). NAMD feature column now complete (N1–N4). Remaining deps: **M4** (mrDNA linkers into ARBD) + **O2** (oxDNA residual gaps). |
| `M-UNIFIED-PANEL` | 6 sidebar panels → 1, proven by per-engine card PARITY | pending — **U1 + U2 shipped 2026-07-08**. U1 = capability descriptor (5 engines × 8 cards, PARITY census, 19 tests). **U2 = shared Forces (E-field) card factory** `forces_card.js` — collapses the 3 triplicated field cards (`efield_setup.js` + `cando_efield_setup.js` DELETED; LAMMPS field third delegated) into ONE `initForcesCard({engine})` emitting byte-identical `{field_pN,dir,enabled}` per engine (13-test parity oracle, proven vs live old code; LAMMPS's 9 pre-existing tests preserved). **U3 slice 1 shipped 2026-07-08** = canonical job-list model+renderer (`jobs_panel_model.js`/`jobs_panel_render.js`) extracted from oxDNA (byte-parity pin) + mrDNA converged. **U3 slice 2a shipped 2026-07-08** = cando + lammps converged onto the same renderer (renderer gained an OPTIONAL per-row action so lammps keeps its inline Stop button; oxDNA byte-parity held); the canonical renderer now serves 4/5 panels. Conformance oracle `jobs_panel_model.test.js` 14/14. **U3 slice 2b shipped 2026-07-08** = the 2882-line NAMD outlier converged; renderer gained THREE generic gated slots (chevron / postLabelMarkers / symbolOverride) so the tree+chevron, ensemble summary, seed/Alpine badges, ⧗ remote-queued symbol + `[data-md-queued]` hook, and Fix action all ride canonical machinery — the renderer now serves **5/5 panels**; bespoke `_jobRow` deleted (−104 LOC), row ctx extracted to the pure `mdJobRowCtx` factory. NAMD payload-parity oracle `md_jobs_panel.test.js` +9, oxDNA byte-parity pin still green. **U3 slice 2c-1 shipped 2026-07-08** = the shared STATEFUL scaffold (section-collapse + advanced-drawer + REST poll) factored into `jobs_panel_base.js` (`initJobsPanelBase`); mrDNA + CanDo deleted their byte-identical `_applyCollapsed`/`_clearPoll`/`_scheduleNextPoll` and drive the base. jsdom conformance oracle `jobs_panel_base.test.js` +17, panels −42 LOC. **U3 slice 2c-2 shipped 2026-07-08** = LAMMPS converged onto `initJobsPanelBase` — first live `arrowStyle:'class'` consumer + first `onClose` cleanup (`_viewsOff`+`detachGizmo`); PARITY oracle `lammps_jobs_panel.test.js` +3 (drove the real panel through collapse/adv/poll, run green pre-rewire FIRST then post → adapted-code pin), −9 LOC. **U3 slice 2c-3a shipped 2026-07-08** = oxDNA section-collapse + poll converged (arrowStyle:`'class'`; PARITY oracle whose stop-on-collapse assertion FAILED pre-rewire = adapted delta proven; advanced drawer stays bespoke — its `display:none;display:grid` markup would flip first-click); oxDNA panel 90/90, frontend 2362/2362. **U3 slice 2c-3b shipped 2026-07-08 → U3 DONE (5/5 panels)** = the md (NAMD) panel's section-collapse AND advanced drawer converged onto `initJobsPanelBase` (arrowStyle:`'class'`, advArrowStyle:`'rotate'`; no tick/hasActive — md's WebSocket + remote `setInterval` poll stay bespoke, torn down by the base's `onClose`). md's adv drawer CONVERGES (clean `display:none` markup, no flip hazard). PARITY oracle drives the real `initMdJobsPanel`, proven behaviour-preserving via git-stash rerun (green on bespoke + converged); md 75/75, frontend 2365/2365, smoke 23/23, main.js Δ=0. Run-button host deliberately left per-panel (engine-divergent controls; cohesion); `runButtonEnabled` stays a shared helper for U4. **All 5 engine panels (mrDNA/CanDo/LAMMPS/oxDNA/md) now de-duplicate onto ONE canonical job-list renderer + ONE stateful collapse/advanced/poll scaffold.** **U4 shipped 2026-07-08 → CLOSED** = new `engine_selector.js` (pure `panelVisibility`/`selectedEngineCards` + `initEngineSelector` factory) fronts the 5 panels with a `#simulate-panel` segmented control; card visibility driven by the U1 descriptor, unsupported cards greyed-with-a-why-tooltip (not absent). 11-test parity/pure-state oracle, frontend 2376/2376, smoke 23/23, main.js +16 pure wiring; live-with-design gesture deferred to MV-28. **M-UNIFIED-PANEL = 6 panels → 1 selector, proven by per-engine card PARITY (U1+U2+U3+U4 done).** |
| `M-JOB-PLANNER` | chain jobs unattended (stage-spec + executor + planner UI) | pending — **P1+P2+P3 shipped 2026-07-08**. P1 = `MdPipeline` stage-spec + pure builder. **P2 = chain EXECUTOR** (`md_chain_executor.py`): stage N spawns SEEDED FROM N-1's realised child on completion; failure HALTS; `resume_chain` retries-only-failed. **P3 = cross-engine output→input**: a `cross_engine` hop (oxDNA/mrDNA root → NAMD stage) reconstructs the atomistic start structure from the CG relaxed frame via the create-time converter (`build_namd_seed`/`_from_mrdna`, nm↔sim-units↔Å already handled) instead of the same-engine `.coor/.xsc` restart — `cross_engine_seed` resolver + `_chain_spawn` branch + `create_md_chain` accepts a CG root; CHAIN oracle 6 pure + 7 route (incl. E2E oxDNA→NAMD chain + halt/resume). **P4 = Plan Run overlay shipped 2026-07-08 → DONE (P1+P2+P3+P4).** `md_plan_run.js` (thin `createModal` glue) over PURE `stage_planner_model.js` (immutable add/⧉dup/↑↓reorder/✕remove/setStage/setRoot + `buildChainPayload` + `chainStatusSummary`); active stage REUSES the shared U2 Forces card + Anchors card (no triplication). CHAIN proven by a TWO-HALF parity oracle (`stage_planner_model.test.js` 12+5 builds a deposition→immobilize→sweep payload BYTE-EQUAL to `tests/test_stage_planner_payload.py` 4, which parses through `CreateChainRequest` + `build_pipeline_plan`→linear chain stage N-from-N-1). `client.js` +4 chain helpers; `md_jobs_panel.js` +`getSelectedJob`; main.js +10 pure wiring. frontend 2415/2415 (12+5 planner tests), just test 4427, smoke 23/23; one-off Playwright asserted `POST /md/chains` body == the authored payload + "stage 1 of 2" renders + 0 console errors (deleted); live gesture owes MV-32 |
| `M-DEPOSITION-CHAIN` | E-field→surface→anchors→field-sweep from one Plan Run | **DONE 2026-07-08 (P1✓ + P2✓ + P4✓ + U2✓)** — the Plan Run overlay (P4) authors the *deposition→immobilize→field-sweep* chain (an E-field stage, an anchor stage, and ⧉-duplicated field-sweep stages, each with reused Forces+Anchors cards) and queues it as one `MdPipeline` that the executor marches unattended; the headline chain now runs from one Plan Run. Residual (documented, out of P4 scope): forces threaded to the conf-snippet level (`external_forces_block`) but not yet into the production RESEED conf end-to-end (P2 follow-up: `ProductionRunRequest.field/anchors`+reseed emission) — the live real-NAMD deposition run is MV-32 |
| `M-MRDNA-FORCES-UI` | mrDNA field/anchors reachable from the unified panel + a new mrDNA hard-surface (M6+M7+M8) | **DONE 2026-07-10 (M6+M7+M8)** — **M8 shipped 2026-07-10 CLOSES the milestone**: the mrDNA **Hard surface** UI card is live (new `mrdna-surface-*` DOM) by mounting the SHARED oxDNA floor card — `initOxdnaFloorSetup` parameterized with an `ids` bag (default = oxDNA ids → the pre-existing oxDNA card test unchanged = backward-compat), no new bespoke card. `buildMrdnaLaunchBody` threads the card's `{dir,offsetNm,stiff}` into `POST /mrdna/jobs` under the cross-engine snake_case `surface:{dir,offset_nm,stiff}` (byte-equal to the oxDNA production surface request; null when off/zero-stiff). The client field-drift guard now honors the **deposition exception** — a field pressing INTO an opposing surface needs no strand anchor — via the newly-EXPORTED `surfaceOpposesField` mirror shared with the chain planner (no geometry re-derived). `engine_capabilities.mrdna.surface off→on` (`domAnchorId='mrdna-surface-toggle'`, presence enforced in live index.html; census stays green). PARITY oracle: `mrdna_jobs_panel.test.js` surface card→body byte-equality + deposition-guard cases, `oxdna_floor_setup.test.js` custom-ids mount, `engine_capabilities.test.js` live-DOM census. main.js Δ=0. frontend 2627/2627, smoke 23/23; live card-gesture→POST owes MV-35 (Run button availability-gated, same as MV-34). **All three mrDNA-forces-UI tasks (M6 field+anchors, M7 surface backend, M8 surface card) now land — mrDNA's field/anchors/surface are all reachable from the unified Simulate panel with a comparable `{dir,offset_nm,stiff}` deflection descriptor.** — **M6 shipped 2026-07-10**: the shared U2 Forces + Anchors cards are mounted in the mrDNA panel (`mrdna-efield-*`/`mrdna-anchors-*` DOM + `forces_card.js` `mrdna` variant + `engine_capabilities` efield/anchors flipped `off→on`), and `_launch` threads `field:{field_pN,dir}` + `anchors:[…]` into `POST /mrdna/jobs` via the pure `buildMrdnaLaunchBody` (byte-identical to CanDo; server-side field-needs-anchor guard mirrored client-side). PARITY oracle `mrdna_jobs_panel.test.js` +7 (card output byte-equals payload; census flip enforced vs live index.html). main.js Δ=0; live gesture owes MV-34. **M7 shipped 2026-07-10** (backend-only, no UI): `mrdna_surface.py` turns the shared `{dir,offset_nm,stiff}` descriptor into a ONE-SIDED HARMONIC WALL — an ARBD grid potential `U=½·stiff·min(0,s)²` (same `add_grid_potential`/`gridFile` mechanism as M2, quadratic not linear) whose `−∇U` repels beads along `+dir̂` on the forbidden side, `0` on the allowed side (round-tripped through `loadGrid`); plane placed `offset` below the lowest bead (`plane_c=min_proj−offset`, generalizes oxDNA `wall_position_from_extent`), FIXED in the lab frame (grid written ONCE, regen re-attaches). Composes with M2's field grid by APPENDING (ARBD superposes gridFile entries) → a deposition run carries both; the runner installs surface AFTER field. `MrdnaJob.surface` + route passthrough + guards; **deposition rule wired: a field pressing INTO an opposing surface needs NO strand anchor** (`field_anchor.surface_opposes_field` relaxes both the route + runner guards). Oracle `tests/test_mrdna_surface.py` **11 fast + 1 slow**, all RED-able. Fast: `.dx` round-trip `−∇U==stiff·\|s\|·dir̂` below / `0` above; off-axis dir̂; plane placement; **field+surface both survive bead regen** (pins the field-first ordering); compose; dry-run gridFile; malformed→400; deposition-rule route guard (3 directions). SLOW ran+passed on-GPU (0.8 pN into a 0.5 nm-clearance plane, 30k steps, no anchor): the free run streams the lowest bead to **s=−32 Å** while the surface **deposits it at s=+3.9 Å** (held just above, none pass through) — a 36 Å hold with no strand anchor. main.js Δ=0; backend-only → no display-vs-oracle (UI is M8). Remaining: **M8** (surface UI card, parity). |

## Data summaries (plots + fits)

_(none yet — `### <TASK-ID> — <topic>` subsections for numeric fits, e.g. CanDo-vs-oxDNA deflection-vs-field
magnitude, as slow real-engine runs produce them.)_
