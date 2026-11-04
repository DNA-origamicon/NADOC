# Experimental scaffold sequence start

Help → Experimental → Scaffold sequence start evaluates the Aksel fixed-route
register model. The scaffold is **circular**. Its displayed nick is only the
sequence origin; it neither interrupts a duplex nor adds a loop-closure cost.
Staple routes and all crossovers remain fixed. Apply rotates scaffold domain
order, keeps the circular source sequence, and regenerates complementary staples.
The operation has feature history and Undo. A document identity and input-content
fingerprint are checked under the mutation lock; background view/history updates
can advance the general revision without invalidating the scored input.

## Distilled scoring algorithm

For each staple, at temperature T in kelvin:

```
G = G_bind + sum(G_loop) + sum(G_hyb)
G_bind = -R T ln(C_staple - C_scaffold/2)
G_hyb = H_NN - T S_NN
log(p) = -logaddexp(0, G/(R T))
Q = sum_staples(log(p)) / total_paired_nt
```

Higher Q is better. This is not an experimental yield predictor. Hybridization
uses SantaLucia–Hicks **2004** nearest-neighbor parameters, initiation and terminal
A/T corrections. The Dunn salt entropy correction is
`0.368 (L-1) ln(0.5 [Tris] + 3.3 sqrt([Mg]))` cal/(mol K); concentrations are molar.
Defaults match the authors' implementation: 50 °C, 10 nM scaffold, 100 nM staples,
12.5 mM Mg and 40 mM Tris.

Between consecutive duplex domains on each staple, take the shorter circular
scaffold distance d between their midpoints. Use contour length `L = 0.6 d` nm,
persistence length 0.9 nm, and
`r² = 1.8 L [1 - (0.9/L)(1-exp(-L/0.9))]`. Then
`C_eff = (3/(2π r² 10^-18))^(3/2) / (6.02×10^23 × 1000)` M and
`G_loop = -RT ln(C_eff)`.

Sources: [Aksel et al., PNAS 2024](https://doi.org/10.1073/pnas.2406769121),
[reference scoring implementation](https://github.com/douglaslab/pyOrigamiBreak/blob/main/autobreak/autobreak.py),
[reference thermodynamic utilities](https://github.com/douglaslab/pyOrigamiBreak/blob/main/autobreak/utilities.py).

The authors' code rounds domain midpoints to integer coordinates. NADOC retains
exact half-integer midpoints, avoiding a coordinate-origin-dependent rounding
artifact. It also unwraps domains crossing the symbolic origin, keeps scaffold
index zero, and uses stable log probabilities. Therefore this reproduces the
energy model, not every indexing/rounding artifact of the upstream CAD adapter.

## Acceleration

Scaffold distance, duplex lengths and binding concentration do not change over
registers. Compute these once. Encode the circular scaffold's nearest-neighbor
energies and prefix sums over two copies. For each duplex, NumPy gathers the
energy of its interval for **all N registers** using two prefix lookups plus
terminal corrections. Accumulate one N-element array per staple, then its log
probabilities into a global array. No per-register design copies, sequence
assignment, shortest-path search, JIT compilation, GPU or worker pool are needed.

Complexity is O(N × duplex_count), with O(N) scoring scratch storage. This removes
the duplex-length factor and Python loop over offsets of literal enumeration.
NumPy CPU results already meet the few-second target, so multiprocessing/GPU
transfer and startup costs have no demonstrated benefit here.

## Supported inputs and interpretation

- One active, fully sequenced scaffold; unknown bases and known truncated
  biological scaffold sources fail with an explanation. Explicit custom sources
  must match the represented length. A stored sequence of unknown provenance is
  treated as the complete circular sequence; the report states its length.
- The existing symbolic start must be an adjacent, co-linear pair on one helix.
  Candidate starts are ordinary scaffold bonds; crossover bonds and insert/skip
  sites are not offered as symbolic nick positions in this first implementation.
  The numerical kernel still evaluates all N registers.
- Unpaired scaffold insertions and skips contribute actual nucleotides; paired
  insertions are rejected until their antiparallel sequence mapping is supported.
  Duplex runs merge across the
  symbolic origin, and split at real changes of pairing continuity or helix.
- Terminal unpaired staple bases are excluded and counted in the report.
  Internal unpaired staple bridges, overlapping pairing and multiple active
  scaffolds are rejected. Off-target interactions and cooperative folding are
  outside this model. Reference strands and other strand types are preserved.
- At route nucleotide i, a start moved forward by c uses source base
  `S[(i-c) mod N]`. Thus its register offset is `(-c) mod N` relative to the
  current assignment. Near-ties within 10^-12 retain the current origin.

## Validation and timing

Tests compare every offset against literal sequence enumeration at 20, 50 and
90 °C; preserve duplex domains through origin changes; verify apply/rescore,
topology preservation, stale-result rejection, invalid input and Undo. UI tests
cover evaluation, application, condition changes and errors.

On 2026-11-03, three local 7,249–7,560-nt designs with 204–213 staples took about
0.06–0.07 s each for mapping, sweep and ranking. Applied results reproduced their
predicted Q exactly. At three registers per design, evaluation using the authors'
thermodynamic utilities (with exact circular midpoints) differed by <2×10^-14.
These are local CPU timings, not a promise for arbitrary design sizes or UI loads.

Reproduce the benchmark without changing source designs:

```sh
.venv/bin/python -m scripts.benchmark_scaffold_register \
  workspace/VoltronCore.nadoc workspace/VoltronCoreScad.nadoc \
  workspace/Gerling2018_FigS1_p7560_LOOP_OVERHANGS_WITH_EXTRA_T.nadoc
```
