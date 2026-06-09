# Exp25 — Full B-tube Early Relaxation Probes

Goal: simulate the full B_tube origami in short, restartable windows so we can
measure how the all-atom model relaxes immediately after construction. These
runs are diagnostic: they are meant to identify systematic template/CAD strain
and produce better atomistic starting positions, not to claim production
stability.

Starting point:

- Full B_tube NAMD GBIS package from `experiments/exp22_btube_md_benchmark/results/namd_run/`.
- The earlier benchmark blew up shortly after `reinitvels 310` following only
  500 minimization steps. That suggests the raw template model needs a gentler
  startup and/or retained restraints before any unrestrained production.

Initial probe ladder:

1. `F001_min_only_5k`: minimization only, writes a minimized restart/PDB.
2. `F002_cold_10ps_k5`: 10 ps at 50 K, 0.5 fs, strong positional restraints.
3. `F003_warm_20ps_k2`: 20 ps at 150 K, 0.5 fs, moderate restraints.
4. `F004_prod_20ps_k1`: 20 ps at 310 K, 1.0 fs, weak retained restraints.

The ladder is intentionally conservative. If a stage fails, that failure is the
result: record where and why, then adjust the startup rather than forcing a long
run.

Use `scripts/setup_full_relax_probes.py` to generate configs and restraint PDBs.
