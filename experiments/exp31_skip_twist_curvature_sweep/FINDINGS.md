# exp31 — interim findings (live)

Running notes while the sweep is in progress; the formal write-up is `conclusion.md` (after
`results/COMPLETE`). See `hypothesis.md` for predictions.

## F1 — twist accumulates spatially NON-UNIFORMLY → evidence for local refinement (2026-06-27)

The detailed twist-vs-position profiles (cumulative twist along the bundle, 24-bp bins,
differential sim−analytic; `results/profiles/*.csv`, combined per-strategy panels in
`results/skip_twist_curvature.png`) show the global twist is not laid down evenly along the
bundle.

**Baseline (uniform_d+0, period 48, 150 uniform staggered skips):**

| region | cumulative twist | share of total |
|---|---|---|
| front half, 0–200 bp | ~6.0° (flat, ~0) | ~10% |
| back half, 200–400 bp | 6.0° → 57.7° (steep ramp) | ~90% |

The front half is locally near-untwisted while the back half is strongly over-wound — *despite a
spatially-uniform deletion pattern*. A uniform-density correction therefore over-corrects the
front and under-corrects the back. The actionable implication: concentrate added deletions in the
over-wound bp~200–400 region. This is direct, real-structure proof that **local (non-uniform)
twist correction is more appropriate than uniform density for this structure** — the precondition
the regional/local-refinement work needs (see `memory/project_regional_autorefine.md`, where this
is logged as the evidence base; it does NOT reopen *wholesale* redistribution, which failed for
register-swing reasons — the right tool is localized edits targeting the profile's high-slope
region, with the edit budget scaled to the integrated slope).

Comparison note: `incremental_d-4` shows a lower end-to-end twist than the baseline, but the
*shape* matters as much as the endpoint — a structure with low net twist but a bent or kinked
profile is not equivalent to a genuinely straight one. The per-strategy profile overlays are the
tool for reading that.

Status when logged: sweep in progress (uniform/incremental arms through Δ=−4…−1 + baseline; +Δ
arm and the deviation arm pending). Re-examine all three strategies' profiles across Δ at
completion.

## F2 — WHY the back half is over-wound: ruled out placement/measurement/bend → structural (2026-06-27)

Investigating the consistent back-loading of the uniform profiles (user request). Four candidate
causes tested against the archived data; the first three are RULED OUT:

1. **Skip placement — RULED OUT.** Computed the actual axial position of every deletion (helix
   axis lerp, `/tmp/skip_density.py`): the baseline's 150 skips split 75 front / 75 back with a
   flat 8-bin axial histogram (~19 each). The Δ≠0 `place_uniform` runs are likewise axially flat.
   The skips ARE uniform along the bundle; the residual twist is not.
2. **Measurement back-bias — RULED OUT.** The analytic (straight design) cumulative-twist profile
   reads flat-zero throughout (range −0.05…+0.02°). The differential isn't manufacturing a back
   ramp; the straight depiction reads straight at every position.
3. **Bend↔twist coupling — RULED OUT.** Back-loading does NOT track bend: uniform_d+2 is 75%
   back-loaded with only 1.0° bend, while uniform_d−3 has 37° bend but 65% back-loading. A bent
   bundle's global-frame projection is not the source.
4. **Structural / boundary asymmetry — SUPPORTED.** Both placement strategies back-load (uniform
   47–92%, incremental 36–74%), and "back" = the deterministic +axis end (the axis sign-normalised
   the same way every build), so the over-winding is tied to a SPECIFIC physical end and is
   systematic across independent relaxations (not random kinetics). Reading: the front half relaxes
   to design (well-corrected) while the back half retains over-twist despite uniform de-twisting
   deletions — i.e. asymmetric TORSIONAL BOUNDARY CONDITIONS. Leading mechanism: the seamless
   scaffold routing / staple-break (nick) architecture or an end crossover-density asymmetry makes
   one end torsionally freer than the other, so over-twist relaxes from the free end inward and
   piles up against the stiffer end (the back half). Independent of bend, placement, measurement.

## F3 — strategy verdict + INTERRUPTED for exp32 (2026-06-28)

Sweep interrupted at 22/27 sims (all 22 passed the structural-integrity gate: bp-retention
0.92–0.99, FENE-safe, stretch ~1.5 nm). The strategy comparison was already decisive
(endpoint°/flatness max|profile|°):

- **Incremental-gap (B) — the winner.** The ONLY strategy to reach flat-zero: at 222 skips it hit
  endpoint −3°, max|profile| **5°** (vs uniform 46/53° and deviation 59/68° at the same count). It
  also kept the most linear endpoint-vs-skips trend, i.e. each added skip in the largest gap buys
  predictable de-twisting. Keeping the baseline marks fixed and adding only at the widest gaps
  perturbs the register least, so the profile flattens instead of swinging.
- **Uniform restagger (A) — robust but never flat.** Re-staggering all skips each step keeps net
  twist controllable but leaves the back-loaded shape; still 46/53° at 222 skips.
- **Deviation-guided (C) — WORST, despite being the "adaptive" one.** Consistently highest
  flatness (68–95°). Root cause: it steers on the UNSIGNED positional deviation field
  (`geometry_deviation_map`), which mixes bend, end-fraying, and twist — it does NOT track the
  SIGNED local over-twist. So it adds skips in the wrong places. **This is the key lesson feeding
  exp32:** the right signal is the twist PROFILE's local slope (signed over-twist per segment), and
  the right placement is incremental-gap WITHIN the over-wound segment.

→ exp32 = profile-guided adaptive incremental-gap refinement (use the twist profile to pick
over-wound axial segments; fill them via incremental-gap; iterate to flat-zero). See that
experiment's dir. Logged to `LESSONS.md` (deviation-guided disproven) + [[project_regional_autorefine]].

Open next diagnostics (do NOT block the sweep): (a) map crossover-plane + strand-break (nick)
density vs axial position — is the back end stiffer / is there a discontinuity at the flat→ramp
transition? (b) the deviation-guided arm (strategy C, places skips at the prior sim's hotspot) is
the experiment's own test — if back-loading is genuine under-correction, C should concentrate skips
in the back half and FLATTEN the profile; that would both confirm this diagnosis and demonstrate
local refinement works. (c) longer production on one baseline to check it's not slow torsional
equilibration (consistency across runs argues against, but worth one confirmation).
