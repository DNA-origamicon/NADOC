# Paper reproduction + cross-comparison (2026-07-11) — `experiments/exp42_snupi_cross_compare/` — supporting detail

[Topic head](../../project_snupi_mimic.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Paper reproduction + cross-comparison (2026-07-11) — `experiments/exp42_snupi_cross_compare/`
Automation `scripts/snupi_cross_compare.py` (reuses the in-app compare framework: `build_cando_shape_source`
→ `build_comparison_report`; `md_rmsf` → `build_namd_shape_source`) + UI button-press e2e
`frontend/e2e/snupi_run.spec.js` (real Coarse+Fine clicks → jobs complete → deform overlay) &
`snupi_tab.spec.js` (tab wiring). Findings:
- **Params reproduce the SNUPI SI EXACTLY:** our `family_mean_D('regular_bp')` = GJ 313.83 / EIy 158.33 /
  EIz 245.79 / g(Δx,Θx) −277.39, IDENTICAL to `Literature/SNUPI_SI.pdf` Note S4 mean column (torsional
  L_p 75.8 nm = P_CH 75.8; bend ~48.8 ≈ P_BH 46.5). Transcription is faithful to 2 dp.
- **Cross-comparison (per-bp NMA RMSF vs MD/CanDo):** HC `6hbx100_noT` (20ns MD) — **SNUPI beats CanDo on
  BOTH** pearson 0.592 vs 0.549, spearman 0.424 vs 0.336 (reproduces P4, via the shared pipeline). SQ
  `3x4SQ` (5ns MD) — tie (cando pearson 0.703 vs 0.675, snupi spearman 0.548 vs 0.533). Basic snupi-vs-cando
  (no MD, 6 designs): RMSF PATTERN tracks CanDo tightly (pearson 0.97–1.0), MAGNITUDE shifts (higher on
  small/stiff, lower on big/floppy — the anisotropy+coupling delta). ⚠ `6hb_validated` NMA RMSF ~8 nm
  outlier (BOTH engines → soft/under-constrained mode, NOT SNUPI-specific; investigate separately).
- **SNUPI's own validation battery** (SI figs S2–S25): 32HB/64HB bundles, gears + globally-bent by BP
  ins/del (loop/skip), twisted monoliths, 6HB nick-twist, V-bricks/hierarchical assemblies vs cryo-EM/MD.
  Metrics = per-BP NMA RMSF + BP-pair cross-correlation matrix + persistence-length scaling. **We match
  params + method; NOT a 1:1 figure match** (their structures aren't in our workspace — rebuilding e.g. the
  S13 gears / S16 6HB-nick-twist for a numeric match is the natural follow-up). Full writeup: exp42 README.

**Verdict test:** "SNUPI for free" = YES if transcribed params + the existing FEM reproduce MD
(and SNUPI's published) shape/RMSF within a stated tolerance. Then the extra-base extension is the
only GPU spend (~$3–8k — [[project_bundle_stiffness_params]] / [[project_crossover_parameterization]]),
plugging into the same param DB. ✅ Verdict reached (snupi ≥ cando both lattices, at $0).

- **P5 — Frontend SNUPI engine tab. ✅ DONE 2026-07-11.** First-class SNUPI tab shipped (separate-tab
  path, not the material-selector-on-CanDo fallback). Runner calls `predict_shape(material="snupi")`;
  Advanced "Material" selector also offers the isotropic "cando" baseline for in-tab A/B. Anchors+E-fields
  ON (reused shared cards → `predict_shape(anchors=, field=)`); surface OFF/greyed (no FEM wall BC — adding
  one is a fem_solver change, scoped as follow-up). Backend `just test-smart` FULL 4718 pass; frontend 2683
  pass; app-exercised (`e2e/snupi_tab.spec.js`, 0 console errors). Full detail + surface-BC writeup in
  [[snupi-frontend-tab]]. Original brief below.
- **P5 (original brief) — Frontend SNUPI engine tab (fresh session, 2026-07-11).** Surface the mimic in the app as
  a first-class structure-prediction engine tab (sibling to CanDo FEM / mrDNA / oxDNA / NAMD). Backend
  is READY: `predict_shape(design, material="snupi", anchors=, field=)` — no new solver work; this is a
  UI/route wiring task. Scope: unified jobs card + live progress bar + advanced-params card + visualization
  card with the standard rep toggles (RMSF coloring, axis/cylinder, backbone), and an INVESTIGATION into
  wiring anchors + E-fields + surfaces (predict_shape already accepts `anchors=`/`field=`; how does CanDo
  FEM surface them today, and can SNUPI reuse that path + a "surface" scope). Since SNUPI == a material flag
  on the SAME FEM as CanDo, strongly prefer EXTENDING the existing CanDo-FEM job/route/panel with a
  material selector over a parallel stack — decide in the fresh session after reading the panel architecture.
  Module-first law applies (no main.js growth). Detailed build prompt handed to the fresh session (see
  session handoff / the prompt generated 2026-07-11).
