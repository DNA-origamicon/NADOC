# Exp28: Hierarchical Coarse Tube CG

Goal: simulate massive DNA-origami tubes at the coarsest representation that
still preserves source-design identity for later atomistic reconstruction.

This is intentionally experiment-local.  The whole tube is not flattened into
one `Design`; each origami unit is a symbolic repeated instance with:

- source `.nadoc`
- ring/unit repeat indices
- 4x4 world transform
- named coarse connector/site positions

Only selected reconstruction windows are expanded into normal NADOC designs.

## Run

```bash
python experiments/exp28_hierarchical_tube_cg/scripts/run_hierarchical_tube.py \
  --spec experiments/exp28_hierarchical_tube_cg/tube_spec.example.json \
  --out-dir experiments/exp28_hierarchical_tube_cg/results/example \
  --perturb-nm 1.0
```

For a large symbolic-only smoke run:

```bash
python experiments/exp28_hierarchical_tube_cg/scripts/run_hierarchical_tube.py \
  --spec experiments/exp28_hierarchical_tube_cg/tube_spec.micron_symbolic.json \
  --out-dir experiments/exp28_hierarchical_tube_cg/results/large_symbolic \
  --no-reconstruct
```

## Outputs

- `tube_spec.resolved.json` — spec after defaults and overrides.
- `relaxed_instances.json` — symbolic instances and final transforms.
- `cg_trajectory.json` — coarse center trajectory and restraint energies.
- `shape_report.json` — closure, clash, and energy summary.
- `reconstruction_manifest.json` — selected window and identity lineage.
- `window_atomistic/` — optional expanded `.nadoc`, PDB/PSF, identity maps,
  and atomistic diagnostics for the selected window.

## Scope

v1 targets shape relaxation, not assembly kinetics or whole-tube atomistic MD.
mrDNA remains a local refinement layer for selected windows rather than the
primary whole-tube simulator.
