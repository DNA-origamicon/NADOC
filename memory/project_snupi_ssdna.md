---
name: project_snupi_ssdna
description: "Phased plan — give SNUPI jobs a real ssDNA treatment: bridging ssDNA (SNUPI-exact beam, closes gap G9) + FREE ssDNA tails (overhangs & dangling scaffold ends — a NADOC extension SNUPI structurally cannot represent). Target: VoltronCore with hydrodynamics, MD-quality trajectories/figures."
metadata:
  node_type: memory
  type: project
---

# SNUPI ssDNA — bridging elements + free tails (overhangs & scaffold ends)

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

## HANDOFF — read this block first

| Phase | Scope | Status |
|---|---|---|
| **SS-0** | Mesh representation: `FEMNode.kind`, ssDNA run classifier, design ssDNA audit script | ✅ 2026-07-13 |
| **SS-1** | SNUPI bridging ssDNA element (gap **G9**): interior gaps + cross-helix hops | ✅ 2026-07-13 |
| **SS-2** | Free ssDNA tails in the **dynamics** engine (overhangs + scaffold ends) | ✅ 2026-07-13 |
| **SS-3** | Hydrodynamic drag on tails (coarse-blob partition over ss nodes) | ✅ 2026-07-13 |
| **SS-4** | Display: overhang/scaffold-end beads follow their simulated ss chain | ✅ 2026-07-13; **app exercise 2026-07-14 found the OH15 anchor-polarity bug — fixed, needs a re-look in the app** |
| **SS-5** | VoltronCore validation + figures; topic-file reconciliation | ☐ not started |

Each phase is one session. Do them in order — SS-2 depends on SS-0's node class, SS-3 on SS-2's nodes,
SS-4 on SS-3's positions. SS-1 is independent of SS-0 and could be done first or in parallel.

**When you finish a phase:** flip its row to ✅ with the date, add a sub-section below with what shipped +
the measured numbers, and update the "Current state" bullets. Do not rewrite this header's structure.

<a id="-ss-0-done-2026-07-13"></a>
- [✅ SS-0 DONE (2026-07-13)](details/project_snupi_ssdna/01-ss-0-done-2026-07-13.md#-ss-0-done-2026-07-13)

<a id="-ss-1-done-2026-07-13--gap-g9-closed"></a>
- [✅ SS-1 DONE (2026-07-13) — gap G9 closed](details/project_snupi_ssdna/01-ss-0-done-2026-07-13.md#-ss-1-done-2026-07-13--gap-g9-closed)

- [✅ SS-1 DONE (2026-07-13) — gap G9 closed — continued detail](details/project_snupi_ssdna/01-ss-0-done-2026-07-13.md)

<a id="-ss-2-done-2026-07-13--free-tails-are-explicit-langevin-chains"></a>
- [✅ SS-2 DONE (2026-07-13) — free tails are explicit Langevin chains](details/project_snupi_ssdna/01-ss-0-done-2026-07-13.md#-ss-2-done-2026-07-13--free-tails-are-explicit-langevin-chains)

<a id="the-three-things-that-were-not-obvious-read-before-touching-tail-physics"></a>
- [The three things that were NOT obvious (read before touching tail physics)](details/project_snupi_ssdna/01-ss-0-done-2026-07-13.md#the-three-things-that-were-not-obvious-read-before-touching-tail-physics)

<a id="gate--the-wlc-oracle-met"></a>
- [Gate — the WLC oracle, met](details/project_snupi_ssdna/02-gate--the-wlc-oracle-met.md#gate--the-wlc-oracle-met)

<a id="measured-and-both-were-open-questions-in-the-plan"></a>
- [Measured, and both were open questions in the plan](details/project_snupi_ssdna/02-gate--the-wlc-oracle-met.md#measured-and-both-were-open-questions-in-the-plan)

<a id="current-state-after-ss-2"></a>
- [Current state (after SS-2)](details/project_snupi_ssdna/02-gate--the-wlc-oracle-met.md#current-state-after-ss-2)

<a id="-ss-3-done-2026-07-13--tails-feel-the-solvent"></a>
- [✅ SS-3 DONE (2026-07-13) — tails feel the solvent](details/project_snupi_ssdna/02-gate--the-wlc-oracle-met.md#-ss-3-done-2026-07-13--tails-feel-the-solvent)

<a id="the-design-decision-and-why-it-needs-no-new-rpy-math"></a>
- [The design decision, and why it needs no new RPY math](details/project_snupi_ssdna/02-gate--the-wlc-oracle-met.md#the-design-decision-and-why-it-needs-no-new-rpy-math)

<a id="the-thing-ss-3-actually-found-the-tails-were-frozen-rods"></a>
- [The thing SS-3 actually found: the tails were frozen rods](details/project_snupi_ssdna/02-gate--the-wlc-oracle-met.md#the-thing-ss-3-actually-found-the-tails-were-frozen-rods)

<a id="shipped"></a>
- [Shipped](details/project_snupi_ssdna/02-gate--the-wlc-oracle-met.md#shipped)

<a id="gate--voltroncore-7088-core--571-tail-beads"></a>
- [Gate — VoltronCore (7088 core + 571 tail beads)](details/project_snupi_ssdna/02-gate--the-wlc-oracle-met.md#gate--voltroncore-7088-core--571-tail-beads)

### Still open

- **⟨R_ee²⟩ is not converged and cannot be** from a trajectory (SS-2 finding 3). The tails now *start*
  at the WLC value and stay in its neighbourhood (16-mers 17.3 vs 13.7; 28-mers 50.0 vs 24.6 on 2
  samples), which is the correct claim to make. Per-tail statistics for SS-5 need the pivot sampler,
  not the trajectory.
- **No excluded volume.** A tail can pass through the duplex it hangs off. Pre-existing (SS-2), and it
  matters more now that tails are compact coils sitting close to the core.
- The coarse hydro's dense 6B×6B matvecs dominate the step cost (~70 ms/step at VoltronCore scale) — a
  60k-step production run is ~70 min. An SS-5 perf item, not an SS-3 regression.

<a id="-ss-4-done-2026-07-13--the-tails-reach-the-screen--live-app-exercise-still-owed"></a>
- [✅ SS-4 DONE (2026-07-13) — the tails reach the screen (⚠ live-app exercise still owed)](details/project_snupi_ssdna/03-ss-4-done-2026-07-13--the-tails-reach-the-screen--live-app-exerc.md#-ss-4-done-2026-07-13--the-tails-reach-the-screen--live-app-exercise-still-owed)

<a id="shipped-1"></a>
- [Shipped](details/project_snupi_ssdna/03-ss-4-done-2026-07-13--the-tails-reach-the-screen--live-app-exerc.md#shipped-1)

<a id="-the-mean-of-a-coil-is-not-a-coil"></a>
- [⚠ The mean of a coil is not a coil](details/project_snupi_ssdna/03-ss-4-done-2026-07-13--the-tails-reach-the-screen--live-app-exerc.md#-the-mean-of-a-coil-is-not-a-coil)

<a id="separate-bug-found-and-fixed-47-of-every-frame-was-beads-that-are-never-drawn"></a>
- [Separate bug found and fixed: 47% of every frame was beads that are never drawn](details/project_snupi_ssdna/03-ss-4-done-2026-07-13--the-tails-reach-the-screen--live-app-exerc.md#separate-bug-found-and-fixed-47-of-every-frame-was-beads-that-are-never-drawn)

<a id="gate--voltroncore-3000-step-dynamicstails-run-60-s"></a>
- [Gate — VoltronCore (3000-step dynamics+tails run, 60 s)](details/project_snupi_ssdna/03-ss-4-done-2026-07-13--the-tails-reach-the-screen--live-app-exerc.md#gate--voltroncore-3000-step-dynamicstails-run-60-s)

<a id="-the-oh15-bug-found-by-the-user-in-the-app-2026-07-14--the-anchor-is-not-always-the-5-end"></a>
- [🐞 The OH15 bug (found by the user in the app, 2026-07-14) — the anchor is NOT always the 5' end](details/project_snupi_ssdna/03-ss-4-done-2026-07-13--the-tails-reach-the-screen--live-app-exerc.md#-the-oh15-bug-found-by-the-user-in-the-app-2026-07-14--the-anchor-is-not-always-the-5-end)

### Known, and left alone deliberately

- **The duplex core's displayed jitter is ~2.5× its physical node motion** (raw node fluctuation
  0.107 nm → displayed bead 0.257 nm). The winding rebuilds each helix's cross-section frame from the
  DEFORMED nodes, and adjacent nodes are only 0.34 nm apart, so 0.1 nm of thermal node noise tilts the
  local tangent by ~17° and a bead 1 nm out from the axis swings with it. **Pre-existing** (every SNUPI/
  CanDo trajectory has it, not just tails), and it means the animation shows the core boiling somewhat
  more than the physics says — which also flattens the visual contrast with the tails. Fixing it means
  winding on a smoothed/reference axis and adding the node displacement as a translation. **An SS-5
  item**; do not fold it into a tails change.
- Each trajectory frame is Kabsch-fitted onto the rendered design independently, so a ~1° fit
  difference rocks a 100 nm structure by a couple of nm globally. Also pre-existing player behaviour.

---

<a id="why-this-exists"></a>
- [Why this exists](details/project_snupi_ssdna/04-why-this-exists.md#why-this-exists)

<a id="what-the-snupi-literature-actually-does-settled--do-not-re-research-this"></a>
- [What the SNUPI literature actually does (settled — do not re-research this)](details/project_snupi_ssdna/04-why-this-exists.md#what-the-snupi-literature-actually-does-settled--do-not-re-research-this)

<a id="snupi-ssdna-constants--the-laws-inputs-not-the-element-source-snupidefaultsnp88-153"></a>
- [SNUPI ssDNA constants — the LAWS' INPUTS, not the element (source `~/SNUPI/Default.snp:88-153`)](details/project_snupi_ssdna/04-why-this-exists.md#snupi-ssdna-constants--the-laws-inputs-not-the-element-source-snupidefaultsnp88-153)

<a id="the-three-cases-the-whole-plan-in-one-table"></a>
- [The three cases (the whole plan in one table)](details/project_snupi_ssdna/04-why-this-exists.md#the-three-cases-the-whole-plan-in-one-table)

## Architectural decisions (agreed — do not relitigate mid-phase)

1. **Free tails live in the DYNAMICS engine only. They never enter the static K or the NMA.**
   This is the load-bearing decision. A floppy tail has near-zero eigenvalues; if its DOF enter the
   NMA operator, the 200 lowest modes become *all tail modes* and the validated duplex-core RMSF
   (exp42: snupi→MD pearson 0.62 HC / 0.76 SQ, DCCM 0.491 > cando 0.454) is destroyed. It would also
   near-singularize the static shape solve. Keeping tails out of K means **every validated static number
   stays byte-identical**, and Langevin — which samples them naturally and correctly — carries them.
   If you ever want tail RMSF as an observable, take it from the trajectory, not from the NMA.
2. **Bridging ssDNA is SNUPI-exact:** one collapsed beam between the two flanking bp nodes, rest length =
   WLC RMS end-to-end distance. It DOES enter K and the NMA (it is load-bearing), so SS-1 is an `[R]`
   change and must be re-measured against exp42.
3. **Free tails are a documented NADOC extension beyond published SNUPI.** Say so in the code docstrings,
   the UI, and any figure caption. We are not claiming SNUPI does this.
4. **Three-Layer Law:** ssDNA node positions are Physical-layer/display-only. They are derived from
   topology, never written back. `_PHASE_*` constants untouched throughout.
5. **Gating:** everything behind `material="snupi"`. The CanDo path stays byte-identical, as with G1–G12.
6. **Coarse hydro is mandatory at VoltronCore scale.** Exact RPY at 7088 nodes ≈ 75 GB → the preflight
   guard (`check_friction_memory`) refuses it. Tails must be blob-partitionable from the start (SS-3).

<a id="voltroncore-inventory-measured-by-the-ss-0-classifier-2026-07-13--the-sizing-target"></a>
- [VoltronCore inventory (measured by the SS-0 classifier 2026-07-13 — the sizing target)](details/project_snupi_ssdna/05-voltroncore-inventory-measured-by-the-ss-0-classifier-2026-07-13.md#voltroncore-inventory-measured-by-the-ss-0-classifier-2026-07-13--the-sizing-target)

<a id="-fixed-in-ss-1--separate-bug-found-by-the-ss-0-audit-rigid-beams-through-vacuum"></a>
- [✅ FIXED in SS-1 — separate bug found by the SS-0 audit: RIGID BEAMS THROUGH VACUUM](details/project_snupi_ssdna/05-voltroncore-inventory-measured-by-the-ss-0-classifier-2026-07-13.md#-fixed-in-ss-1--separate-bug-found-by-the-ss-0-audit-rigid-beams-through-vacuum)

<a id="ss-0--mesh-representation--ssdna-audit-no-behavior-change"></a>
- [SS-0 — mesh representation + ssDNA audit (no behavior change)](details/project_snupi_ssdna/05-voltroncore-inventory-measured-by-the-ss-0-classifier-2026-07-13.md#ss-0--mesh-representation--ssdna-audit-no-behavior-change)

<a id="ss-2--free-ssdna-tails-in-the-dynamics-engine"></a>
- [SS-2 — free ssDNA tails in the dynamics engine](details/project_snupi_ssdna/05-voltroncore-inventory-measured-by-the-ss-0-classifier-2026-07-13.md#ss-2--free-ssdna-tails-in-the-dynamics-engine)

<a id="ss-3--hydrodynamic-drag-on-the-tails"></a>
- [SS-3 — hydrodynamic drag on the tails](details/project_snupi_ssdna/05-voltroncore-inventory-measured-by-the-ss-0-classifier-2026-07-13.md#ss-3--hydrodynamic-drag-on-the-tails)

<a id="ss-4--display-tails-follow-their-simulated-chain"></a>
- [SS-4 — display: tails follow their simulated chain](details/project_snupi_ssdna/06-ss-4--display-tails-follow-their-simulated-chain.md#ss-4--display-tails-follow-their-simulated-chain)

<a id="ss-5--voltroncore-validation--figures"></a>
- [SS-5 — VoltronCore validation + figures](details/project_snupi_ssdna/06-ss-4--display-tails-follow-their-simulated-chain.md#ss-5--voltroncore-validation--figures)

<a id="kickoff-prompt-for-a-fresh-session-edit-the-phase-name"></a>
- [Kickoff prompt for a fresh session (edit the phase name)](details/project_snupi_ssdna/06-ss-4--display-tails-follow-their-simulated-chain.md#kickoff-prompt-for-a-fresh-session-edit-the-phase-name)

<a id="references"></a>
- [References](details/project_snupi_ssdna/06-ss-4--display-tails-follow-their-simulated-chain.md#references)
