from copy import deepcopy
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'.development-artifacts/revnano-gerling2018'))
from REVNANO import srt
from ordered_pruning import install

def make_tree(routes):
    tree={}
    for route in routes:
        node=tree
        for depth,segment in enumerate(route):
            history=route[:depth+1]
            if segment not in node:
                node[segment]=[history,sum(n for _,n in history),False,None if depth==len(route)-1 else {}]
            node=node[segment][3]
    return tree

def test_pruning_distinguishes_route_order(monkeypatch):
    routes=[[(1556,6),(6452,4),(5955,4)],[(1556,6),(5955,4),(6452,4)]]
    original=srt.prune_all_but_shortest_route_of_staple_routing_tree
    monkeypatch.setattr(srt,'prune_all_but_shortest_route_of_staple_routing_tree',original)
    old=make_tree(routes);original(old,routes[0]);srt.propagate_pruning_in_staple_routing_tree(old)
    assert srt.list_of_valid_leaf_histories(old,[])==routes
    stats,_=install()
    for route in routes:
        tree=make_tree(routes);srt.prune_all_but_shortest_route_of_staple_routing_tree(tree,route)
        srt.propagate_pruning_in_staple_routing_tree(tree)
        assert srt.list_of_valid_leaf_histories(tree,[])==[route]
        before=deepcopy(tree);srt.prune_all_but_shortest_route_of_staple_routing_tree(tree,route)
        assert tree==before
    assert stats['calls_with_permuted_routes']==2

def test_pruning_matches_upstream_when_routes_do_not_permute(monkeypatch):
    routes=[[(1,7),(20,7)],[(1,7),(40,7)],[(100,14)]]
    original=srt.prune_all_but_shortest_route_of_staple_routing_tree
    monkeypatch.setattr(srt,'prune_all_but_shortest_route_of_staple_routing_tree',original)
    expected_trees=[]
    for route in routes:
        expected=make_tree(routes);original(expected,route);srt.propagate_pruning_in_staple_routing_tree(expected)
        expected_trees.append(expected)
    install()
    for route,expected in zip(routes,expected_trees):
        actual=make_tree(routes);srt.prune_all_but_shortest_route_of_staple_routing_tree(actual,route);srt.propagate_pruning_in_staple_routing_tree(actual)
        assert actual==expected
