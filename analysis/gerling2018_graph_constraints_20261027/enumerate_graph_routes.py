"""Enumerate whole routes conditional on the seven-base reciprocal predictions.

This expands beyond the previous annotation pool: all 1/5/10T terminal masks
and all internal TT masks are considered, with exact contiguous paired blocks
of at least five bases. Scaffold-seam splits without TT are not exhaustive.
"""
from collections import Counter, defaultdict
import csv
import json

from analyze import ROOT, OUT, PREVIOUS, COMP, N, hits, jumps, partner


def main():
    st, sc, _ = json.loads((PREVIOUS / "42hb13_best_contactmap.json").read_text())
    ref = json.loads((ROOT / "backend/data/gerling2018_42hb13.json").read_text())["sequences"]
    occupied = {int(p) for p, r in sc.items() if r["staple_id"] >= 0}
    old_edges = {(e["from"], e["to"]) for m in st.values() for e in jumps(m["base_i53"])}
    predictions = defaultdict(list)
    for r in csv.DictReader((OUT / "predicted_partner_matches.csv").open()):
        if min(int(r["left_exact_free_nt"]), int(r["right_exact_free_nt"])) >= 7:
            predictions[int(r["candidate_published_id"])].append(r)
    old_candidates = json.loads((OUT / "whole_route_candidates.json").read_text())
    all_candidates, inventory = [], []
    for i, row in enumerate(ref):
        sid, q = row["index"], row["sequence"]
        if sid not in predictions:
            continue
        required = {}
        conflicts = []

        def require(position, value):
            if position in required and required[position] != value:
                conflicts.append((position, required[position], value))
            required[position] = value

        for r in predictions[sid]:
            t, u, v = int(r["TT_start_1based"])-1, int(r["expected_from"]), int(r["expected_to"])
            require(t, -1)
            require(t+1, -1)
            for k in range(7):
                require(t-1-k, (u+k) % N)
                require(t+2+k, (v-k) % N)
        if conflicts:
            inventory.append({"published_id": sid, "anchor_conflicts": conflicts, "whole_routes": 0})
            continue
        for p, b in required.items():
            assert q[p] == (COMP[b] if b >= 0 else "T")
        unique = {}
        nodes = 0

        def record(mapping, text, method):
            m = tuple(mapping)
            assert len(m) == len(q) and text.replace("*", "") == q
            assert all(m[p] == b for p, b in required.items())
            used = [b for b in m if b >= 0]
            assert len(set(used)) == len(used) and not occupied.intersection(used)
            assert all(q[p] == COMP[b] for p, b in enumerate(m) if b >= 0)
            unique[m] = {"published_id": sid, "reference_index": i,
                         "annotated_sequence": text, "base_i53": list(m),
                         "paired_nt": len(used), "method": method,
                         "closes_existing_junctions": [e for e in jumps(m) if partner((e["from"], e["to"])) in old_edges]}

        for left in (1, 5, 10):
            if q[:left] != "T"*left or any(required.get(p, -1) != -1 for p in range(left)):
                continue
            for right in (1, 5, 10):
                end = len(q)-right
                if q[end:] != "T"*right or any(required.get(p, -1) != -1 for p in range(end, len(q))):
                    continue
                mapping = [-1]*len(q)

                def walk(start, used, parts):
                    nonlocal nodes
                    nodes += 1
                    if nodes > 1000000:
                        raise RuntimeError(f"Candidate enumeration exceeded explicit bound for {sid}")
                    for stop in range(start+5, end+1):
                        if stop != end and (q[stop:stop+2] != "TT" or stop+2+5 > end):
                            continue
                        if any(required.get(p, 0) == -1 for p in range(start, stop)):
                            continue
                        if stop != end and any(required.get(p, -1) != -1 for p in range(stop, stop+2)):
                            continue
                        word = q[start:stop]
                        for route in hits(word):
                            if occupied.intersection(route) or used.intersection(route):
                                continue
                            if any(p in required and required[p] != b for p, b in zip(range(start, stop), route)):
                                continue
                            mapping[start:stop] = route
                            if stop == end:
                                record(mapping, "*"+q[:left]+"*"+"".join(parts+[word])+"*"+q[end:]+"*", "all_TT_masks_min5")
                            else:
                                mapping[stop:stop+2] = [-1, -1]
                                walk(stop+2, used.union(route), parts+[word, "*TT*"])
                            mapping[start:stop] = [-1]*(stop-start)

                walk(left, set(), [])
        expanded_count = len(unique)
        for c in old_candidates:
            if c["published_id"] == sid and all(c["base_i53"][p] == b for p, b in required.items()):
                if tuple(c["base_i53"]) not in unique:
                    record(c["base_i53"], c["annotated_sequence"], "previous_pool_or_Stage3_route")
        inventory.append({"published_id": sid, "predicted_junctions": len(predictions[sid]),
                          "required_paired_bases": sum(b >= 0 for b in required.values()),
                          "whole_routes": len(unique), "expanded_min5_routes": expanded_count,
                          "enumeration_nodes": nodes})
        all_candidates.extend(unique.values())
    counts = Counter(c["published_id"] for c in all_candidates)
    unique = [c for c in all_candidates if counts[c["published_id"]] == 1]
    used = Counter(b for c in unique for b in c["base_i53"] if b >= 0)
    summary = {"candidate_staples": len(predictions), "complete_routes": len(all_candidates),
               "staples_with_routes": len(counts),
               "conditional_unique_staples": [c["published_id"] for c in unique],
               "conditional_unique_paired_nt": len(used),
               "conditional_unique_overlap_positions": [b for b, n in used.items() if n > 1],
               "inventory": inventory}
    (OUT / "graph_constrained_candidates.json").write_text(json.dumps(all_candidates, indent=2)+"\n")
    (OUT / "graph_enumeration_summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
