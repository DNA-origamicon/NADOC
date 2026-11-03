"""Audit reciprocal crossover predictions without changing the source contact map.

All scaffold coordinates are zero based. A staple jump x -> y predicts the
opposite jump (y+1) -> (x-1), conditional on a full reciprocal junction.
This is a hypothesis, not a requirement at every junction.
"""
import csv
import hashlib
import json
from collections import Counter
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
PREVIOUS = ROOT / "analysis/gerling2018_revnano_variations_20261027"
SCAFFOLD = (ROOT / "backend/core/p7560.txt").read_text().strip()
COMP = SCAFFOLD.translate(str.maketrans("ACGT", "TGCA"))
N = len(SCAFFOLD)
DESC = "".join(COMP[-i % N] for i in range(N)) * 2


def partner(edge):
    x, y = edge
    return (y + 1) % N, (x - 1) % N


def jumps(mapping):
    paired = [(i, b) for i, b in enumerate(mapping) if b >= 0]
    return [
        {"from": x, "to": y, "left_staple_base": i, "right_staple_base": j,
         "unpaired_between": j - i - 1}
        for (i, x), (j, y) in zip(paired, paired[1:])
        if y != (x - 1) % N
    ]


@lru_cache(None)
def hits(sequence):
    result = []
    i = DESC.find(sequence)
    while 0 <= i < N:
        result.append(tuple((-i - k) % N for k in range(len(sequence))))
        i = DESC.find(sequence, i + 1)
    return result


def save_csv(name, rows):
    if not rows:
        return
    with (OUT / name).open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    key = "42hb13"
    source = PREVIOUS / f"{key}_best_contactmap.json"
    st, sc, circular = json.loads(source.read_text())
    assert circular and len(sc) == N
    ref = json.loads((ROOT / f"backend/data/gerling2018_{key}.json").read_text())["sequences"]
    occupied = {int(p) for p, r in sc.items() if r["staple_id"] >= 0}
    edges = {}
    for sid, m in st.items():
        for e in jumps(m["base_i53"]):
            edge = e["from"], e["to"]
            assert edge not in edges and partner(partner(edge)) == edge
            edges[edge] = {**e, "published_id": ref[int(sid)]["index"]}

    audit, matches = [], []
    for edge, entry in edges.items():
        mate = partner(edge)
        status = ("paired" if mate in edges else
                  f"missing_{sum(b in occupied for b in mate)}_endpoints_occupied")
        audit.append({**entry, "expected_from": mate[0], "expected_to": mate[1],
                      "status": status,
                      "partner_published_id": edges.get(mate, {}).get("published_id", "")})
        if status != "missing_0_endpoints_occupied":
            continue
        u, v = mate
        for i, row in enumerate(ref):
            if str(i) in st:
                continue
            q = row["sequence"]
            for t in range(1, len(q) - 2):
                if q[t:t+2] != "TT":
                    continue
                left = right = 0
                while (t-left-1 >= 0 and q[t-left-1] == COMP[(u+left) % N]
                       and (u+left) % N not in occupied):
                    left += 1
                while (t+2+right < len(q) and q[t+2+right] == COMP[(v-right) % N]
                       and (v-right) % N not in occupied):
                    right += 1
                if min(left, right) < 5:
                    continue
                matches.append({"source_published_id": entry["published_id"],
                                "source_from": edge[0], "source_to": edge[1],
                                "expected_from": u, "expected_to": v,
                                "candidate_published_id": row["index"],
                                "TT_start_1based": t+1,
                                "left_exact_free_nt": left, "right_exact_free_nt": right,
                                "local_sequence": q[t-left:t+2+right]})

    # Whole-strand alternatives in a bounded, declared candidate model. Existing
    # whole staples are fixed for this diagnostic. Blocks may be exact contiguous
    # matches, or already placed Stage3 routes for the identical paired substring.
    best = json.loads((PREVIOUS / "selected_best.json").read_text())[key]
    trial = ROOT / best["path"]
    selected = json.loads((trial / "annotations.json").read_text())
    diag = json.loads((trial / "solver/fragment_diagnostics.json").read_text())
    pool = json.loads((PREVIOUS / "expanded_candidate_pools.json").read_text())[key]
    candidates, failures = [], []
    for i, row in enumerate(ref):
        if str(i) in st:
            continue
        q = row["sequence"]
        alternatives = {k: v["annotation"] for k, v in pool[i].items()}
        alternatives[selected[i]["annotated_sequence"]] = selected[i]
        fragment_routes = {}
        blocks = [s for s in selected[i]["segments"] if s["kind"] == "paired_candidate"]
        ids = [i] + diag["extra_staples"].get(str(i), [])
        for block, virtual_id in zip(blocks, ids):
            route = diag["staples_placed"].get(str(virtual_id), [])
            if route:
                mapping = tuple((first-k) % N for first, length in route for k in range(length))
                assert "".join(COMP[p] for p in mapping) == block["sequence"]
                fragment_routes[block["start_1based"], block["end_1based"]] = mapping
        unique = {}
        rejected = Counter()
        for annotation in alternatives.values():
            assert annotation["annotated_sequence"].replace("*", "") == q
            segments = [s for s in annotation["segments"] if s["kind"] == "paired_candidate"]
            options = []
            for seg in segments:
                possibilities = set(hits(seg["sequence"]))
                route = fragment_routes.get((seg["start_1based"], seg["end_1based"]))
                if route:
                    possibilities.add(route)
                options.append([p for p in sorted(possibilities)
                                if len(set(p)) == len(p) and not occupied.intersection(p)])
            if not all(options):
                rejected["no_free_route_for_block"] += 1
                continue
            mapping = [-1] * len(q)
            generated = 0

            def enumerate_routes(k, used):
                nonlocal generated
                if generated >= 100000:
                    raise RuntimeError("Enumeration limit reached; do not label results exhaustive")
                if k == len(segments):
                    generated += 1
                    m = tuple(mapping)
                    if m in unique:
                        return
                    evidence = [e for e in jumps(m) if partner((e["from"], e["to"])) in edges]
                    unique[m] = {"published_id": row["index"], "reference_index": i,
                                 "annotated_sequence": annotation["annotated_sequence"],
                                 "base_i53": list(m), "paired_nt": len(used),
                                 "closes_existing_junctions": evidence,
                                 "seven_multiple_blocks": sum(s["length"] % 7 == 0 for s in segments)}
                    return
                seg = segments[k]
                start, end = seg["start_1based"]-1, seg["end_1based"]
                for route in options[k]:
                    if used.intersection(route):
                        continue
                    mapping[start:end] = route
                    enumerate_routes(k+1, used.union(route))

            enumerate_routes(0, set())
        candidates.extend(unique.values())
        failures.append({"published_id": row["index"], "annotation_alternatives": len(alternatives),
                         "whole_routes": len(unique),
                         "whole_routes_closing_existing_junctions": sum(bool(c["closes_existing_junctions"]) for c in unique.values()),
                         "rejected_annotations": dict(rejected)})
    summary = {"source_contactmap_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
               "fixed_complete_staples": len(st), "fixed_scaffold_bases": len(occupied),
               "crossover_counts": dict(Counter(r["status"] for r in audit)),
               "reciprocal_pairs": sum(r["status"] == "paired" for r in audit)//2,
               "local_predictions": {}, "whole_route_candidates": len(candidates),
               "unplaced_staples_with_whole_route_candidates": len({c["published_id"] for c in candidates}),
               "unplaced_staples_with_graph_supported_whole_routes": len({c["published_id"] for c in candidates if c["closes_existing_junctions"]})}
    for minimum in (5, 7):
        filtered = [r for r in matches if min(r["left_exact_free_nt"], r["right_exact_free_nt"]) >= minimum]
        groups = {}
        for r in filtered:
            groups.setdefault((r["expected_from"], r["expected_to"]), set()).add(r["candidate_published_id"])
        summary["local_predictions"][str(minimum)] = {
            "supported_expected_edges": len(groups),
            "unique_candidate_oligo": sum(len(v) == 1 for v in groups.values()),
            "distinct_candidate_oligos": sorted({r["candidate_published_id"] for r in filtered})}
    save_csv("crossover_audit.csv", audit)
    save_csv("predicted_partner_matches.csv", matches)
    save_csv("whole_route_inventory.csv", failures)
    (OUT / "whole_route_candidates.json").write_text(json.dumps(candidates, indent=2)+"\n")
    (OUT / "audit_summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
