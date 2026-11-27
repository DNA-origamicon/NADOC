# Equilibrium Tm research tools (experimental)

No production integration or certified precision. Read the retained protocol and
results under `docs/benchmarks/equilibrium_tm_20261121/` before use.

`proposals.py` adapts the existing bounded VMMC benchmark. It adds adjustable
translation/rotation/cluster-cap proposals, four-walker umbrella training, and an
optional native minimum-base-site-distance coordinate. It preserves DNA2,
sequence-dependent interactions, salt, box, and the periodic-image/energy guards.
It copies existing native exports unchanged; it authors no NADOC documents.
The additional order parameter is sampling metadata, not a molecular transform.

```sh
uv run python -m tools.oxdna_tm_research.proposals \
  --job-dir EXISTING_JOB --unbound-conf EXISTING_UNBOUND_DAT \
  --binary PERIODIC_SAFE_OXDNA --output NEW_DIRECTORY \
  --translation .5 --rotation 1 --maxclust 12 \
  --distance-split 1 --training-walkers 4 --tuning-rounds 8 \
  --equil-steps 200000 --block-steps 1000000 --blocks 1 \
  --cadence 1000 --seed 611100 --minutes 12 --target-halfwidth 1
```

The default stopping rule is fixed-budget. Native-histogram precision checks are
provisional because extrapolation omits temperature-dependent electrostatics.
Never certify a result from these checkpoints. Full-Hamiltonian postprocessing:

```sh
uv run python -m tools.oxdna_tm_research.pairing CAMPAIGN \
  --binary MATCHING_DNANALYSIS --output CAMPAIGN/pairing_audit
uv run python -m tools.oxdna_tm_research.analyze CAMPAIGN \
  --binary MATCHING_DNANALYSIS
```

`analyze` reevaluates saved production frames at 41 temperatures, checks source
energies against sampling output, verifies that the temperature-energy change is
accounted for by stacking plus electrostatics, removes the exact frozen bias,
and applies the finite-size heterodimer correction. It reports importance-weight
ESS (not independent sample count), autocorrelation, endpoint round trips,
replica/start disagreement and time-batch intervals. The all-pair audit checks
native-pair counts and optionally quantifies the effect of including non-native
interstrand bonds in the binding definition. Compact time-resolved sufficient
statistics are retained for independent statistical reanalysis after raw pruning.

The two-dimensional histogram helper sums both distance bins at q=0. Weights
are indexed q + 9*d for this 8-bp system. The minimum distance is over the eight
native partner pairs, measured between base sites with native PBC handling.
The split used here is 1 oxDNA length unit. Far states with q>0 must have zero
counts; the trainer refuses otherwise. No implicit truncation of occupied states.
This coordinate is not strand center-of-mass distance.

`nearest_neighbor.py` is a separate undamaged-DNA empirical calculation using
SantaLucia 1998, Table 2 and the entropy salt correction. It does not estimate
DNA2 equilibrium or supply CPD parameters. `calibration.py` stress-tests the
interval procedure against synthetic persistent two-state chains with known Tm;
it does not validate molecular coverage. `compare.py` summarizes recorded states.
The two orchestration scripts reproduce this workstation's exploratory sequence;
use the parameterized CLI above on another machine.

Local dependencies include the uncommitted prior research modules
`backend/core/oxdna_vmmc.py`, `backend/core/oxdna_vmmc_precision.py`, and
`tools/oxdna_umbrella/native.py`. Exact hashes and source snapshots accompany the
retained metrics. The installed engine is used read-only. A clean checkout must
not assume deleted hybrid binaries or historical absolute paths are present.
