---
name: cpd-umbrella-sampling
description: "Free energy of the designed CPD weld between extra crossover bases (2hb_1xT). Phase 0 done: unbiased 161.8 ns says the weld NEVER forms (min d 7.44 A, reactive corner 0.000%). CV pair is (d_mid, eta), frame-free. Read before touching colvars/US/free-energy work."
metadata:
  node_type: memory
  type: project
---

# CPD umbrella sampling — free energy of the designed extra-base weld

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

Experimental CPD work is excluded from general development tests. The dated resume/campaign notes are not authorization to start sampling. Scientific opt-in and the molecular/topology authorization rules remain required.

**The question.** `2hb_1xT` places one extra T at each of two reciprocal crossovers so they
can photo-weld (UV point welding, Dietz-style CPD formation). **Does the physics support that
design choice?** We are testing it, not assuming it.

<a id="-resume-here-2026-07-31"></a>
- [▶ RESUME HERE (2026-07-31)](details/project_cpd_umbrella_sampling/01-resume-here-2026-07-31.md#-resume-here-2026-07-31)

<a id="phase-2--window-seeding-2026-07-31-result-the-unbiased-run-seeds-513-windows"></a>
- [Phase 2 — window SEEDING (2026-07-31). Result: the unbiased run seeds 5/13 windows.](details/project_cpd_umbrella_sampling/01-resume-here-2026-07-31.md#phase-2--window-seeding-2026-07-31-result-the-unbiased-run-seeds-513-windows)

<a id="plan-inverted-2026-08-01-eabf-first-ladder-second"></a>
- [Plan inverted 2026-08-01: eABF FIRST, ladder second](details/project_cpd_umbrella_sampling/01-resume-here-2026-07-31.md#plan-inverted-2026-08-01-eabf-first-ladder-second)

<a id="the-eabf-emitter-was-broken-and-is-now-fixed-2026-08-01"></a>
- [The eABF emitter was BROKEN and is now fixed (2026-08-01)](details/project_cpd_umbrella_sampling/01-resume-here-2026-07-31.md#the-eabf-emitter-was-broken-and-is-now-fixed-2026-08-01)

<a id="production-runs-can-carry-a-bias-2026-08-01"></a>
- [Production runs can carry a bias (2026-08-01)](details/project_cpd_umbrella_sampling/01-resume-here-2026-07-31.md#production-runs-can-carry-a-bias-2026-08-01)

<a id="-fixed-2026-07-31--resumed-runs-were-analysed-at-13-coverage"></a>
- [✅ FIXED 2026-07-31 — resumed runs were analysed at ~1/3 coverage](details/project_cpd_umbrella_sampling/02-fixed-2026-07-31--resumed-runs-were-analysed-at-13-coverage.md#-fixed-2026-07-31--resumed-runs-were-analysed-at-13-coverage)

<a id="phase-1--what-shipped-the-weld-is-visible-in-3d"></a>
- [Phase 1 — what shipped (the weld is visible in 3D)](details/project_cpd_umbrella_sampling/02-fixed-2026-07-31--resumed-runs-were-analysed-at-13-coverage.md#phase-1--what-shipped-the-weld-is-visible-in-3d)

<a id="the-target--verified-from-the-design-not-assumed"></a>
- [The target — verified from the design, not assumed](details/project_cpd_umbrella_sampling/02-fixed-2026-07-31--resumed-runs-were-analysed-at-13-coverage.md#the-target--verified-from-the-design-not-assumed)

## The collective variables — (d_mid, eta), and they are FRAME-FREE

The KIMMDY geometric rate (`~/Work/kimmdy-namd-cpd/src/kimmdy_namd_cpd/rate.py`) is

```
k = exp( -( k1·|d − d0| + k2·|η − η0| ) )
  k1 = 2.017 nm⁻¹   k2 = 0.0300 deg⁻¹   d0 = 0.157 nm   η0 = 16.74°
```

`d = |0.5·((C5₂−C5₁) + (C6₂−C6₁))|` simplifies exactly to **the distance between the two
C5=C6 bond midpoints**. So both CVs are Colvars-native:

- **d_mid** — `distance` between two atom groups, each `{C5, C6}`. C5 and C6 are both carbon,
  so centre-of-mass == centre-of-geometry == the bond midpoint. No `customFunction` needed.
- **eta** — `dihedral` on (C5_a, C6_a, C6_b, C5_b).

**Do NOT add C6–C6 as a third axis.** C6 is already inside `d_mid` as the midpoint. A third
axis would be near-collinear and does not enter the rate. The rate-relevant space is 2D.

**Reference implementation already exists** (hand-written, use as the format oracle):
`/media/jojo/Archive/NAMD/CPD_1xT/colvars_cpd_metrics.in` — same two CVs. Its sibling
`colvars_cpd_smd.in` steers d_mid 7→5 Å at k=0.25.

Being internal coordinates, they need **no body-fixed frame** — which matters, see below.

<a id="phase-0-result--the-weld-does-not-form-1618-ns-unbiased-k0"></a>
- [Phase 0 result — the weld does not form (161.8 ns unbiased, k=0)](details/project_cpd_umbrella_sampling/03-phase-0-result--the-weld-does-not-form-1618-ns-unbiased-k0.md#phase-0-result--the-weld-does-not-form-1618-ns-unbiased-k0)

<a id="1xt-vs-2xt--one-t-cannot-reach-two-can-suggestive-not-yet-conclusive"></a>
- [1xT vs 2xT — one T cannot reach, two can (suggestive, not yet conclusive)](details/project_cpd_umbrella_sampling/03-phase-0-result--the-weld-does-not-form-1618-ns-unbiased-k0.md#1xt-vs-2xt--one-t-cannot-reach-two-can-suggestive-not-yet-conclusive)

## Scope limit — the PMF bottoms out at vdW contact

`d0 = 1.57 Å` is a *cyclobutane C–C bond* — the product. A classical force field cannot reach
it. The useful PMF range is **~3.4 Å (vdW contact between ring midpoints) → ~12 Å**. ⟨k⟩ is
integrated over that range only; the last 2 Å to product is QM territory and out of scope.
So the umbrella must close **~8 Å**, from 11.4 down to ~3.4.

## HARD GATE — topology must be clean before and after every run

[[project_crossover_catenation]] records that a catenated junction **"mimics a soft rotational
hinge"** and is **invisible to C1′/WC health checks** (an affected 2hb_1xT run reported
`c1_paired_fraction = 1.0`). The hinge it fakes is torsional — i.e. exactly η. An F(d,η)
surface is uniquely vulnerable to this defect and would look entirely plausible while being
wrong. Catenation was fixed 2026-07-28; the ring-piercing defect (which the catenation repair
was itself manufacturing) shipped **2026-07-31**, so builds between those dates can pass
catenation and still be pierced.

Verified clean 2026-07-31:

```
scripts/check_catenation.py workspace/2hb_1xT.nadoc     -> catenated 0/1, pierced 0
scripts/check_ring_piercing_frame.py <pkg>/2hb_1xT.psf <both dcds> --stride 200  -> 0
```

Run **both** gates on the seed *and* the final frame of every umbrella window.

<a id="frame-rigidity--why-the-3d-cartesian-map-is-demoted"></a>
- [Frame rigidity — why the 3D Cartesian map is demoted](details/project_cpd_umbrella_sampling/04-frame-rigidity--why-the-3d-cartesian-map-is-demoted.md#frame-rigidity--why-the-3d-cartesian-map-is-demoted)

<a id="phased-plan"></a>
- [Phased plan](details/project_cpd_umbrella_sampling/04-frame-rigidity--why-the-3d-cartesian-map-is-demoted.md#phased-plan)

<a id="corrections-and-dead-ends--do-not-repeat"></a>
- [Corrections and dead ends — do not repeat](details/project_cpd_umbrella_sampling/04-frame-rigidity--why-the-3d-cartesian-map-is-demoted.md#corrections-and-dead-ends--do-not-repeat)

<a id="tooling"></a>
- [Tooling](details/project_cpd_umbrella_sampling/04-frame-rigidity--why-the-3d-cartesian-map-is-demoted.md#tooling)

<a id="related"></a>
- [Related](details/project_cpd_umbrella_sampling/04-frame-rigidity--why-the-3d-cartesian-map-is-demoted.md#related)
