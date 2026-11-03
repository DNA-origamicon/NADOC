---
name: project_skip_twist_curvature_sweep
description: "exp31 — 3x6x400 SQ skip-count sweep vs global twist + new integrated-curvature metric, across 3 placement strategies"
metadata: 
  node_type: memory
  type: project
  originSessionId: dbfe337c-0487-4baa-aff7-14ee31e09249
---

# exp31 — skip count vs twist & curvature sweep (3×6×400 SQ)

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

Launched 2026-06-27. Maps the total-skips → total-twist response curve around the analytical
baseline (period 48) for a fresh 3×6×400 seamless square bundle, plus a NEW curvature guard, to
understand why autorefine can't optimize past the analytical skip spacing and whether placement
strategy matters. See `experiments/exp31_skip_twist_curvature_sweep/` (hypothesis.md, run.py,
plot.py, README.md, conclusion.md-pending). Extends [[project_skip_twist_selfconsistency]] +
[[project_regional_autorefine]].

<a id="design"></a>
- [Design](details/project_skip_twist_curvature_sweep/01-design.md#design)

<a id="new-code-all-pure-tested-full-suite-green-3373p"></a>
- [New code (all pure-tested, full suite green 3373p)](details/project_skip_twist_curvature_sweep/01-design.md#new-code-all-pure-tested-full-suite-green-3373p)

<a id="orchestration"></a>
- [Orchestration](details/project_skip_twist_curvature_sweep/01-design.md#orchestration)

<a id="oxdna-benchmark-cuda-proxy-bug--root-caused--fixed-2026-06-27"></a>
- [oxDNA benchmark CUDA-proxy bug — ROOT-CAUSED + FIXED 2026-06-27](details/project_skip_twist_curvature_sweep/01-design.md#oxdna-benchmark-cuda-proxy-bug--root-caused--fixed-2026-06-27)

<a id="launch-command-running"></a>
- [Launch command (running)](details/project_skip_twist_curvature_sweep/01-design.md#launch-command-running)

<a id="expectations-under-test-from-prior-square-lattice-findings"></a>
- [Expectations under test (from prior square-lattice findings)](details/project_skip_twist_curvature_sweep/01-design.md#expectations-under-test-from-prior-square-lattice-findings)

<a id="disk--archiving-added-2026-06-27--ran-out-of-disk-mid-series"></a>
- [Disk / archiving (added 2026-06-27 — ran out of disk mid-series)](details/project_skip_twist_curvature_sweep/01-design.md#disk--archiving-added-2026-06-27--ran-out-of-disk-mid-series)

<a id="key-finding--twist-is-spatially-non-uniform--local-refinement-warranted-2026-06-27"></a>
- [KEY FINDING — twist is spatially non-uniform → local refinement warranted (2026-06-27)](details/project_skip_twist_curvature_sweep/01-design.md#key-finding--twist-is-spatially-non-uniform--local-refinement-warranted-2026-06-27)

## CROSS-ENGINE CHECK — mrdna does NOT reproduce the SQ global twist (2026-06-28)

User asked whether mrdna could drive the skip-twist loop more cheaply than oxDNA. Built
`experiments/exp31_skip_twist_curvature_sweep/mrdna_compare.py`: rebuilds the EXACT oxDNA
skip designs from `results.json` (`skips:{helix:[bp]}` → `build_explicit_skip_from_design`),
relaxes with mrdna, scores with the SAME `core_reference_geometry`/`_filter_to_reference_core`/
`measure_bundle_twist`/`compute_twist_profile` — only the engine differs.

**Result (period-48 baseline, 150 skips, 14686 nt):**
| coarse steps | mrdna twist_diff | mrdna curv | oxDNA |
|---|---|---|---|
| 2e6 | −0.12° | 1.58 | **+51.4° twist / 1.72 curv** |
| 1.2e7 | −1.19° | 1.47 | (8M prod) |

mrdna's global twist stays **≈0° even at 12M coarse steps** (mrdna default is 5e7) while oxDNA
is +51°. Twist PROFILE: oxDNA ramps to +57.7° (flat-front/back-loaded); mrdna flat at +0.19°
(`results/mrdna/twist_profile_compare.png`). CRUCIALLY mrdna **curvature is comparable** (1.47–1.58
vs 1.72) — it captures bending/global shape, the gap is **specifically the twist DOF**.

**NO-SKIP CONTROL (clinching — user-requested, /tmp/mrdna_noskip.py).** A ~0° reading on the
*skipped* design alone is AMBIGUOUS: it could mean (a) mrdna is twist-blind, or (b) mrdna captures
twist and says the analytical skips fully nullify it (disagreeing with oxDNA's +51° residual). The
discriminator is the BARE bundle (0 skips), which MUST be strongly over-wound if mrdna sees SQ twist
at all. Result: bare bundle mrdna twist = **+0.8° @12M** (−0.41 @2M) — statistically identical to the
skipped design's −1.2°, curv 1.49–1.57. Removing every skip changed mrdna's global twist by ~0°.
→ **Interpretation (a): mrdna is genuinely twist-blind here; it is NOT validating the analytical
placement.** Mechanism:
mrdna's default bead model is generated "without twist" (coarse), and even with `coarse_local_twist=
True` the soft crossover torsional stiffness (~0.05 kJ/mol/Å², see [[project_crossover_parameterization]])
lets skip strain relax locally instead of accumulating into a global supertwist — a concrete instance
of the literature's "mrdna neglects twist-stretch/twist-bend coupling" caveat.

**CONCLUSION: mrdna CANNOT stand in for oxDNA as the twist-nulling signal in the skip-twist loop**,
despite being far cheaper. It IS still viable for the curvature/shape part. oxDNA stays the twist oracle.

### mrdna-run GOTCHAS (cost real debugging — keep)
1. **`model.simulate(coarse_steps=…, fine_steps=…)` SILENTLY SWALLOWS those kwargs** — it's a
   single-stage `ArbdModel` method that runs default steps (~7s no-op → spurious ~0 twist regardless
   of step count). Use `mrdna.simulate.multiresolution_simulation(model, name, coarse_steps=,
   fine_steps=, coarse_output_period=, fine_output_period=, coarse_local_twist=)` for a real
   coarse→fine relaxation. (`scripts/benchmark_mrdna_roundtrip.py` + the round-trip tests use
   model.simulate deliberately — they only need *a* relaxation, not a specific depth.)
2. **multiresolution writes 4 stages**: `-0` coarse (5bp/bead), `-1`/`-2` fine (1 bead/bp+O bead),
   `-3` ATOMISTIC (~30× atoms, NO DCD). `_find_fine` must pick the largest stage **that has a matching
   DCD** (atomistic has none) → else psf↔dcd atom-count mismatch on read-back. Prefer the LAST fine
   stage (`-2`) on the NATOM tie.
3. Throughput on this 3080 Ti, 14686 nt: coarse ~15k steps/s, fine ~2.8k steps/s, +~73s fixed
   overhead/run (model-gen + atomistic backmap + I/O). 1.2e7 coarse ≈ 16 min/run.

<a id="nick-artifact-test--refuted-the-51-is-not-a-nick-artifact-2026-06-28"></a>
- [NICK-ARTIFACT TEST — REFUTED: the +51° is NOT a nick artifact (2026-06-28)](details/project_skip_twist_curvature_sweep/02-nick-artifact-test--refuted-the-51-is-not-a-nick-artifact-2026-06.md#nick-artifact-test--refuted-the-51-is-not-a-nick-artifact-2026-06-28)

## exp31 STATUS: paused at 17/25 (2026-06-28)
Driver exited cleanly after deviation Δ=-2 (00:46); no watchdog running, GPU freed for the mrdna
comparison. Remaining points (deviation Δ=-3,-4; uniform/incremental Δ=+2 etc.) NOT run. results.json
has the 17 done. To resume: relaunch run.py (resume-safe, reloads from results.json).

<a id="exp32-result--profile-guided-mimo-secant-diverged-2026-06-28"></a>
- [exp32 RESULT — profile-guided MIMO secant DIVERGED (2026-06-28)](details/project_skip_twist_curvature_sweep/03-exp32-result--profile-guided-mimo-secant-diverged-2026-06-28.md#exp32-result--profile-guided-mimo-secant-diverged-2026-06-28)

<a id="decisive-re-read-of-exp31-data--placement-is-the-whole-lever-2026-06-28"></a>
- [DECISIVE re-read of exp31 data — PLACEMENT is the whole lever (2026-06-28)](details/project_skip_twist_curvature_sweep/03-exp32-result--profile-guided-mimo-secant-diverged-2026-06-28.md#decisive-re-read-of-exp31-data--placement-is-the-whole-lever-2026-06-28)

<a id="exp34-result--the-noise-was-an-equilibration-artifact-net-zero-is-d4222-skips-2026-06-29"></a>
- [exp34 RESULT — the noise was an EQUILIBRATION artifact; net-zero is d+4=222 skips (2026-06-29)](details/project_skip_twist_curvature_sweep/03-exp32-result--profile-guided-mimo-secant-diverged-2026-06-28.md#exp34-result--the-noise-was-an-equilibration-artifact-net-zero-is-d4222-skips-2026-06-29)

<a id="exp35-result--the-10m-equil-fix-is-necessary-but-not-sufficient-d4-does-not-equilibrate-to-0-on-a-cold-build-2026-06-30"></a>
- [exp35 RESULT — the 10M-equil fix is necessary but NOT sufficient; d+4 does NOT equilibrate to 0 on a cold build (2026-06-30)](details/project_skip_twist_curvature_sweep/03-exp32-result--profile-guided-mimo-secant-diverged-2026-06-28.md#exp35-result--the-10m-equil-fix-is-necessary-but-not-sufficient-d4-does-not-equilibrate-to-0-on-a-cold-build-2026-06-30)

<a id="historical-exp34--set-up-not-yet-launched-2026-06-28"></a>
- [(historical) exp34 — set up, NOT yet launched (2026-06-28)](details/project_skip_twist_curvature_sweep/03-exp32-result--profile-guided-mimo-secant-diverged-2026-06-28.md#historical-exp34--set-up-not-yet-launched-2026-06-28)
