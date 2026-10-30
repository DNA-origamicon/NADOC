"""Experimental Stage2 connectivity across explicitly annotated loopouts.

Adds known edges only between consecutive, placed fragments of the SAME oligo.
Optional context scoring evaluates a candidate against its placed predecessor
and successor. It does not create base-pair matches, alter sequences or permit
overlap. Lattice edges are only a soft preference and are separately switchable.
"""
import networkx as nx


def fragment_neighbors(origami):
    before, after = {}, {}
    for parent, extras in origami["extra_staples"].items():
        chain = [parent] + list(extras)
        for a, b in zip(chain, chain[1:]):
            after[a] = b
            before[b] = a
    return before, after


def end(route, n):
    first, length = route[-1]
    return (first-length+1) % n


def add_loopout_edges(origami):
    added = 0
    before, after = fragment_neighbors(origami)
    for a, b in after.items():
        left, right = origami["staples_placed"].get(a), origami["staples_placed"].get(b)
        if not left or not right:
            continue
        x, y = end(left, origami["scaffold_nt"]), right[0][0]
        if not origami["B"].has_edge(x, y):
            origami["B"].add_edge(x, y)
            added += 1
    return added


def install(link_loopouts=True, context_weight=1., lattice_edges=(), lattice_bonus=0.):
    from REVNANO import stage2, srt
    original_init = stage2.initialise_base_graph_B
    original_add = stage2.add_1route_G1_staples_to_origami
    original_distance = stage2.staple_routing_distance
    original_update = stage2.update_G1_staples_dictionary
    allowed = {tuple(e) for e in lattice_edges}
    stats = {"link_loopouts": link_loopouts, "context_weight": context_weight,
             "lattice_bonus": lattice_bonus, "loopout_edges_added": 0,
             "candidate_context_evaluations": 0, "lattice_supported_links_scored": 0,
             "single_section_fragments_with_context": []}
    scored_single = set()

    def initialise(origami):
        original_init(origami)
        if link_loopouts:
            stats["loopout_edges_added"] += add_loopout_edges(origami)

    def add(origami):
        number = original_add(origami)
        if link_loopouts:
            stats["loopout_edges_added"] += add_loopout_edges(origami)
        return number

    def update(origami):
        if not context_weight:
            return original_update(origami)
        before, after = fragment_neighbors(origami)
        distances = {}

        def gap(a, b):
            if a not in distances:
                distances[a] = nx.single_source_shortest_path_length(origami["B"], a)
            value = distances[a][b] + 1
            if lattice_bonus and (a, b) in allowed:
                stats["lattice_supported_links_scored"] += 1
                value = max(0., value-lattice_bonus)
            return value

        remove = []
        for sid in origami["G1_staples"]:
            tree = origami["staple_routing_trees"][sid]
            if tree is None:
                continue
            routes = srt.list_of_valid_leaf_histories(tree, [])
            if len(routes) <= 1:
                remove.append(sid)
                if not routes:
                    origami["staple_ids_with_zero_route"].append(sid)
                continue
            left = origami["staples_placed"].get(before.get(sid), [])
            right = origami["staples_placed"].get(after.get(sid), [])
            costs = []
            for route in routes:
                cost = original_distance(origami, route)
                if left:
                    cost += context_weight*gap(end(left, origami["scaffold_nt"]), route[0][0])
                if right:
                    # The graph is undirected; use the fixed right anchor as the
                    # BFS source for efficient caching. Directed lattice test is
                    # evaluated explicitly in the original staple direction.
                    x, y = end(route, origami["scaffold_nt"]), right[0][0]
                    if y not in distances:
                        distances[y] = nx.single_source_shortest_path_length(origami["B"], y)
                    value = distances[y][x]+1
                    if lattice_bonus and (x, y) in allowed:
                        stats["lattice_supported_links_scored"] += 1
                        value = max(0., value-lattice_bonus)
                    cost += context_weight*value
                if left or right:
                    stats["candidate_context_evaluations"] += 1
                    if len(route) == 1:
                        scored_single.add(sid)
                costs.append(cost)
            ordered = sorted(costs)
            origami["G1_staples"][sid] = [len(routes), routes, costs, ordered[0] != ordered[1]]
        for sid in remove:
            del origami["G1_staples"][sid]
        stats["single_section_fragments_with_context"] = sorted(scored_single)

    stage2.initialise_base_graph_B = initialise
    stage2.add_1route_G1_staples_to_origami = add
    stage2.update_G1_staples_dictionary = update
    return stats
