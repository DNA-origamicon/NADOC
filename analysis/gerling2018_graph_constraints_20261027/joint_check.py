"""Check all graph-supported whole routes jointly; do not optimize coverage."""
import os
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
import json
import itertools
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_array

OUT = Path(__file__).resolve().parent


def main():
    candidates = json.loads((OUT / "graph_constrained_candidates.json").read_text())
    groups = defaultdict(list)
    for i, c in enumerate(candidates):
        groups[c["published_id"]].append(i)
    row, col, data, low, high = [], [], [], [], []

    def constraint(variables, lower, upper):
        r = len(low)
        low.append(lower)
        high.append(upper)
        for i in variables:
            row.append(r)
            col.append(i)
            data.append(1.)

    for indices in groups.values():
        constraint(indices, 1., 1.)
    occupants = defaultdict(list)
    for i, c in enumerate(candidates):
        for b in c["base_i53"]:
            if b >= 0:
                occupants[b].append(i)
    for indices in occupants.values():
        if len(indices) > 1:
            constraint(indices, 0., 1.)
    matrix = coo_array((np.array(data), (np.array(row, dtype=np.int32), np.array(col, dtype=np.int32))),
                       shape=(len(low), len(candidates))).tocsc()
    common = dict(c=np.zeros(len(candidates)), integrality=np.ones(len(candidates), dtype=np.int32),
                  constraints=LinearConstraint(matrix, low, high), options={"time_limit": 30})
    result = milp(bounds=Bounds(0, 1), **common)
    assert result.status in (0, 2), result.message
    report = {"all_11_staples_simultaneously_feasible": result.status == 0,
              "status": int(result.status), "message": result.message}
    if result.status == 2:
        ids = list(groups)

        def test_subset(subset):
            lower = np.array(low)
            upper = np.array(high)
            for r, sid in enumerate(ids):
                lower[r] = upper[r] = float(sid in subset)
            args = {**common, "constraints": LinearConstraint(matrix, lower, upper)}
            answer = milp(bounds=Bounds(0, 1), **args)
            assert answer.status in (0, 2), answer.message
            return answer.status == 0

        bad_pairs = [pair for pair in itertools.combinations(ids, 2) if not test_subset(pair)]
        core = ids.copy()
        for sid in ids:
            reduced = [s for s in core if s != sid]
            if not test_subset(reduced):
                core = reduced
        lower = np.array(low)
        lower[:len(ids)] = 0
        relaxed = milp(**{**common, "c": -np.ones(len(candidates)),
                          "bounds": Bounds(0, 1),
                          "constraints": LinearConstraint(matrix, lower, high)})
        assert relaxed.status == 0, relaxed.message
        unique = [candidates[indices[0]] for indices in groups.values() if len(indices) == 1]
        used = [b for c in unique for b in c["base_i53"] if b >= 0]
        report.update(pairwise_conflicts=bad_pairs, one_minimal_conflict_set=core,
                      maximum_jointly_placeable_staples=int(round(-relaxed.fun)),
                      individually_unique_staples=[c["published_id"] for c in unique],
                      individually_unique_jointly_nonoverlapping=len(used) == len(set(used)),
                      individually_unique_added_nt=len(set(used)))
        conflict_bases = []
        for a, b in bad_pairs:
            # Coordinates used by every alternative of both conflicting oligos.
            a_always = set.intersection(*[{p for p in candidates[i]["base_i53"] if p >= 0} for i in groups[a]])
            b_always = set.intersection(*[{p for p in candidates[i]["base_i53"] if p >= 0} for i in groups[b]])
            conflict_bases.append({"staples": [a, b], "necessarily_shared_scaffold_positions": sorted(a_always & b_always)})
        report["conflict_details"] = conflict_bases
        (OUT / "conditional_unique_routes.json").write_text(json.dumps(unique, indent=2)+"\n")
    if result.status == 0:
        feasible, excluded = [], []
        for i, c in enumerate(candidates):
            bounds = np.zeros(len(candidates))
            bounds[i] = 1
            answer = milp(bounds=Bounds(bounds, 1), **common)
            assert answer.status in (0, 2), answer.message
            (feasible if answer.status == 0 else excluded).append(i)
        survivors = [candidates[i] for i in feasible]
        grouped = defaultdict(list)
        for c in survivors:
            grouped[c["published_id"]].append(c)
        forced = [v[0] for v in grouped.values() if len(v) == 1]
        occupied = [b for c in forced for b in c["base_i53"] if b >= 0]
        assert len(set(occupied)) == len(occupied)
        report.update(feasible_routes=len(survivors), eliminated_routes=len(excluded),
                      conditional_unique_staples=[c["published_id"] for c in forced],
                      conditional_unique_added_nt=len(occupied),
                      remaining_routes_by_staple={k: len(v) for k, v in grouped.items()})
        (OUT / "joint_feasible_candidates.json").write_text(json.dumps(survivors, indent=2)+"\n")
        (OUT / "conditional_unique_routes.json").write_text(json.dumps(forced, indent=2)+"\n")
    (OUT / "joint_check_summary.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
