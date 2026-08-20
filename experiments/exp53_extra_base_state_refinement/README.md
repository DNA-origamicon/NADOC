# exp53 — Extra-base dominant-state refinement

This experiment turns the archived 2-helix extra-base trajectories into a refreshable
evidence set for **where extra bases prefer to be**.  It deliberately excludes
`24hb_1xT`; large-bundle trajectories belong to the lattice-spacing study, not this
junction-local state analysis.

The pipeline is split in two:

1. `extract` reads a DCD and writes the multi-metric per-frame records already defined by
   exp46 (`t`, hop-referenced bow, fixed-axis coordinates, base pose, stacking, partner
   clearance, backbone bonds, pairing, and global paired fraction).
2. `analyse` filters invalid frames, finds contiguous stable windows, clusters three
   independently useful metric panels, and reports populations/transitions only when the
   resulting states recur.  Re-analysis never rereads a DCD.

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
- Each insert is clustered separately. A pooled, hop-referenced comparison can be added
  later without erasing crossover-specific asymmetry.
- Static ring-piercing validation is a hard prerequisite for scientific use. The refresh
  command records it separately from dynamic frame filtering.
