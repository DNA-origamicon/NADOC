"""Validate and present the graph-constraint diagnostic, without promoting a map."""
import csv
import hashlib
import json
from collections import Counter

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch

from analyze import ROOT, OUT, PREVIOUS, COMP, N, hits, jumps, partner


def main():
    audit = json.loads((OUT / "audit_summary.json").read_text())
    enumeration = json.loads((OUT / "graph_enumeration_summary.json").read_text())
    joint = json.loads((OUT / "joint_check_summary.json").read_text())
    source = PREVIOUS / "42hb13_best_contactmap.json"
    st, sc, _ = json.loads(source.read_text())
    reference = json.loads((ROOT / "backend/data/gerling2018_42hb13.json").read_text())["sequences"]
    candidates = json.loads((OUT / "graph_constrained_candidates.json").read_text())
    counts = Counter(c["published_id"] for c in candidates)
    for c in candidates:
        q = reference[c["reference_index"]]["sequence"]
        mapping = c["base_i53"]
        assert c["annotated_sequence"].replace("*", "") == q
        used = [b for b in mapping if b >= 0]
        assert len(used) == len(set(used))
        assert all(sc[str(b)]["staple_id"] < 0 for b in used)
        assert all(q[i] == COMP[b] for i, b in enumerate(mapping) if b >= 0)
        assert all(q[i] == "T" for i, b in enumerate(mapping) if b < 0)
    for r in csv.DictReader((OUT / "predicted_partner_matches.csv").open()):
        q = next(row["sequence"] for row in reference if row["index"] == int(r["candidate_published_id"]))
        t, u, v = int(r["TT_start_1based"])-1, int(r["expected_from"]), int(r["expected_to"])
        assert partner((int(r["source_from"]), int(r["source_to"]))) == (u, v)
        assert q[t:t+2] == "TT"
        for k in range(int(r["left_exact_free_nt"])):
            assert q[t-1-k] == COMP[(u+k) % N] and sc[str((u+k) % N)]["staple_id"] < 0
        for k in range(int(r["right_exact_free_nt"])):
            assert q[t+2+k] == COMP[(v-k) % N] and sc[str((v-k) % N)]["staple_id"] < 0
    # Validate the orientation rule and exclude inline loops from crossover counts.
    assert partner((20, 100)) == (101, 19)
    assert partner(partner((N-1, N-2))) == (N-1, N-2)
    assert jumps([20, 19, -1, -1, 18, 17]) == []
    assert len(jumps([20, 19, -1, -1, 100, 99])) == 1
    assert hashlib.sha256(source.read_bytes()).hexdigest() == audit["source_contactmap_sha256"]
    unique = [c for c in candidates if counts[c["published_id"]] == 1]
    rows = [{"published_id": c["published_id"], "paired_nt": c["paired_nt"],
             "matched_existing_junctions": len(c["closes_existing_junctions"]),
             "annotation": c["annotated_sequence"],
             "status": "conditional unique in tested route model; not a confirmed reconstruction"}
            for c in unique]
    with (OUT / "conditional_unique_staples.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    repeated = []
    for route in hits("CATTACC"):
        repeated.append({"first_scaffold_base_0based": route[0], "last_scaffold_base_0based": route[-1],
                         "occupied_by_published_ids": sorted({reference[sc[str(b)]["staple_id"]]["index"]
                                                             for b in route if sc[str(b)]["staple_id"] >= 0}),
                         "occupied_bases": sum(sc[str(b)]["staple_id"] >= 0 for b in route)})
    validation = {"all_candidate_sequences_exact": True, "all_candidates_nonoverlapping_with_fixed_map": True,
                  "all_local_predictions_rechecked": True, "source_map_unchanged": True,
                  "CATTACC_sites": repeated, "candidates_checked": len(candidates)}
    (OUT / "validation.json").write_text(json.dumps(validation, indent=2)+"\n")

    fig, ax = plt.subplots(figsize=(11, 6), layout="constrained")
    ax.set(xlim=(0, 10), ylim=(0, 6))
    ax.axis("off")

    def box(x, y, label, color="#eaf1f5"):
        ax.text(x, y, label, ha="center", va="center", fontsize=11,
                bbox={"boxstyle": "round,pad=.65", "facecolor": color, "edgecolor": "#78909c"})

    def arrow(x1, y1, x2, y2, color="#526d82", style="-"):
        ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="->", mutation_scale=13,
                                    color=color, linewidth=1.6, linestyle=style))

    ax.text(5, 5.65, "A graph constraint exposes a conflicting placement", ha="center",
            fontsize=16, fontweight="bold")
    box(1.7, 4.4, "Staples 125 + 213\nreciprocal junction evidence")
    box(5, 4.4, "Staple 147")
    box(8.4, 4.4, "p7560: 5236–5242\nCATTACC", "#dceee2")
    box(5, 2.7, "Staple 111\nsame repeated domain")
    box(8.4, 2.7, "p7560: 4390–4396\n4 of 7 bases occupied by 92", "#fae6cc")
    box(8.4, 1.0, "p7560: 2779–2785\noccupied by 177 + 199", "#fae6cc")
    arrow(3.25, 4.4, 4.35, 4.4)
    arrow(5.65, 4.4, 7.3, 4.4)
    arrow(5.7, 3.05, 7.3, 4.1, "#b54a4a")
    ax.text(6.8, 3.5, "conflict", fontsize=10, color="#b54a4a")
    arrow(5.75, 2.7, 7.05, 2.7, "#b27c30", "--")
    arrow(5.6, 2.3, 7.05, 1.25, "#b27c30", "--")
    ax.text(2.3, 1.45, "Revisit the blocking routes\nand the assumed junctions.\nDo not assign both staples\nto the same scaffold bases.",
            ha="center", va="center", fontsize=11, color="#33475b", linespacing=1.5)
    ax.text(5, .15, "Scaffold coordinates are 0-based. This is a constraint diagram, not physical helix geometry.",
            ha="center", fontsize=9, color="#536275")
    for suffix in ("png", "svg"):
        fig.savefig(OUT / f"conflict_example.{suffix}", dpi=160)
    plt.close(fig)
    report = """GERLING2018 42hb (1)–(3): RECIPROCAL-CROSSOVER CONSTRAINT DIAGNOSTIC
2026-10-27

RESULT: graph constraints provide useful local assignments, but also expose a
conflict that cannot be resolved by treating the existing 80.3% as fixed truth.
No source NADOC design, selected REVNANO map, or approved annotations changed.
No new REVNANO run was performed. This is a separate diagnostic candidate model.

CURRENT MAP
176/213 whole staples; 6071/7560 scaffold bases. There are 395 staple jumps
between nonconsecutive scaffold positions. 218 jumps form 109 reciprocal pairs.
Of the remaining jumps, 94 have both predicted partner endpoints free, 46 have
one endpoint occupied, and 37 have both occupied by other connections.
Inline loopouts on consecutive scaffold positions are not counted as crossovers.

PARTNER RULE
If a staple jumps from scaffold position x to y, a full reciprocal junction
predicts an opposite jump from y+1 to x-1, modulo 7560. This assumes those
adjacent scaffold positions belong to the corresponding duplex continuations.
A nick, deliberate half-junction, scaffold junction, deletion/insertion or wrong
route can break the assumption. Missing reciprocity is not automatically an error.

LOCAL SEQUENCE EVIDENCE
Search all 37 unplaced raw oligos for TT with exact scaffold-complementary flanks
at the predicted endpoints, excluding already occupied bases.
47 predicted partners have at least five exact bases on each side, pointing to
25 distinct unplaced oligos. 43 have at least seven on each side, pointing to
22 oligos. Each supported prediction identifies only one unplaced oligo at the
stated threshold. These are local connections, not 22 completed reconstructions.

WHOLE-STRAND CONSTRAINTS
First enumerate the previous annotation pool plus identical placed Stage3
fragment routes, holding the 176 complete staples fixed. This yields 502 whole
routes for 16 unplaced staples. Then impose all seven-base reciprocal predictions
for each supported oligo and expand beyond the annotation pool: all terminal
1T/5T/10T choices and all internal TT masks, with contiguous exact paired blocks
of at least five bases, are considered. Also retain compatible routes from the
first enumeration, which can contain already inferred scaffold-seam splits.
326 routes remain across 11 staples. No enumeration bound was hit.

Five staples have one full route each in this conditional model:
22 (42 paired bases), 61 (40), 98 (35), 147 (49), 209 (40).
These five are mutually nonoverlapping and add 206 bases. They would give 6277
covered bases (83.0%) if accepted. They are NOT promoted as confirmed recovery.
For example, three separate reciprocal junctions constrain all 35 paired bases
of staple 98, through existing staples 49, 34 and 1.

GLOBAL CONFLICT
A binary feasibility check requires one route per candidate oligo and forbids
sharing any scaffold base. All 11 oligos cannot be placed together in this
model; at most 10 can. Every possible route of 111 conflicts with the route of
147 at scaffold positions 5236–5242 (0-based), the repeated domain CATTACC.
An alternative exact CATTACC site at 4390–4396 is partly occupied by current
staple 92 (four bases); the third site at 2779–2785 is occupied by 177 and 199.
This identifies routes to reopen, not proof that 92 alone is incorrect.
All five individually unique candidates fit together, but that does not resolve
the conflict with 111 or establish a unique complete structure.

NEXT SOLVER MODEL
Use trusted long anchors and reciprocal-junction evidence to rank placements.
Allow weak existing routes to move when they block stronger combined evidence.
Solve small connected conflict components jointly: strand order, complementarity,
single occupancy, TT alternatives, paired-junction candidates, and observed
helix adjacency. Prefer 7-base spacing, but allow nicks, scaffold seams and
published exceptions. Report assignments shared by every feasible solution
separately from chosen high-scoring hypotheses. Use the figure's visible helix
labels when assigning geometry; these sequence-only coordinates are not labels.

LIMITS
The route model does not exhaustively enumerate short domains below five bases
or new scaffold-seam splits without TT. Current placements and assumed reciprocal
junctions can be wrong. Thus conditional uniqueness and model infeasibility do
not prove biological uniqueness or impossibility. Coverage alone is not accuracy.
The annotated list has 7459 candidate paired bases, so demanding 7560 paired
bases without revisiting annotations or genuine unpaired scaffold is unjustified.

FILES
crossover_audit.csv: every current jump and expected partner.
predicted_partner_matches.csv: exact local candidates with published staple IDs.
graph_enumeration_summary.json: whole-route count for each supported staple.
joint_check_summary.json: global feasibility and minimal conflicting pair.
conditional_unique_staples.csv / conditional_unique_routes.json: five hypotheses.
conflict_example.png/.svg: why 111/147 requires reopening existing placements.
validation.json: all 326 routes and every local match rechecked; no mismatches,
self-overlap, occupied-base overlap, non-T exclusions or source-map mutation.

REPRODUCE (from repository root)
.venv/bin/python analysis/gerling2018_graph_constraints_20261027/analyze.py
.venv/bin/python analysis/gerling2018_graph_constraints_20261027/enumerate_graph_routes.py
.venv/bin/python analysis/gerling2018_graph_constraints_20261027/joint_check.py
.venv/bin/python analysis/gerling2018_graph_constraints_20261027/report.py

BACKGROUND
REVNANO authors discuss misplaced sequence-consistent staples and using graph
shortest-path outliers, symmetry and junction ambiguity to aid reconstruction:
https://doi.org/10.1016/j.csbj.2023.07.011
AMBIG checks how already reconstructed junctions can shift while preserving
complementarity; it is not a missing-staple completion algorithm:
https://contactmap.readthedocs.io/en/latest/contact2ambig.html
"""
    (OUT / "README.txt").write_text(report)
    print(json.dumps(validation, indent=2))


if __name__ == "__main__":
    main()
