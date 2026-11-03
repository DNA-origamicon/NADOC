# Curves+ CALIBRATION — verdict: use Curves+ as the per-frame engine (2026-07-19) — supporting detail

[Topic head](../../project_extra_base_4fs_geometric_fixb.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

### Curves+ CALIBRATION — verdict: use Curves+ as the per-frame engine (2026-07-19)
Installed **Curves+ 3.0.3 from bioconda** (`mamba create -n curves -c bioconda curves`, NO sudo, NO
registration — 3DNA needs a forum download; Curves+ = same Olson/Cambridge step-param convention, is
what Lankáš/Lavery/ABC use per-frame). Binary `~/miniforge3/envs/curves/bin/Cur+`, libs
`~/miniforge3/envs/curves/.curvesplus/standard`. Cur+ input gotchas (worked out): CHARMM prime atom
names → STAR names (C1'→C1*) required (no auto-convert); strand selection lines use SUBUNIT ORDER not
PDB resid (`1:12` / `24:13`); dir flags `2 1 -1 0 0` = 2 strands, +1/-1 = 5'-3'/3'-5'. Helpers:
`extract_duplex_fragment.py` (cut a 12-bp fragment PDB + matching step recipe), `kabsch_frame_test.py`.
DIFF (my base-normal extractor vs Curves+, 1xT 12-bp fragment frame 1128, over the 7 non-broken steps):
**tilt corr 0.85 slope 1.06 ✓, roll corr 0.82 slope 1.17 ✓** (bending convention CORRECT — the roll
"softness" was NOT convention, it was broken steps + frame noise inflating the TEMPORAL variance);
**slide corr −0.41 (SIGN FLIPPED — my ŷ=C1'-C1' opposes Curves+ base-frame y), twist corr −0.22
(UNRELIABLE — base-normal in-plane axis fails on distorted bases), 4/11 steps outright broke**
(twist 76° vs Curves+ 27°). ⇒ **My numpy extractor is NOT accurate enough per-step for quantitative
stiffness; Curves+ is.** PLAN: (1) duplex/regular_bp + nicked stiffness → run Curves+ PER FRAME on the
fetched trajectory (field-standard, clean). (2) Keep my numpy extractor ONLY for the on-pod LIVE checker
(relative convergence, no per-step precision needed) + the crossover TRANSLATIONAL (EA/shear, robust from
C1' centers). (3) Crossover ROTATIONAL: test Curves+ on a 2-bp pseudo-duplex of the two crossover bp
(its cross-helix step) — Curves+ can't do cross-helix natively but may handle a 2-bp fragment. Fragment
was distorted/mispaired (~4/12 WC — build_c1_pairs geometric pairing in a strained origami region);
pick a cleaner fragment next time.
SNUPI itself ran almost NO new MD (reused Bathe-2012 32hb trajectories + 3DNA values); the "100 ns"
is the atomistic-origami VALIDATION lineage (Yoo–Aksimentiev 140 ns, Pan–Bathe 150–500 ns) for GLOBAL
shape/RMSF/collective modes + the slow crossover interhelical angle θ (Pan–Bathe: NOT converged at
100 ns) — a different statistical object than local per-motif stiffness, which does converge fast.

### REFINED 2xT extra_base_co — all 1159 post-eq frames (2026-07-19)
Transfer to home is ~0.9 MB/s (22.85 GB ≈ 7 h — impractical), so `crossover_worker.py` (self-contained
numpy: dcd_fast + snupi_step_params + kabsch_frame_test + recipe npz) runs ON the pod over the volume-
local full 6 ns DCD (1535 frames), returns only the 6×6. `run_xover_on_pod.py` uploads+runs it on the
replica pod. **Result (1159 post-eq frames, frame 375→, vs the earlier thin 168): EA 965 GAy 700 GAz 378 pN
| GJ 27 EIy 27 EIz 13 pN·nm² (wired into snupi_params.json — replaced the 168-frame EA 1439/1032/593).**
KEY: the **ROTATIONAL was ALREADY converged** (GJ 27, EI 13-27 unchanged 168→1159 fr — its variance is
well-sampled: 330 xover × frames; the "slow rotational" worry was overstated). The **TRANSLATIONAL was
the under-sampled part** (EA 1439→965 as the longer window caught more slow junction breathing). Insert-
count trend now clear: **more inserts → softer AXIAL** (1-insert 1xT EA 1664 → 2-insert 2xT EA 965),
rotational similar (both soft hinges ~5-10× under SNUPI single_co). ⚠ Fetch mishap: a fetch process died
leaving pod ou1vxof3z0wwnm orphaned+billing → caught + reaped via a finally-reap fetch. Replica pod
gcptdv331ilquk (5090) ran a 5 ns independent replica; at ~3 ns processed on-pod (`process_replica_and_reap.py`,
124 post-eq frames) then REAPED (finally-reap; nothing billing, all pods gone). **Independent replica
CROSS-CHECK: ROTATIONAL agrees (GJ 24 vs 27, EIz 12 vs 13 — robust, not a single-trajectory artifact).**
BUT it INVERTS the slow-DOF assumption: the **TRANSLATIONAL is the slow-converging one** — short windows
over-estimate EA (replica 124fr→1647, existing first 168fr→1439, full 1159fr→965); EA keeps softening as
the window grows, so **wired EA 965 is the best estimate but likely an UPPER bound** (the junction's slow
AXIAL breathing needs more ns, NOT the rotation). Rotational (GJ 27) is the solid part. Total campaign
billing this session ~$8-12 (2xT replica + fetch pods); ledger `spent()` still inflated from destroyed
pods (cosmetic). To tighten EA: longer 2xT (or pool the 1xT continuation @9ns for the 1-insert axial).

### ✅ Curves+ per-frame pipeline VALIDATED (2026-07-19) — regular_bp recovers B-DNA + correct couplings
`curves_stiffness.py`: pick a 12-bp duplex fragment (geometric pairs, NOT WC-filtered), per DCD frame
write a star-atom PDB + run Cur+ + parse (C) Inter-BP, accumulate per-step TEMPORAL 6x6 cov → k=kT·Cov⁻¹.
**1xT (148 frames): twist std 3.6° roll/tilt 4.9° rise 0.28Å (all B-DNA); twist Lp 103 / bend Lp 51 nm;
GJ 428 EIz 213 pN·nm² (SNUPI regular_bp ~314-400/~246); twist-stretch −205 pN·nm (SNUPI −277 — CORRECT
sign+magnitude).** The roll-soft/coupling-sign saga was MY numpy extractor, NOT the physics. GOTCHAS
(fixed): PDB needs altLoc col-17 space (else 3-char atom names merge into resname); prime→STAR names;
**clean cur* files before each Cur+ run** (Cur+ won't overwrite → failed re-run leaves prev .lis →
identical params every frame = zero variance); singular cov from Cur+ 0.1° rounding → pinv. **SEQUENCE
FINDING: the 24hb build used a NON-design (arbitrary) sequence** — build_c1_pairs pairs are geometrically
correct (WC dist 10.0Å = non-WC 9.9Å) but only 30% resname-complementary (longest WC run 5 bp), so
resname-WC filtering FAILS; pair geometrically → sequence-AVERAGED stiffness (fine for regular_bp family
mean; no per-dinucleotide without the design sequence). 2xT re-fetch running (subset py base64'd to dodge
shell-quoting). NEXT: Curves+ per-frame on 2xT duplex; crossover via Curves+ 2-bp pseudo-fragment OR my
extractor's robust translational.

### RESULTS — 2xT extra-base motif FIRST QUANTITATIVE ESTIMATE (2026-07-19)
2xT subset fetched: `dab9e728433e/2xT_subset.dcd` (2.9 GB, 168 frames, 1.6-3.6 ns window). Pod reaped, $0.
- **2xT regular_bp (Curves+, nbp=8 loosened filter — 2xT is strained, longest clean run ~9 bp):** twist
  34.2° rise 3.37Å; std tilt 5.9/roll 6.8/twist 4.8°; EA 1487 GJ 244 EIy 134 EIz 102 pN·nm²; twist Lp 59
  bend Lp 25 nm; twist-stretch −145 pN·nm (correct sign). **2xT duplex is SOFTER than 1xT (twist Lp
  59 vs 103, bend 25 vs 51)** — physically consistent with the 2× pre-twist strain.
- **2xT extra-base CROSSOVER motif — TRANSLATIONAL (robust, C1'-centers only, no frame noise):** span
  L=1.89 nm (= SNUPI CO axial ~1.9nm ✓); fluctuation std axial 0.64 / perp 0.82,1.06 Å; **EA(stretch)
  1885 pN, GAy(shear) 1167, GAz(shear) 698 pN.** This is the FIRST quantitative estimate of the novel
  motif and REPLACES fem_solver.py:490's placeholder (a translational-only WLC spring, k_rot=0).
- **Crossover ROTATIONAL (torsion/bend) — STILL A GAP.** Curves+ can't do a cross-helix step (fits
  stacked-duplex 3.4Å geometry, not an 18Å junction); my extractor's rotational is frame-noise-limited
  (Curves+ calib proved unreliable per-step). No existing tool does a clean cross-helix 6-DOF. Options:
  (a) build a Kabsch-3DNA-frame cross-helix extractor (started in kabsch_frame_test.py, imperfect);
  (b) accept translational + inherit rotational from nearest published single_co motif; (c) longer/
  better-equilibrated 2xT (won't fix the FRAME limitation, only sampling). TOOLS: `curves_stiffness.py`
  (regular_bp, VALIDATED), the inline crossover-translational extractor. To add the motif to SNUPI:
  new family block in snupi_params.json + classify extra_bases crossovers into it + extend MOTIF_FAMILIES
  (see the earlier fem_solver map). Sequence-averaged only (non-design build sequence).

### ✅✅ CROSS-HELIX EXTRACTOR BUILT + CALIBRATED — extra-base motif 6x6 DELIVERED (2026-07-19)
`kabsch_frame_test.bp_frames_kabsch` = a numpy Kabsch-3DNA base-frame extractor. **CALIBRATED against
Curves+ per-step on the 1xT duplex (`curves_kabsch_calib.py`): ALL 6 DOF corr ~1.0 slope ~1.0** (shift
1.00/1.00, slide 1.00/0.99, rise 0.99/1.01, tilt 0.99/1.01, roll 0.98/1.00, twist 0.99/0.98). KEY FIX:
bp origin = averaged 3DNA base-frame origins (Kabsch-fitted `_kabsch_R` now returns origin), NOT C1'
midpoint (that broke rise corr −0.18→0.99 + slide offset). Unlike Curves+ it works CROSS-HELIX.
`crossover_stiffness_kabsch.py` applies it to the 2xT crossover (330 xovers, 168 frames, L=2.29nm),
measuring the rotational FLUCTUATION relative to each crossover's reference orientation (Rrel_ref) so the
large cross-helix mean angle doesn't ill-condition the log-map. **RESULT — extra-base crossover 6x6:
TRANSLATIONAL EA 1439 GAy 1032 GAz 593 pN (in SNUPI crossover range, ~co_nick), ROTATIONAL GJ 27 EIy 31
EIz 13 pN·nm² (~5-10× SOFTER than SNUPI single_co GJ127/EIy177/EIz147).** THE NOVEL PHYSICS: the unpaired
inserts make the junction a FLEXIBLE ROTATIONAL HINGE (soft torsion+bend) while stretch/shear stay
crossover-typical — exactly what SNUPI's fixed 74-motif set cannot represent + why fem_solver:490's
k_rot=0 placeholder is qualitatively right (rot IS soft) but not zero. CAVEATS: rotational still 32-49°
std → first estimate, and the junction is the SLOW mode (168 frames/1.6-3.6ns may under-sample it, per
Pan-Bathe not-converged-at-100ns); sequence-averaged. NEXT: wire into snupi_params.json as a 6th family
`extra_base_co` + classify extra_bases crossovers into it (fem_solver `_classify_crossovers` + `motif_D`).
