"""Regression checks for the experimental topology hints."""
import copy
import importlib
import sys
import unittest
from pathlib import Path
import networkx as nx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'.development-artifacts/revnano-gerling2018'))
from REVNANO import stage2, srt
from loopout_context import add_loopout_edges, install, end
from route_seeds import make_tree


class ConnectivityTests(unittest.TestCase):
    def tearDown(self):
        importlib.reload(stage2)

    def test_only_adjacent_placed_fragments_on_the_same_oligo_connect(self):
        o = {'scaffold_nt':100, 'extra_staples':{0:[2,3],1:[4]}, 'B':nx.Graph(),
             'staples_placed':{0:[[21,7]], 1:[[45,7]], 2:[[71,7]], 3:[], 4:[[91,7]]}}
        self.assertEqual(add_loopout_edges(o), 2)
        self.assertEqual({frozenset(e) for e in o['B'].edges}, {frozenset((15,71)),frozenset((39,91))})
        self.assertEqual(add_loopout_edges(o), 0)
        o['staples_placed'][3] = [[9,7]]
        self.assertEqual(add_loopout_edges(o), 1)
        self.assertTrue(o['B'].has_edge(65,9))
        self.assertEqual(end([[2,7]],100), 96)

    def fixture(self):
        routes = [[(120,7)],[(720,7)]]
        return {'scaffold_nt':1000, 'scaffold_type':'CIRCULAR', 'extra_staples':{0:[1,2]},
                'staples_placed':{0:[[139,7]],1:[],2:[[110,7]]}, 'B':nx.cycle_graph(1000),
                'staple_routing_trees':{1:make_tree(routes)}, 'G1_staples':{1:[]},
                'staple_ids_with_zero_route':[]}

    def test_context_breaks_repeat_tie_without_creating_routes_or_placements(self):
        o = self.fixture()
        stage2.update_G1_staples_dictionary(o)
        self.assertEqual(o['G1_staples'][1][2], [7,7])
        self.assertFalse(o['G1_staples'][1][3])
        before = copy.deepcopy(o)
        install(link_loopouts=False, context_weight=1)
        stage2.update_G1_staples_dictionary(o)
        self.assertLess(*o['G1_staples'][1][2])
        self.assertTrue(o['G1_staples'][1][3])
        self.assertEqual(o['G1_staples'][1][1], before['G1_staples'][1][1])
        self.assertEqual(o['staples_placed'], before['staples_placed'])
        self.assertEqual(o['staple_routing_trees'], before['staple_routing_trees'])
        o['staples_placed'][0] = [[739,7]]
        o['staples_placed'][2] = [[710,7]]
        stage2.update_G1_staples_dictionary(o)
        self.assertGreater(*o['G1_staples'][1][2])

    def test_no_neighbors_preserves_original_scores(self):
        o = self.fixture()
        o['extra_staples'] = {}
        stage2.update_G1_staples_dictionary(o)
        baseline = copy.deepcopy(o['G1_staples'])
        install(context_weight=1)
        stage2.update_G1_staples_dictionary(o)
        self.assertEqual(o['G1_staples'], baseline)

    def test_seed_routes_survive_normal_tree_pruning(self):
        routes = [[(7250,9),(103,1)],[(569,8),(104,2)],[(7250,8),(104,2)]]
        tree = make_tree(routes)
        srt.propagate_pruning_in_staple_routing_tree(tree)
        self.assertEqual(srt.list_of_valid_leaf_histories(tree, []), routes)
        tree[(7250,9)][2] = True
        srt.propagate_pruning_in_staple_routing_tree(tree)
        self.assertEqual(srt.list_of_valid_leaf_histories(tree, []), routes[1:])


if __name__ == '__main__':
    unittest.main()
