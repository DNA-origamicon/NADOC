"""Bounded immutable scaffold lookup, keyed by every sequence/traversal input."""
from functools import lru_cache


@lru_cache(maxsize=1)
def scaffold_base_entries(scaffolds, loop_skips):
    modifications = dict(loop_skips)
    result = {}
    for sequence, domains in scaffolds:
        bases = iter(sequence)
        for helix_id, direction, traversal in domains:
            for bp in traversal:
                delta = modifications.get((helix_id, bp), 0)
                if delta <= -1:
                    continue
                values = tuple(next(bases, "N") for _ in range(delta + 1))
                # Active scaffolds precede reference scaffolds; all consume
                # their own sequence even where a previous strand owns a site.
                result.setdefault((helix_id, bp, direction), values)
    return tuple(result.items())
