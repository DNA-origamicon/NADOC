# Where things are — supporting detail

[Topic head](../../project_crossover_catenation.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Where things are

- `backend/core/junction_topology.py` — connectors, reciprocal pairs, vectorised Gauss `Lk`,
  `catenation_report`, `gate_seed_topology`, plus `package_connector_rows` /
  `catenation_in_frame` for measuring a NAMD trajectory.
- `backend/core/extra_base_repair.py` — the repair ladder (scores BOTH defects).
- `backend/core/ring_piercing.py` — the threaded-ring detector: `model_piercings` /
  `piercing_report` / `assert_not_pierced` on a model, `PierceScope` for the ladder.
- `scripts/check_catenation.py` — Screen 0, build-only, run before spending GPU time; reports
  catenation AND piercings off one build.
- `scripts/check_ring_piercing_frame.py` — screens an already-built structure (a job's PSF +
  seed PDB / `.coor` / DCD), for deciding whether an existing run's data is usable.
- Gate sites: `md_protocols.prepare_mgh_slow_release`, `namd_package.build_namd_package`,
  `namd_vacuum`, `routes_md` (`allow_catenated_seed` overrides BOTH defects). Recorded in every
  manifest as `topology_check`, now with `n_ring_pierced` + `ring_pierced`.
- `audit_bonds` gained `catenation` + `ok_including_topology` (its `ok` is unchanged).
