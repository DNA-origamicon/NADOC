# exp53 — Extra-base dominant-state refinement

This experiment turns archived extra-base trajectories into a refreshable evidence set
for **where extra bases prefer to be**.  Alongside the controlled 2-helix systems, the
`24hb_1xT` large-bundle ensemble supplies many simultaneously sampled junctions for the
same junction-local state analysis.  Whole-bundle lattice motion is removed by the
per-junction, hop-referenced coordinates before clustering.

The pipeline is split in two:

1. `extract` reads a DCD and writes the multi-metric per-frame records already defined by
   exp46 (`t`, hop-referenced bow, fixed-axis coordinates, base pose, stacking, partner
   clearance, backbone bonds, pairing, and global paired fraction).
2. `analyse` filters invalid frames, finds contiguous stable windows, clusters three
   independently useful per-site metric panels, then pools canonical C1′ positions by
   reciprocal Holliday-junction side. Re-analysis never rereads a DCD.

Run everything currently available:

```bash
uv run python experiments/exp53_extra_base_state_refinement/refresh.py all
```

Or update one stage:

```bash
uv run python experiments/exp53_extra_base_state_refinement/refresh.py inventory
uv run python experiments/exp53_extra_base_state_refinement/refresh.py extract --part 2hb_0-1xT
uv run python experiments/exp53_extra_base_state_refinement/refresh.py analyse
```

Outputs live in the ignored `results/` directory. `inventory.json` is the durable source
registry. Add a new stored job there and rerun `all`; existing extractions are reused when
the DCD size and modification time have not changed.

## Interpretation contract

- A frame is valid only when global pairing, local flanking pairing, both linker bonds,
  and rigid-template fit pass their thresholds.
- A stable window is a contiguous valid run, not a hand-selected time interval.
- Populations are reported only for recurrent `switching` states. A one-way split is
  labelled `drift`; its frame fractions are not equilibrium populations.
- The primary state panel is hop-position. Pose/orientation and environment panels are
  independent validation metrics. Agreement is reported with adjusted Rand index (ARI).
- Per-insert analyses remain in the state artifact as provenance. For the compact Help
  audit, stable positions are pooled in the canonical helix-pair frame and separated into
  lower-bp `i`/left and adjacent higher-bp `i+1`/right ensembles. Inserts without a
  reciprocal crossover one bp away are counted and excluded rather than guessed into a
  side.
- Pooled fitting uses an evenly interleaved, deterministic cap of 2,500 observations per
  side. A cluster's displayed nucleotide is an actual trajectory medoid with its measured
  helix spacing and reconstructed P–C5′–C3′–C1′–base pose; it is not an averaged molecule.
- The optional atomistic view fits NADOC's heavy-atom residue template to the medoid's
  measured P, C5′, C3′, C1′ and base-center anchors. This explicitly reconstructs the
  deoxyribose C1′–C2′–C3′–C4′–O4′ ring; the payload labels measured versus fitted atoms
  and reports the anchor-fit RMSD.
- The combined audit panel places selected `i` and `i+1` medoids directly into one
  canonical helix-pair frame. It applies no medoid-to-medoid alignment and reports the
  C1′ displacement vector, so apparent relative position and orientation remain measured
  quantities rather than presentation artifacts.
- Static ring-piercing validation is a hard prerequisite for scientific use. The refresh
  command records it separately from dynamic frame filtering.
