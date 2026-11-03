# Suggested CreateBladeJobRequest knobs — historical evidence

[Topic head](../../project_blade_frontend.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Suggested CreateBladeJobRequest knobs
`mode` (relax|seed_namd), `design_source_path`, `correction` (baseline|unified), relax:
`minimize_iters`,`langevin_ps`,`nb_cutoff_A`; seed_namd: `production_steps`,`dcd_freq`,
`ion_conc_mM`,`mg_conc_mM`; `autostart`.

## Open questions — ANSWERED 2026-07-20 (see STATUS block at top)
- MVP = **relax-only**. `seed_namd` is rejected at create time until wired.
- Display = playback **+ uncertainty was requested**, but uncertainty is BLOCKED (no ensemble
  checkpoint — see the STATUS blocker). Playback is built; the overlay is refused at the API.
- **Yes, sim-guard gated** — `_check_sim_guard()` refuses a CUDA relax while a heavy sim owns
  the machine. CPU platform is exempt (it's the escape hatch), and the guard fails open.
