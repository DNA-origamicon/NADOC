# Sim-coverage loop — session log, oracle catalog, lessons

Companion to [`SIM_COVERAGE_PLAN.md`](SIM_COVERAGE_PLAN.md) + [`sim_coverage_plan.json`](sim_coverage_plan.json).
One entry per session/commit. Live task status lives in the JSON; this is the durable narrative + the reusable
oracle library.

## Conventions

- One task per session, one commit (`feat(<engine>-coverage): <task> + <oracle>`), auto to master, no push.
- Pass criterion = a **comparable prediction with a property oracle**, never a bare run. Each session row ends
  with **"Comparable prediction gained, not just a run: ___."**
- New code is module-first; `backend/core` imports nothing from `backend/api`; metrics reuse the shared card.
- Fast/slow: real-engine tests get registered in `tests/conftest.py` (`_SLOW_MODULES`/`_SLOW_TESTS`); everything
  else stays in the fast loop.
- Three-Layer Law: outputs are Physical/display-only; anchors/fields are job-request annotations.

## How to check coverage (the probe)

```bash
# Which features does each engine cover? Grep the headless entry points + oracles per engine.
rg -l "def .*(anchor|field|extra_base|linker)" backend/core backend/physics
# Which engines feed the comparison card?
rg -n "register.*compare-source|compute_shape_descriptors" backend/core/shape_metrics.py 2>/dev/null
# Cross-engine agreement results land in sim_coverage_metrics.md § "Cross-engine agreement".
```

## Oracle catalog — the reusable validation building blocks (MIRROR THESE)

Fill one row per shipped oracle so later tasks reuse rather than re-derive.

| Oracle / pattern | Asserts (property, not "ran") | File(s) | Reuse for |
|---|---|---|---|
| **(S4) field-response** ✅ | anchors held ≤ tol AND free nts deflect along +field AND monotone in \|F\|; cross-engine deflection cosine +1 identical / −1 opposite / 0 orthogonal, magnitude-ratio = compliance ratio; zero-field & no-free raise; copy-aware, no-shared-free→None | `shape_metrics.py::{field_response_profile,compare_field_response}`, `tests/test_shape_field_response.py` | every engine's E-field task (C2, M2, N1); S5 field panel |
| **(S1) shape descriptors** ✅ | straight→twist≈0 & bend≈0; `_twist_bundle(60)`→60±10°, signed+monotone; `_arc_bundle(R,sweep)`→arc-span±12° & R±25%; can-go-red (twist>20 on twisted frame); single-helix→twist None | `backend/core/shape_metrics.py::compute_shape_descriptors`, `tests/test_shape_metrics.py` | every descriptor-emitting task (O1, C5, M5, N4); S3 consumes its dict; S4 field panel |
| **(S2) deviation + RMSF profiles** ✅ | identical→rmsd 0; known non-rigid displacement recovered exactly (align=False); rigid pose removed by Kabsch, shear survives (align=True); static ensemble→rmsf 0; known amplitude→A/√2 round-trip; align strips bulk drift keeps site fluctuation; normalize max→1 + rescale-back + all-zero safe | `backend/core/shape_metrics.py::{deviation_profile,rmsf_from_ensemble,normalize_rmsf_profile}`, `tests/test_shape_deviation_rmsf.py` | S3 (agreement math consumes both); per-nt deviation-map + flexibility-map for any engine (O1/C5/M5/N4) |
| **(S3) descriptor agreement** ✅ | identical→signed %Δ 0 & Pearson 1 & shape-RMSD 0; +10/−10° twist→±10% signed; scaled RMSF→Pearson 1, reversed→<−0.99, constant→None (not NaN); rigid pose→shape-RMSD≈0 but shear survives; **CanDo dir-less RMSF vs oxDNA per-strand collapses to per-bp & correlates**; `reference_for` honors oxdna=shape/field, cando=rmsf, NAMD-override, missing→None | `backend/core/shape_metrics.py::{compare_descriptors,reference_for}`, `tests/test_shape_compare.py` | all cross-validation milestones (S5 card, O1/C5/M5/N4 sources) |
| **(S5) comparison report** ✅ | per-observable reference selection (oxDNA=shape/field, CanDo=RMSF, NAMD-override); scalar reference→0-delta & candidate recovers ±known %; zero-ref→None (no div0); identical RMSF→Pearson 1 + overlay points; rigid-shift→shape-RMSD≈0; field cosine +1/−1 & mag-ratio 3; 1-engine→raw-no-agreement; empty→not-ready; missing observable omits its rows; REST start→poll→result+404 | `backend/core/shape_compare.py::build_comparison_report`, `backend/api/routes_shape_metrics.py`, `tests/test_shape_compare_report.py` | the compare card; per-engine source-bundle contract for C5/O1/M5/N4 |
| _(display-vs-oracle)_ ✅ (S5) | card's displayed numbers == headless oracle within tol; else STOP+ask | one-off Playwright per card (deleted after) | S5 ✓, C5, M5, N4 |
| **(U3) canonical job-row PARITY pin** ✅ | new pure model + DOM renderer reproduce the OLD oxDNA `_jobRow`/`_renderList` byte-for-byte: the test carries a VERBATIM copy of the old row/list code (`oldOxdnaJobRow`) and drives OLD+NEW on fresh DOMs → identical `outerHTML` across every branch (root/child/running-spinner/[AR]/archived+size+📦/stale-⚠/selected); flat-list convergence (mrDNA ctx) numbers rows + maps status key; poll-signature stable on health-only change; `runButtonEnabled` = available&&!launching&&!blocked | `frontend/src/ui/{jobs_panel_model.js,jobs_panel_render.js}`, `frontend/src/ui/jobs_panel_model.test.js` | U3 remainder (cando/lammps/md converge onto renderer; run-button base; stateful `initJobsPanelBase`); U4 selector iterates the same rows |
| **(U3 s2a) cando+lammps conformance** ✅ | renderer's OPTIONAL per-row action (`m.action`/`onAction`, gated on `ctx.rowAction`): models the action ONLY for active jobs, renders a Stop button on active rows whose click fires `onAction(jobId)` with stopPropagation (row `onClick` does NOT fire), and a ctx WITHOUT `rowAction`→every `action===null`→no button (oxDNA-parity guard); cando flat ctx numbers rows newest-first + maps cando status key + spinner-while-active + surfaces Coarse/Fine as a LEADING TAG (not a bespoke column) + no button | `frontend/src/ui/{jobs_panel_model.js,jobs_panel_render.js}`, `frontend/src/ui/jobs_panel_model.test.js` (+5 it, 14/14) | U3 slice 2b (md chevron via the same optional-control mechanism); the action slot for any future per-row control |
| **(U3 s2b) NAMD payload parity** ✅ | the pure `mdJobRowCtx` factory + canonical renderer emit the exact per-row payload the bespoke NAMD `_jobRow` produced: parent gets `chevron={childCount,collapsed,title}` (collapsed→ensemble-summary post-label marker + subtree hidden; open→no summary), replica child `label`/`title`/`indent`+empty index, CG-seed + Alpine `postLabelMarkers` (text+title), remote-queued `symbolOverride={glyph:'⧗',dataset:{mdQueued}}` (+ the `[data-md-queued]` DOM hook the poll-refresh needs), Fix `action` only on VRAM-OOM + out-of-date `stale`; chevron click fires `onChevron` NOT row `onClick`; leaf still gets an empty chevron span. Three generic slots (chevron/postLabelMarkers/symbolOverride) gated on ctx opt-in → oxDNA byte-parity pin re-ran green | `frontend/src/ui/{jobs_panel_model.js,jobs_panel_render.js}`, `frontend/src/ui/md_jobs_panel.js` (`mdJobRowCtx`/`mdJobRowSig`), `frontend/src/ui/md_jobs_panel.test.js` (+8 it) | U3 slice 2c (stateful `initJobsPanelBase` — run buttons + poll loop + section collapse + advanced drawer); U4 selector iterates these same rows |
| **(U3 s2c) shared stateful scaffold de-dup** ✅ | one `initJobsPanelBase({section,els,pollMs,hasActive,tick,onOpen,onClose,arrowStyle})` reproduces the bespoke collapse + advanced-drawer + poll scaffold BYTE-FOR-BYTE: a jsdom conformance oracle pins each effect — `applyCollapsed(true/false)` sets `body.display`=`none`/`''` + arrow=▸/▾ + fires onClose(+clearPoll)/onOpen; heading click persists via `section_collapse_state` then applies; adv toggle shows/hides `advBody` + ▾/▸; poll `setTimeout(tick,pollMs)` ONLY when `shouldPoll({open,hasActive})` (open&&active), cleared on collapse — proven with fake timers; pure `bodyDisplay`/`arrowChar`/`shouldPoll`/`applyArrow` (text/class/rotate) unit-tested. mrDNA + CanDo deleted their identical scaffold (−21 LOC each) + drive the base with their own hooks; CanDo's display-card collapse stays bespoke | `frontend/src/ui/jobs_panel_base.js`, `frontend/src/ui/jobs_panel_base.test.js` (+17 it), `frontend/src/ui/{mrdna,cando}_jobs_panel.js` | U3 slice 2c-2 (LAMMPS `arrowStyle:'class'`+onClose-cleanup, oxDNA/md `'rotate'`+inline-collapse+remote poll); U4 selector mounts the base per selected engine |
| **(U3 s2c-2) LAMMPS scaffold parity** ✅ | the LAMMPS panel drives `initJobsPanelBase` (first live `arrowStyle:'class'` consumer + first `onClose` that runs `_viewsOff()`+`detachGizmo()`) with IDENTICAL behaviour to its bespoke `_applyCollapsed`/`_schedulePoll`: a PARITY block drove the REAL `initLammpsJobsPanel` factory through the actual heading-click collapse (body hidden + `is-collapsed` class + views reset to Off + gizmo detached), the advanced-drawer toggle (`advBody` show/hide + ▾/▸ text arrow), and the open+active poll gate (poll fires while open, STOPS once collapsed) — with fake timers. Run GREEN against the pre-rewire code FIRST (pins real behaviour, not the new wiring), then re-run green after → parity, not green-by-construction (adapted-code pin: the base adds the open-guard the bespoke poll lacked) | `frontend/src/ui/lammps_jobs_panel.js`, `frontend/src/ui/lammps_jobs_panel.test.js` (+3 it, 19/19) | oxDNA/md 2c-3 (`'rotate'` arrow + inline `_collapsed` var + md's remote `setInterval`); U4 selector mounts the base per engine |
| **(U3 s2c-3a) oxDNA scaffold parity** ✅ | the oxDNA panel drives `initJobsPanelBase` for its SECTION-COLLAPSE + POLL (arrowStyle:`'class'`; hasActive = visible-active OR selected-running) with IDENTICAL behaviour to its bespoke module-level `_collapsed`/`_scheduleNextPoll`/`_pollTimer`: a PARITY block drove the REAL `initOxdnaJobsPanel` through the heading-click collapse (body hidden + `is-collapsed` class), the open+active poll gate (poll fires while open, STOPS once collapsed), and no-poll-when-idle — with fake timers. The stop-on-collapse assertion FAILED pre-rewire (3 vs 2: bespoke let one trailing poll fire after collapse) and PASSES post-rewire = adapted-code pin proven, not green-by-construction (the base's `clearPoll()` on collapse is the one benign delta). The ADVANCED drawer stays BESPOKE on purpose: oxDNA's `_advOpen` boolean opens on first click, the base reads `display` and the markup's `display:none;display:grid` computes visible → converging would flip first-click. `_revealMdPanel`/left-tab-change/workspace-path-change/init-ordering all rewired to `_base.isOpen()/applyCollapsed/clearPoll/schedulePoll/initCollapsed` (fresh-context review: all 6 adapted sites CONFIRMED equivalent + no TDZ) | `frontend/src/ui/oxdna_jobs_panel.js`, `frontend/src/ui/oxdna_jobs_panel.test.js` (+3 it, 90/90) | md 2c-3b (module-level `_collapsed` reads + 2nd remote `setInterval` poll + cross-panel md-collapse coordination); U4 selector mounts the base per engine |
| **(U3 s2c-3b) md scaffold parity — CLOSES U3 (5/5 panels)** ✅ | the md (NAMD) panel drives `initJobsPanelBase` for its SECTION-COLLAPSE **and its ADVANCED DRAWER** (arrowStyle:`'class'`, advArrowStyle:`'rotate'`; NO tick/hasActive — md has no primary poll, its WS + `_remotePollTimer`/`_prewarmTimer`/`_displayTimer` stay bespoke and are torn down by the `onClose` hook). Investigation shrank the feared scope: `_collapsed` lived in only 3 logical sites, and `_pollTimer` was vestigial/dead. A PARITY block drives the REAL `initMdJobsPanel` (auto-mocked api client): section collapse toggles body-display + `is-collapsed` arrow; adv drawer FIRST-CLICK-OPENS + `rotate(90deg)` arrow; open fires `_onOpen` fetch, collapse STOPS the remote SLURM poll (`onClose`). KEY vs oxDNA: md's adv drawer CONVERGES too — its markup is a clean `display:none` (no `display:none;display:grid` flip hazard). Behaviour is byte-identical (no oxDNA-style delta) → proven via GIT-STASH RERUN: the 3 specs pass against the stashed bespoke md.js AND the converged code = behaviour-preserving adapted-code pin. Run-button host deliberately NOT put in the base (engine-divergent controls; cohesion) — `runButtonEnabled` stays a shared helper for U4 | `frontend/src/ui/md_jobs_panel.js`, `frontend/src/ui/md_jobs_panel.test.js` (+3 it, 75/75) | U4 selector mounts the base per selected engine + drives the card stack off the U1 descriptor |
| **(O1) oxDNA source bundle** ✅ | descriptors == `measure_bundle_twist(core)` on the exact core-filtered frame (same estimator, self-consistent — ABSOLUTE not the differential graph); core mask drops ssDNA ends; `production_rmsf` `rmsf`→`rmsf_nm` remap (None dropped); field passthrough; drops into `build_comparison_report` as ready `oxdna` SHAPE reference; empty core ref→None descriptors (RED) | `backend/core/oxdna_shape_source.py::build_oxdna_shape_source`, `backend/api/routes_oxdna.py::get_oxdna_shape_source`, `tests/test_oxdna_shape_source.py` | the SAME source-bundle contract for C5/M5/N4 (each engine builds `{engine, descriptors, rmsf, shape_frame, field}` from its own frame + core mask) |

| **(C1) CanDo anchors (Dirichlet BC)** ✅ | synthetic beam: pinned node u==0 at its DOFs, free tip moves under a test load; BC pins EXACTLY the requested nodes' 6 DOF, `None`/`[]`→centroid (never singular); resolver maps base+cluster scopes→duplex-core node indices (both strands→one node) & drops stale/out-of-core; prestress solve holds the clamped node <1e-9 while the rest deflects >1e-3; unresolved anchor = no-op (positions identical, free-free RMSF preserved) | `backend/physics/fem_solver.py::{apply_boundary_conditions,solve_prestress_shape,resolve_anchor_nodes,predict_shape}`, `tests/test_cando_anchors.py` | every engine's ANCHOR task (M1/N2) via the SAME `resolve_anchor_particles` scope resolver → node/bead/atom indices; C2 (E-field needs anchors) |
| **(C2) CanDo E-field (S4 on FEM frame)** ✅ | `assemble_field_force`: uniform body load = 2·`field_pN`·dir_hat/node (duplex node = 2 backbones), translational DOF only, None/zero-mag/zero-dir→zero vector, linear in magnitude; end-to-end (S4 `field_response_profile` on the RAW clamped-solve frame, NOT Kabsch-reposed display frame): anchors held (drift≈0) + free deflects ALONG field (proj≥0.5nm) + MONOTONE in \|E\| + zero-field→no deflection (RED); `predict_shape(field=)` threads through & `field=None` is a byte-identical no-op | `backend/physics/fem_solver.py::{assemble_field_force,solve_prestress_shape,predict_shape}`, `tests/test_cando_field.py` | every engine's E-FIELD task (M2/N1) — same `{field_pN,dir}` per-nt-force descriptor; **C5 field-source must emit field-response from the RAW frame, not display positions** |

| **(C3) CanDo extra-base compliant connector** ✅ | an extra-base crossover meshes as a 2-node WLC ssDNA spring (`k_rot==0`, `k_trans==3·kT/(2·L_c·L_p)`, `<K_PENALTY/1e3`) NOT a rigid link → spring count == #inserted, springs+rigid conserved (mesh reflects inserts; no added nodes — CanDo connects EXISTING bp nodes); `k_trans` softens monotone in insert length (`k∝1/L_c`); synthetic 2-node compliance: same load → spring node deflects >1e3× a rigid link (`u==F/k_trans` vs `F/K_PENALTY`); SLOW real `predict_shape`+NMA: a band of inserts raises LOCAL per-bp RMSF at those nodes (>1.3×, ~1.87× obs, every affected node up) via S3 `compare_descriptors` RMSF channel; RED-guard self-vs-self flat (<1.05×). **Asserts NO twist/bend DIRECTION** (softening a distributed load is non-monotone; geometric crossover reasoning forbidden) — RMSF is the sign-unambiguous softening signal + CanDo's observable | `backend/physics/fem_solver.py::build_fem_mesh` (mechanism), `tests/test_cando_extra_bases.py` | C4 (linker connector element reuses the WLC-spring pattern); every engine's extra-base flexibility check (M3/N3) — softening → higher RMSF, cross-validatable |

| **(C5) CanDo source bundle** ✅ | descriptors == `compute_shape_descriptors` on the exact core-filtered `predict_shape` frame (same S1 estimator, self-consistent — ABSOLUTE); core mask drops ssDNA ends; per-bp NMA `rmsf`→card shape with **`direction=None`** (dropped None); field passthrough; empty core→None (RED); **integration: `[oxdna, cando]`→`build_comparison_report` ready, refs shape=oxdna/rmsf=cando, cando shape-RMSD finite (~0 rigid shift), oxDNA RMSF Pearson 1.0 n=24 (dir-less pairs per-strand via `_rmsf_per_bp`)** | `backend/core/cando_shape_source.py::build_cando_shape_source`, `backend/api/routes_cando.py::get_cando_shape_source`, `tests/test_cando_shape_source.py` | the SAME source-bundle contract for M5/N4; CanDo is the RMSF reference column |

| **(C4) CanDo linker connector** ✅ | THE bright line on a synthetic two-part mesh: a WLC-spring linker transmits a load part A→part B (node moves), NO linker→part B exactly `0`; a rigid (ds) link couples >10× a soft (ss) tether. Additive-no-regression: an independent legacy `scaf∧stap` recompute == `_duplex_bp_per_helix` on a linker-free 6HB (byte-identical dict). Real routed-6HB **ds**: overhangs+`__lnk__` bridge gain duplex bp, bridge meshed, rigid hops WIRE the bridge to BOTH overhang helices (connectivity, not just count), 0 springs. Real **ss**: bridge stays ssDNA/unmeshed, exactly +1 WLC spring (`k_rot==0`, `k_trans==WLC(6)`) spanning the two DISTINCT overhang helices | `backend/physics/fem_solver.py::{_duplex_bp_per_helix,_add_linker_hops,build_fem_mesh}`, `tests/test_cando_linkers.py` | every engine's LINKER task (M4/N3) — a materialized ds bridge = duplex beams+rigid hops, a ss bridge = a WLC tether; the additive-duplex + hop-at-strand-junction pattern generalizes to any engine that meshes/beads the generated linker topology |

| **(N2) NAMD anchors (fixedAtoms)** ✅ | resolver: base scope→EXACTLY that nucleotide's residue ordinals, strand→all its residues, stale/empty→∅ (drops silently, matches `resolve_anchor_particles`); `sort_chains` natural(export_pdb) vs lexicographic(psfgen) DIVERGES past 26 strands (the fix — wrong order silently pins offset residues); marker PDB marks B=1 on EXACTLY the resolved residues' heavy atoms (H free, HETATM never, RED empty→0 fixed) by contiguity-walk == the ENM's; conf emits `fixedAtoms on/File/Col B` only with anchors; SLOW real-psfgen prepare end-to-end marks exactly + every ladder conf enables it + manifest records it; SLOW 176-strand `export_pdb` output residue sequence == natural, ≠ sorted (divergence proof) | `backend/core/namd_topology.py::{built_pdb_residue_keys,resolve_anchor_residue_indices}`, `backend/core/md_protocols.py::{write_anchor_restraints_pdb,_segment_conf,_min_conf,prepare_mgh_slow_release}`, `tests/test_namd_anchors.py` | N1 (anchored E-field run reuses the fixedAtoms plumbing); the ordinal-bridge + shared-scope-resolver pattern for any atomistic engine; M1 (mrDNA anchors) via the same `resolve_anchor_particles`→bead map |

| **(N1) NAMD native E-field (eField)** ✅ | `namd_efield_vector({field_pN,dir})`→NAMD `eField` (kcal/mol/Å/e) such that `q·E·K == field_pN·dir̂` per nucleotide (q=−1 e = one phosphate, NO fudge); F=q·E inversion pins magnitude+normalisation+SIGN (backbone q<0 → eField antiparallel); None/zero-mag/zero-dir→None; conf emits `eFieldOn/eField` only with a field, zero-field BYTE-IDENTICAL; every conf writer carries it (`_segment_conf`/`_min_conf`/both production/shell-reprep/remote+local resume); SLOW real psfgen: internal residue == −1.000 e, 5TER/3TER termini −0.47/−0.53 e (sum −1) → strand feels −(N−1) e (measured, not assumed); SLOW **real-NAMD differential probe** (field-on vs off, T=0, one strand fixed): fixed atoms move 0, free ΔCOM cosine 0.99996 along +dir, \|ΔCOM\| within 10% of ½(F/M)t² from `field_pN`×NAMD's-own −7 e (independent of `KCAL_MOL_A_IN_PN` — RED-checked, doubling it makes real NAMD falsify); REST guards: field-needs-anchor / field+multi-GPU / malformed→400; prep raises if a field's anchors resolve to ∅ | `backend/core/md_protocols.py::{namd_efield_vector,external_forces_block,_segment_conf,_min_conf,prepare_mgh_slow_release}`, `backend/api/routes_md.py`, `tests/test_namd_efield.py` | every engine's E-FIELD task (M2) — same `{field_pN,dir}` per-nt-force descriptor; the "predict from the ENGINE'S OWN charges, not the emitted vector" independence pattern; N4 field-source (emit from the pre-display frame) |

| **(M1) mrDNA anchors (ARBD RESTRAINT)** ✅ | shared `resolve_anchor_particles`→per-nt `(helix,bp,dir)` keys→nearest CG bead by 3D POSITION (mrDNA groups helices by base-pairing not NADOC helix id + collapses each bp to 1 fwd bead — name/index map unreliable, so position via the input `r` array; both r+beads in Å same frame, RED-checked); stale/ssDNA/extra-base keys drop→`[]`; strand scope→contiguous bead run, strict non-empty subset, every anchored-nt's nearest bead is held; **FAST end-to-end: real ARBD `.restraint.txt` (via `simulate(dry_run)`) carries EXACTLY `len(held)` RESTRAINT lines**; idx pinned two independent ways (flat `s.beads` enumerate == ARBD `.idx` for coarse/no-orientation-bead model) set-equal; k==our spring, pinned pos==bead's own pos (an anchor); `install_anchor_restraints` wraps `generate_bead_model` so RESTRAINTs survive `clear_beads()`+regen between multiresolution stages (RED: 0 without wrapper, ≥1 with); coarse single-pass pins the as-built beads; SLOW **real ARBD coarse run**: anchored beads hold 0.55 Å vs free 3.81 Å (**7×**, median, DCD final frame) | `backend/core/mrdna_anchors.py::{resolve_anchor_beads,apply_anchor_restraints,install_anchor_restraints,restraint_records}`, `backend/core/{mrdna_job,mrdna_runner}.py`, `backend/api/routes_mrdna.py`, `tests/test_mrdna_anchors.py` | M2 (mrDNA E-field needs anchors — reuse `install_anchor_restraints` + the position-bead resolver); any engine that beads a design + needs a job-request anchor (the shared-scope→engine-index bridge, position variant) |

| **(M2) mrDNA E-field (ARBD grid-potential force)** ✅ | per-bead force = `field_pN·(nt in bead)·(pN→kcal/mol/Å)·dir̂` with `nt in bead = mass/dpn`, `dpn = total_bead_mass/total_nt` (beads charge 0 → force applied directly), asserted vs a FIRST-PRINCIPLES pN→kcal/mol/Å (not the code constant); 2×mass→2×force; TOTAL force = `field_pN·total_nt`; constant force via a RAMP POTENTIAL `U=-(F·r)` through `add_grid_potential`/`gridFile` (`-∇U==F` round-tripped from the `.dx` via `loadGrid`) — **NOT `forceXGrid`, which crashes ARBD on a constant grid**; per-type grid wiring + dry-run conf emits `gridFile field_*.dx`; `install_field_force` wraps `generate_bead_model` so grids re-attach to fresh types after regen (RED-checked), idempotent (grid_potentials overwritten); REST guards field-needs-anchor/malformed(incl non-numeric)→400; runner RAISES if a field's anchors held 0 beads; SLOW **real ARBD field-on vs off, one strand anchored**: anchored held (~0.5 Å) while free bulk deflects ALONG +field (~8.5 Å vs field-off ±2 Å), \|Δ\| within [0.45,2.0]× the overdamped Brownian pred `D·F·T/(k_B·T)` from the engine's OWN diffusivity/mass + field_pN via the first-principles constant (independent of the emission constant) | `backend/core/mrdna_field.py::{field_force_vector,dalton_per_nucleotide,_write_ramp_grid,apply_field_force,install_field_force}`, `backend/core/{mrdna_job,mrdna_runner}.py`, `backend/api/routes_mrdna.py`, `tests/test_mrdna_field.py` | M4 (mrDNA linkers) + M3 (extra bases) reuse the per-type grid + regen-wrap; any CG engine's uniform-field task (the ramp-potential idiom + per-nt→per-bead mass-scaling + overdamped-drift oracle); N4/M5 field-source (emit deflection from the relaxed frame) |

| **(N4) NAMD source bundle (gold override)** ✅ | descriptors == `compute_shape_descriptors` on the exact core-filtered frame (same S1 estimator, ABSOLUTE); core mask drops ssDNA ends; `md_rmsf` `rmsf`→`rmsf_nm` remap (None dropped); field passthrough; empty core→None (RED); **THE HEADLINE: `[oxdna,cando,namd]`→`build_comparison_report` references.shape=='namd' AND references.rmsf=='namd' — NAMD overrides BOTH policy engines (gold override)**; negative control (absent NAMD → shape=oxdna/rmsf=cando, proving the flip is NAMD-caused); SLOW real 2hb NAMD DCD→`md_rmsf`→ready namd source, override holds on real data | `backend/core/namd_shape_source.py::build_namd_shape_source`, `backend/api/routes_md.py::get_md_shape_source`, `tests/test_namd_shape_source.py` | the source-bundle contract, complete — all four engines (O1/C5/M5/N4) now feed the card; the gold-override assertion pattern for any future NAMD-referenced observable |

| **(M3) mrDNA extra bases in the BUILT model** ✅ | inserts survive coarse-graining into the ARBD `SegmentModel` as flexible ssDNA — `_model_seg_stats` builds the model (`model_from_basepair_stack_3prime`) & sums nt by segment class + bead children: built-model total nt grows by EXACTLY `n_extra` (single insert AND all-crossovers); ALL growth lands in `SingleStrandedSegment` while `DoubleStrandedSegment` nt is INVARIANT (ds_nt=504 unchanged) → inserts are ssDNA/flexible/non-rigid, never WC-paired into a rigid segment; bulk bead cloud grows (136→229). Strengthens pre-loop coarse pin #6 (`with_ss>base_ss`) into a quantitative present-as-flexible-ssDNA proof. **PRESENCE+FLEXIBILITY only, NO bend/twist direction** (crossover-geometry reasoning forbidden). Can-go-red 3 ways (dropped insert→d_tot≠n_extra; paired into ds→ds changes; other type→ss≠n_extra). No production code (bridge shipped e47edb8) — M3 was the VERIFY task | `tests/test_mrdna_extra_bases.py` (`_model_seg_stats` + 3 pins), builds via `backend/core/mrdna_bridge.py::{mrdna_model_from_nadoc,_build_nt_arrays}` | N3 (NAMD extra-base/linker validation — assert insert/linker atoms present + descriptors computable, same PRESENCE/FLEXIBILITY-not-direction pattern); any engine's extra-base coverage check |
| **(P1) MdPipeline stage-spec + chain builder** ✅ | ONE ordered object generalizes the 3 provenance hops (`parent_job_id` + `run_kind="production"` + `seed_oxdna/mrdna_job_id`); `build_pipeline_plan` chains each stage from its IMMEDIATE predecessor (stage 0 → `root_job_id`@`root_checkpoint`; stage N → `parent_job_id=stage{N-1}`, `start_checkpoint="stage{N-1}::output"`); distinct per-stage seeds == `generate_seeds(base,n)`; **1-stage parity: `parent_job_id`/`run_kind="production"`/seed=54321/checkpoint-passthrough == `spawn_md_production`'s first child**; `cross_engine` flag (parent_engine≠stage.engine) REPRESENTS the seed_oxdna/mrdna generalization (P3 converts coords); LITERAL-CONSTANT red guards (parent≠root, checkpoint≠root's, not-two-back) — RED-verified offline (always-seed-from-root mutation fails, revert→green); dict round-trip. PURE, no jobs/no topology (Three-Layer clean) | `backend/core/md_pipeline.py::{PipelineStage,MdPipeline,StagePlan,build_pipeline_plan,validate_pipeline,stage_output_ref}`, `tests/test_md_job_pipeline.py` | P2 (executor consumes `StagePlan`, submits stage N on N-1's completion, halt+resume-from-failed); P3 (`cross_engine` hop → coordinate conversion); P4 (Plan Run UI builds an `MdPipeline`, reuses U2's Forces card per stage) |
| **(P3) cross-engine coordinate handoff** ✅ | PURE `cross_engine_seed(plan, resolved_parent_job_id)`→`CrossEngineSeed`\|`None` generalizes the two seed hops into one table `{oxdna:'oxdna_job_id', mrdna:'mrdna_job_id'}`: same-engine hop→`None` (checkpoint restart); oxDNA/mrDNA root→the matching seed field pointed at the RESOLVED predecessor (never the `stageN` placeholder); raises on unsupported sink (only NAMD rebuilds atomistic from coarse), unknown source engine, unresolved parent. `_chain_spawn` branches: cross-engine→`create_md_job(oxdna_job_id\|mrdna_job_id=parent, field/anchors from stage forces)` (the create-time converter `build_namd_seed`/`_from_mrdna` — nm↔sim-units↔Å already handled), same-engine→unchanged `spawn_md_production`. **Stage protocol default "production" REMAPPED to a valid relaxation preset for the create path** (else create 400s → chain fails; RED-verified vs forward-verbatim). `create_md_chain` accepts an oxDNA/mrDNA root, validated via `assert_namd_seed_available`/`assert_mrdna_namd_seed_available` (frame-on-disk, not MdJob). E2E CHAIN: oxDNA root seeds NAMD stage 0 via reconstruct → completed stage 0 chains same-engine NAMD stage 1 via checkpoint → completed; halt-on-stage0-failure then resume re-runs ONLY stage 0 via a fresh reconstruct. Pure over Physical layer (forces = job-request annotations, no Design write) | `backend/core/md_pipeline.py::{cross_engine_seed,CrossEngineSeed}`, `backend/api/routes_md.py::{_chain_spawn,create_md_chain}`, `tests/test_md_job_pipeline.py` (6 pure) + `tests/test_md_milestone1.py::TestMdCrossEngineChain` (7 route/CHAIN) | P4 (Plan Run UI: a plan's cross-engine stages now execute; reuse the create-path seed contract); any future engine-adapter that seeds NAMD from a new CG source (extend `CROSS_ENGINE_SEED_FIELD`) |

| **(P4) planner payload == MdPipeline** ✅ | TWO-HALF parity: `stage_planner_model.buildChainPayload(model)` (pure add/dup/reorder/remove/setStage/setRoot; immutable, deep-copies field.dir+anchors; `_cleanField` drops disabled/zero field→null) builds a `CreateChainRequest` JSON BYTE-EQUAL to the Python `DEPOSITION_SWEEP_PAYLOAD` literal, which parses through the route's `CreateChainRequest`/`ChainStageRequest` pydantic contract → valid `MdPipeline` (`validate_pipeline`) → `build_pipeline_plan` LINEAR chain (stage N parent=stage{N-1}, checkpoint=stage{N-1}::output, cross_engine on the oxdna→namd stage 0, distinct seeds; RED: downstream≠root). `chainStatusSummary(chainDict)`→ 'stage N of M / queued-behind / partial-failure / resumable' from the executor's `ChainRun.to_dict` shape | `frontend/src/ui/stage_planner_model.js`, `frontend/src/ui/stage_planner_model.test.js` (12), `tests/test_stage_planner_payload.py` (4) | any future chain-authoring UI; the status vocabulary for a job-status card; validating a hand-built chain payload |

_(rows above are seeded targets; mark them shipped as the tasks land.)_

## Session entries

### 2026-07-08 — `P4` Plan Run overlay → CLOSES M-JOB-PLANNER + M-DEPOSITION-CHAIN

**Capability/de-dup proven, not just wired:** the user can now *author a multi-stage chain in one overlay and
queue it as a single `MdPipeline` that runs unattended* — and the **queued chain provably equals the payload the
UI built**. The bright line is a TWO-HALF parity oracle: the pure `stage_planner_model.buildChainPayload` (vitest)
constructs a 3-stage *deposition→immobilize→field-sweep* payload BYTE-EQUAL to a Python literal that the backend
half proves parses through the route's `CreateChainRequest` contract and resolves via `build_pipeline_plan` into a
LINEAR chain (stage N seeded from stage N-1, cross-engine on stage 0). So the UI authors a *runnable P1/P2/P3
chain*, not "a button".

- **Pick.** P4 — the ▶ NEXT and the only U/P-track eligible task (deps P2+P3+U2 all done); closes two milestones.
- **Module-first.** Load-bearing logic is the PURE `stage_planner_model.js` (no DOM/fetch/topology). `md_plan_run.js`
  is thin `createModal` glue that REUSES the shared U2 Forces card (`initForcesCard` engine:'namd', private
  `plan-efield-*` ids) + the shared Anchors card (`initOxdnaAnchorsSetup`, `plan-anchors-*` ids) for the active
  stage — edits write back through `setStage`, switching stages loads via `applyConfig`. No triplicated markup.
- **Wiring.** `client.js` +4 (`createChain`/`listMdChains`/`getMdChain`/`resumeMdChain`, `_oxdnaJSON` style);
  `md_jobs_panel.js` gained `return {getSelectedJob:_selectedJob}` (was `undefined`) → also finally activates N4's
  `getMdJob` compare-source wiring in main.js. `main.js` LOC Δ=+10 (import + factory init + one `⛓ Plan Run…`
  button listener — pure wiring). Stage engine is FIXED 'namd' (the executor only spawns NAMD stages; cross-engine
  is the ROOT hop, and the model/payload support a CG root — proven by the parity fixture using an oxdna root).
- **Review.** Fresh-context read-only review CONFIRMED payload/parity/status/immutability correct and caught TWO
  real `_activeIndex`-tracking bugs in `md_plan_run.js` (removing/reordering a stage *before* the active one left
  the editor pinned to the wrong stage → later edits landed on the wrong stage). FIXED by extracting pure
  `activeIndexAfterRemove`/`activeIndexAfterReorder` (remap the selection through the same transform the model
  applied) + 5 vitest cases for the exact failing scenarios.
- **Gate.** oracle 12+5 vitest + 4 pytest green; `just test` 4427 passed/110 skip/1 xfail (no failures); `just
  test-frontend` 2415; lint clean on touched (19 pre-existing debt untouched); `just smoke` 23/23.
- **Display-vs-oracle.** A one-off Playwright drove the REAL overlay in the running app: stubbed a completed job
  list, authored a 2-stage plan (stage 0 field 7 pN +y), captured `POST /md/chains`, asserted the body == the
  authored payload + `chainStatusSummary` renders "stage 1 of 2" + **0 console errors** → deleted. Live gesture
  (3D-selection→anchor-chip inside a stage; a real unattended chain run + halt/Resume) owes **MV-32**.
- **Gotcha (not a product bug).** The one-off first flagged `_jobs.find is not a function` — my stub returned
  `{jobs:[...]}` but the real `/md/jobs` is a BARE array; the overlay's `_loadRoots` handles both, so fixing the
  STUB (not the product) cleared it. Second gotcha: raw `npx vitest` silently resolved a broken global 4.1.10
  (no jsdom → mass DOM-test failure); the pinned 4.1.1 via `just test-frontend` is correct — always use `just`.

**Comparable prediction gained, not just a run:** N/A for a UI task — the CHAIN capability is the deliverable, and
it's proven (queued chain == a valid `MdPipeline` linear chain), not "the panel renders". M-JOB-PLANNER and
M-DEPOSITION-CHAIN both CLOSED.

### 2026-07-08 — `P3` cross-engine output→input (oxDNA/mrDNA relax → NAMD) through the chain executor

**Capability/de-dup proven, not just wired:** a chain stage now runs *seeded from the previous ENGINE's relaxed
frame* — a completed oxDNA/mrDNA root hands its coordinates to a NAMD stage 0, reconstructed via the *existing,
validated* create-time converter (`build_namd_seed`/`build_namd_seed_from_mrdna`), NOT the same-engine
`.coor/.xsc` checkpoint restart — and on a stage failure the chain HALTS and resume re-runs only the failed
stage. The two hand-wired seed hops (`seed_oxdna_job_id`/`seed_mrdna_job_id`) are now one table the executor
consumes.

- **Pick.** P3 — the ▶ NEXT and the only P-track task eligible (P1+P2 done, P4 blocked on it); U/P tracks are the
  current priority over the parked feature tail (M4/N3/O2).
- **Investigation (read-only subagent) reframed the task.** The oxDNA/mrDNA→NAMD *coordinate + unit* conversion
  ALREADY EXISTS and is validated: `oxdna_runner.build_namd_seed` reconstructs an atomistic model from the oxDNA
  relaxed `last_conf` via CG spline (sim-units→nm inside `read_configuration`); `mrdna_runner`'s analogue does
  Å→nm; both feed `build_atomistic_model` and are wired into `create_md_job` via `oxdna_job_id`/`mrdna_job_id`.
  So P3 was NOT a new unit conversion — it was **routing the chain's `cross_engine` hop through that converter**.
  The no-op seam: `_chain_spawn` ignored `plan.cross_engine` and always called `spawn_md_production` (a
  same-engine restart that `_load_job`s the parent as an `MdJob` → fails on a CG parent).
- **Module** (`backend/core/md_pipeline.py`, still pure, Three-Layer clean): new `cross_engine_seed(plan,
  resolved_parent_job_id)`→`CrossEngineSeed`|`None`. Same-engine→`None` (checkpoint restart); cross-engine→the
  seed field from `CROSS_ENGINE_SEED_FIELD={oxdna:'oxdna_job_id', mrdna:'mrdna_job_id'}` pointed at the RESOLVED
  predecessor; raises on unsupported sink (only NAMD rebuilds atomistic from coarse), unknown source, or
  unresolved parent.
- **Executor wiring** (`backend/api/routes_md.py`): `_chain_spawn` branches on `cross_engine_seed` — cross-engine
  builds a `CreateJobRequest(oxdna_job_id|mrdna_job_id=parent, field/anchors from the stage forces, run_target,
  autostart)` and calls `create_md_job` (reusing its guards + the transient-precondition raise the executor's
  bounded retry already handles); same-engine path unchanged. `create_md_chain` now accepts an oxDNA/mrDNA root,
  validated via the same `assert_namd_seed_available`/`assert_mrdna_namd_seed_available` frame-on-disk check the
  launch card uses. Realizable hop = a completed CG ROOT → NAMD stage 0 (the executor only spawns NAMD; a
  mid-chain CG *stage* would need a CG spawn adapter — out of scope). `main.js` LOC Δ = 0.
- **Review-caught bug (real, fixed).** A stage's protocol defaults to `"production"` (`ChainStageRequest`), but
  `create_md_job` rejects any protocol ∉ `SUPPORTED_PROTOCOLS={mgh_slow_release,equilibrium_aware_namd}` → every
  DEFAULT oxDNA/mrDNA→NAMD stage would 400 → retry×3 → chain fails. Fix: the cross-engine (relaxation-)create
  path maps a non-relaxation stage protocol onto `EQUILIBRIUM_AWARE_PROTOCOL` (an explicit valid relaxation
  protocol is forwarded). **RED-verified** against the pre-fix forward-verbatim code (`Unknown protocol:
  'production'`).
- **Oracle** — 13 new FAST. 6 PURE (`tests/test_md_job_pipeline.py`): oxdna-root→`oxdna_job_id`+resolved-parent,
  mrdna-root→`mrdna_job_id`, same-engine→`None`, unsupported-sink raise, unknown-source raise, unresolved-parent
  raise. 7 ROUTE/CHAIN (`tests/test_md_milestone1.py::TestMdCrossEngineChain`, spawns stubbed): cross-engine uses
  the create path with `oxdna_job_id`+field+anchors (NOT `spawn_md_production`), mrdna→`mrdna_job_id`, same-engine
  uses the checkpoint path, `"production"`→valid-relaxation-protocol REMAP (RED-proven), explicit relaxation
  protocol forwarded, and the E2E CHAIN (oxDNA root → NAMD s0 reconstruct → same-engine NAMD s1 checkpoint →
  completed) + halt-on-s0-failure then resume-reruns-only-s0. New logic ⇒ green-first-run valid; the one adapted
  concern (the protocol bug) proven RED.
- **Review** (fresh-context, read-only): routing (no same-engine→create, no cross-engine→`spawn_md_production`),
  `create_md_chain` CG-root validation (still 400s on missing/incomplete; namd branch byte-unchanged), raise
  conditions, the **all-or-nothing spawn invariant** (every `create_md_job` guard precedes the single
  `_spawn_prep_job` that creates the job → a raised cross-engine spawn guarantees no job, so bounded-retry is
  safe), and Three-Layer cleanliness all CONFIRMED. The one real finding (protocol) fixed + pinned.
- **Gate:** oracle 13/13 (+ broader MD-chain files 99/99); `just test` = **4423 passed / 110 skip / 1 xfail**
  (rerun after the protocol fix; +2 = the two protocol pins vs the pre-fix 4421 run, no drop, no xdist flake);
  ruff clean on all touched files. No card/UI →
  display-vs-oracle N/A (backend-only, like C1/C2/P1/P2). SLOW real oxDNA→NAMD handoff (a live completed oxDNA
  job + real NAMD prep) NOT run → **MV-29** (precedent: P2's real 2-stage chain owed an MV). Substrate for P4;
  `M-JOB-PLANNER` now needs only P4.

### 2026-07-08 — `U4` engine selector + one *Simulate* section → CLOSES `M-UNIFIED-PANEL`

- **Pick.** `U4` (handoff ▶ NEXT; deps U2+U3 both `done`; critical leverage). The last unified-panel task —
  fronting the 5 stacked engine panels with one selector closes M-UNIFIED-PANEL.
- **Oracle FIRST — a per-engine PARITY/de-dup pin, not "it renders".** `engine_selector.test.js` (11 tests):
  (1) PURE STATE — `panelVisibility(e)` shows EXACTLY engine `e`, hides the other four (unknown → all hidden);
  `selectedEngineCards(e)` returns the FULL 8-card universe (never absent), its `state:'enabled'` subset ===
  EXACTLY the U1 `enabledCardKeys(e)`, and every `'greyed'` card carries the descriptor's `cardReason(e,·)` (a
  non-empty string). Ground truth is the U1 descriptor's own helpers, so a selector that omitted/invented a card
  diverges → red. (2) FACTORY — a jsdom harness with 5 stub panel elements: `initEngineSelector` renders one
  button per engine in `ENGINE_KEYS` order; `select(x)` shows only x's panel (`display:''`) + hides the rest
  (`display:'none'`) + marks the active button; a bad `select()` is a no-op; the strip renders one chip per
  universe card with greyed chips carrying the reason as a `title`; `onSelect` fires once per selection; a
  button click selects. Green first run — this is **new logic** (not a moved/adapted lift), so green-first-run is
  valid proof.
- **Module-first build.** New `frontend/src/ui/engine_selector.js` — `initEngineSelector({selectorMount,
  stripMount, panelEls, initial, onSelect})→{select,getSelected,el}`; pure `panelVisibility`/
  `selectedEngineCards`/`isEngine` exported for the oracle. It reads card facts ONLY from the U1
  `engine_capabilities.js` (`ENGINE_KEYS`/`ENGINE_LABELS`/`engineCards`) — single source, so no re-audit. It owns
  no engine logic and no panel internals: it toggles whole-panel `display` (verified none of the 5 panels toggle
  their own whole-panel display — the panels own only their body-collapse, so the selector is the sole owner).
- **DOM + CSS.** A new `#simulate-panel` section (heading "Simulate" + `#engine-selector-mount` +
  `#engine-capability-strip`) inserted before `#oxdna-jobs-panel` in the Dynamics tab; CSS for the segmented
  control (`.engine-selector`/`.engine-selector-btn.is-active`) + capability chips
  (`.capability-chip.is-enabled`/`.is-greyed[cursor:help]`).
- **Wiring.** `main.js` +16 lines — 1 import + one `initEngineSelector({...})` with the 5 panel-element lookups,
  placed right after `initEngineActivityHeaders()` (all 5 panels mounted by then). ALL pure wiring (imports +
  factory init + element lookups), NO cohesive logic — logic lives in the module. (Handoff hoped flat-or-lower;
  +16 is pure wiring per the module-first law, which flags only a *cohesive* net rise. Routing the 5 panel
  inits through a loop to offset is a riskier change beyond U4's oracle scope — deferred.)
- **Gates.** Oracle 11/11; full frontend **2376/2376** (was 2365, +11, no drop); `just lint` fails only on **19
  pre-existing Python ruff** errors (backend/core + tests — none in files I touched; I touched no `.py`); smoke
  23/23 (real app boots the selector init path clean). One-off display-vs-oracle Playwright drove the REAL app
  DOM: 5 buttons render, each engine's `select` shows exactly its panel + hides four, the rendered chip set ===
  the descriptor, greyed chips carry a `title` — PASSED, but it ran against the **welcome overlay** (the API
  design-load didn't reach the frontend view — doc-context), so it exercised the selector DOM without a rendered
  design. Spec deleted after; **MV-28** filed for the live-with-design gesture + hover-tooltip.
- **STATUS = `done` — CLOSES `M-UNIFIED-PANEL`** (U1 descriptor + U2 Forces card + U3 job-list/scaffold base +
  U4 selector). The 6 sidebar panels are now fronted by ONE engine selector whose card visibility is driven by
  the U1 capability descriptor; unsupported cards are **greyed-with-a-why-tooltip, not absent**. NEXT = Track P
  resumes (`P3` cross-engine output→input) toward M-JOB-PLANNER.
- **Capability/de-dup proven, not just wired:** selecting engine X shows EXACTLY X's U1-supported cards and greys
  the rest (present-with-reason) — a single descriptor now drives per-engine visibility across all 5 panels,
  machine-pinned by the 11-test parity/pure-state oracle.

### 2026-07-08 — `U3` slice 2c-3b — converge the md (NAMD) panel scaffold onto `initJobsPanelBase` → CLOSES `U3` (all 5 panels)

- **Pick.** `U3` slice 2c-3b (handoff ▶ NEXT, and rubric #4 "finish the in-progress track"). The last of the 5
  panels; converging it completes the stateful-scaffold de-duplication and unblocks `U4`.
- **Investigation SHRANK the feared scope.** The handoff warned of "module-level `_collapsed` read in ~6 sites"
  + "a 2nd remote `setInterval` poll" needing careful handling. In fact: (a) `_collapsed` lived in only **3
  logical sites** — the init-apply, the heading handler, and the terminal mount gate — all in the collapse block;
  (b) md's `_pollTimer` was **vestigial/dead** (declared + cleared in `_closeWs`, never scheduled); md's live
  updates ride a **WebSocket** + `_remotePollTimer`/`_prewarmTimer`/`_displayTimer` (all `setInterval`, all
  bespoke), so md never used the base's primary `setTimeout` poll at all. So the base is wired with NO
  `tick`/`hasActive` — its `clearPoll()` is a harmless no-op; md's real teardown rides the `onClose` hook.
- **Oracle FIRST (adapted, proven by git-stash rerun).** A PARITY block drives the REAL `initMdJobsPanel`
  (auto-mocked `../api/client.js` so it constructs without the network): (1) section starts collapsed, heading
  click toggles body-display + `is-collapsed` arrow; (2) advanced drawer FIRST-CLICK-OPENS + `rotate(90deg)`
  arrow, second closes; (3) opening fires `_onOpen` (fetches jobs), collapsing STOPS the remote SLURM poll (a
  running Alpine job keeps `_remotePollTimer` re-fetching while open; `onClose`→`_stopRemotePoll` clamps it).
  Behaviour is byte-identical (unlike oxDNA 2c-3a there is **no** stop-on-collapse delta), so the pin was proven
  by **git-stashing the md.js rewrite and re-running the 3 specs against the bespoke code → GREEN**, then green
  again on the converged code = behaviour-preserving adapted-code pin, not green-by-construction.
- **The convergence.** `const _base = initJobsPanelBase({section:'md-jobs-panel',
  els:{heading,body,arrow,advToggle,advArrow,advBody}, arrowStyle:'class', advArrowStyle:'rotate',
  onOpen:()=>_onOpen(), onClose:()=>{_stopMdPrewarm();_stopRemotePoll()}})`. Deleted `let _collapsed`/`let
  _advOpen` + the bespoke collapse + advanced blocks; removed the now-unused `getSectionCollapsed`/
  `setSectionCollapsed` import; rewired the terminal `if(!_collapsed) _onOpen()`→`_base.initCollapsed(true)`
  (same end-of-init slot, preserving the apply-then-onOpen ordering).
- **ADVANCED drawer CONVERGES (the difference from oxDNA 2c-3a).** md's `md-jobs-adv-body` markup is a clean
  `style="display:none"` (no `display:none;display:grid` double-declaration), so the base's display-reading
  toggle opens on first click exactly as md's old `_advOpen`-false-start boolean did — no flip hazard. So both
  the section AND the advanced drawer ride the base.
- **Gates:** oracle +3 (md panel 75/75); full frontend **2365/2365** (was 2362, +3, no drop); smoke 23/23 (real
  app boots the md panel init path clean); `main.js` LOC Δ = 0; frontend lint N/A; no Python touched. Fresh-context
  read-only review: all 6 review points CONFIRMED (no TDZ — `_onOpen`/`_stopMdPrewarm`/`_stopRemotePoll` are
  hoisted `function` decls referenced via lazy arrows; `_collapsedParents` chevron tree untouched; cross-panel
  `_revealMdPanel` reveal intact), no defects.
- **In-app GESTURE not hand-driven → MV-27.** Behaviour-preserving + byte-identical DOM (real-panel PARITY drives
  it at the DOM level + smoke boots the md init path), so no Playwright leg this session; MV-27 filed for the live
  heading-click collapse + advanced-drawer + reload-persistence + poll-stop.
- **STATUS = `done` — CLOSES `U3` (all 5 panels — mrDNA/CanDo/LAMMPS/oxDNA/md — now share the canonical job-list
  renderer + the `initJobsPanelBase` collapse/advanced/poll scaffold).** The run-button HOST was deliberately not
  extracted into the base: run controls are genuinely engine-divergent (Relax/Production vs Coarse/Fine vs
  Alpine-submit vs LAMMPS), so hosting them would give the base many reasons to change (violates cohesion); the
  pure `runButtonEnabled` helper remains available for `U4`. NEXT = `U4` (engine selector + one *Simulate*
  section, unsupported cards greyed-with-tooltip per U1).
- **Capability/de-dup proven, not just wired:** the md panel's collapse state machine + advanced-drawer toggle are
  DELETED and now owned by the shared `initJobsPanelBase` (5th/last consumer), proven by a PARITY oracle that
  drives the real `initMdJobsPanel` and passes identically against the stashed bespoke code and the converged
  code. All 5 engine panels now de-duplicate onto one job-list renderer + one stateful scaffold.

### 2026-07-08 — `U3` slice 2c-3a — converge the oxDNA panel's section-collapse + poll onto `initJobsPanelBase` (U3 stays in_progress)

- **Pick.** `U3` slice 2c-3a (handoff ▶ NEXT was 2c-3 = oxDNA + md). Scoped to **oxDNA only** this session — oxDNA
  (1986 LOC) and md (2803 LOC, with a 2nd remote `setInterval` poll + cross-panel md-collapse coordination) are
  each substantial ADAPTED refactors; converging both in one session risks a parity error. oxDNA alone is a
  complete, reviewable, oracle-backed unit; md is 2c-3b next session.
- **Oracle FIRST (adapted-code, proven in-place-first).** Added a PARITY block driving the REAL
  `initOxdnaJobsPanel` through the converged behaviours: (1) section starts collapsed, heading click toggles body
  + `is-collapsed` arrow; (2) polls `listOxdnaJobs` on the interval while open with a running job, STOPS once
  collapsed; (3) does NOT poll when open but idle (the shared gate). Ran GREEN against the BESPOKE code first —
  and the stop-on-collapse assertion **FAILED** (3 vs 2): the bespoke collapse never cleared the pending
  `_pollTimer`, so one trailing poll fired. That failure PROVES the pin is meaningful (not green-by-construction);
  the base's `clearPoll()` on collapse clamps it. The other two assertions passed on both = byte-identical there.
- **The convergence.** Created `_base = initJobsPanelBase({section, els:{heading,body,arrow}, pollMs:POLL_MS,
  arrowStyle:'class', hasActive:()=>_hasActiveJob()||(selected&&running), tick:_fetchJobs, onOpen:_onOpen})`.
  Removed the module-level `_collapsed`/`_pollTimer` vars + the `_scheduleNextPoll` def. Rewired: `_scheduleNextPoll()`
  callsites→`_base.schedulePoll()`; the left-tab-change `_pollTimer` clear→`_base.clearPoll()`; the three
  `_collapsed` reads (tab-change, workspace-path-change, `_revealMdPanel`)→`_base.isOpen()`/`applyCollapsed(true)`;
  the terminal `if(!_collapsed) _onOpen()`→`_base.initCollapsed(true)`.
- **ADVANCED drawer LEFT bespoke — deliberate.** oxDNA tracks it with an `_advOpen` boolean (first click OPENS);
  the base reads `advBody.style.display`, and the real markup's `style="display:none;display:grid"` computes to
  `'grid'` (last duplicate wins → visible), so a base-driven first click would HIDE. Converging would flip the
  first-click direction = a behavior change, not a lift. Same rationale as the viz-card staying bespoke.
- **Gates:** oracle +3 (oxDNA panel 90/90); full frontend **2362/2362** (was 2359, +3, no drop); smoke 23/23
  (real app boots the oxDNA panel init path clean); `main.js` LOC Δ = 0; no Python touched (`just lint`'s 19
  errors are pre-existing Python debt, none in my files). Fresh-context read-only review: all 6 adapted sites
  CONFIRMED equivalent, only the intended `clearPoll`-on-collapse delta, no TDZ, no stray refs.
- **In-app GESTURE not hand-driven → MV-26.** The one-off display-vs-oracle Playwright was blocked by unrelated
  left-tab-switch plumbing (`#tab-content-dynamics` stayed `display:none` after both a force-click and a
  localStorage-seeded restore) — the tab controller wiring is orthogonal to this change. Rather than rabbit-hole
  (protocol: Playwright is troubleshooting-only), filed MV-26 for the live heading-click + reload-persistence +
  live-poll-stop. The vitest PARITY drives the real panel at the DOM level = the behavioral proof; smoke covers
  the in-app init path.
- **STATUS = `in_progress` (slice 2c-3a of U3).** REMAINING for U3: slice 2c-3b (md: module-level `_collapsed`
  reads + 2nd remote `setInterval` poll + cross-panel md-collapse coordination stay bespoke around the base),
  then U4 (engine selector + one Simulate section).
- **Capability/de-dup proven, not just wired:** oxDNA's collapse state machine + poll timer are DELETED and now
  owned by the shared `initJobsPanelBase` (4th consumer after mrDNA/CanDo/LAMMPS), with a PARITY oracle that FAILS
  on the bespoke code and PASSES on the converged code.

### 2026-07-08 — `U3` slice 2c-2 — converge the LAMMPS panel scaffold onto `initJobsPanelBase` (U3 stays in_progress)

**Capability/de-dup proven, not just wired:** LAMMPS is the FIRST live consumer of the base's `arrowStyle:'class'`
path and the first to use an `onClose` cleanup hook — its bespoke `_applyCollapsed` / heading-click /
`advToggle` listener / `_clearPoll` / `_schedulePoll` (~20 LOC) are gone; it drives the shared
`initJobsPanelBase` and its collapse/advanced-drawer/poll behaviour is proven IDENTICAL by a parity oracle that
drove the real panel through the actual gestures — run green against the pre-rewire code first, then green again
after. Slice 2c-1's `'class'`/`'rotate'` arrow idioms were unit-pinned but consumer-less; 2c-2 makes `'class'` load-bearing.

- **Pick.** `U3` slice 2c-2 (handoff ▶ NEXT): converge the remaining three panels' scaffold. Scoped to **LAMMPS
  only** — the base already supports everything it needs (section `arrowStyle:'class'`, an `onClose` hook, a
  `'text'` advanced-drawer arrow) with exactly ONE *adapted* delta (its poll lacked the base's open-guard).
  oxDNA/md (module-level `_collapsed` var read in ~6 sites, cross-panel md-collapse coordination, md's 2nd remote
  `setInterval`) are a bigger, riskier convergence → deferred to slice 2c-3.
- **Convergence** (`lammps_jobs_panel.js`): dropped the `section_collapse_state` import + `_pollTimer` + the
  `_applyCollapsed`/heading/`advToggle`/`_schedulePoll`/`_clearPoll` blocks; added `const _base =
  initJobsPanelBase({ section:'lammps-jobs-panel', els:{heading,body,arrow,advToggle,advArrow,advBody},
  arrowStyle:'class', hasActive:()=>anyActive(_visibleJobs()), tick:()=>_fetchJobs(), onOpen:()=>_onOpen(),
  onClose:()=>{_viewsOff(); forcesSetup?.detachGizmo?.()} })`. Rewired `_schedulePoll()`→`_base.schedulePoll()`,
  mount `_applyCollapsed(getSectionCollapsed(...))`→`_base.initCollapsed(true)`, and the two
  `body.style.display!=='none'` reads (refresh + design-changed) →`_base.isOpen()`. The bespoke viz-card
  collapse (`vizToggle`/`vizArrow`, no persistence) stays bespoke. Net **−9 source LOC** (334→325).
- **Oracle** (`lammps_jobs_panel.test.js`, +3 it → 19): a PARITY block drove the REAL `initLammpsJobsPanel` factory
  — collapse via a heading click hides the body + sets `is-collapsed` + resets a live view to Off + calls
  `detachGizmo`; the advanced-drawer toggle shows/hides `advBody` + flips the ▾/▸ text arrow; and with a running
  job the poll fires a re-fetch after `pollMs` while open then STOPS once collapsed (fake timers). **Adapted-code
  pin proven:** the block was run GREEN against the pre-rewire code first (pins real behaviour, not the base
  wiring), then green again after the rewire.
- **Gate:** LAMMPS panel+logic 38/38, full frontend **2359/2359** (+3, no drop), smoke 23/23; a one-off Playwright
  drove the real LAMMPS section collapse + advanced-drawer gesture in-app (zero console errors, deleted after).
  Fresh-context review CONFIRMED all six parity checks (collapse, adv drawer, poll, no-dangling-refs, viz-card
  untouched, no TDZ) + noted the open-guard is an incidental HARDENING (cancels a collapse-during-in-flight-fetch
  timer the old code would have armed). No Python touched → backend `just test` not required; frontend lint N/A.
  `main.js` LOC Δ = 0. **No MV row owed** — behaviour-preserving, byte-identical DOM, no new pixels; the gesture
  was Playwright-exercised.

### 2026-07-08 — `U3` slice 2c-1 — shared STATEFUL jobs-panel base (collapse + advanced + poll); converge mrDNA + CanDo (U3 stays in_progress)

**Capability/de-dup proven, not just wired:** the three behaviours that wrap every jobs panel identically —
section-collapse, the advanced-parameters drawer, and the REST poll loop — no longer live copy-pasted in each
`*_jobs_panel.js`. They're one factory (`initJobsPanelBase`); mrDNA + CanDo deleted their verbatim `_applyCollapsed`
/ heading-click / advToggle / `_clearPoll` / `_scheduleNextPoll` and drive the base instead. The de-dup is proven
by a jsdom **conformance oracle** that pins the base reproduces each bespoke DOM effect (body/arrow toggle +
persisted collapse state, advanced-drawer show/hide, poll fires `tick` after `pollMs` ONLY when open && active and
clears on collapse) — with fake timers, not "the panel renders".

- **Pick.** `U3` slice 2c (the last Track-U piece before U4): the stateful base the handoff called out. Scoped to
  mrDNA + CanDo — the two panels whose scaffold was **byte-identical** (same `_applyCollapsed`, same text-arrow ▸/▾,
  same open-guarded `_scheduleNextPoll`), so the extraction is a verbatim lift with a clean parity proof. LAMMPS
  (arrow via `is-collapsed` class + a poll that lacks the open-guard = *adapted*, not verbatim), oxDNA and md
  (`style.transform` arrow + inline `_collapsed` var + md's extra remote `setInterval`) are deferred to 2c-2 so
  their non-identical scaffold doesn't muddy this slice's parity claim.
- **Base** (`jobs_panel_base.js`, 129 LOC, ONE reason to change, deps = `section_collapse_state` + injected
  els/hooks): pure exported decisions `bodyDisplay`/`arrowChar`/`shouldPoll`/`applyArrow` + the factory
  `initJobsPanelBase({tab,section,els,pollMs,arrowStyle,advArrowStyle,hasActive,tick,onOpen,onClose})` →
  `{isOpen,applyCollapsed,clearPoll,schedulePoll,initCollapsed}`. `arrowStyle` covers all three panel idioms
  (`text`/`class`/`rotate`), each unit-tested, but only `text` has a live consumer this slice — so 2c-2 is a pure
  consumer-add.
- **mrDNA + CanDo** (`{mrdna,cando}_jobs_panel.js`): dropped the `section_collapse_state` import + `_pollTimer` +
  the collapse/adv/poll blocks; added a lazy-arrow-wired `const _base = initJobsPanelBase({...})` and rewired
  `_scheduleNextPoll()`→`_base.schedulePoll()`, final `_applyCollapsed(getSectionCollapsed(...))`→
  `_base.initCollapsed(true)`. Each panel keeps its own `_hasActiveJob`/`_onOpen`; CanDo's separate display-card
  collapse block is untouched. Callbacks are lazy arrows (`()=>_fetchJobs()`) so the base captures functions
  defined later in the closure — no TDZ. Net **−42 source LOC** across the two panels.
- **Oracle** (`jobs_panel_base.test.js`, +17 it): pure-helper units (bodyDisplay, arrowChar ▾/▸, shouldPoll's
  open&&active gate, applyArrow across text/class/rotate + null-safe) + a jsdom conformance block against a fixture
  DOM — collapse hides/shows + sets the arrow + fires the right hook + persists (a fresh base reads the persisted
  collapsed state), advanced-drawer toggles both ways, and the poll (fake timers) fires only under open+active,
  doesn't fire collapsed/idle, and is cleared by `applyCollapsed(true)`.
- **Gate:** base+mrdna+cando+model tests 83/83, full frontend **2356/2356** (+17, no drop), smoke 23/23; a one-off
  Playwright drove the real mrDNA + CanDo collapse + advanced-drawer gestures in-app (zero console errors, deleted
  after). No Python touched → backend `just test` not required; frontend lint N/A. `main.js` LOC Δ = 0. **No MV row
  owed** — this is a behaviour-preserving refactor with no new pixels (MV-25 already covers the NAMD row features);
  the gestures were Playwright-exercised.

### 2026-07-08 — `U3` slice 2b — converge the NAMD (md) job list onto the canonical renderer (U3 stays in_progress)

**Capability/de-dup proven, not just wired:** the 2882-line NAMD panel — the richest, the last non-converged
one — now renders its job list through the SAME shared model+renderer as the other four. Its bespoke 144-line
`_jobRow` is DELETED; the renderer now serves **5/5** panels. The convergence is proven by a payload-parity
oracle: the extracted pure `mdJobRowCtx` factory emits the exact per-row payload the bespoke row produced for
every NAMD-specific variant (tree chevron, collapsed-ensemble summary, CG-seed / Alpine post-label badges, the
⧗ remote-queued symbol override with its live-refresh `[data-md-queued]` hook, the "Fix" VRAM-OOM action, the
out-of-date ⚠) — not "the panel renders". oxDNA's byte-parity pin re-ran green, so the three new generic slots
are provably invisible to the panels that don't opt in.

- **Pick.** `U3` slice 2b — the NAMD outlier called out in the handoff; finishing it makes the canonical
  renderer serve all five panels, leaving only slice 2c (stateful `initJobsPanelBase`) + `U4` on Track U.
- **Model/renderer** (`jobs_panel_model.js`/`jobs_panel_render.js`): added THREE generic optional slots, each
  gated on ctx opt-in so a ctx that omits them (oxDNA) is byte-unchanged — `chevron` (leading expand/collapse
  span; every row gets an empty spacer, parents get the ▸/▾ toggle → `onChevron`, `stopPropagation`),
  `postLabelMarkers(job,{childCount,collapsed})` (spans between label and timestamp), `symbolOverride(job)`
  (replaces the spinner/badge status glyph, carries an optional `dataset`). `buildJobListModel` now threads
  `childCount` from `flattenJobTree`; `collapsed` derives from `ctx.collapsedIds`. NAMD's Fix button reuses the
  existing trailing `action` slot (a minor reposition — after the symbol — an intentional visual upgrade).
- **md** (`md_jobs_panel.js`): extracted the row ctx into a module-scope pure factory `mdJobRowCtx({selectedId,
  collapsedIds,jobs,dimColor,warnColor,formatTime})` + a shared `mdJobRowSig` (both `mdListSignature` and the
  ctx's `rowSig` now key off the same per-row fields — single source of truth). Rewrote `_renderList` through
  `jobListSignature`/`buildJobListModel`/`renderJobList` (auto-collapse of Alpine-ensemble parents preserved,
  mutating `_collapsedParents` before the model reads `ctx.collapsedIds`); `_toggleCollapse` still nulls
  `_listSig` (collapse isn't in the signature). Deleted the bespoke `_jobRow` + the `statusBadge`/`statusKeyFor`/
  `makeStatusLegend`/`flattenJobTree` imports; `_legendEl`→`_legend={el:null}` (renderJobList's memo hook). Net
  **−104 source LOC** across the three files.
- **Oracle** (`md_jobs_panel.test.js`, +9 it): a NAMD payload-parity block driving `mdJobRowCtx` +
  `buildJobListModel`/`renderJobList` — chevron on a parent (collapsed→summary marker, subtree hidden; open→no
  summary), replica child labels/titles/indent, CG-seed + Alpine post-label badges, ⧗ symbol override + the
  `[data-md-queued]` DOM hook the poll-refresh selector needs, Fix-action only on VRAM-OOM + out-of-date ⚠,
  chevron click fires `onChevron` NOT the row `onClick`, a **wired Fix button** click fires `onAction` (not
  select), and a leaf still gets an empty chevron span. The existing oxDNA byte-parity pin
  (`jobs_panel_model.test.js` 14/14) re-ran green after the renderer change (adapted-code discipline: the
  extension is proven invisible to oxDNA by the pin, not by green-first-run).
- **Review** (fresh-context, read-only) caught a **HIGH regression**: the initial `_renderList` rewrite wired
  `onClick`/`onChevron` but **omitted `onAction`**, leaving the Fix (VRAM-OOM) button rendered-but-inert and
  `_openVramFix` dead. Fixed (added `onAction: (jobId)=>_openVramFix(jobId)`) + added the wired-Fix-click oracle
  above so it can't silently recur. Two LOW/informational items (Fix button now sits after the status symbol =
  intended oxDNA-chrome convergence; `statusKeyFor` third-arg `null` vs `undefined` = equivalent) accepted. All
  six explicit checks (no dangling refs, auto-collapse ordering, poll short-circuit, closure-freeness of the
  factory, oxDNA no-op for opt-out ctx) came back clean.
- **Gate:** jobs-panel test files 238/238, full frontend **2339/2339** (+9, no drop), smoke 23/23; frontend
  lint N/A (backend ruff only). No Python touched → backend `just test` not required. `main.js` LOC Δ = 0. Live
  NAMD-row pixels (tree chevron/collapse, ensemble summary, seed/Alpine badges, ⧗ queued, Fix button) owe
  **MV-25**.

### 2026-07-08 — `U3` slice 2a — converge cando + lammps job lists onto the canonical renderer (U3 stays in_progress)

**Capability/de-dup proven, not just wired:** the canonical job-list renderer now serves **4 of the 5** engine
panels (oxDNA byte-identical, mrDNA + cando + lammps converged). oxDNA's byte-parity pin stayed green while the
renderer gained an OPTIONAL per-row control — so consolidation provably changed nothing observable for oxDNA,
and the two newly-converged panels are pinned by a CONFORMANCE oracle (mode-as-tag, active-only Stop that fires
`onAction` with stopPropagation, no-`rowAction`⇒no-button guard), not "the panel renders".

- **Pick.** U3 (continue) slice 2a — the cheap "flat like mrDNA" remainder; keeps Track U (the current
  priority) moving. Deferred the md-outlier (2b) + stateful `initJobsPanelBase` (2c) to keep the session
  session-sized.
- **Renderer/model** (`jobs_panel_render.js`/`jobs_panel_model.js`): added an optional trailing per-row control
  — `buildJobRowModel` sets `action = ctx.rowAction ? (ctx.rowAction(job)||null) : null`; `renderJobRow` appends
  a `<button>` only when `m.action` truthy, click = `e.stopPropagation()` + `onAction(m.jobId)`; `renderJobList`
  threads `onAction`. oxDNA/mrDNA/cando omit `rowAction` → `action===null` → no button → byte-parity intact.
- **cando** (`cando_jobs_panel.js`): new `_rowCtx()` (engine `cando`, flat, `candoJobIsActive`, Coarse/Fine as a
  leading tag with title) + `_listSig`/`_legend` + rewired `_renderList` through the canonical model+renderer;
  deleted the old bespoke row + `statusBadge`/`statusKeyFor` imports. Gains `[N]` index, spinner, legend,
  poll-sig short-circuit.
- **lammps** (`lammps_jobs_panel.js`): new `_rowCtx()` (engine `lammps`, flat, `jobRowLabel`, `rowAction` →
  active-only Stop button reusing the old Stop style) + `_listSig`/`_legend` + rewired `_renderList`; two-branch
  empty text preserved, `_visibleJobs()`/show-all honored, Stop still calls `_stop(jobId)`.
- **Oracle** (`jobs_panel_model.test.js`, +5 it → 14/14): cando flat convergence (mode tag, spinner, no button) +
  the action-button block (active-only, click fires onAction not select, no-rowAction⇒no-button). The existing
  oxDNA byte-parity pin re-ran green after the renderer change (adapted-code discipline: the extension is proven
  invisible to oxDNA by the pin, not by green-first-run).
- **Review** (fresh-context, read-only): no correctness bugs; traced the one edge (empty-text uses `_jobs.length`
  while the sig uses `_visibleJobs()`) and confirmed it's unreachable via a real single-tab gesture.
- **Gate:** affected panels 166/166, full frontend **2330/2330** (+5, no drop), smoke 23/23; frontend lint N/A
  (no eslint config; `just lint` = backend ruff only). No Python touched → backend `just test` not required.
  `main.js` LOC Δ = 0 (no wiring change). Live cando/lammps row pixels owe **MV-24**.

### 2026-07-08 — `P1` MdPipeline stage-spec data model + pure chain builder (opens Track P)

**Capability/de-dup proven, not just wired:** ONE ordered `MdPipeline` object reproduces the three
special-cased provenance hops and chains them — a headless builder turns *[field → surface → anchored
field-sweep]* into a linear chain where **stage N is seeded from stage N-1's output**, the data backbone the
whole job-planner track (P2 executor, P3 cross-engine, P4 Plan Run UI) stands on.

- **Pick.** P1 — dep-free, pure-backend foundation; unblocks all of P2/P3/P4 + half of M-DEPOSITION-CHAIN, with
  a clean fast oracle and none of U2's adapted-frontend-extraction risk.
- **Module** (`backend/core/md_pipeline.py`, imports only `md_ensemble` — Three-Layer clean, no `Design` touch):
  `PipelineStage{engine,protocol,field,anchors,surface,run_target,cluster_name,length_ns,steps,label}` +
  `.forces()`; `MdPipeline{stages,root_job_id,root_engine}` + `to_dict/from_dict` (P2/P4 persist it);
  `build_pipeline_plan(pipeline,*,root_checkpoint,base_seed=54321,stage_id_for)` → a chain of `StagePlan`
  descriptors. Stage 0 seeds from `root_job_id`@`root_checkpoint`; stage N>0 from `parent_job_id=stage{N-1}`,
  `start_checkpoint=stage_output_ref('stage{N-1}')="stage{N-1}::output"`. Every hop `run_kind="production"`;
  seeds = `generate_seeds(base,n)` (base..base+n-1). `cross_engine` = parent_engine≠stage.engine (the
  seed_oxdna/mrdna generalization; P3 does the coords). **Creates NO jobs, runs NO submission** (that's P2).
- **Oracle** (`tests/test_md_job_pipeline.py`, 9 FAST): forces-bundle grouping; validation raises on
  empty/bad-run_target/no-engine; **3-stage chain each-from-immediate-predecessor** with literal-constant red
  guards (parent≠"relax-root", checkpoint≠"equilibrated", stage2 parent≠stage0 → not-two-back); distinct seeds
  == `generate_seeds`; **1-stage parity** vs `spawn_md_production` (parent_job_id/run_kind/seed=54321/checkpoint
  passthrough/cross_engine False); cross-engine hop flagged (oxdna→namd); dict round-trip + `StagePlan.to_dict`
  JSON-serializable. **RED-verified offline:** an always-seed-from-root mutation fails the chaining test; revert
  → 9/9 green.
- **Review** (fresh-context, read-only): CONFIRMED-CORRECT — genuine immediate-predecessor chaining, genuine
  1-stage provenance parity (cross-checked vs `routes_md.spawn_md_production` L1596-1611 + `generate_seeds`),
  oracle genuinely red-capable (literal-constant guards, not tautological), no Three-Layer violation. Noted a
  by-design semantic (a pipeline stage's seed axis = sequential stages, not production-sibling fan-out; only
  1-stage parity is required and holds).
- **Gate:** oracle 9/9; `just test` = **4393 passed / 110 skip / 1 xfail** (+9 new, no drop; the xdist
  isolation flake did not fire this parallel run); ruff clean on both touched files (the 20 repo ruff errors are
  banked pre-existing debt in OTHER files). No card/UI → display-vs-oracle N/A (like C1/C2); P4 owes the
  planner-UI MV row. `main.js` LOC Δ = 0 (backend-only).

### 2026-07-08 — `M3` mrDNA extra bases PRESENT as flexible ssDNA in the built ARBD model

**Comparable prediction gained, not just a run:** the mrDNA CG model's flexible-ssDNA content now provably
**responds to extra crossover bases** — every inserted base becomes exactly one single-stranded (flexible,
non-rigid) nucleotide in the built ARBD `SegmentModel`, verifiable headlessly and cross-comparable to CanDo's
C3 signal (both engines say: inserts → more local flexibility, never a bend direction).

- **Task shape.** M3 was explicitly a *verification* task ("verify past the existing display bridge →
  beads present in the simulated model"). The bridge that materializes `Crossover.extra_bases` as ssDNA beads
  shipped pre-loop (`e47edb8`), with pins #1–5 over the pre-model nt-ARRAYS and a coarse pin #6
  (`with_ss > base_ss`). M3 adds the missing **built-model** oracle — no production code.
- **Oracle** (`tests/test_mrdna_extra_bases.py`, new `_model_seg_stats` helper + 3 mrdna-gated FAST pins, ~0.8s
  each): build the `SegmentModel` and sum nt by segment class + bead children. (a) total nt grows by EXACTLY
  `n_extra` for a single "TT" AND for "TT" on all crossovers; (b) that growth is **entirely** in
  `SingleStrandedSegment` while `DoubleStrandedSegment` nt is invariant (`ds_nt`=504 in every case) — the
  flexibility/non-rigid property; (c) the CG bead cloud itself grows (136→229) in bulk, proving it is genuinely
  *past* coarse-graining, not an nt-array re-count. Measured deltas (all-crossovers "TT", n_extra=106):
  `d_tot=106, d_ss=106, d_ds=0, d_beads=93`.
- **Can-go-red 3 ways:** a dropped insert → `d_tot≠n_extra`; an insert WC-paired into a rigid ds segment →
  `ds` changes and `ss` delta ≠ n_extra; a third segment type → `ss` delta ≠ n_extra. Fresh-context review:
  no real gaps.
- **Banked gotcha honored:** extra-base softening is asserted only as **RMSF flexibility / bead-presence**,
  never a twist/bend DIRECTION (the C3/M3/N3 rule — crossover-geometry reasoning forbidden).
- **Gate:** oracle 15/15 green; `just lint` clean on the file (the ~19 repo ruff errors are the banked
  pre-existing debt in other files). Full `just test` = 4366 passed / 72 skip / 1 xfail + **1 pre-existing
  non-deterministic xdist isolation flake** (`test_cando_extra_bases::test_extra_bases_raise_local_flexibility_rmsf`
  — a slow FEM test in an unrelated file/engine; passes in isolation in 7.9s; a *different* victim than the
  `test-fast` run surfaced, confirming a reshuffle-exposed latent bug, not my test-only change). No pass-count
  drop attributable to M3 (added 5 passing tests). The precisely-bisected polluter is logged to
  `issues_ledger.md`.

### 2026-07-08 — `N4` NAMD source bundle → FOURTH/LAST live card column (gold-override reference)

**Comparable prediction gained, not just a run:** the cross-engine comparison card now carries **all
four engines** (oxDNA O1, CanDo C5, mrDNA M5, **NAMD N4**), and NAMD is the **gold-override reference** —
when a NAMD job is selected the card scores oxDNA/CanDo/mrDNA's shape AND RMSF *against NAMD* (the
experimentally-anchored MD engine), the first time the roster is complete and NAMD anchors the comparison.

- **What shipped.** `backend/core/namd_shape_source.py` `build_namd_shape_source(shape_frame, core_reference,
  *, rmsf_positions=None, field=None)` — the O1/C5/M5 twin, same SOURCE-BUNDLE CONTRACT `{engine:"namd",
  descriptors, rmsf, shape_frame, field}`: core-filter to the rigid dsDNA core, emit NAMD's ABSOLUTE
  `compute_shape_descriptors`, remap `rmsf`→`rmsf_nm`. Behaviorally the oxDNA builder with `engine="namd"` —
  `md_trajectory.md_rmsf` emits the SAME positions shape as `production_rmsf` (each entry carries BOTH
  `backbone_position` AND `rmsf`, string `direction`), so shape + RMSF come from ONE Kabsch-aligned pass
  (time-mean structure = the low-noise shape; per-nt trajectory variance = the RMSF).
- **Route** `GET /md/jobs/{id}/shape-source` (`get_md_shape_source`) reuses `_md_traj_inputs` (the job's
  FROZEN prepared design snapshot, not live editor state) + `_run_md_analysis(...'rmsf','md_rmsf'...)` (shares
  the flexibility-map RMSF cache) → passes `result["positions"]` as BOTH `shape_frame` and `rmsf_positions`
  → `{ready(=descriptors is not None), n_frames, ...bundle}`.
- **Frontend** `api.getMdShapeSource` + compare-card `getSources` fetches the selected MD job → `[oxdna, cando,
  mrdna, namd]`; `main.js` captures `const mdPanel` + lazy `getMdJob` (no TDZ — `mdPanel` created via
  `initMdJobsPanel` BEFORE `oxdnaPanel`'s init). **main.js LOC Δ = +3 (pure wiring).** Field deferred
  (`field:None`, like O1/C5/M5).
- **Gold override is the value-add, not the builder.** The builder is a near-clone of O1; N4's bright line is
  that `shape_metrics.reference_for` (`_GOLD_ENGINE="namd"`, wired in S3) returns `"namd"` for every
  observable once a NAMD source is present, and `build_comparison_report` honors it — so the oracle's headline
  is `references.shape=="namd"` AND `references.rmsf=="namd"` on `[oxdna,cando,namd]`, with a negative-control
  proving the flip is NAMD-caused.
- **Oracle** `tests/test_namd_shape_source.py` 8 (7 fast + 1 slow, conftest-registered). The slow real-NAMD
  test RAN on-machine (the 2hb fixture is present): real DCD → `md_rmsf` → ready namd source, override holds.
- **Gates:** oracle 8/8; `just test` 4362 passed / 72 skip / 1 xfail (no drop; the prior xdist active-design
  flake `test_namd_efield::test_no_field_skips_both_guards` PASSED this run); `just lint` clean on touched (19
  pre-existing debt in OTHER files untouched — `feedback_no_bulk_reformat`); `just test-frontend` 2294; `just
  smoke` green (pre + post). Fresh-context review: CONFIRMED-CORRECT, no bugs, no TDZ, Three-Layer clean.
- **Display-vs-oracle:** NOT a new card — a new backend source route into the S5-validated render path (like
  C5/M5). Live 4-engine eyeball → **MV-21** (updated with the N4 slice, including the reference-relabel check).
- **NOTE — unrelated uncommitted `md_vram` work in the tree.** The session inherited a separate WIP stream
  (md_vram/atomistic_cache/namd_runner host-OOM handling) uncommitted. Only the N4 hunk of `routes_md.py` was
  staged (via `git apply --cached` of the trimmed hunk); the `md_vram` changes were left untouched for their
  own commit.

### 2026-07-08 — `M5` mrDNA source bundle → THIRD live card column (CG-trajectory RMSF + copy-key fix)

- **Picked** `M5` — the handoff's `▶ NEXT` recommendation and highest cross-val value among the eligible set
  (deps `S5` met). Card-source tasks lead on cross-validation value, and mrDNA context was warm from M1/M2 (rubric
  #4, finish the in-progress track). Puts a THIRD live engine column on the S5 comparison card via the proven
  SOURCE-BUNDLE CONTRACT: does the cheap CG relaxation predict oxDNA's relaxed shape?
- **What shipped.** mrDNA is now the third live source of the S5 cross-engine comparison card — Physical-layer read
  only, no topology touch.
  - `backend/core/mrdna_shape_source.py` `build_mrdna_shape_source(shape_frame, core_reference, *, rmsf=None,
    field=None)` — the mrDNA twin of O1/C5, same contract `{engine, descriptors, rmsf, shape_frame, field}`:
    core-filter the reconstructed relaxed display frame to the rigid dsDNA core (`_filter_to_reference_core` vs
    `core_reference_geometry`), emit mrDNA's **ABSOLUTE** `compute_shape_descriptors` (S1 estimator), map a per-nt
    RMSF list to the card's rmsf shape.
  - **CG-trajectory RMSF** — `mrdna_runner.mrdna_trajectory_rmsf(design, job_dir)` reconstructs the per-nt relaxed
    frame at each DCD timestep (the same actual-relaxed-axis reconstruction `nuc_pos_override_display_from_coarse`,
    per frame; frames evenly subsampled to `max_frames=40` to bound the per-frame Universe reload) and feeds the
    ensemble to the shared S2 `rmsf_from_ensemble(align=True)` (Kabsch strips the CG bundle's box diffusion). The
    trajectory-variance RMSF source the descriptor set names for oxDNA/NAMD/mrDNA.
  - **COPY-KEY GAP fix (the M5-specific engineering).** mrDNA's `_display_positions` emits crossover extra-base
    inserts as `{helix_id:"__xb__", bp_index:<crossover-id STRING>, direction:k}` — a **string** bp_index that
    crashes the shared `_dev_key` (`int(bp_index)`) oxDNA never lets into its source. The gap bites the SHAPE
    column: the display frame handed to the builder carries those inserts, and `_filter_to_reference_core` /
    `_core_column_key` drop them (non-int bp → not in the core) before the descriptors run. The RMSF list comes
    from the trajectory reconstruction (int keys only, no `__xb__`); `_rmsf_profile` still skips non-int bp
    defensively so a hand-built list can't smuggle one in.
  - `GET /mrdna/jobs/{id}/shape-source` (`routes_mrdna.py`) — reads the job's cached display + a threadpooled
    trajectory RMSF + snapshot design's core reference, returns `{ready(=descriptors is not None), n_frames,
    ...bundle}`; graceful no-display → `{ready:False}`, no-snapshot → 500 (mirrors sibling C5 route).
  - Frontend: `api.getMrdnaShapeSource` + the compare card's `getSources` now also fetches the selected mrDNA job's
    bundle → `[oxdna, cando, mrdna]`. `main.js` captures `const mrdnaPanel` + passes a lazy `getMrdnaJob: () =>
    mrdnaPanel?.getSelectedJob?.()` (same proven no-TDZ pattern as `getCandoJob`).
  - **Field deferred** (`field:None`) — like O1/C5; a follow-up once an anchored mrDNA field run's relaxed frame is
    on hand (build it the M2 way).
- **Oracle** `tests/test_mrdna_shape_source.py` (**9 tests: 8 fast + 1 slow**): engine tag + descriptor
  self-consistency, core mask drops ssDNA ends, **copy-key coverage** (a real display frame with string-bp `__xb__`
  inserts builds a valid bundle — inserts dropped, core intact, descriptors unchanged; RED if the guard were
  gone), rmsf remap (copy preserved, drops None + non-int), field passthrough, empty-core→None RED, **trajectory-
  RMSF path** (monkeypatched reconstruction + fake trajectory length: subsamples to `max_frames`, int keys feed
  `rmsf_from_ensemble`, <2-frame→None), **cross-engine integration** (`[oxdna, mrdna]`→`build_comparison_report`
  ready, shape ref=oxdna, mrdna shape-RMSD ≈0 on a rigid shift); 1 SLOW (registered in conftest): a real ARBD
  coarse run → `_display_positions` + `mrdna_trajectory_rmsf` (n_frames≥2, finite rmsf) → ready mrDNA source.
- **Gates.** oracle 8 fast + 1 slow green; `just test` = **4352 passed / 72 skipped / 1 xfailed / 1 failed** — the
  1 failure is the **documented xdist active-design flake** `test_namd_efield::test_no_field_skips_both_guards`
  (the `/api/md/jobs` create route reads global `design_state` another file's test left; passes ISOLATED and
  ALONGSIDE the new file; my change is additive mrDNA/card code that never touches `design_state`). ruff clean on
  touched; vitest + smoke below. Fresh-context review: product CONFIRMED-CORRECT (contract, key types, guards,
  route, no-TDZ); it flagged the RMSF `__xb__` guard as defending an impossible production input → addressed by
  adding the FAST trajectory-RMSF pin + honest docstring (the gap's real locus is the shape column). **main.js LOC
  Δ = +4** (pure wiring: capture the factory return + one lazy dep). **Display-vs-oracle:** NOT a new card — only a
  new backend source route into the S5-validated render path (already scraped-vs-oracle in S5), exactly like C5 →
  live cross-engine eyeball = **MV-21** (updated with the M5 slice).
- **Comparable prediction gained, not just a run:** the comparison card now carries a THIRD independent engine —
  mrDNA's absolute CG-relaxed shape descriptors + aligned-shape RMSD scored against oxDNA's shape reference, plus a
  CG-trajectory RMSF. oxDNA, CanDo, and mrDNA now cross-validate on the same design through one shared card.

### 2026-07-07 — `M1` mrDNA anchors (ARBD RESTRAINT)

- **Picked** `M1` — per the handoff's rubric recommendation: reuses the SAME shared-scope-resolver→engine-index
  bridge C1/N2 established, and unblocks `M2` (mrDNA field, dep=M1) → the LAST anchored-field milestone
  (`M-ALL-ANCHORS-FIELD` now needs only M2).
- **Investigated** the real mrDNA/ARBD seams: mrDNA groups helices by *base-pairing* (`basepairs_and_stacks_to_helixmap`),
  NOT by NADOC `helix_id` — so a segment's `name` is unreliable for mapping; and the CG model collapses each base
  pair to ONE forward bead. Empirically confirmed (throwaway probes): the model's beads share the input `r`-array
  Å frame (Z matched exactly), `bead.add_restraint((k,))` pins a bead to its own position, `get_restraints()`→
  `(bead,(k,))`, and `model.simulate(dry_run=True)` writes the real `potentials/<name>.restraint.txt`.
- **Built** `backend/core/mrdna_anchors.py` (`initX`-style pure helpers, core imports no `backend/api`): the shared
  `resolve_anchor_particles`→per-nt keys→**nearest CG bead by 3D position** (position-based sidesteps the helix
  remap + 1-bead-per-bp collapse); `apply_anchor_restraints` pins them; `install_anchor_restraints` wraps the
  model's `generate_bead_model` so the RESTRAINTs are re-applied after mrDNA's `clear_beads()`+regeneration between
  multiresolution stages (coarse→fine→frozen-twist wipe beads several times), and applies immediately to the
  as-built coarse beads for the single-pass path. `MrdnaJob.anchors` + route passthrough + runner install — all
  JOB-REQUEST annotation, nothing written to the Design (Three-Layer Law). **main.js LOC Δ = 0** (backend-only).
- **Oracle** `tests/test_mrdna_anchors.py` (6 fast + 1 slow), oracle-first. FAST asserts the bright line: the REAL
  ARBD input file (`dry_run` writer, not our mirror) carries a RESTRAINT line for EXACTLY the resolved beads; idx
  pinned two independent ways (flat enumerate == ARBD `.idx`); stale scope→∅; regeneration-survival RED-checked
  (0 restraints without the wrapper, ≥1 with). SLOW **real ARBD coarse run**: strand-scope anchor holds 10/60
  beads at 0.55 Å median vs free 3.81 Å (**7×**) — the physical anchor prediction, independent of the input check.
  Registered slow in `conftest.py` (`test_real_arbd_anchored_beads_hold`).
- **Gates**: `just test` 4334 passed / 72 skipped (+6 fast oracle over the 4328 baseline; the lone failure was the
  slow test's output-path assumption — mrdna writes PSF to the run dir, DCD under `output/` — fixed, slow test
  green in isolation). `ruff` clean on all M1 files (the ~20 pre-existing errors in other test files left alone
  per `feedback_no_bulk_reformat`). Fresh-context review: no correctness gaps against the oracle (independently
  verified frame/units, per-regen re-apply, no Three-Layer violation, FAST oracle is a true end-to-end check).
- **No display-vs-oracle step**: M1 is a headless anchor entry point — no card/graph, so the Playwright display
  check (step 8) does not apply.
- **Comparable prediction gained, not just a run**: a mrDNA CG run now *holds* a chosen scope (7× hold/move) while
  the rest relaxes — the anchored-region prediction the other engines (C1 CanDo BC, N2 NAMD fixedAtoms) already
  emit, on the SAME shared scope resolver; and it unblocks M2's anchored-field cross-validation.

### 2026-07-08 — `M2` mrDNA uniform E-field (CLOSES M-ALL-ANCHORS-FIELD)

- **Picked** `M2` — the handoff's `▶ NEXT` and the last piece of `M-ALL-ANCHORS-FIELD` (dep M1 done). Reuses M1's
  anchor plumbing + the shared per-nt force descriptor CanDo (C2) / NAMD (N1) already emit.
- **Investigated** the real mrDNA/ARBD force seams (read-only): ARBD restraints are harmonic-only (no constant
  force); the ARBD-native uniform force is a per-`ParticleType` grid — either `forceXGrid` (tabulated force) or a
  `gridFile` potential. Empirically (throwaway probes on a built 6HB): DNA beads carry **charge 0** (so no q·E
  path — apply force directly), split into 2 types D000 (mass 690 ≈5 nt) / D001 (mass 1380 ≈10 nt) with mass ∝ nt
  count; integrator is Langevin past a ~1-timestep relaxation ⇒ **overdamped** drift `Δx = D·F·T/(k_B·T)`.
- **KEYSTONE (cost me a crash):** setting `forceXGrid`/`forceGridScale` with a constant 2×2×2 `.dx` → real ARBD
  **CUDA illegal-memory-access crash** regardless of force magnitude (field-off ran clean, so it was the grid
  format, not the force). The mrDNA-blessed idiom is a **ramp POTENTIAL** `U=-(F·r)` (`arbdmodel.grid.constant_force`)
  applied via `add_grid_potential`/`gridFile` — `-∇U = F` gives the uniform force with no crash. Switched to that.
- **Built** `backend/core/mrdna_field.py` (pure helpers, core imports no `backend/api`): `field_force_vector`
  (per-bead force scaled by `mass/dalton_per_nucleotide`, so TOTAL force = `field_pN × total_nt` exactly),
  `_write_ramp_grid` (linear ramp `.dx`), `apply_field_force` (per-type grid), `install_field_force` (wraps
  `generate_bead_model` so grids survive bead regeneration between multiresolution stages, idempotent).
  `MrdnaJob.e_field` (named `e_field` NOT `field` — `dataclasses.field` is used for `stages` just above and would
  shadow) + `CreateMrdnaJobRequest.field` + guards + runner install after anchors (raises on 0 held beads).
  All JOB-REQUEST annotation, nothing written to the Design (Three-Layer Law). **main.js LOC Δ = 0** (backend-only).
- **Oracle** `tests/test_mrdna_field.py` (9 fast + 1 slow), oracle-first. FAST: per-bead force vs a FIRST-PRINCIPLES
  pN→kcal/mol/Å (independent of the code constant), 2×mass→2×force, `.dx` ramp `-∇U==F` round-trip via `loadGrid`,
  per-type grid wiring, dry-run conf emits `gridFile field_*.dx`, regen-survival RED-checked, 2 REST guards. SLOW
  **real ARBD (2 coarse runs, field-on vs off, one strand anchored)**: anchored held ~0.5 Å while the free bulk
  deflects ALONG +field ~8.5 Å (field-off ±2 Å wander), magnitude within [0.45,2.0]× the overdamped Brownian
  prediction from the engine's OWN diffusivity/mass — **~12% agreement** at the operating point. Registered slow
  in `conftest.py`. Field/steps chosen so the field drift dominates the anchored bulk's stochastic relaxation
  wander while the anchor-adjacent bonds stay intact (a much stronger field rips them → ARBD instability).
- **Fresh-context review** (read-only subagent): product code CORRECT; three findings, all fixed — (1) the
  field-needs-anchor guard only counted anchor CHIPS → the runner now RAISES if the field's anchors resolve to 0
  held beads (the actual COM-drift guard, mirroring N1's prep raise); (2) the slow oracle's magnitude prediction
  used the code's `field_force_vector` so the emission constant CANCELLED in the ratio (green-by-construction for
  the constant) → rebuilt the prediction from `field_pN × _PN_IN_KCAL_MOL_A` directly so a corrupted emission
  constant now falsifies (the exact constant stays pinned by the FAST oracle); (3) a non-numeric field value
  raised inside the route → now caught → clean 400. Band tightened [0.35,2.5]→[0.45,2.0] to catch a ≥2× error.
- **Gates**: 10/10 oracle (9 fast + 1 slow, slow verified green ×4); `just test` 4345 passed / 72 skipped / 1 xfailed
  (fresh full suite, no drop; lone xfail = pre-existing job-archive xdist flake); `ruff` clean on touched files
  (pre-existing debt in other files untouched, per `feedback_no_bulk_reformat`).
  No card/UI → display-vs-oracle N/A (like C1/C2/M1). Live field-job gesture owes an MV row (no in-app field
  picker for mrDNA yet — the field is API-only, like M1's anchors).
- **Comparable prediction gained, not just a run:** a mrDNA CG run now DEFLECTS a resolved free region ALONG a
  uniform field (anchor held, ~8.5 Å along-field vs ±2 Å off) at ~12% of the overdamped Brownian prediction from
  its OWN mobility — the anchored-field deflection CanDo (C2) + NAMD (N1) already emit, off the SAME per-nt force
  descriptor — **closing M-ALL-ANCHORS-FIELD**: all three job engines run an anchored E-field job with a
  comparable along-field descriptor.

### 2026-07-05 — `S1` shape descriptors (shared-metric track head)

- **Picked** `S1` — head of the shared-metric track (M-METRIC-CORE), no deps, critical: no cross-validation
  *claim* is possible until a comparable descriptor set exists. Unblocks S3/S4/O1/C5.
- **Built** `backend/core/shape_metrics.py::compute_shape_descriptors(positions, *, n_slices=0)` — a thin,
  engine-agnostic composition layer over the *locked* `oxdna_health` bundle estimators. One call over any
  engine's display-position map (`{helix_id, bp_index, direction, backbone_position, …}`) returns:
  `twist_total_deg` (signed global twist), `twist_per_turn_deg` (÷ axial_span/`BDNA_PITCH_NM`≈3.505),
  `bend_angle_deg` + `bend_radius_nm` (both from ONE `bundle_slab_centreline` polyline via `_chord_sagitta_bend`
  → internally consistent), `radius_of_gyration_nm`, `end_to_end_nm` (chord between the two axial-end
  cross-section centroids), `axial_span_nm`, `n_nucleotides`. Degenerate frames → per-descriptor `None`
  (twist needs ≥2 helices) instead of crashing.
- **Additive helper** `oxdna_health.bundle_slab_centreline` (+31/−0; the locked estimators are byte-unchanged) —
  exposes the slab-centroid centreline so bend angle+radius derive from the same polyline. Reviewed +31/−0 with
  one caller.
- **Oracle** `tests/test_shape_metrics.py` (9 tests, **fast**), written before the module (imported it first → red
  on missing import). Asserts *properties*: null straight bundle, recovered programmed twist (signed+monotone),
  recovered arc-span angle+radius, Rg grows with bundle radius, and a can-go-red twisted frame. Fresh-context
  review: no defects; one by-design note (core-filtering is the caller's job on real ssDNA-ended frames).
- **Gates**: oracle 9/9; `just test-fast` = 4057 passed / 1 pre-existing flaky (`test_job_archive::
  test_md_list_includes_size` — passes in isolation, the known xdist active-design cross-test artifact, not this
  diff); `ruff check` clean on the 3 touched files (repo has unrelated pre-existing lint debt — not swept, per
  `feedback_no_bulk_reformat`). No UI this session (the card is S5) → no smoke/Playwright.
- **main.js LOC Δ = 0** (backend-only, no frontend).
- **Comparable prediction gained, not just a run:** any engine's frame now yields the SAME twist/bend/Rg/
  end-to-end descriptor set on the SAME substrate — the common yardstick S3 needs to say "these two engines
  agree to X%". (Not itself a cross-engine comparison — that's S3/S5 — but the prerequisite measurement layer.)

### 2026-07-06 — `S2` deviation + RMSF profiles (shared-metric track)

- **Task**: generalize the two engine-specific flexibility/deviation implementations into `shape_metrics.py` as
  engine-agnostic per-nucleotide profiles S3's `compare_descriptors` will consume. Backend-only, fast, no UI.
- **Shipped** (all read-only over positions — Three-Layer Law; copy-aware `(helix,bp,dir,copy)` keys throughout):
  - `deviation_profile(cand, ref, *, align=True)` → `{positions:[{…,deviation}], rmsd_nm, min/max/mean_deviation,
    n}`. `align=True` = Kabsch best-fit candidate→ref (reuses `oxdna_health._kabsch_superpose`; strips rigid pose,
    intrinsic twist/bend survives) — generalizes `geometry_deviation_map`/`measure_geometry_rmsd`. `align=False` =
    direct key-matched distance (exact residual) — generalizes `cando_deviation.compute_deviation`.
  - `rmsf_from_ensemble(frames, *, align=True)` → per-nt RMS fluctuation about the mean over a frame list; the
    variance core of `oxdna_health.production_rmsf` stripped of the oxDNA trajectory-file I/O, so NAMD/mrDNA/any
    ensemble can feed it. CanDo instead supplies NMA RMSF directly (`predict_shape["rmsf"]`).
  - `normalize_rmsf_profile(profile)` → keyed `"{helix}:{bp}:{dir}"` [0,1] map from any `{helix_id,bp_index,
    rmsf_nm,direction?}` list (dir-less → both strands); generalizes `fem_solver.normalize_rmsf` off the mesh.
- **Oracle** `tests/test_shape_deviation_rmsf.py` (**10 tests, fast**), written before the code (imported the new
  names first → red on missing import). Asserts *properties*: rmsd 0 on identical, exact per-nt recovery of a
  known non-rigid displacement, Kabsch removes a pure rotate+translate (`d_raw>1.0` contrast) while a shear
  survives, static ensemble→0, `A/√2` amplitude round-trip, `align=True` strips ~3.6 nm bulk drift yet keeps a
  single-site fluctuation, normalize max→1 + rescale-back + all-zero safety. Fresh-context review: no defects;
  flagged the `align=True`-with-real-motion RMSF branch as unpinned → added
  `test_align_removes_bulk_drift_but_keeps_site_fluctuation` to close it (10th test).
- **Gates**: oracle 10/10; `just test` = **4128 passed / 66 skipped / 1 xfailed** (full suite, no drop); the 3
  touched files are ruff-clean (repo has unrelated pre-existing lint debt in other test files — not swept, per
  `feedback_no_bulk_reformat`). No UI this session (card is S5) → no smoke/Playwright. **main.js LOC Δ = 0**
  (backend-only).
- **Comparable prediction gained, not just a run:** any engine's frame(s) now yield the SAME per-nucleotide
  deviation-from-design (+global RMSD) and the SAME per-nucleotide RMSF on the shared substrate — the two
  profile yardsticks S3 needs to say "engine A's flexibility/shape agrees with engine B to r/Δ". (Not itself a
  cross-engine comparison — that's S3 — but its second prerequisite measurement, completing S1+S2.)

### 2026-07-06 — `S3` cross-engine agreement math (shared-metric track)

- **Picked** `S3` — critical path to `M-METRIC-CORE`: deps S1+S2 both done, and it's the last pure-math
  primitive before the S5 comparison card. It turns S1's descriptor dicts + S2's profiles into an actual
  *agreement score* — the first task that produces a cross-validation *number*, not just a shared measurement.
- **Built** `backend/core/shape_metrics.py` — two engine-agnostic entry points (pure over Physical-layer dicts,
  no topology):
  - `compare_descriptors(candidate, reference, *, align_shape=True)` — scores three observable classes:
    (1) `COMPARABLE_SCALARS` (7 shape descriptors) → `{candidate, reference, abs_delta, signed_pct_delta}`,
    pct = (cand−ref)/|ref|·100, `None` scalar → incomparable, zero-ref → abs_delta w/ `None` pct (no div0);
    (2) `rmsf` → Pearson+Spearman over shared base pairs `{pearson, spearman, n, candidate/reference_mean_rmsf_nm}`,
    degenerate (constant or <2 shared) → `None` coeff (not NaN, via `_finite_or_none`);
    (3) `shape_rmsd_nm` → reuses `deviation_profile(align=True)` Kabsch (rigid pose zeroed, real shape survives).
    A partial bundle yields a partial comparison (missing observable → `None`), never a crash.
  - `reference_for(engines, observable)` — per-observable policy (`shape`/`field`→oxdna, `rmsf`→cando) with
    NAMD gold-override across *all* observables; missing policy engine / unknown observable / empty → `None`
    (a missing reference is reported, never silently mis-assigned).
- **Oracle** `tests/test_shape_compare.py` (**13 tests, fast**), imports written first (red on missing name).
  Asserts *properties*: identical-source perfect agreement; signed-%Δ sign+magnitude; None/zero-ref safety;
  RMSF scaled→Pearson 1 / reversed→<−0.99 / constant→None; aligned-shape RMSD ignores a rigid rotate+translate
  but catches a shear; and `reference_for` policy + NAMD override + missing→None.
- **Review-caught HIGH bug, fixed**: the first cut keyed RMSF on `direction`, but CanDo's NMA RMSF (the *policy
  RMSF reference*) is direction-less (1 entry/bp) while ensemble RMSF is per-strand (2/bp) — the key-sets never
  intersected, so the one pairing the policy exists to make (`reference_for(...,"rmsf")=="cando"` vs any
  ensemble engine) silently returned `None`. Fix: `_rmsf_per_bp` collapses BOTH profiles to a per-`(helix,bp,
  copy)` mean over strand direction (mirrors the strand-agnostic collapse already in `normalize_rmsf_profile`).
  Added `test_rmsf_cando_directionless_vs_ensemble_per_strand_correlates` to pin exactly that case (the oracle
  had been green-by-construction on `direction="forward"` on both sides).
- **Gates**: oracle 13/13 (32/32 across S1+S2+S3); `just test` = **4140 passed / 66 skipped / 1 xfailed / 1
  pre-existing flaky** (`test_job_archive::test_md_list_includes_size` — passes in isolation, the known xdist
  active-design cross-test artifact, not this diff); `ruff check` clean on the 2 touched code files (repo has
  unrelated pre-existing lint debt — not swept, per `feedback_no_bulk_reformat`). No UI this session (card is
  S5) → no smoke/Playwright/display-vs-oracle (N/A: no card yet).
- **main.js LOC Δ = 0** (backend-only, no frontend).
- **Comparable prediction gained, not just a run:** two engines' frames now yield an actual agreement score —
  signed %Δ per shape descriptor, Pearson/Spearman on the per-bp RMSF profile, and Kabsch-aligned shape RMSD —
  with the reference chosen per-observable by policy (incl. NAMD override). This is the first cross-*validation*
  number in the loop; S5 wraps it in the generate/view/export card.

### 2026-07-06 — `S4` unified field-response descriptor (shared-metric track)

- **Picked** `S4` — highest-leverage eligible task: shared-metric track leads, deps=S1 met, low effort, closes
  half of what remained in `M-METRIC-CORE` (S4+S5) and unblocks the E-field oracle every engine's field task
  (C2, M2, N1) will reuse + enriches the S5 card's field panel.
- **Built** `backend/core/shape_metrics.py` — the engine-agnostic E-field layer (pure read-over-positions, no
  topology; NOT Kabsch-aligned — the anchored region IS the common frame, aligning would erase the measured
  motion):
  - `field_response_profile(field_positions, reference_positions, field_dir, anchor_keys, *, anchor_tol_nm=1.0,
    min_free_proj_nm=0.5)` — generalizes `oxdna_health.measure_field_response`. Reproduces its aggregates +
    physical verdict byte-for-byte (`passed` = anchored_max_drift ≤ tol AND free_proj_along_field ≥ min; same two
    `ValueError`s on zero field-dir / no free nts) and ADDS a copy-aware `per_nt` deflection map
    `[{helix_id,bp_index,direction,copy,disp_vec_nm,disp_nm,proj_along_field_nm,anchored}]` plus the mean free
    `deflection_vec_nm`. Keys via `_dev_key` (copy-distinct so inserted-base copies stay separate); anchor
    membership is copy-AGNOSTIC (an anchored bp pins all its copies).
  - `compare_field_response(candidate_profile, reference_profile)` — cross-engine agreement over the SHARED FREE
    nucleotides: `cosine_similarity` (cosine of the two engines' concatenated free displacement vectors:
    identical→+1, opposite→−1, orthogonal→0) + `magnitude_ratio` (‖cand‖/‖ref‖ = relative compliance), `None`
    on degenerate/empty (`n_shared_free=0`). Both profiles normalize `direction` identically → no S3-style
    silent-empty-intersection.
- **Oracle** `tests/test_shape_field_response.py` (**13 tests, fast**), imports written first (red on missing
  name). Asserts *properties*: anchors held + free deflect along field, per-nt map covers every shared nt with
  correct anchored flags, deflection monotone in |F|, fails when anchors drift or free doesn't deflect,
  copy-aware keys stay distinct, zero-field & no-free raise; cross-engine cosine +1/−1/0, magnitude-ratio=3.0 at
  3× compliance, no-shared-free→all-None. Fresh-context review: no correctness gaps against the oracle.
- **Gates**: oracle 13/13 (45/45 across S1–S4); `just test` = **4155 passed / 66 skipped / 1 xfailed** (full
  suite, no drop from S3's 4140 + these 13 + repo growth); `ruff check` clean on the 2 touched files (repo has
  unrelated pre-existing lint debt in other test files — not swept, per `feedback_no_bulk_reformat`). No UI this
  session (field panel lands in the S5 card) → no smoke/Playwright/display-vs-oracle (N/A: no card yet).
- **main.js LOC Δ = 0** (backend-only, no frontend).
- **Comparable prediction gained, not just a run:** two engines' E-field responses now yield an actual agreement
  score — a copy-aware per-nt deflection field, the free-region projection-along-field, and a cross-engine
  deflection cosine + magnitude ratio — so "does CanDo deflect the way oxDNA does under the same field?" becomes
  a number, not a vibe. This is the E-field half of the cross-validation deliverable; S5 wraps it in the card.

### 2026-07-06 — `S5` cross-engine comparison CARD (closes M-METRIC-CORE)

- **Picked** `S5` — the last shared-metric task; the S1–S4 math existed but couldn't be *reported*. Closes
  M-METRIC-CORE and unblocks the per-engine emission tasks (C5/O1/M5/N4). deps=S3 met.
- **Backend** `backend/core/shape_compare.py::build_comparison_report(sources)` — a PURE assembly that composes
  S3/S4 (`reference_for` + `compare_descriptors` + `compare_field_response`) into one card payload from a list of
  per-engine source bundles `{engine, descriptors?, rmsf?, shape_frame?, field?}`: a scalar table (each engine's
  value + signed %-delta vs the SHAPE reference), per-engine RMSF overlay profiles (collapsed per-bp), agreement
  rows (shape-RMSD vs shape-ref, RMSF Pearson/Spearman vs rmsf-ref, field cosine/ratio vs field-ref), and a field
  panel (per-engine held+deflected verdict + cosine-vs-ref). Per-observable reference honors the S3 policy
  (oxDNA=shape/field, CanDo=RMSF, NAMD overrides all). Graceful: 1 engine → raw values no deltas; missing
  observable → no rows for it; never crashes. Read-only over Physical-layer dicts (Three-Layer Law) — no topology.
- **Backend route** `backend/api/routes_shape_metrics.py` — daemon-thread registry (mirrors `routes_oxdna_metrics`):
  `POST /shape/compare/start` (body `{sources:[…]}`) → `{metrics_id}`; `GET /shape/compare/{run_id}` →
  `{state, progress, result?}`. Registered in `main.py`. (Compute is instant now — sources are posted
  pre-computed — but the daemon pattern is kept so the per-engine tasks can later make source-*gathering* slow
  without changing the card.)
- **Frontend** `frontend/src/ui/shape_compare_card.js` — the card factory + PURE helpers (`fmtNum`, `fmtDelta`,
  `scalarTableModel`, `rmsfOverlaySpec` via the shared `metric_graph.buildChartSpec`, `comparisonCSVs`).
  Generate → gather sources → `POST`/poll → render scalar table + RMSF overlay canvas + agreement table + field
  panel; Export → shared `metric_export_modal` (PNG of the overlay via `renderToDataURL`, CSV of the three tables).
  Hosted as a collapsible card in the oxDNA Dynamics panel, wired from `initOxdnaJobsPanel` (`getSources: ()=>[]`
  for now — live per-engine sources are O1/C5/M5/N4, tracked as MV-21). Reuses `metric_graph`/`metric_export_modal`
  verbatim — the card machinery is bound, not rebuilt. **`main.js` LOC Δ = 0.**
- **Oracle** `tests/test_shape_compare_report.py` (**14 tests, fast**), written before the assembly (imported the
  new name first → red). Asserts *properties*: per-observable reference selection incl. NAMD-override; scalar
  reference=0-delta & candidate recovers ±known %; zero-ref→None delta no div0; identical RMSF→Pearson 1 + overlay
  points; rigid-shifted frame→shape-RMSD≈0 (Kabsch); field cosine +1/−1 & magnitude-ratio 3; 1-engine→raw no
  agreement; empty→not-ready; missing observable omits its rows; REST start→poll→result + 404.
- **Frontend pins** `frontend/src/ui/shape_compare_card.test.js` (6 pure-helper + 3 wiring tests): fmt/null, table
  view-model column order + reference flag, overlay series order (ref first) + empty, CSV sections/numbers,
  Generate→poll→render fills tables + enables Export, empty-sources reports not-ready without a run, refresh clears.
- **Display-vs-oracle** (one-off Playwright, deleted): drove the REAL card + REAL client against the REAL
  throwaway backend with two synthetic engine sources; scraped the rendered table and asserted it shows the
  backend oracle's `+10.0%` twist delta, `oxdna · ref`, RMSF Pearson `1.000`, and `Reference: shape=oxdna` —
  displayed == oracle. Passed. Standing human-eye check on live cross-engine data filed as **MV-21**.
- **Gates**: oracle 15/15; `just test-frontend` = **2200 passed / 177 files**; `just test` = **4170 passed / 66
  skipped / 1 xfailed** (full suite, no drop — S4's 4155 + these 15 + the field-ref-fix test);
  `ruff check` clean on all touched backend files (repo's 19 pre-existing lint errors in other test files
  untouched, per `feedback_no_bulk_reformat`); `just smoke` green (pre-work) + the one-off display-vs-oracle.
  Fresh-context review: no correctness bugs; math + layer discipline + backend↔frontend shape contract all
  sound. One benign edge flagged (policy field-reference mislabelled when it carries no field data) — FIXED this
  session (field comparison/panel now resolve the reference among field-carrying engines; new test
  `test_field_reference_resolves_among_field_carrying_engines_only`).
- **Comparable prediction gained, not just a run:** the cross-engine comparison built in S3/S4 is now
  GENERATABLE/VIEWABLE/EXPORTABLE — one card turns two engines' descriptor bundles into a scalar-delta table, an
  RMSF-overlay + Pearson/Spearman, an aligned-shape RMSD, and a field-deflection cosine, with PNG/CSV export.
  M-METRIC-CORE is closed; every per-engine emission task (C5/O1/M5/N4) now has a card to feed.

### 2026-07-06 — `O1` oxDNA source bundle → first LIVE card column (M-CANDO-FIELD track)

- **What shipped.** The S5 comparison card had `getSources: () => []` — the machinery existed but no engine fed
  it. O1 wires the FIRST live source: `backend/core/oxdna_shape_source.py::build_oxdna_shape_source(shape_frame,
  core_reference, rmsf_positions?, field?)` — a PURE Physical-layer assembly that core-filters the relaxed frame
  to the rigid dsDNA core (`_filter_to_reference_core` against `core_reference_geometry` — same mask the
  Graphs-&-Metrics card uses, so ssDNA ends drop out), computes `compute_shape_descriptors` (S1) on it, and maps
  `production_rmsf` positions into the card's rmsf-profile shape. Route `GET /oxdna/jobs/{id}/shape-source`
  (routes_oxdna.py) reads the latest relaxed `last_conf` (same frame `/display` shows) + optional trajectory
  RMSF; frontend `getSources` async-fetches the selected job's bundle. `main.js` Δ = 0.
- **Oracle** `tests/test_oxdna_shape_source.py` (**7 tests, fast**), written before the module (imported the
  missing name first → red). Asserts: descriptors == `measure_bundle_twist(core)` on the exact core frame (the
  "matches oxdna_health" property — same locked estimator, self-consistent), core mask drops ssDNA-end columns
  absent from the reference, `rmsf`→`rmsf_nm` remap (None-rmsf dropped), field passthrough, the bundle drops into
  `build_comparison_report` as a ready `oxdna` SHAPE reference (value present, no self-delta), and RED: an empty
  core reference → None descriptors/frame → not a usable column.
- **Review-caught (claim, not bug).** The descriptors are oxDNA's **absolute** twist/bend on the relaxed frame
  (the cross-engine-comparable quantity — oxDNA-abs vs CanDo-abs), which is the RIGHT choice; but my docstrings +
  the MV-21 wording overclaimed they "match the Graphs-&-Metrics twist/curvature". That card plots the
  **differential** (measured − analytic) twist over the *production trajectory* — a different quantity on a
  different frame. Corrected the module + route docstrings and MV-21 so nobody expects the two cards to show
  equal numbers. Code unchanged; the oracle already asserted self-consistency with the estimator, not the graph.
- **Field deferred.** O1 emits `field: None`. A field bundle needs `field_response_profile` with the pre-field
  reference frame + resolved anchor_keys + field vector off a field JOB — a natural follow-up when C2 needs the
  oxDNA field reference. Shape + RMSF (O1's oracle) ship now.
- **Gates.** 7/7 oracle; `just test` 4177 passed / 66 skip / 1 xfail; ruff clean on touched files (the 19-error
  pre-existing debt in OTHER test files untouched, per `feedback_no_bulk_reformat`); vitest 2200; `just smoke`
  green (pre-work). Live-on-real-relaxed-job eyeball = **MV-21** (updated).
- **Comparable prediction gained, not just a run:** the comparison card now renders a REAL oxDNA column — a
  relaxed job's shared shape descriptors + RMSF, core-filtered — instead of an empty source list; the moment a
  second engine (C5 CanDo) lands, the card computes an actual oxDNA-vs-CanDo agreement with no further card work.

### 2026-07-06 — `C1` CanDo FEM anchors (Dirichlet BC) — M-CANDO-FIELD/COMPLETE track

- **Picked** `C1` — shared-metric track (M-METRIC-CORE) is done, so the next milestone is **M-CANDO-FIELD**
  (needs C1, C2; S4/S5/O1 already done). Rubric: **anchors-before-field**; C1 is low-effort, high-leverage,
  and unblocks C2 (critical) plus the whole CanDo feature track. Eligible alternatives (C3/M1/M3/N1/…) rank
  lower (don't unblock the leading milestone).
- **What shipped.** Anchors (a physical tether held fixed) for the CanDo FEM shape solve — the CanDo analogue
  of a boundary condition. Backend-only; anchors are a **job-request annotation, never a `Design`/topology
  edit** (Three-Layer Law: `predict_shape(..., anchors=...)` kwarg, nothing mutated).
  - `apply_boundary_conditions(K, f, mesh, fixed_nodes=None)` — generalized from the single centroid pin to
    pin all 6 DOF of each `fixed_nodes` index (Dirichlet). `None` **or an empty list** → centroid fallback, so
    a stale anchor that resolves to nothing never leaves the system singular.
  - `solve_prestress_shape(..., fixed_nodes=None)` clamps them at **every** corotational load step → the
    anchored region stays exactly at rest while the rest deflects under the loop/skip eigenstrain.
  - `resolve_anchor_nodes(design, mesh, anchors)` — reuses the **shared oxDNA scope resolver**
    (`oxdna_interface.resolve_anchor_particles`: overhang/cluster/domain/strand/base) → per-nt `(helix,bp,dir)`
    keys collapsed onto the single duplex-core axis node per bp (FORWARD+REVERSE → one node). Out-of-core nts
    (ssDNA ends, extra-base sentinel keys) drop silently — same stale-tolerance as the oxDNA resolver.
  - `predict_shape(design, *, anchors=None)` threads anchors through **both** the nonlinear and linear paths and
    surfaces `anchor_keys: [[helix, bp], …]`. RMSF stays free-free NMA regardless (intrinsic flexibility).
- **Oracle** `tests/test_cando_anchors.py` (**10 tests, fast**), written before the code (imported the new
  names first → red). Asserts *properties*, not "ran": synthetic straight beam — pinned node `u==0` at its DOFs
  & the free tip deflects along a test load; BC pins exactly the requested nodes / `[]`→centroid; resolver maps
  base + cluster scopes to the right node set & drops a stale selection; **prestress solve holds the
  most-deflecting node <1e-9 while the rest still deflects >1e-3** (the physical anchor property, pre-Kabsch);
  an anchor genuinely changes the Kabsch-posed `predict_shape` output + reports `anchor_keys`; an unresolved
  anchor is a no-op (positions identical). Fresh-context review: **no correctness gaps**; honest note — the
  "free-free NMA preserved" RMSF half is *green-by-construction* (the RMSF path never receives anchors, so it's
  free-free by design — consistent with the stated oracle; the positions no-op is the load-bearing check). The
  RMSF comparison uses Pearson>0.999 + mean-within-2% because `eigsh` passes no `v0` → ARPACK start-vector
  jitter makes element-wise `allclose` the wrong tool (that jitter is not an anchor effect).
- **Gates.** oracle 10/10; `just test` = **4186 passed / 66 skipped / 1 xfailed** (+ the 1 known pre-existing
  `test_job_archive::test_md_list_includes_size` xdist active-design flaky — passes in isolation, I touched no
  job-archive code); ruff clean on both touched files (the pre-existing lint debt in OTHER files untouched, per
  `feedback_no_bulk_reformat`). No card/UI this task → **display-vs-oracle Playwright is N/A**. **main.js LOC Δ = 0**
  (backend-only). NB: `just smoke` (pre-work) had one pre-existing FAILING spec unrelated to C1 —
  `assembly_exit_cleanup` (assembly-teardown console error, already has a partial fix commit `d5be41c`) — routed
  to `issues_ledger.md`, not a C1 regression (backend-only change, gated on `just test`).
- **Comparable prediction gained, not just a run:** the CanDo FEM can now hold a **resolved anchor** (u==0 at
  the tethered node) while the rest of the bundle relaxes — the boundary condition every anchored-field
  cross-validation needs. This is the substrate for C2 (E-field deflection is measured *against* a held anchor)
  and shares the exact `resolve_anchor_particles` scope resolver with the oxDNA/mrDNA/NAMD anchor tasks
  (M1/N2), so "anchor scope X" means the same nucleotides across all four engines.

### 2026-07-06 — `C2` CanDo FEM uniform E-field (closes M-CANDO-FIELD)

- **Picked** `C2` — deps (C1) now met; the **M-CANDO-FIELD headline** and the only task left for that milestone.
  Rubric: shared-metric track done, anchors-before-field satisfied (C1), C2 is critical-leverage + closes a
  milestone. "Does the cheap FEM predict oxDNA's field deflection?" is the whole point of the CanDo track.
- **What shipped.** A uniform electric-field body load for the CanDo FEM shape solve — backend-only; the field is
  a **job-request annotation, never a topology edit** (Three-Layer Law), threaded exactly like C1's anchors.
  - `assemble_field_force(mesh, field)` — builds the equivalent nodal-force vector from the **shared oxDNA
    descriptor** `{"field_pN": <force per NUCLEOTIDE, pN>, "dir": [x,y,z]}` (the SAME per-nt force oxDNA applies
    per bead — `OXDNA_FORCE_PN` convention). Each duplex axis node carries `FEM_FIELD_CHARGES_PER_NODE=2`
    backbones → translational load `2·field_pN·dir_hat` (pN), rotational DOF zero (a pure body force). `None` /
    `{}` / zero-mag / zero-dir → exact zero vector; magnitude linear.
  - **Dead load, not co-rotating.** Assembled ONCE in global coords before the corotational loop and added to the
    per-step-reframed eigenstrain each of `n_steps` increments — so it stays fixed in the lab frame as the bundle
    bends (the E-field doesn't rotate with the DNA, unlike the loop/skip eigenstrain). Threaded through
    `solve_prestress_shape(..., field=)` (nonlinear) + `predict_shape(design, *, anchors=, field=)`. A field needs
    ≥1 anchor to hold against (COM drift) — reuses C1's `resolve_anchor_nodes`.
- **Oracle** `tests/test_cando_field.py` (**7 tests**), scored by the shared **S4** `field_response_profile` —
  the exact descriptor oxDNA is validated on. 3 fast `assemble_field_force` unit props (none/zero no-op,
  2·chg/node translational-only + normalized direction, linear magnitude); 4 end-to-end nonlinear-solve tests
  (registered **slow** in conftest): anchored 6HB + transverse field → **anchors held (drift≈0) + free deflects
  ALONG field (proj≥0.5nm)** (the S4 verdict) + **monotone in |E|** (fp 0.05→5.2nm, 0.1→10.4nm) + **zero-field →
  no deflection** (RED guard: else the eigenstrain, not the field, is driving) + `predict_shape(field=)` threads
  through & `field=None` is byte-identical to omitting it.
  - **KEY: measured on the RAW clamped-solve frame, NOT `predict_shape`'s display positions.** `predict_shape` →
    `deformed_positions_with_axis` Kabsch-**reposes** each frame onto the displayed design geometry with a
    per-frame rigid transform, so the straight (field-off) and bent (field-on) frames land in DIFFERENT poses and
    the anchor spuriously "drifts" ~5nm. The raw solved axis-node frame is a genuine common frame (the 6 clamped
    end nodes fully constrain rigid-body motion) → no alignment needed, anchor drift ≈0. **→ the C5 field-source
    builder must emit field-response from the RAW frame, not display positions** (banked below).
  - `n_steps=8` — converged (proj stable across 8→30) and stable; the corotational solve **blows up (element
    inversion → `L**3` overflow) for `field_pN ≳ 0.5`**, so gentle fields (0.05–0.1) were chosen for the oracle.
  - Fresh-context review: **no correctness gaps**. Honest limitation: the public `predict_shape(field=)`'s S4
    verdict is proven only *indirectly* — it routes through the exact `solve_prestress_shape(field=)` the property
    tests validate; asserting S4 on its Kabsch-reposed display frame would falsely fail (inherent, documented).
- **Gates.** oracle 7/7; `just test` = **4194 passed / 66 skipped / 1 xfailed** (+8 vs C1's 4186 = the 7 new
  tests; no drops; slow suite ran under load ~50 from its own real oxDNA+NAMD sim tests → 12min wall, not a
  regression); ruff clean on all 3 touched files. No card/UI → **display-vs-oracle Playwright N/A** (like C1).
  **main.js LOC Δ = 0** (backend-only).
- **Comparable prediction gained, not just a run:** the cheap CanDo FEM now reproduces the **oxDNA field-deflection
  regime** — an anchored tethered-arm whose free region deflects *along* the applied field, *monotone* in field
  magnitude, driven by the *same per-nucleotide force* oxDNA uses. **Closes M-CANDO-FIELD** (C1, C2, S4, S5, O1 all
  done): the shared S4 descriptor now scores both engines from the same load, so a real oxDNA-vs-CanDo field
  cross-validation is one C5 field-source wiring away.

### 2026-07-06 — `C5` CanDo source bundle → SECOND live card column (first oxDNA-vs-CanDo agreement)

- **Picked** `C5` — the handoff's `▶ NEXT` and highest-leverage eligible task (deps `S5` met). The shared-metric
  track is done, so cross-val value dominates: C5 turns the S5 card from an oxDNA-only view (O1) into the **first
  real cross-engine comparison** by adding CanDo as the second source. Low effort (mirror O1's proven template).
- **What shipped.** CanDo is now the second live source of the S5 cross-engine comparison card — Physical-layer
  read only, no topology touch.
  - `backend/core/cando_shape_source.py` `build_cando_shape_source(shape_frame, core_reference, *, rmsf=None,
    field=None)` — the CanDo twin of O1's `oxdna_shape_source`, same SOURCE-BUNDLE CONTRACT: core-filter
    `predict_shape()['positions']` to the rigid dsDNA core (`_filter_to_reference_core` vs `core_reference_geometry`,
    ssDNA ends dropped), emit CanDo's **ABSOLUTE** `compute_shape_descriptors` (S1 estimator, not a differential),
    map `predict_shape()['rmsf']` (`{helix_id,bp_index,rmsf_nm}`) to the card's rmsf shape.
  - **CanDo NMA RMSF is DIRECTION-LESS** (both strands share one axis node) → emitted with `direction=None`. The
    cross-engine `_rmsf_per_bp` collapses over direction anyway (the S3 lesson), so `direction=None` still pairs
    CanDo's per-bp RMSF with oxDNA's per-strand ensemble RMSF instead of a silent empty intersection.
  - `GET /cando/jobs/{id}/shape-source` (`routes_cando.py`) — reads the job's cached display + rmsf + snapshot
    design, builds the core reference, returns `{ready(=descriptors is not None), ...bundle}`; graceful
    no-display → `{ready:False}`, no-snapshot → 500 (mirrors sibling `/cylinders`,`/deviation`).
  - Frontend: `api.getCandoShapeSource` + the compare card's `getSources` (hosted in the oxDNA panel) now fetches
    **both** the selected oxDNA job's bundle AND the selected CanDo job's bundle → `[oxdna, cando]`. `main.js`
    captures `const candoPanel` and passes a lazy `getCandoJob: () => candoPanel?.getSelectedJob?.()` (the CanDo
    panel is created after the oxDNA panel; the arrow only fires on a Generate click, so no TDZ).
  - **Field deferred** (`field:None`) — like O1. When added it MUST come from the RAW `solve_prestress_shape`
    frame, not `predict_shape`'s Kabsch-reposed display positions (C2 lesson).
- **Oracle** `tests/test_cando_shape_source.py` (**7 tests**): 6 fast pure (engine tag + descriptor
  self-consistency, core mask drops ssDNA ends, rmsf remap direction-less + drops None, field passthrough,
  empty-core→None RED, **integration**: `[oxdna, cando]`→`build_comparison_report` ready, refs shape=oxdna /
  rmsf=cando, CanDo shape-RMSD finite ≈0 on a rigid 0.2nm shift, oxDNA RMSF **Pearson 1.0 n=24**, cando
  rmsf_profile `is_reference`); 1 SLOW (registered in conftest): routed 6HB → real `predict_shape` →
  `build_cando_shape_source` → finite absolute descriptors + finite rmsf → ready lone-CanDo report (rmsf ref=cando).
- **Gates.** oracle 7/7 (6 fast + 1 slow); `just test` = **4206 passed / 66 skipped / 1 xfailed**; ruff clean on
  touched files (20 pre-existing debt in OTHER test files untouched per `feedback_no_bulk_reformat`); vitest 2214;
  smoke green (assembly_exit_cleanup flaked once under parallel load, passes isolated — unrelated path). Fresh-
  context review: **CONFIRMED-CORRECT**, no bugs, no TDZ, Three-Layer clean. **main.js LOC Δ = +4** (pure wiring:
  a lazy dep + capturing an existing factory's return). **Display-vs-oracle:** the two-engine (oxdna+cando) card
  RENDERING was already scraped-vs-oracle in S5 (synthetic sources → +10% twist delta, RMSF Pearson 1.000); C5
  only wires the real backend route into that S5-validated render path → live cross-engine eyeball = **MV-21**
  (updated with the C5 slice).
- **Comparable prediction gained, not just a run:** the comparison card now produces the **first real oxDNA-vs-
  CanDo agreement numbers** — CanDo's absolute shape descriptors + aligned-shape RMSD scored against the oxDNA
  shape reference, and oxDNA's RMSF correlated (Pearson/Spearman) against **CanDo as the RMSF reference**. Two
  independent structure predictors now cross-validate on the same design through one shared card.

### 2026-07-06 — `C3` CanDo extra crossover bases as compliant connectors (M-CANDO-COMPLETE track)

- **Picked** `C3` — the handoff's `▶ NEXT` recommendation and highest-leverage eligible task (no deps). Finishes
  the most-progressed track (CanDo: C1/C2/C5 done, only C3+C4 left) → context locality, and extra-bases is high
  leverage. Rubric: prefer finishing an in-progress track.
- **Key finding (honest):** the compliant-connector **mechanism already existed** in `build_fem_mesh` — a
  crossover carrying `extra_bases` meshes as a 2-node WLC ssDNA spring (`k_trans=3·kT/(2·L_c·L_p)`, `k_rot=0`, a
  CanDo CONN3D2 analogue) instead of a rigid link. It shipped **untested** in the Phase-5 commit `9121b78`; the
  JSON's "currently display-only gap-fill" note overlooked it. So C3's bright-line deliverable was the **missing
  property ORACLE**, not new production code — proving the mechanism yields a measurable, correct-sign,
  cross-validatable softening ("not just a run").
- **What shipped.** `tests/test_cando_extra_bases.py` — 3 FAST + 1 SLOW (slow registered in `conftest.py`). All
  read-only over topology; `_with_inserts` does `model_copy(deep=True)` before stamping `extra_bases` (fixture
  construction, not a solver-side topology mutation — Three-Layer clean).
  - **FAST census** — an extra-base crossover meshes as a compliant spring (`k_rot==0`, `k_trans==` the WLC
    formula, `<K_PENALTY/1e3`) and leaves the rigid-link set; spring count `==` #inserted crossovers,
    springs+rigid conserved. CanDo models ssDNA connections as connectors between EXISTING bp nodes → **no added
    nodes**, so "mesh reflects inserts" = the connector TYPE/compliance, not node count.
  - **FAST monotone** — `k_trans("T") > k_trans("TT") > k_trans("TTTT")`, `k1==2·k2`, `k∝1/L_c`; even the
    stiffest insert is `<K_PENALTY/1e4`.
  - **FAST compliance** — a synthetic 2-node connector mesh: under the SAME transverse load a WLC-spring crossover
    lets its node deflect `>1e3×` a rigid link (`u==F/k_trans` vs `F/K_PENALTY`, both exact). Single connector →
    the softening sign is unambiguous, no geometric reasoning.
  - **SLOW softening** — routed 6HB, inserts on a middle-third BAND of crossovers → real `predict_shape`+free-free
    NMA shows LOCAL per-bp RMSF at the inserted-crossover nodes rises `>1.3×` (~**1.87×** observed), EVERY affected
    node more flexible; surfaced through the shared S3 `compare_descriptors` RMSF channel
    (`candidate_mean_rmsf > reference*1.1`). **RED-guard:** a self-vs-self base rerun over the same nodes is flat
    (`<1.05×`), so the softening is attributable to inserts, not NMA jitter.
- **Deliberately asserts NO twist/bend DIRECTION.** Softening inter-helix coupling redistributes a distributed
  field/eigenstrain load **non-monotonically** (verified probe: the anchored-field free along-field projection is
  NOT a clean function of insert count — inserts on all 50 crossovers *lower* it while disintegrating the bundle
  to 7 nm RMSF). Reasoning about the twist/bend sign geometrically is exactly what the crossover rules forbid.
  RMSF/flexibility is the physically-unambiguous softening signal AND CanDo's designated reference observable —
  so the oracle rides that channel.
- **Gates.** oracle 4/4 (3 fast in 1.0s + 1 slow); `just test` = **4210 passed / 66 skipped / 1 xfailed** (was
  4206 → +4 = the new tests, no drops); ruff clean on touched files. Fresh-context review: **no correctness
  gaps**, the 2-node compliance math hand-verified (`F/k_trans` vs `F/K_PENALTY`), RED-guard meaningful,
  Three-Layer clean. No card/UI → display-vs-oracle **N/A** (backend-only, like C1/C2). **main.js LOC Δ = 0.**
- **Comparable prediction gained, not just a run:** the CanDo FEM now makes a **measurable, correct-sign
  flexibility prediction for extra crossover bases** — inserts raise local per-bp RMSF ~1.87×, scored through the
  shared S3 RMSF channel, so an oxDNA/NAMD ensemble RMSF (which also rises at ssDNA inserts) can cross-validate it.
  CanDo's fourth-feature (extra-bases) coverage is now a proven prediction, not an untested code path.

### 2026-07-07 — `C4` CanDo linkers / overhang connections (CLOSES M-CANDO-COMPLETE)

- **Picked** `C4` — the handoff's `▶ NEXT` and last CanDo task (deps `C3` met); finishes the most-progressed
  track and **closes M-CANDO-COMPLETE** (C1,C2,C3,C5 done). Rubric: prefer finishing an in-progress track +
  milestone-unblock bonus.
- **User clarification reframed the task (ask-first paid off).** The plan imagined a C3-style FJC spring between
  two resolved overhang nodes. But a probe showed `connect_overhangs` **materializes real topology**: a linked
  overhang is DUPLEX (the overhang staple hybridizes to the linker's reverse-complementary binding domain — the
  user's correction) and the route generates the overhang complement strand + a `__lnk__` bridge helix (ds: a
  duplex 2-strand bridge; ss: a single-stranded bridge = the flexible tether). The real gap was that
  `build_fem_mesh` **couldn't see the duplex the linker builds**: `_duplex_bp_per_helix` counted *scaffold∧staple*
  only, so *staple∧linker* (linked overhang) and *linker∧linker* (ds bridge) meshed to **nothing** (probe:
  `Counter()` nodes, 0 springs, 0 links). Asked the user (2 focused questions) → approved **additive duplex +
  hop-coupling**, **ds = duplex beams + rigid hops / ss = WLC spring**.
- **What shipped (two additive changes, `backend/physics/fem_solver.py`, backend-only).**
  1. **`_duplex_bp_per_helix`** now returns `(scaf∧stap) ∪ (fwd∧rev∧link)` — buckets bp by strand DIRECTION and by
     LINKER type; the `∧link` gate makes the new term **empty on any design with no linker strands**, so the
     classic set is byte-for-byte unchanged (zero exp36 regression). A ss bridge (one backbone) has empty
     `fwd∧rev` → correctly excluded (it's the tether, not duplex).
  2. **`_add_linker_hops`** closes the load path at each LINKER strand's helix-hop junctions (these are NOT
     `Design.crossovers`): walks the strand's meshed duplex domains 5'→3', coupling consecutive meshed domains on
     different helices — **RIGID link** if directly adjacent (a ds bridge), **WLC spring** (`k_rot=0`,
     contour = skipped-ssDNA-run × `RISE_SS`) if they flank an unmeshed ss run (a ss linker). ds hops →
     `rigid_links`, ss hops → `springs`; reuses the existing beam/crossover/spring assembler, **no new mesh field,
     no assembler change.**
- **Oracle** `tests/test_cando_linkers.py` — 5 FAST. THE bright line on a synthetic 2-part mesh (a WLC linker
  transmits a load part A→part B; NO linker → part B exactly `0`; rigid couples `>10×` the soft tether).
  Additive-no-regression (independent legacy `scaf∧stap` recompute `==` `_duplex_bp_per_helix` on a linker-free
  6HB — full dict equality). Real routed-6HB **ds** (overhangs+bridge gain duplex bp, bridge meshed, rigid hops
  **wire the bridge to BOTH overhang helices** — connectivity via `_connector_helix_pairs`, not a bare count;
  0 springs) + **ss** (bridge stays unmeshed, exactly +1 WLC spring spanning the two DISTINCT overhang helices,
  `k_trans==WLC(6)`). Real fixture = `_place_two_overhangs_on_6hb` (well-formed 5'→3' domains; the hand-built
  `_seed_two_overhang_leaves` has malformed REVERSE `start<end` → empty `domain_bp_range` → won't mesh — noted).
- **Gates.** oracle 5/5 (all fast, <1s); `just test` = **4215 passed / 66 skipped / 1 xfailed** (was 4210 → +5,
  no drops); FEM-solver + exp36-curvature calibration guards green (no regression); ruff clean on touched.
  Fresh-context review: **both code changes correct + genuinely additive, no bug** — flagged 2 census/
  green-by-construction oracle tests, both **strengthened** (rigid>soft magnitude; ds rigid-hop connectivity).
  No card/UI → display-vs-oracle **N/A** (backend-only, like C1/C2/C3). **main.js LOC Δ = 0.**
- **Comparable prediction gained, not just a run:** the CanDo FEM now mechanically **couples two parts through a
  linker** — a ds overhang-connection meshes as a stiff duplex bridge, a ss one as a compliant WLC tether — so a
  load/eigenstrain on one part propagates to the other with a linker-type-dependent stiffness. This closes CanDo's
  fourth feature: all four unconventional features (anchors, E-field, extra-bases, linkers) are covered predictions
  feeding the comparison card. **M-CANDO-COMPLETE done.**

### 2026-07-07 — `N2` NAMD anchors (fixedAtoms) — M-ALL-ANCHORS-FIELD track

- **Mechanism.** NAMD anchors = `fixedAtoms` (Dirichlet hold), NOT the ramped `consref`/`conskfile` block. NAMD
  allows only ONE `conskfile`, already spent on the slow-release all-DNA restraint; `fixedAtoms` is orthogonal, so
  anchors persist immobile across the whole ladder while the harmonic restraint ramps to zero. This matches the
  CanDo Dirichlet-BC / oxDNA high-stiffness-trap semantics (an anchor holds hard), and makes the FAST oracle
  ("marks EXACTLY the resolved atoms") IMPLY "held" via NAMD's fixed-atom guarantee — no GPU run needed.
- **Shared-resolver reuse (the whole point).** `resolve_anchor_residue_indices` reuses the SAME
  `resolve_anchor_particles` scope resolver (overhang/cluster/domain/strand/base) that oxDNA (C1's `resolve_anchor_nodes`
  mirror) and the CanDo FEM use → per-nucleotide `(helix,bp,dir)` keys, mapped to atomistic residues by the
  `Atom.helix_id/bp_index/direction` provenance (the same bridge `protein_enm._dna_terminus_model_atom` uses).
- **THE lesson (review-caught HIGH): a positional mark must mirror the EXACT generator that built the target PDB.**
  psfgen's `writepdb` blanks the segid column and the 1-char chain aliases past 62 strands, so a NAMD constraints/
  fixedAtoms PDB (matched to the structure by atom ORDER) can only be addressed by residue ORDINAL — never segid or
  (chain,resid). But there are TWO package-PDB generators with DIFFERENT residue orders: `export_pdb`
  (`require_full_topology=False`, the `mgh_slow_release` default) groups chains by `itertools.groupby` in NATURAL
  first-occurrence order (A,B,…,Z,AA,…); psfgen (`require_full_topology=True`) SORTS chains lexicographically
  (A,AA,…,B). They coincide for ≤26 strands and DIVERGE past it → a resolver that hard-codes one sort silently
  fixes offset residues on any real (100s-of-staples) origami. A DNA-only ≤12-strand test can't see it (natural==
  sorted). Fix: `built_pdb_residue_keys(sort_chains=)` + `resolve_anchor_residue_indices(full_topology=)` select the
  matching order (and `include_proteins`), threaded from prepare's `require_full_topology`; proven on the 176-strand
  `make_18hb_routed_design` (real `export_pdb` output residue sequence == natural, ≠ sorted). Bank: **when marking a
  file NAMD matches positionally, don't re-derive the order independently — reproduce the specific generator's
  ordering, and test at a strand count that makes the orderings diverge.**

### 2026-07-07 — `N1` NAMD native E-field (eFieldOn/eField) — closes NAMD's anchor+field pair

- **Comparable prediction gained, not just a run:** NAMD now drives every nucleotide with the SAME per-nt force
  `field_pN` oxDNA/LAMMPS/CanDo use — verified by a real-NAMD differential probe: an anchored strand holds
  exactly, the free strand's field-isolated ΔCOM points along +field (cosine 0.99996) with magnitude within 10%
  of `½(F/M)t²` computed from `field_pN` and NAMD's own −7 e strand charge. So a NAMD field-deflection descriptor
  is now directly comparable to oxDNA's (S4) and CanDo's (C2) on the same tethered-arm regime.
- **Mechanism.** `namd_efield_vector({field_pN,dir})` → NAMD `eField` (kcal·mol⁻¹·Å⁻¹·e⁻¹) with the exact
  conversion `eField = field_pN·dir̂ / (K·q)`, `K=69.477 pN` per kcal·mol⁻¹·Å⁻¹, `q=−1 e`. NO effective-charge
  fudge (unlike the frontend's V/m→pN `q_eff≈0.25` helper): in **explicit solvent** the condensed counterions are
  real particles that screen the field themselves, so the physically-correct AND cross-engine-comparable driving
  force on the DNA is the bare −1 e per phosphate. Emitted via `external_forces_block` — the ONE writer that now
  owns both the N2 `fixedAtoms` block and the field, DRY across `_segment_conf`/`_min_conf`/both production
  writers/shell-reprep/remote+local resume.
- **Review-caught HIGH (fixed).** The API guard "a field needs an anchor" counts anchor CHIPS, but a non-empty
  scope that RESOLVES to nothing (stale / ssDNA-only) slips past it → prep now raises rather than launch the
  COM-drift run the guard exists to prevent. Two production conf writers (`_conservative`/`_seed`) also silently
  dropped anchors since N2 — now carry both anchors and field. `md_shell_reprep` read anchors/field back from a
  manifest it wrote WITHOUT them (no-op) — now threads them through prepare so the marker PDB is rebuilt for the
  carved system.
- **Engine facts extracted from the NAMD binary, not guessed.** `strings namd3` gave the exact fatal
  "EField is not compatible with multi-GPU GPUresident" (→ a 400 guard; single-GPU is fine) and confirmed
  NPT+`fixedAtoms` runs without error (a pressure-accuracy caveat for LARGE fixed regions, already documented in
  the N2 code comment; negligible for end-anchors). Also fixed 2 pre-existing frontend bugs the review surfaced:
  toast severity `'warn'`→`'warning'`, and a V/m sub-panel's duplicate inline `display:grid` (rendered visible
  then inverted on first click).

### 2026-07-08 — `U1` engine capability descriptor + registry (unified-panel track foundation)

- **De-dup PROVEN as a single source of truth, not just wired:** `engine_capabilities.js` now names, for all 5
  engines × 8 cards (run/efield/anchors/surface/advanced/viz/metrics/joblist), exactly what each bespoke panel
  renders today — the data the shared U2 Forces factory / U3 jobs-base / U4 selector will iterate INSTEAD of the
  5 hand-written `*_jobs_panel.js`. Every unsupported card is **present-but-disabled with a why-reason**
  (mrDNA efield/anchors "run at the ARBD model level, no per-run card yet"; CanDo/NAMD "no hard-surface BC";
  LAMMPS/mrDNA "no standalone metrics card") — so U4 can grey-with-tooltip where today the panel simply OMITS
  the card. That absent→disabled shift is the whole point of the descriptor.
- **PARITY census oracle (19 tests), three independent tripwires:** (1) descriptor's enabled/disabled flags +
  anchor ids must match a hand-audited census field-for-field → editing the descriptor alone goes red;
  (2) every ENABLED card's `domAnchorId` must EXIST in the live `index.html` (no inventing a card) — read via
  `fs`, grep-equivalent; (3) every UNSUPPORTED card's conventional probe id must be ABSENT from `index.html`
  (no silent support). Plus a completeness check: every engine carries an entry for every card (`never absent`).
- **Oracle caught a real anchor error:** LAMMPS renders its job list as a bare `lammps-jobs-list` container with
  NO collapsible `-toggle` (unlike the other 4 engines) — the first descriptor guessed `lammps-jobs-list-toggle`
  and tripwire #2 went red against the DOM. Fixed the anchor; the census is now the true panel inventory.
- **Pure data + helpers** (`supportsCard`/`cardReason`/`enabledCardKeys`/`engineCards`, all safe on unknown
  keys); no DOM, no I/O, no `main.js` wiring yet (consumed by U2–U4). `main.js` LOC-Δ = 0. New module → green-
  first-run is valid proof (not adapted/moved code). No card rendered → no display-vs-oracle Playwright; the
  standing eyeball owes an MV row when U4 renders the unified stack.
- **Review (fresh-context, read-only):** census + oracle + helpers CLEAN; verified all 34 enabled anchors exist
  and all 7 disabled probes absent. One LOW future-drift note — tripwire #3 guesses a card's *conventional* id,
  so a future card reusing the shared `efield-toggle` id under a different engine could stay green; can't produce
  a current false result; left as-is (tripwires #1+#2 carry the parity).

### 2026-07-08 — `U3` (slice 1) canonical job-list model + renderer — unified-panel track

- **User steer reframed the task:** the oxDNA jobs panel is the CANONICAL one (correct parent/child indent,
  list index, status icons, legend, naming); all engines should CONVERGE to conform to it — the shared base is
  the oxDNA model, not a lowest-common-denominator. Re-scoped this session's slice accordingly (effort=high; a
  5-panel big-bang incl. the 2882-line md outlier is reckless in one session).
- **De-dup PROVEN by byte-parity PIN, not just wired:** extracted the oxDNA row/list SHAPE into a PURE
  `jobs_panel_model.js` (`buildJobRowModel`/`buildJobListModel`/`jobListSignature`/`runButtonEnabled`) + a DOM
  `jobs_panel_render.js` (`renderJobRow`/`renderJobList`). The oracle `jobs_panel_model.test.js` carries a
  VERBATIM copy of the OLD oxDNA `_jobRow`/`_renderList` (`oldOxdnaJobRow`) and drives OLD+NEW on fresh DOMs →
  identical `outerHTML` across every branch (root/child/running-spinner/[AR]/archived+size+📦/stale-⚠/selected).
  This is the ADAPTED-CODE PIN done right (old-vs-new byte-equal, not green-first-run).
- **Rewired the CANONICAL panel (oxDNA) onto the shared module** — deleted its `_jobRow`/`_listSignature`/local
  `makeSpinner`; `_renderList` now `renderJobList(buildJobListModel(jobs, _rowCtx()), …)` with the same
  signature short-circuit; oxDNA-specific data (displayName/childLabel/[AR] tags/stale/archive/size) all supplied
  as `_rowCtx()` callbacks. oxDNA DOM is byte-identical (pin + its own 87/87 tests + smoke). `makeSpinner` moved
  to the shared `job_status_symbol.js` (re-exported from oxDNA for its importers/tests).
- **Converged the smallest panel (mrDNA) as the first real de-dup:** mrDNA's ad-hoc flat innerHTML `_renderList`
  replaced by the same `buildJobListModel`+`renderJobList` — an intentional VISUAL UPGRADE: mrDNA rows now gain a
  `[N]` list index, a spinner while running (was a static glyph), a status legend, and the poll short-circuit.
  Its `_rowCtx` is flat (`hierarchical:false`, no tree/archive/size). Vitest render test builds real DOM for 2
  mrDNA jobs (spinner on running, glyph on completed). Live-pixel eyeball owes **MV-23**.
- **Gates:** oracle 9/9; affected panels 112/112; frontend 183 files / 2325 passed (+9 new, no drop); smoke
  23/23; ruff N/A (frontend-only; the 19 pre-existing `just lint` errors are untouched Python debt). `main.js`
  LOC Δ = 0 (no wiring change — the two panels self-rewire). Net −48 LOC across the panels (de-dup). Fresh-context
  read-only review: no confirmed issues; the pin is genuine (old-vs-old-free).
- **STATUS = `in_progress` (slice 1 of U3).** REMAINING: converge cando/lammps/md onto the renderer (md is the
  2882-line outlier — tree via `flattenJobTree` w/ collapse chevron, setInterval + remote/Alpine timers, no
  returned api); factor the shared run-button/poll/collapse/advanced-drawer into a stateful
  `initJobsPanelBase({engine,descriptor,deps})`; `runButtonEnabled` exists but no panel consumes it yet.
- **Capability/de-dup proven, not just wired:** the canonical oxDNA job-row DOM is now emitted from ONE shared
  model+renderer (byte-identical pin), and mrDNA's bespoke row rendering is DELETED in favor of it.

### 2026-07-08 — `U2` shared Forces (E-field) card factory — unified-panel track

- **De-dup PROVEN by per-engine PARITY, not just wired:** the THREE triplicated Electric-field cards collapse
  into ONE `forces_card.js` `initForcesCard({engine,ids?,gizmo?,getBaseCount?,getAnchorCount?,onChange?})` →
  `{getFieldSpec,isEnabled,refresh,applyConfig,detachGizmo}`, `getFieldSpec()`→`{field_pN,dir,enabled}`. DELETED
  `efield_setup.js` (oxDNA, gizmo) + `cando_efield_setup.js` (CanDo+NAMD, numeric); the LAMMPS field third of
  `lammps_forces_setup.js` now DELEGATES to the factory (its Anchors + Surface cards + public API
  `getForces/getAnchors/fieldNeedsAnchor/detachGizmo` unchanged). Rewired call sites: `main.js`
  (`engine:'oxdna'`+gizmo), `cando_jobs_panel.js` (`engine:'cando'`), `md_jobs_panel.js` (`engine:'namd'`).
- **Per-engine divergences are DATA, not code paths** (`FORCES_FIELD_VARIANTS` + `FORCES_FIELD_IDS`): gizmo vs
  numeric (driven by whether a `gizmo` is passed), V/m sub-panel (driven by DOM-id presence — LAMMPS has none),
  default dir `[0,1,0]` vs LAMMPS `[1,0,0]`, ready-line style (`apply` "needs ≥1 anchor", verb run/solve, vs
  `lammps` weak-warn + contextual anchor note read from `getAnchorCount`), gizmo-visibility gate (`open-or-job`
  oxDNA vs `open-and-enabled` LAMMPS), job-arrow persistence, close-on-leave-tab.
- **ADAPTED-CODE PIN (CLAUDE.md), proven the right way:** the parity oracle drove the LIVE old bespoke factories
  AND the new `initForcesCard` through the SAME input sequence on fresh DOMs and asserted byte-equal payloads for
  all 4 engines — proof against the in-place old code, **not green-first-run** (13/13 green while both existed).
  The durable `forces_card.test.js` then pins each engine's explicit payload + gizmo-drag + applyConfig + V/m +
  ready lines. Independently, the refactored LAMMPS module still passes its **9 pre-existing** tests
  (behaviour-preservation — those tests predate the change).
- **The one thing unit tests can't cover, verified separately:** all field DOM ids in `FORCES_FIELD_IDS` confirmed
  present in the live `index.html` (a typo'd id → silent no-op in the app), and `just smoke` (console-error gate,
  loads a real design) green 23/23 → the rewired cards mount + boot clean in the running app.
- **Gates:** forces_card oracle 13/13; frontend 182 files / 2315 passed (−16 = 2 deleted bespoke test files, their
  coverage folded into `forces_card.test.js` + preserved LAMMPS tests — no product regression); smoke 23/23; ruff
  N/A (frontend-only, no `.py`; the 19 pre-existing `just lint` errors are untouched Python debt). `main.js` LOC
  Δ = +1 (import swap + `engine:'oxdna'` arg; no cohesive logic added — the field logic MOVED out, factory init
  is thin wiring). Display-vs-oracle: DOM byte-identical rewire (same ids/markup) → live 4-panel gesture owes
  **MV-22**.
- **Review (fresh-context, read-only) caught ONE real regression, fixed:** the reviewer confirmed all 4 engines'
  field payloads are byte-equivalent to the pre-refactor cards, but found that leaving the Dynamics tab with the
  LAMMPS field card **open + enabled** no longer detached its scene arrow (old LAMMPS detached unconditionally;
  the shared handler's `else _syncGizmo()` re-attached under LAMMPS's `open-and-enabled` gate). Fixed: the
  tab-change handler now `_close_()`s where the card closes on leave (oxDNA) else `gizmo.detach()` directly —
  reproducing both bespoke cards' always-detach-on-leave. Added a RED-verified regression test (both oxDNA +
  LAMMPS detach on leave; fails on the old `_syncGizmo()` path). Benign non-regression the reviewer noted +
  kept: the shared `magInput` handler also calls `_syncVpm()` for oxDNA (the old oxDNA card didn't) — updates the
  V/m helper's display value only, never the `{field_pN,dir,enabled}` payload (harmonizes both cards to keep V/m
  live). Final: 14/14 oracle, 2316 frontend, smoke 23/23.
- **Comparable prediction / capability gained, not just a run:** the E-field job payload every engine POSTs is now
  emitted by ONE factory with machine-proven byte-parity per engine — the field spec that drives CanDo's q·E load,
  NAMD's eField, oxDNA's per-nt string force, and LAMMPS's CG force is provably identical across the consolidation,
  so U3/U4 can collapse the panels with zero observable change to what each engine simulates.

### 2026-07-08 — `P2` chain EXECUTOR (advance / halt / resume-from-failed) — job-planner track

- **CHAIN capability PROVEN, not just wired:** `backend/core/md_chain_executor.py` turns a P1 `MdPipeline` into a
  live, self-advancing chain. The bright line — *stage N runs SEEDED FROM stage N-1's output; on failure the
  chain HALTS and RESUMES from the failed stage (retry-only-failed)* — is proven headless by the FAST CHAIN
  oracle (`tests/test_md_chain_executor.py`, 12 tests, fully mocked spawn/status). `test_advances_seeded_from_
  predecessor` asserts stage 1's parent is stage 0's REALISED job id (not the root) with a literal RED guard;
  `test_resume_reruns_only_the_failed_stage` asserts the completed stage keeps its job id + `done` status and is
  never handed to the spawner twice.
- **Engine-agnostic state machine, injected callbacks:** the only engine touch-points are `spawn(ctx)->job_id`
  and `job_status(job_id)->running|completed|failed`. Primitives `reconcile_running` / `next_spawn` /
  `mark_spawned` let the async driver `await` a real spawn between two pure transitions; `step_chain` composes
  them sync for the oracle. `resume_chain` resets from `failed_stage_index()` down to pending. Persistence
  (`save/load/list_chains` → `workspace/md_chains/{id}/chain.json`) round-trips the plan + stage states.
- **Real NAMD wiring lives in the API layer** (keeps `backend/core` free of `backend/api`): `routes_md`
  `_chain_job_status` maps `MdStatus`, `_chain_spawn` REUSES `spawn_md_production` VERBATIM (it already seeds a
  production child from ANY completed job — relaxation OR production — which IS the chain hop; run target/length
  flow from the stage; local autostarts, alpine queues). `advance_chains(workspace)` drives every persisted chain
  one transition and is called from the MD supervisor loop (`main.py`) → a chain marches stage-to-stage
  UNATTENDED. Routes: `POST /md/chains` (build+persist+kick stage 0), `GET /md/chains[/{id}]`,
  `POST /md/chains/{id}/resume`. Headless route oracle `tests/test_md_milestone1.py::TestMdChain` (4): create →
  real stage-0 production child (start stubbed); create refuses a non-completed root; halt-on-failure → resume
  spawns a NEW stage-0 child while stage 1 stays pending; resume rejects a non-failed chain.
- **Forces carry into the child conf via the SHARED emitter:** `stage_forces_conf(forces)` reuses
  `md_protocols.external_forces_block` (the `fixedAtoms`+`eField` block every launch card writes); the oracle
  asserts a field stage → `eField` line, an anchor stage → `fixedAtomsFile` line, byte-identical to the emitter.
  **KNOWN P2 FOLLOW-UP (documented, not a gap in scope):** threading those forces all the way into the
  production *reseed* conf needs `ProductionRunRequest.field`/`anchors` + reseed-conf emission — the shared-emitter
  proof is at the conf-snippet level, not yet injected end-to-end. P3 (cross-engine seed) + P4 (planner UI) build
  on this.
- **Fresh-context review — core CLEAN, 3 edge findings acted on:** it CONFIRMED no double-spawn/skip/re-run-
  completed/fail-to-halt bug, correct persistence round-trip, correct `failed_stage_index`+resume-reset, no
  off-by-one, no event-loop concurrency double-spawn. (1 MED/HIGH) the broad-except spawn failure was a PERMANENT
  halt → HARDENED `advance_chains` with a bounded retry (`StageState.spawn_attempts`, `_MAX_STAGE_SPAWN_ATTEMPTS=3`,
  mirrors `namd_runner`'s `MAX_*_RESUMES`): a transient precondition (prev stage's remote outputs not yet
  downloaded) leaves the stage pending + retries next tick, halting only past the cap; `resume_chain` resets the
  budget (`test_transient_spawn_failure_retries_then_halts`). The ALPINE root cause it flagged — `md_executor.
  fetch_outputs` marks a remote job `completed` even when its output download failed → **filed ISSUE-15** (pre-
  existing `md_executor` bug, out of P2 scope). (2 LOW) `_chain_spawn` discards the plan's per-stage seed (all
  stages get 54321; harmless — different coords) → documented follow-up. (3 latent) added the all-or-nothing
  spawn-invariant comment.
- **SLOW real 2-stage local chain NOT run** (needs live NAMD; a sim may be running → owes an **MV row**, precedent
  = `md_cutoff`/N1). Three-Layer clean (no Design/topology touch; forces are job-request annotations). Gates:
  oracle 12/12 + route 5/5; `just test` **4410 passed** / 110 skip / 1 xfail (was 4393; +17 = new tests, no drop,
  xdist flake didn't fire); ruff clean on all touched. `main.js` LOC-Δ = 0 (backend-only, no frontend).
- **Capability/de-dup proven, not just wired:** the CHAIN capability — stage N seeded from N-1's output, halt +
  resume-from-failed-stage — is proven by the RED-verified FAST oracle + the real-child route oracle, not "a
  Plan Run button exists".

## Lessons (anti-patterns banked)

### Banked from O1

- **"Matches oxdna_health" is ambiguous — pin the estimator, not the graph.** The card's descriptor and the
  Graphs-&-Metrics card both derive from `measure_bundle_twist`, but the metrics card reports the DIFFERENTIAL
  (measured − analytic) over the production mean while the shared descriptor reports the ABSOLUTE value on the
  relaxed frame. Same function, different reference + frame → different number. When a task says "match existing
  values within tol", decide WHICH value: the raw estimator output (what cross-engine comparison wants) or the
  differential the existing UI displays. The oracle should assert self-consistency with the estimator on the
  chosen frame — asserting equality to the differential graph would be wrong-by-construction.

### Banked from S3

- **Direction-keyed matching silently drops the primary cross-engine pairing.** Engines disagree on strand
  convention: CanDo NMA RMSF is a direction-less axis-node value (1/bp); `rmsf_from_ensemble` (oxDNA/NAMD/mrDNA)
  is per-strand (2/bp). Keying a cross-engine match on `direction` leaves an empty intersection → a *silent*
  `None`, which reads as "no data" not "misconfigured key". When reconciling per-nucleotide profiles ACROSS
  engines, collapse to the coarsest shared unit (per base pair) first. `normalize_rmsf_profile` already knew
  this (emits both strands for a dir-less entry); the new code initially didn't. **A green oracle that hand-
  matches `direction` on both sides is green-by-construction** — pin the *mixed*-convention case explicitly.

### Banked from C2

- **Field-response must be measured on the RAW solve frame, not the display frame.** `predict_shape` Kabsch-
  reposes each output frame onto the displayed design geometry with a *per-frame* rigid transform (for overlay).
  Comparing a field-off and a field-on `predict_shape` output therefore compares two *differently-posed* frames,
  and an anchored region that is genuinely clamped at rest appears to "drift" several nm. `field_response_profile`
  is deliberately NOT Kabsch-aligned (the anchored region IS the common frame) — so it must be fed the RAW
  clamped-solve node positions, where the anchor sits at identical positions in both frames. **Any engine's field-
  source builder (C5/M2/N4) must emit its deflection descriptor from the pre-display / pre-alignment frame.** A
  green oracle built on the display frame would either falsely fail or silently mis-measure the anchor hold.
- **A corotational eigenstrain+field solve is only conditionally stable.** Large body loads invert elements
  (`L→0`/huge → `L**3` overflow) before the physics is wrong. Pick load magnitudes in the converged, stable band
  and assert *properties* (monotone, along-field, held) rather than absolute deflection matching a calibration —
  the absolute V/m→force calibration is a separate, deferred concern (editable effective-charge, per the plan).

### Banked from N1

- **Predict the response from the ENGINE'S OWN quantities, not from the code under test.** The obvious
  real-engine field oracle — "compute the expected deflection from the `eField` vector we emitted, assert NAMD
  reproduces it" — is green-by-construction for the unit conversion: a wrong `KCAL_MOL_A_IN_PN` scales BOTH the
  emitted `eField` (hence NAMD's real force) and the prediction, so they still agree. The fix is to state the
  prediction in the SHARED DESCRIPTOR's own units (`field_pN`) and multiply by a charge read from NAMD's OWN PSF
  (`abs(q_free)` phosphates) with an SI-only accel constant — nothing on the assertion side touches the
  production constant. RED-checked: doubling `KCAL_MOL_A_IN_PN` then makes REAL NAMD falsify it. Generalize:
  a cross-engine oracle that feeds the engine a value and predicts the result from that SAME value only tests
  plumbing; predict from an INDEPENDENT measurement of the engine's state.
- **A "force per nucleotide" is not uniform at strand ends — measure the force field, don't assume it.** Writing
  the oracle first caught my own error: I assumed every DNA residue is −1 e. The real psfgen PSF shows 5TER/3TER
  hydroxyl termini at −0.47/−0.53 e (they sum to one phosphate), so an N-mer feels −(N−1) e — NAMD is right,
  oxDNA's uniform per-bead `field_pN` is the approximation. The deficit is ~2% on a real origami. Do NOT "fix" it
  by rescaling `eField` to match oxDNA's total — that corrupts the internal per-nt load, which is the quantity
  the engines actually share. Bank: when a descriptor claims "per X uniform", verify it against the force field
  at the boundaries before pinning a total.

### Banked from M2

- **ARBD constant force = a ramp POTENTIAL grid, NOT `forceXGrid`.** The obvious "tabulated force" path
  (`ParticleType.forceXGrid`/`forceYGrid`/`forceZGrid` + a constant `.dx`) **crashes real ARBD** (CUDA illegal
  memory access) regardless of force magnitude — confirmed by A/B (field-off ran clean, field-on with the grid
  crashed at any strength). The mrDNA-blessed idiom is `arbdmodel.grid.constant_force` → a linear ramp potential
  `U=-(F·r)` applied via `add_grid_potential`/`gridFile`, whose negative gradient is the uniform force. Bank:
  reach for the engine's OWN helper (`constant_force`) before hand-rolling a grid; probe A/B (feature-off vs on)
  isolates a format crash from a physics blow-up.
- **A CG bead's field force scales with its nucleotide content, recovered from its MASS.** The shared descriptor
  is force per NUCLEOTIDE; a coarse bead holds several bp. mrDNA CG beads carry **charge 0** (no q·E to lean on),
  but their mass is ∝ nt count (measured: 1380 Da/full 5-bp bead, 690/half), so `nt in bead = mass/dpn` with
  `dpn = total_bead_mass/total_nt`. Scaling the per-type force by mass makes the TOTAL applied force `field_pN ×
  total_nt` exactly — the same total the per-nt engines apply — with NO per-bead approximation (one type = one
  mass = exact). Generalizes to any CG engine whose beads coarse-grain multiple nucleotides.
- **A damped CG (Langevin/Brownian) field oracle predicts OVERDAMPED drift, not ballistic ½at².** Past its
  ~1-timestep velocity relaxation the bead is overdamped, so a constant force gives terminal drift `Δx =
  D·F·T/(k_B·T)` from the engine's OWN per-type diffusivity `D` (Å²/ns) — not NAMD's short-time `½(F/M)t²`. On a
  small tethered structure the field drift competes with a stochastic ±2 Å relaxation wander of the loosely-held
  free bulk, so pick field/steps where the field drift is several × the wander (but gentle enough that
  anchor-adjacent bonds don't rip → ARBD instability) and assert a field-on-vs-off DIFFERENTIAL. **Independence
  (the N1 trap, re-hit here):** predicting the drift from the code's own `field_force_vector` cancels the
  emission constant in the ratio (green-by-construction) — predict the force from `field_pN × first-principles
  pN→kcal/mol/Å` instead, so a corrupted emission constant falsifies; keep the exact-constant check in the FAST
  oracle.

## Difficulties ledger (genuinely-stuck items + why)

_(none yet — if a task is set `status="blocked"`, record the reason + what was tried here.)_
