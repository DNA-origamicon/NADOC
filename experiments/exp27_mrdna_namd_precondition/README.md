# Exp27: mrDNA Coarse Preconditioning for NAMD Starts

Goal: test whether mrDNA coarse-grained relaxation can provide better
per-nucleotide starting positions for a topology-preserving atomistic rebuild
before NAMD minimization/warmup.

Scope flag:

- `no_crossover_extrabases_only`
- The default workflow refuses designs that contain explicit crossover
  `extra_bases`.
- This is intentional. Designs with user-controlled thymine/linker bases need a
  separate validation path where those bases are represented in both mrDNA and
  atomistic maps. The scripts must not add hidden bases.

Primary script:

```bash
python experiments/exp27_mrdna_namd_precondition/scripts/mrdna_coarse_to_namd.py \
  --design workspace/B_tube.nadoc \
  --out-dir experiments/exp27_mrdna_namd_precondition/results/B_tube_coarse_test \
  --stem B_tube_mrdna_coarse \
  --mrdna-steps 100000
```

Useful dry/zero-step check:

```bash
python experiments/exp27_mrdna_namd_precondition/scripts/mrdna_coarse_to_namd.py \
  --design workspace/B_tube.nadoc \
  --out-dir experiments/exp27_mrdna_namd_precondition/results/B_tube_zero_step \
  --stem B_tube_zero \
  --mrdna-dry-run \
  --mrdna-steps 0
```

Expected outputs:

- `precondition_report.json`
- `{stem}.pdb`
- `{stem}.psf`
- `{stem}.identity.json/.tsv`
- `{stem}.design_maps.json`
- `{stem}.basepairs.json/.tsv`
- `{stem}.stacking.json/.tsv`
- `restraints/*.extrabonds`
- `namd_gbis_smoke.conf`
- `mrdna/` raw mrDNA outputs

Environment note:

The current local runtime imports `mrdna` from the editable checkout
`/home/jojo/Work/mrdna-tool`. Set `MRDNA_TOOL_PATH` to use a different checkout.

Evaluation:

```bash
python experiments/exp27_mrdna_namd_precondition/scripts/evaluate_mrdna_preconditioning.py \
  --design workspace/B_tube.nadoc \
  --psf experiments/exp27_mrdna_namd_precondition/results/B_tube_coarse_1k/mrdna/B_tube_mrdna_coarse_1k.psf \
  --dcd experiments/exp27_mrdna_namd_precondition/results/B_tube_coarse_1k/mrdna/output/B_tube_mrdna_coarse_1k.dcd \
  --out-json experiments/exp27_mrdna_namd_precondition/results/B_tube_coarse_1k/evaluation.json
```

Current conclusion from the 2026-05-21 B-tube test:

- mrDNA coarse preconditioning runs and covers all 24 helices.
- It generated 12,802 override entries after excluding 1,618 crossover endpoint
  keys.
- It did not reduce the all-atom covalent bond outliers:
  raw max bond = 0.3634 nm, mrDNA-preconditioned max bond = 0.3634 nm;
  raw bonds >0.30 nm = 104, mrDNA-preconditioned bonds >0.30 nm = 104.
- A 20-step NAMD GBIS minimization startup completed, but reported thousands
  of bad-contact atoms initially and extremely high VDW energy. This is not a
  production-ready unrestrained start.

Interpretation:

mrDNA is useful as a coarse geometry/helix-path stage, but the current direct
crossover B-tube failure is dominated by atomistic crossover endpoint and local
sugar-phosphate strain. Coarse helix relaxation alone is therefore not the full
solution for preparing full B-tube NAMD production runs.
