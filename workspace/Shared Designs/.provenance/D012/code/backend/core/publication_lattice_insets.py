"""Require agreement between repeated numbered cross-section insets."""
import math
from statistics import median


def consensus_insets(observations, row_ids, fit, *, selected_panel=False):
    if len({label for label,_ in observations}) == len(observations):
        return fit(dict(observations), row_ids)
    radius = median(circle[2] for _,circle in observations)
    pending = set(range(len(observations))); groups = []
    while pending:
        group = [pending.pop()]; cursor = 0
        while cursor < len(group):
            _, (x,y,_) = observations[group[cursor]]; cursor += 1
            neighbors = {i for i in pending if math.hypot(
                observations[i][1][0]-x, observations[i][1][1]-y) < 2.2*radius}
            pending -= neighbors; group.extend(sorted(neighbors))
        groups.append([observations[i] for i in group])
    if selected_panel:
        complete = [group for group in groups if {label for label, _ in group} == set(row_ids)]
        if complete:
            # A selected route panel can share a page with a separate small
            # design using a subset of the same helix labels.
            groups = complete
    fits = []
    for group in groups:
        circles = dict(group)
        if len(circles) != len(group):
            return {'resolved':False,'reason':'Repeated lattice labels within one inset.'}
        candidate = fit(circles, row_ids)
        if not candidate.get('resolved'):
            return {'resolved':False,'reason':'Repeated lattice insets are incomplete or ambiguous.'}
        fits.append(candidate)
    if not fits or any(f['cells'] != fits[0]['cells'] for f in fits):
        return {'resolved':False,'reason':'Repeated lattice insets disagree.'}
    return {**fits[0], 'inset_copies':len(fits),
            'basis':'All separately fitted numbered insets agree after translation normalization.'}
