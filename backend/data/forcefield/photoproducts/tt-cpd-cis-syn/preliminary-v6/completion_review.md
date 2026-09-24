# Overnight CPD benchmark review

**The bounded native/stability benchmark passes.** The array completed 68 half-
nanosecond blocks: 34 ns total, in 7 h 53 min. It stopped cleanly because another
block would not fit the admission margin for the eight-hour wall budget. No
partial block was terminated or counted as validated. CPD/control replica 1
reached 6 ns each; the other four reached 5.5 ns each. All comparisons below use
the common 0–5.5 ns window, with the late window defined as 4.0–5.5 ns.

## Verification

The independent audit verifies all 68 unique admitted keys, 17,000 DCD frames,
expected first/final timesteps and frame spacing, zero native exits, exact restart
source hashes and all analysis input hashes. Configurations contain no additional
minimization, velocity regeneration or positional restraints. Every completed
block passes the recorded numerical, stereochemical, heavy-bond, temperature,
density and image-clearance gates. All sampled image-gap lower bounds exceed
43.60 Å, far beyond the 12 Å direct-space cutoff. Block mean temperatures span
299.05–299.39 K; total mass densities span 1.02434–1.02488 g/mL.

## Structural outcome

| Replica | Additional sampling (ns) | Late whole-DNA RMSD (Å) | Late A6–B15 distance-contact fraction |
|---|---:|---:|---:|
| cpd 1 | 6.0 | 1.59 | 0.927 |
| cpd 2 | 5.5 | 1.70 | 0.897 |
| cpd 3 | 5.5 | 2.97 | 0.191 |
| control 1 | 6.0 | 1.77 | 0.837 |
| control 2 | 5.5 | 1.93 | 0.961 |
| control 3 | 5.5 | 1.82 | 0.891 |

CPD replicas 1 and 2 retain low lesion-local displacement and mostly paired
A6–B15. CPD replica 3 enters a distinct lesion-site state around 4–4.5 ns:

- A6–B15 mean donor–acceptor distances change from 3.01/2.98 Å in 3.5–4 ns
  to 6.66/4.43 Å in 5–5.5 ns. Both contacts are present in 96.8% of frames in
  the earlier block and in none of the frames of the final two blocks.
- The two lesion-base local-fit RMSD rises from about 0.30 Å to 0.65–0.68 Å.
  This metric includes relative base geometry, not only deformation within a ring.
- B15/B16 glycosidic circular means shift from −62.7/−159.0° to −49.2/−77.4°;
  B16 sugar-ring torsions also shift. This is a coupled local conformational event.
- CPD crosslinks remain intact (final-block means about 1.612/1.578 Å),
  and no monitored stereocenter changes sign. Periodic image proximity does not
  explain this transition under the recorded clearance bounds.

The numerical gates deliberately did not prohibit base-pair opening. An opening
in one of three CPD replicas is therefore a substantive structural observation,
not a retroactive numerical failure or proof that parameters are wrong. We have
not established its equilibrium population, reversibility, physical correctness
or a statistically reliable difference from controls. The controls start from
uncrosslinked damaged-crystal coordinates; that starting-state limitation remains.
Control local-site RMSD references the corresponding uncrosslinked bases and
should not be ranked directly against the covalently constrained CPD metric.

## Stopping criterion and next work

The overnight exercise achieved its bounded objective: the candidate works in
native NAMD DNA duplex trajectories without numerical failure or the previous
box/starting-pair defects. It is unnecessary to keep extending all trajectories
until every global RMSD trace looks flat. This benchmark does not justify a claim
that the lesion-site conformational ensemble is converged.

Prioritize inspection of the closed/open CPD 3 states and independent glycosidic/
backbone energetic checks. Determine whether the opened state is an accessible
physical conformation or an overly favorable basin before deciding on parameter
changes. Do not refit bonds/angles solely to suppress this one opening event.
Reversible state sampling or new starts would be appropriate only if an opening
population or free-energy claim is required. General strand-builder integration
and independent energetic validation remain separate work items.

No additional simulations or spending were initiated by this review. Production
readiness remains disabled. The finite-time native/stability benchmark is marked
passed while lesion-site ensemble validation remains pending.

## Evidence and delivery

`overnight_review_audit.json` contains the independent execution audit and balanced
replica summaries. `overnight_review.png` / `.pdf` show 50 ps summaries for clarity;
these bins are not asserted independent. `cpd3_pair_opening.json` contains the
opening distances and circular torsion means. All underlying per-block trajectories,
restarts and `local_diagnostics.json` files are retained. The completion event
successfully resumed the originating agent and its token is acknowledged in
`completion_wake_ack.json`.
