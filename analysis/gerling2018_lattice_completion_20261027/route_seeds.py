"""Add explicitly documented exact routes after Stage0, as candidates, not pins.

This experimental rescue can include short scaffold-seam pieces supported by
external junction evidence. Stage1–3 still enforce competition and overlap rules.
Only zero-route/no-tree fragments are eligible, avoiding changing any Stage0
definite placement on which other generated trees may already depend.
"""
import copy


def make_tree(routes):
    root = {}
    for route in routes:
        node, history, count = root, [], 0
        for depth, (first, length) in enumerate(route):
            key = (first, length)
            history = history + [key]
            count += length
            if key not in node:
                node[key] = [history.copy(), count, False, None if depth == len(route)-1 else {}]
            node = node[key][3]
    return root


def install(seeds):
    from REVNANO import stage0, srt, dna
    original = stage0.process
    stats = {"requested": seeds, "added": [], "skipped_existing_routes": []}

    def process(origami, *args):
        original(origami, *args)
        comp = origami["scaffold53"].translate(str.maketrans("ACGT", "TGCA"))
        n = origami["scaffold_nt"]
        for seed in seeds:
            parent = seed["published_id"]-1
            chain = [parent]+origami["extra_staples"].get(parent, [])
            sid = chain[seed["paired_block_index_0based"]]
            assert origami["staples53"][sid] == seed["sequence"]
            tree = origami["staple_routing_trees"][sid]
            existing = srt.list_of_valid_leaf_histories(tree, []) if tree else []
            if existing:
                stats["skipped_existing_routes"].append({"published_id": seed["published_id"], "virtual_id": sid, "routes": len(existing)})
                continue
            assert sid not in origami["staple_ids_with_1definite_route"]
            assert not origami["staples_placed"][sid]
            for route in seed["routes"]:
                positions = [(first-k) % n for first, length in route for k in range(length)]
                assert len(set(positions)) == len(positions)
                assert "".join(comp[p] for p in positions) == seed["sequence"]
            dna.remove_staple_footprint_from_scaffold(origami, sid)
            origami["staple_routing_trees"][sid] = make_tree(seed["routes"])
            for field in ("staple_ids_with_no_tree", "staple_ids_with_zero_route"):
                origami[field] = [i for i in origami[field] if i != sid]
            stats["added"].append({"published_id": seed["published_id"], "virtual_id": sid,
                                   "route_count": len(seed["routes"]), "sequence": seed["sequence"]})
        # The upstream Stage0 summary describes pre-rescue trees; preserve it
        # explicitly and publish updated routing statistics separately.
        stats["stage0_before_rescue"] = copy.deepcopy(origami["stage0_result"])
        stats["tree_stats_after_rescue"] = srt.routing_tree_stats(origami)

    stage0.process = process
    return stats
