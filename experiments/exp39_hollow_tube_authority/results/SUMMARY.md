# exp39 (G2) — hollow-tube per-helix authority vs geometry

## Routing audit (every generated tube)

| tube | D | hollow | helices | crossovers | mesh nodes | nonadj xo | nick@xo | flags |
|---|--:|:--:|--:|--:|--:|--:|:--:|---|
| hollow_d3 | 3 | True | 8 | 88 | 1344 | 0 | True | clean |
| hollow_d4 | 4 | True | 12 | 132 | 2016 | 0 | True | clean |
| hollow_d5 | 5 | True | 16 | 176 | 2688 | 0 | True | clean |
| hollow_d6 | 6 | True | 20 | 220 | 3360 | 0 | True | clean |
| solid_d2 | 2 | False | 4 | 43 | 672 | 0 | True | clean |
| solid_d3 | 3 | False | 9 | 126 | 1512 | 0 | True | scaffold not single (2) |
| solid_d4 | 4 | False | 16 | 246 | 2688 | 0 | True | clean |

*(nick@xo = staple nick on a crossover — a GENERAL square-autostaple limitation, present on solid too; not hollow-specific. nonadj xo = crossover across the hollow, the real red flag — must be 0.)*

## Law 1: ∂bend/∂skip vs moment arm r_h (per tube)

| tube | corr(r, |dbend|) | max|dbend| | r range (nm) |
|---|--:|--:|---|
| hollow_d3 | +0.78 | 2.17 | 2.2–3.2 |
| hollow_d4 | -0.02 | 0.85 | 3.6–4.8 |
| hollow_d5 | +0.51 | 0.98 | 4.5–6.4 |
| hollow_d6 | +0.56 | 0.45 | 5.7–8.0 |
| solid_d2 | +nan | 5.13 | 1.6–1.6 |
| solid_d4 | +0.74 | 1.18 | 1.6–4.8 |

## Law 2: ∂twist/∂skip — per-tube mean (does it scale with size?)

| tube | D | N helices | mean dtwist/skip | std | mean·N |
|---|--:|--:|--:|--:|--:|
| hollow_d3 | 3 | 8 | -0.869 | 0.685 | -6.95 |
| hollow_d4 | 4 | 12 | -0.327 | 0.246 | -3.93 |
| hollow_d5 | 5 | 16 | -0.183 | 0.088 | -2.93 |
| hollow_d6 | 6 | 20 | -0.098 | 0.054 | -1.95 |
| solid_d2 | 2 | 4 | -2.098 | 0.394 | -8.39 |
| solid_d4 | 4 | 16 | -0.320 | 0.132 | -5.12 |

*(If `mean·N` is ~constant across tubes, ∂twist/∂skip ∝ 1/N — the cross-section scaling exp37/exp36 saw: more helices share the torsional load, so each skip steers twist less.)*


## G2 VERDICT
- **Routing validated for hollow tubes** (d3–d6): single scaffold covering all helices, ZERO
  across-hollow crossovers, full duplex mesh. The audit FLAGGED a genuinely mis-routed `solid_3x3`
  (auto_scaffold left 2 disjoint scaffolds) — excluded from the fit. `nick@xo` is a general
  square-autostaple limitation (solid too), not hollow-specific.
- **Twist authority ∝ ~1/(N·r)** — clean, monotonic: each skip steers global twist far less as the
  cross-section grows (N helices share + relieve the torsional load over larger moment arms). solid_d2
  −2.1°/skip → hollow_d6 −0.10°/skip.
- **Bend authority ∝ moment arm** (bimetallic) with an envelope that also shrinks with size, BUT the
  per-helix signal is noise-limited on symmetric/large tubes: thin rings have ~no r-variance, and a
  single-skip bend on a big straight tube sits near the scalar arc-bend ~0.6° floor.
- **⇒ Keep the in-loop measured Jacobian (G1) for accuracy; use the geometry law as a SEED** (set the
  density scale, cut probe iterations) not a replacement. For large designs, `1/(N·r)` + symmetry-orbit
  grouping (G5) is the scaling path. Methodology fix for G3: probe bend with a MULTI-skip perturbation
  (e.g. +5, divided) to clear the estimator floor; asymmetric sections (G3) give a larger, cleaner
  bend-authority signal than symmetric tubes.
