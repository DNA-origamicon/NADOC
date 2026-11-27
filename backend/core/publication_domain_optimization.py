"""Scaffold occupancy optimization shared by compatibility and anchor challenges."""
import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix, vstack


class DomainOccupancy:
    def __init__(self, search, scaffold_length):
        self.rows = search['rows']
        self.length = scaffold_length
        count = len(self.rows)
        if not 1 <= count <= 500 or scaffold_length < 1:
            raise ValueError('Compatibility search bounds exceeded.')
        self.weight = 1 + sum(max((c['domain_count'] for c in r['candidates']), default=0) for r in self.rows)
        self.options, costs, rr, cc, vv = [], [], [], [], []
        self.pair_maps = []
        for i, row in enumerate(self.rows):
            for j, candidate in enumerate([*row['candidates'], None]):
                if candidate is not None and not candidate['domains']:
                    continue
                column = len(self.options)
                self.options.append((i, j if candidate is not None else None))
                pairs = {}
                if candidate:
                    for d in candidate['domains']:
                        for k in range(d['length']):
                            pos = d['oligo_start'] + k
                            if pos in pairs:
                                raise ValueError('Candidate reuses an oligo base.')
                            pairs[pos] = (d['scaffold_start'] + d['scaffold_step'] * k) % scaffold_length
                sites = list(pairs.values())
                if len(sites) != len(set(sites)):
                    raise ValueError('Candidate reuses a scaffold base.')
                self.pair_maps.append(pairs)
                rr.append(i); cc.append(column); vv.append(1.)
                for site in sites:
                    rr.append(count + site); cc.append(column); vv.append(1.)
                costs.append(-len(sites) * self.weight + (candidate['domain_count'] if candidate else 0))
        self.costs = np.asarray(costs, dtype=float)
        self.matrix = coo_matrix((vv, (rr, cc)), shape=(count + scaffold_length, len(costs))).tocsc()
        self.lower = np.r_[np.ones(count), np.zeros(scaffold_length)]
        self.upper = np.ones(count + scaffold_length)

    def solve(self, time_limit, *, objective=None, excluded=(), cost_ceiling=None):
        if not .05 <= time_limit <= 60:
            raise ValueError('Invalid solver time budget.')
        upper_bounds = np.ones(len(self.options))
        upper_bounds[list(excluded)] = 0
        matrix, lower, upper = self.matrix, self.lower, self.upper
        if cost_ceiling is not None:
            matrix = vstack([matrix, coo_matrix(self.costs[None, :])]).tocsc()
            lower = np.r_[lower, -np.inf]; upper = np.r_[upper, cost_ceiling]
        return milp(self.costs if objective is None else objective,
                    integrality=np.ones(len(self.options)), bounds=Bounds(0, upper_bounds),
                    constraints=LinearConstraint(matrix, lower, upper),
                    options={'time_limit': time_limit, 'mip_rel_gap': 0.})

    def assignments(self, result):
        if result.x is None:
            return []
        return [{'row_id': self.rows[i]['row_id'], 'candidate_index': j}
                for col in np.flatnonzero(result.x > .5) for i, j in [self.options[col]]]

    def anchor_columns(self, anchor):
        required = {anchor['oligo_start'] + k: (anchor['scaffold_start'] - k) % self.length
                    for k in range(anchor['length'])}
        return [col for col, (i, _) in enumerate(self.options)
                if self.rows[i]['row_id'] == anchor['row_id']
                and all(self.pair_maps[col].get(p) == s for p, s in required.items())]
