# Bare gold qualification

Selected model: neutral INTERFACE 12–6 Au, `iff-au-12-6-neutral-v1`.
[Selection/provenance](../../docs/namd_gold_model_selection.md).
[Measured results and barriers](../../workspace/gold_validation_20260914/RESULTS.md).

## Prepare and run locally

From the repository root; output directories and run prefixes must be new:

```bash
uv run python -m experiments.gold_interfaces.build \
  experiments/gold_interfaces/planar.json workspace/my_gold_slab
uv run python -m experiments.gold_interfaces.build \
  experiments/gold_interfaces/nanoparticle.json workspace/my_gold_particle

uv run python -m experiments.gold_interfaces.native workspace/my_gold_slab \
  --binary /path/to/qualified/namd3 --prefix initial --minimize 500 --steps 10000
uv run python -m experiments.gold_interfaces.native workspace/my_gold_slab \
  --binary /path/to/qualified/namd3 --prefix next --restart initial --steps 10000
uv run python -m experiments.gold_interfaces.analyze workspace/my_gold_slab next
```

For slabs the binary must match the registered EW3DC GPU plugin's engine SHA256.
The examples use ordinary rigid-water masses, 1 fs, full electrostatics each step,
12 Å LJ cutoff and 10 Å switching. Production qualification is always false.
`water_loading_scale=1.18` in the planar recipe is a pilot loading choice for that
specific geometry; central density must be measured for each new recipe. The
particle default is underdense in its short fixed-volume pilot and needs a matched
bulk-density preparation before production. No model parameters were fitted here.

`build_package` rejects unknown geometry/chemistry rather than substituting a wall.
Supported crystal facets: unreconstructed (100)/(111). Particles are spherical fcc
cuts with explicit radius, not equilibrium morphology predictions. Coordinate
transforms are shared through `gold_geometry.transformed_geometry`; runnable
packages currently use Cartesian cells and Z-normal slits. Minimum cell dimension
is 4 nm for the initial resident qualification envelope.

## Managed jobs and reusable recipes

```python
from pathlib import Path
from backend.core.namd_gold_job import prepare_job, extend_job

job = prepare_job(Path("workspace"),
    {"kind": "nanoparticle", "radius_nm": 0.85, "solvent_padding_nm": 1.5},
    steps=10000, timestep_fs=1.0, mobility="restrained")
# Start through POST /api/md/jobs/{job.job_id}/start.
# Once completed, append a segment without changing the initial system:
job = extend_job(job.job_id, Path("workspace"), steps=10000)
```

Equivalent preparation: `POST /api/md/gold/jobs` with a body containing `geometry`,
`mobility`, `salt_mM`, `temperature_K`, `water_loading_scale`, `steps`, `timestep_fs`.
It prepares and records a queued job; it never starts or rents compute.
`GET /api/md/gold/model` reports capabilities. `POST
/api/md/gold/jobs/{id}/continue` accepts `{"steps":10000}`. Start the queued
continuation through the ordinary Start endpoint.

Two retained native managed jobs are `0bcd9bb6d615` (particle, including continuation)
and `9f384731c944` (planar). Resolve their package paths through `MdJob.load` /
`package_dir`, including after archival. No source DNA design is required or altered.
Gold's application sidebar/preset integration and special rendering are pending;
JSON recipes are the reusable preparation presets for now. Review the generated
PDB in a molecular viewer or the saved packing plots.

`namd_gold_package.export_package(package, new_zip)` writes a package with relative
paths and pinned input hashes, excluding output trajectories. Actual remote launch
is deliberately rejected until gold-specific runtime/restart qualification occurs.
Changing a generic job's settings or spawning ordinary production from gold jobs is
also rejected. These controls prevent loss of the model or slab correction.

## Independent checks

```bash
just test-file tests/test_gold_interfaces.py
just test-file tests/test_namd_gold_job.py
just test-file tests/test_namd_gold_api.py
uv run python -m experiments.gold_interfaces.pair_probe workspace/new_pair_probe \
  --binary /path/to/qualified/namd3
uv run python -m experiments.gold_interfaces.restart_probe workspace/my_gold_slab \
  --binary /path/to/qualified/namd3
```

The restart probe defaults to a completed `equilibrate` prefix and compares 40
uninterrupted NVE steps with 20+20 split steps. `--source`, `--tag` and `--dt`
select a checkpoint, fresh output prefix and timestep. It reports differences and
the historical 1e-4 comparison without using that unvalidated threshold as a
physical pass/fail gate. Native failures and invalid checkpoints still raise errors.
New restart configurations use `COMmotion yes` to preserve saved momentum;
previously saved configurations are not rewritten. See the
[restart diagnosis](../../workspace/gold_restart_diagnosis_20260915/RESULTS.md)
for causal controls, repeated-run variability and literature-based NVE checks.
The pair probe neutralizes the partner only to isolate LJ; real packages retain the
reviewed TIP3P/CUFIX charges. Raw NAMD forces are compared against an independent
analytic expression; energies are assessed at the precision printed in the log.

The earlier `controls.py` records the intermediate migration-enabled experiment.
It refuses to overwrite failed runs. Use the individual native commands with new
prefixes for subsequent controls; failures are evidence, not reusable seeds.
