# exp35 — conclusion: the 10M-equil fix removes the FAST twist ramp, but d+4 does NOT equilibrate to 0 (2026-06-30)

## TL;DR
The equilibration lengthening (relax `equil_steps` 100k → **10M**, shipped in
`autorefine_sq_design`) **works at its stated job**: a fresh, properly-equilibrated 3×6×400 d+4
production is post-transient — burn-in `t0 = 0`, the per-frame trace is flat from the first frame
(no +90°→equilibrium ramp), well-sampled (τ=2.9 frames, N_eff 272/800, SEM ±0.68°), and the
whole-production mean the secant steers on **equals** the `detect_equilibration`-trimmed mean
(0.0° gap). **PROMPT residual-transient criteria 1 & 2 PASS.**

BUT the equilibrated d+4 twist is **+18.2 ± 0.7°, not ~0°** (criterion 3 FAILS). This
**contradicts exp34c's warm-started −0.6 ± 0.6°** for the identical 222-skip design and instead
**reproduces the OLD "8M under-equilibrated → +17° → needs d+5" number**. So the exp34c premise
("d+4 equilibrates to zero; the count was always right; only equilibration was broken") is **NOT
reproduced by a fresh cold build with the shipped 10M equil.**

**This is a third outcome the PROMPT's binary didn't anticipate, and the prescribed FAIL remedy —
a burn-in discard in the measurement — is a NO-OP here (`t0` is already 0).** There is no
in-window transient left to trim. The miss is the *slow* twist relaxation, which is longer than
the whole 26M-step run and therefore invisible to `detect_equilibration` inside a 16M production
window — the exact "a low τ / apparent flatness does NOT certify equilibration" trap exp34 warned
about, resurfacing one level up.

## The run
- Design: `place_incremental(bare, baseline_skips(bare, 48), 4)` = **222 skips** (d+4), 3×6×400
  seamless SQ, 14 686 nt. Identical topology to exp34c's d+4.
- Relax: mc 1 000 (CPU) → md_relax 1e6 (CUDA) → **equil 10e6 (CUDA)**. Production: 8 × 2M = **16M**
  (CUDA, 20k-step frame spacing → 800 frames). Real CUDA (`~/oxDNA/build_cuda`), ~77 min wall.
- Health: bp-retained 96.3%, FENE-safe, max backbone stretch 1.51 nm, `healthy=True`. Intact.
- Result: `results/residual_result.json`; PNG `results/profiles/png/residual_d+4.png`.

| quantity | value | criterion |
|---|---|---|
| burn-in `t0` | **0 frames = 0 M steps** | ≤ 1M ✅ |
| whole-production mean | **+18.24°** | — |
| equilibrated mean (post-`t0`) | **+18.24 ± 0.68°** | — |
| \|whole − equilibrated\| | **0.0°** | ≤ 2° ✅ |
| \|equilibrated\| (d+4 ≈ 0?) | **18.24°** | ≤ 2° ❌ |
| τ_int / N_eff | 2.9 / 272 of 800 | well-sampled |

## Why this is a slow-glide-incompleteness result, not a basin fluke or a measurement bug
Count monotonicity (more skips → more negative twist) from exp34c: d+3 = **+35.7°**, d+4 =
**−0.6°**, d+5 = **−19.8°**. exp35's fresh d+4 = **+18.2°** sits *between* exp34c's d+3 and d+4 —
i.e. it relaxed **LESS** than exp34c's (longer-history, warm-started) d+4. Consistent picture:

- The 80M longrun (exp34, d+5) showed the twist starts at +90° and relaxes **monotonically** to
  its plateau; the fast part is ~8M steps but the approach is long-tailed.
- exp35's 10M equil clears the fast +90° ramp (hence `t0=0`, flat production), but the structure is
  still **gliding** from ~+18° toward exp34c's ~0°. A glide whose timescale is ≫ 16M has a
  per-frame slope far below the ±11° per-frame noise → it reads "flat" in a 16M window, and
  `detect_equilibration` (which maximises N_eff *within the given series*) returns `t0=0`. It
  cannot detect a transient longer than the trajectory it is given.
- exp34c's warm-start had ~24M+ of accumulated MD from an already-produced structure → further
  down the glide → nearer 0. Its `t0=4.3M` burn-in was trimming the *tail* of the same glide.

So neither +18.2° nor −0.6° is provably "the" equilibrium; they are two points on one slow
relaxation, sampled at different total-MD ages. **10M equil is still insufficient to pin the d+4
twist**; the shipped autorefine, run cold, would measure +18° at d+4 and therefore steer the
count-secant toward **more** skips (≈ d+5 = 240) to cancel it — reproducing the very "needs d+5"
outcome exp34c believed it had overturned.

## Consequences
1. **The equilibration fix is necessary but NOT sufficient.** It correctly kills the fast +90°
   ramp (a real, shipped improvement — criteria 1 & 2 confirm the secant now steers on the
   post-ramp mean, not a drifting mid-transient value). It does not resolve the slow twist glide.
2. **The PROMPT's FAIL branch does not apply.** Burn-in discard in the measurement cannot fix a
   transient that is longer than the whole production and reads `t0=0`. Do **not** implement it as
   the remedy for this failure — it would change nothing here.
3. **exp34c's "d+4 = net-zero, count was always right" is unconfirmed / likely premature.** A
   fresh, properly-equilibrated cold build reads +18° at d+4. The count target (222 vs 240) is
   **not** pinned by a 26M-step run.
4. **e2e was NOT run.** Its PROMPT-expected outcome ("new: ≈0° at d+4, converges there") is
   contradicted by this data; a cold e2e would most likely converge to ~240 skips (d+5), not 222.
   Deferred to the user pending the discrepancy resolution below (`run.py --mode e2e` + the
   `trigger_export.sh e2e` PNG trigger are wired and ready if wanted).

## Recommended next step (decisive, reuses the archived job)
Continue **this exact d+4 job** (archived at
`/media/jojo/Archive/.../exp35_.../76deb290aba8`) for another ~64M steps (to match the 80M
longrun) via the exp34c warm-restore + `append_production` pattern (`run_burnin._warm_restore`),
tracking `production_twist_series` over the whole pooled trajectory. This distinguishes:
- **(A) slow glide toward 0** (exp34c right, 10M equil just too short): +18° drifts down toward ~0
  over the added steps → fix = a much longer equilibration (or an explicit long-run twist-
  convergence gate: keep equilibrating until the twist's block-averaged slope is ~0), OR
- **(B) metastable +18° basin** (exp34c's −0.6° was a different basin / lucky history): +18° stays
  put → the d+4 equilibrium twist is hysteretic/ill-defined and the count target is genuinely
  path-dependent.

Either way the autorefine needs a twist-**convergence** criterion, not just a fixed 10M equil, before
its count is trustworthy on a cold build. The `detect_equilibration` `t0=0` must NOT be read as
"equilibrated" without a run long enough to bound the slow mode.

## Deliverables produced
- `results/residual_result.json` (corrected verdict text names the third case explicitly).
- `results/profiles/png/residual_d+4.png` (burn-in-marked per-frame twist + PASS-criteria box).
- `results/proxy_result.json` + `proxy_iter{0..3}.png` — step-1 wiring smoke: `autorefine_sq_design`
  completes with the new default and **every iteration's production is measurable** via
  `read_twist_series` (`per_iter_measurable=True`; status `exhausted` on the tiny 3-iteration proxy
  is expected — it's a wiring check, not a physics target).
- `export_png.py` + `trigger_export.sh` — standalone exporter + end-of-job PNG trigger (fires the
  export the instant a mode's result JSON lands; reused for e2e when/if run).
- No backend code changed (only the experiment harness); the equilibration pin stays green.
