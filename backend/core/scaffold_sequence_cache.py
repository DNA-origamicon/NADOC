"""Bounded immutable scaffold lookup, keyed by every sequence/traversal input."""
from functools import lru_cache


@lru_cache(maxsize=1)
def scaffold_base_entries(scaffolds, loop_skips, unpaired_loops=()):
    modifications = dict(loop_skips)
    loops = dict(unpaired_loops)
    result = {}
    for sequence, domains in scaffolds:
        bases = iter(sequence)
        for helix_id, direction, traversal in domains:
            for bp in traversal:
                delta = modifications.get((helix_id, bp), 0)
                if delta <= -1:
                    continue
                values = tuple(next(bases, "N") for _ in range(delta + 1))
                for _ in range(loops.get((helix_id, bp, direction), 0)):
                    next(bases, "N")
                # Active scaffolds precede reference scaffolds; all consume
                # their own sequence even where a previous strand owns a site.
                result.setdefault((helix_id, bp, direction), values)
    return tuple(result.items())
