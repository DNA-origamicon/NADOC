# exp52 — GPU-resident is coupled to system size, not to the integrator

**Date** 2026-08-05 · **System** the exp51 package, reused verbatim (2hb_1xT, **32,754
atoms**, same solvation, same minimisation, same 50 ps restrained equilibration, same
starting checkpoint) · **Hardware** RTX 2080 SUPER, NAMD 3.0.2p1 CUDA, `+p8` ·
**Report** `runs/2hb_1xT/exp52_report.json`

Six cells: the three integrator settings exp51 found sound, each with `GPUresident on` and
with the directive absent. Every other line of the conf is byte-identical between the two
arms of a pair.

| integrator | resident off | resident on | speedup | resident engaged? |
|---|---|---|---|---|
| 1 fs, flexible, standard masses | 28.1 ns/day (3.077 ms/step) | **57.8** (1.494) | **2.06×** | yes |
| 2 fs, rigid, standard masses | 50.7 (3.406) | **97.9** (1.765) | **1.93×** | yes |
| 4 fs, rigid, HMR | 95.9 (3.603) | **177.9** (1.942) | **1.86×** | yes |

All six ran to completion. No RATTLE failures, no velocity-limit deaths, no NAMD refusals.

*Cross-check:* the resident-off arms reproduce exp51's independently-run numbers (29.1 /
49.7 / 101.5 ns/day) to within a few percent, so the two experiments are comparable.

## Answers

**Q1 — Is GPUresident accepted at 1 fs with `rigidBonds none`? YES, and it engages.**
The log shows the resident path active and the run is 2.06× faster. So
`gpu_line = "" if ts == 1.0 else _res_line` in `build_production_conf` is **not** guarding
an incompatibility. It is a throughput opinion that silently overrode the user's own
Advanced-card choice — and on this machine the opinion is backwards.

**Q2 — Is resident a loss below the ~100k-atom crossover? NO. It is a ~2× WIN here.**
This is the significant finding. `_RESIDENT_MIN_ATOMS = 100_000` exists because resident
was measured at **0.88–0.97×** (a loss) at 32.5k atoms — almost exactly this system's size.
On this hardware and this NAMD build it is 1.86–2.06× in the other direction. The constant
is therefore **not portable**, and it is currently applied as if it were: a 32.7k-atom job
on this machine defaults to the offload path and runs at half speed.

What differs from the original measurement: different GPU (RTX 2080 SUPER vs 3080 Ti),
different thread count (`+p8` vs `+p16`), and the patched 3.0.2p1 build. Any of those can
move a crossover that is fundamentally about when fixed per-step GPU overhead stops
dominating. **This is not evidence the old number was wrong when it was taken** — it is
evidence that one hardcoded constant cannot answer the question for every machine.

**Q3 — Does 4 fs + HMR run with resident OFF? YES — 95.9 ns/day, clean.**
This is a matched pair on one system, which the two conflicting records in the tree never
had. It refutes, at this size, the claim still live in `md_protocols.strip_gpu_resident`'s
docstring and in `LESSONS.md` K6:

> "the 4 fs timestep survives only under GPUresident's GPU constraint solver. Without it,
> the CPU RATTLE path blows up on the first step"

The same file already says so 60 lines further down ("SUPERSEDED 2026-07-12"). exp52 makes
it a measurement rather than two anecdotes on different systems.

## What this does not establish

- **One machine, one system size.** 32.7k atoms on one GPU. It says nothing about where the
  real crossover sits on this hardware, only that it is *below* 32.7k — the sweep that would
  locate it (say 10k → 500k) was not run.
- **Throughput only.** Both arms of each pair are the same physics; nothing here re-checks
  structure or energy conservation, which exp51 covers.
- **Not the ladder.** These are production-shaped confs. The ladder's own resident gate
  (`_segment_conf`) never had the timestep coupling and was not under test.

## Consequences applied

1. `build_production_conf`'s `ts == 1.0` special case is **removed**. Resident is resolved by
   `md_integrator.resident_decision()` — hard incompatibility → explicit user choice → size
   crossover — the same function the ladder uses, so the two paths can no longer disagree.
2. The decision now carries a **reason** and a `decided_by`, surfaced in the plan as a
   condition against the GPU-resident control, so "why is this off when I asked for it on?"
   is answerable from the wizard.
3. The refuted K6 sentence is corrected in both places that still assert it.
4. `_RESIDENT_MIN_ATOMS` is **left at 100,000** — a constant measured on other hardware
   should not be re-pinned from a single machine. It is now a stated default that the user's
   own choice overrides (and the override actually works), rather than a silent rule.

## Reproduce

```bash
python experiments/exp52_gpu_resident_coupling/run_matrix.py \
    --package experiments/exp51_integrator_factorial/runs/2hb_1xT/pkg_fast/package/2hb_1xT_namd_solvated \
    -o experiments/exp52_gpu_resident_coupling/runs/2hb_1xT
```
~6 min; reuses exp51's package, so run that first.
