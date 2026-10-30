"""Experimental fix: preserve the ORDER of the selected shortest-path route.

Upstream checks set membership of each segment in the selected history. Two routes
that permute the same segments can both survive, violating the function's intent
and making Stage2 select the same unresolved staple indefinitely. This hook only
corrects that pruning operation; it adds no route and changes no threshold.
"""
def install():
    from REVNANO import srt
    original = srt.prune_all_but_shortest_route_of_staple_routing_tree
    stats = {'enabled': True, 'calls': 0, 'calls_with_permuted_routes': 0}

    def prune_ordered(tree, route):
        if tree is None:
            return
        expected = route[0] if route else None
        for child, node in tree.items():
            if child == expected:
                prune_ordered(node[3], route[1:])
            else:
                node[srt.TREE_IS_PRUNED_INDEX] = True

    def prune(tree, route):
        stats['calls'] += 1
        histories = srt.list_of_valid_leaf_histories(tree, [])
        if any(h != route and all(segment in route for segment in h) for h in histories):
            stats['calls_with_permuted_routes'] += 1
        prune_ordered(tree, route)

    srt.prune_all_but_shortest_route_of_staple_routing_tree = prune
    return stats, original
