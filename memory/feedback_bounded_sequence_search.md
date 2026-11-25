# Bounded scaffold-register and nick-position searches are authorized

User instruction, 2026-11-25: “bounded sequence searches for scaffold shift and
nick position is a generally allowed operation”.

Agents and agent-less reconstruction code may enumerate bounded candidate
scaffold sequence shifts, traversal directions and nick positions, score them
against supplied sequence evidence, and report matches and ambiguities without
asking for permission solely because the starting register or nick is uncertain.
This clarifies the topology-uncertainty rule in CLAUDE.md: deterministic candidate
search is permitted; do not replace evidence with an agent's unsupported guess.

Keep sequence origin separate from an experimentally established physical nick.
A circular sequence alignment alone does not establish where a molecule was cut.
Report ties, missing partners and sequence discrepancies. This authorization does
not waive native authoring history, publication, or molecular-geometry rules.

## One-base discrepancy and deliberate scaffold loops (2026-11-25)

The user authorizes retaining an off-by-one p7704 reconstruction as a candidate
with a confidence penalty, and treating the observed D009 insertions as possible
deliberate scaffold loops. Infer lengths from sequence evidence; do not hardcode
the reference lengths or assert human error as the established cause. Bounded
loop-length/register searches and explicit +/-1 length hypotheses are allowed.
The implementation uses a transparent 10-point sequence-evidence penalty, not a
calibrated probability. Candidate evidence does not authorize unrecorded topology
changes, physical nick relocation or conversion of loops into strand extensions.
