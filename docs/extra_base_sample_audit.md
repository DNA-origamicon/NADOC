# Extra-Base Trajectory Sample Audit

## Purpose

Open **Help → Extra-Base Metrics Audit** to inspect real extra-base observations from a
processed trajectory. The top **Actual trajectory sample viewer** is the trajectory debug
surface; the older Molecular Placement Audit remains the A/B review surface for generated
placement geometry.

The sample viewer supports:

- any registered design and trajectory source;
- a suggested population medoid or any sampled DCD frame;
- one or many crossover IDs, selected from a multi-select list;
- automatic inclusion of each selected crossover's adjacent reciprocal partner; and
- atomistic or schematic rendering with orbit, pan, zoom, and camera reset.

Unrelated crossover pairs are intentionally rendered in separate cards. Each card has its
own crossover-local canonical frame, so placing unrelated sites in one scene would imply a
global spatial alignment that is not present in the metric contract.

## Coordinate and molecular contract

Every pose uses the same right-handed canonical helix-pair frame as the extra-base metrics:

1. **X — interhelix:** lower fixed helix ID to higher fixed helix ID;
2. **Y — helix axis:** increasing base-pair index, orthogonalized against X; and
3. **Z — out of plane:** `X × Y`.

Reciprocal lower-bp `i` and higher-bp `i+1` records therefore share one frame without a
presentation-time fit. The arrows are the chemically directed slab-face normals. Their
reported separation is the ordinary 0–180° angle between directed normals.

The selected frame's P, C5′, C3′, C1′, and base-center anchors are measured trajectory
coordinates. NADOC's residue template is rigid-fit to those anchors to provide the remaining
heavy atoms; the card reports that anchor-fit RMSD. This is an actual measured pose with a
clearly identified atomistic reconstruction, not a population-average molecule. Source and
destination pairing distances, linker bonds, and whole-design paired fraction are returned as
frame-quality context.

The DCD-frame number control snaps to the nearest frame present in the metric dump. The readout
always shows both the internal sample index and resolved DCD frame, which avoids confusing a
stride-sampled index with a trajectory frame number.

## Registering another design or trajectory

The viewer discovers files named `<design>__<role>__metrics.json` in:

`experiments/exp53_extra_base_state_refinement/results/`

The source must be an observable dump emitted by `xb_observables.py`, and its recorded job must
still contain `design.json`. A state-analysis companion is optional: metrics-only files appear in
the source dropdown immediately, while a `<design>__<role>__states.json` companion adds suggested
population-medoid presets and the population panels below the viewer.

For an ad hoc NAMD job:

```bash
uv run python experiments/exp46_xb_placement/xb_observables.py \
  --job /absolute/path/to/job \
  --dcd /absolute/path/to/production.dcd \
  --stride 20 \
  --out experiments/exp53_extra_base_state_refinement/results/my_design__my_run__metrics.json
```

For a permanent archive source, add the job to
`experiments/exp53_extra_base_state_refinement/inventory.json` and use the refresh workflow:

```bash
uv run python experiments/exp53_extra_base_state_refinement/refresh.py all
```

The Help audit is read-only. Browser requests carry only a registered `source_id`, crossover IDs,
and frame selection; they cannot supply an arbitrary server filesystem path.

## API contract

- `GET /api/design/extra-base-sample-audit/catalog?source_id=...` returns sampled frames,
  crossover metadata, reciprocal partners, and optional medoid suggestions.
- `POST /api/design/extra-base-sample-audit` accepts `source_id`, `crossover_ids`, either
  `sample_index` or `frame`, and `include_reciprocal_partners`.

The response schemas are `nadoc.extra-base-sample-catalog.v1` and
`nadoc.extra-base-sample-audit.v1`. The backend keeps at most two parsed metric dumps in memory,
keyed by path size and modification time, so switching among very large sources remains bounded.

## Validation

- `tests/test_extra_base_sample_audit.py` pins catalog discovery, exact and nearest-frame
  selection, reciprocal partner expansion, canonical atomistic poses, and path-safe routes.
- `tests/test_extra_base_metrics_audit.py` verifies metrics-only source discovery without eagerly
  parsing large dumps.
- `frontend/src/ui/extra_base_metrics_audit.test.js` pins suggested presets, exact DCD-frame
  selection, multi-crossover requests, viewer mounting, representation changes, and cleanup.
- `frontend/src/ui/extra_base_cluster_viewer.test.js` pins real-pose scene construction and
  directed-normal arrows.
