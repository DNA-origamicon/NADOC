# Production instability on floppy designs → auto dt-halving recovery (2026-06-25) — supporting detail

[Topic head](../../project_oxdna_extra_bases.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Production instability on floppy designs → auto dt-halving recovery (2026-06-25)

Putting extra bases at EVERY crossover (e.g. VoltronCore: "TT" on all 577) globally
softens the structure — each crossover becomes a 2-nt ssDNA gap instead of a rigid
junction. Such a design can relax fine (healthy 93% bp) yet go numerically unstable
LATE in production: it sampled stably for ~24M/50M steps, then a region nucleated
melting (potential energy climbed −1.388 → −1.26 while temperature held), and a single
scaffold particle's coordinates exploded to ~1e17. oxDNA aborts: "A cell contains more
than _max_n_per_cell (114) particles … particles with very large coordinates …".
Root cause = the production timestep `dt=0.005` (`build_production_stage` /
`build_field_stage` / `build_run_stage` in oxdna_protocol.py; relax stages use 0.002/
0.003) is too aggressive for a large floppy structure under mixed-precision CUDA.

Fix (oxdna_runner.py `run_job` crash handler): on an unbiased MD stage (`kind` in
`_DT_HALVE_KINDS` = production/field/run) crashing with rc≠0 AND a blow-up signature in
the log (`_log_indicates_explosion`: `_max_n_per_cell` / "very large coordinates" /
`nan`), the runner re-runs THAT stage from the clean relaxed seed at HALF the dt
(`_halve_dt_and_restart`: `replace(spec, dt=dt/2)` + `_reset_stage_outputs` so
`_starting_conf` falls back to the relaxed conf, NOT the exploded checkpoint), up to
`max_production_retries` (default 2 → 0.005→0.0025→0.00125). Keeps the fast dt the
default; only floppy/large designs pay the finer timestep. Takes precedence over the
relax-escalation branch (relax was healthy — wrong lever). Exhausted budget → a
plain-language failure telling the user the design is too floppy/strained (relax longer
or use fewer/shorter extra bases). Job model gained `production_retries` /
`max_production_retries` (oxdna_job.py, with `load` setdefaults). Pins in
test_oxdna_relaxation.py: `_log_indicates_explosion` (blow-up vs setup error vs clean),
`_halve_dt_and_restart` transform, field roundtrip, and an e2e `run_job` explode-then-
recover with a mock binary. NOTE: halving dt at fixed step count means the recovered
run samples LESS simulated time; a future improvement could resume from the last GOOD
trajectory frame instead of restarting, and/or double-precision as a final fallback.

## Validation

- `tests/test_oxdna_extra_bases.py` — fast pins: order/topology grows by N, bases on
  the owning strand, n3/n5 thread in-chain, config bond lengths FENE-safe + orthonormal
  frames, read-back drops inserts + off-by-N alignment guard, the phantom-bond pin, and
  the `assert_extra_bases_in_oxdna` harness oracle (can-go-red).
- `tests/test_oxdna_extra_base_production.py` — real CUDA engine, `@pytest.mark.slow`,
  opt-in `NADOC_RUN_OXDNA_SLOW=1`. Parametrized over design (6hb ~1058 nt / 18hb
  ~3210 nt, both seamless-autoscaffolded + autostapled + sequenced) × mode (precise:
  "TT" at one crossover; bulk: "T" at every crossover — 53 on 6hb, 185 on 18hb), then
  relax + 5M-step production at code defaults. ALL FOUR reach `completed` with geometry
  recovered and the duplex re-annealed (retention ≥ 0.85): 6hb ~5 min, 18hb ~7 min each
  on the RTX 3080 Ti. So the wiring is design-agnostic, not 6hb-specific.

Race fix (found via 18hb): `wait_for_terminal` returns the moment the on-disk job is
terminal, but the runner thread writes that status JUST BEFORE it deregisters from the
in-memory `_RUNNING` set — so a programmatic relax→`append_production`/`append_field`
chain could hit the route's `is_running` guard and 400 ("Production requires a completed
relaxation job"). Fixed by having `wait_for_terminal` also wait out the teardown window
(bounded by its timeout) before returning. Benefits all headless automation, not just
the test.

Three-Layer Law: read-only of topology metadata, physical-layer file output only — no
strand-graph mutation. See also [[project_oxdna_benchmarks]] and
[[project_oxpy_binding_patch]].

## Rendering extra bases at REAL simulated positions (Phase 1 done)

Extra-base beads/slabs ALWAYS render (built by `crossover_connections.js`
`buildCrossoverConnections`, present in every mode as children of `_helixCtrl.root`),
but were positioned by a geometric **Bézier arc** between the crossover endpoints
(`updateExtraBaseInstances`, re-interpolated each frame via
`design_renderer.applyClusterCrossoverUpdate`). They never reflected the real ssDNA
conformation. `_xoverArcDataMap.get(crossover_id) → {beadStartIdx, beadCount, simReversed}`
maps `(crossover_id, k)` → bead instance `beadStartIdx + simBeadIndex(k, beadCount,
simReversed)` — **NOT `beadStartIdx + k`**; see the ordering law below.
