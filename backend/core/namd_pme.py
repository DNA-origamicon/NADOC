"""PME grid selection for the qualified NAMD Git-2025-12-04 build.

Mirrors SimParameters.C's automatic grid search. This determines dimensions,
not cuFFT workspace: the latter remains library/plan dependent.
"""
from functools import lru_cache
import math


@lru_cache(maxsize=1024)
def _axis(minimum):
    if not 1 <= minimum <= 2**24:
        raise ValueError('PME dimension outside the supported sizing range')
    max2 = max3 = 2
    value = 1
    while value < minimum:
        max2 += 1; value *= 2
    value = 1
    while value < minimum:
        max3 += 1; value *= 3
    best = 10*(minimum+10)
    for i2 in range(max2+1):
        for i3 in range(max3+1):
            for i5 in range(3):
                for i7 in range(2):
                    for i11 in range(2):
                        if i5+i7+i11 > i2:
                            continue
                        candidate = 2**(i2+1)*3**i3*5**i5*7**i7*11**i11
                        if minimum <= candidate < best:
                            best = candidate
    return best


def pme_grid(box_angstrom, spacing):
    if len(box_angstrom)!=3 or not math.isfinite(spacing) or spacing<=0:
        raise ValueError('Positive PME spacing and three cell dimensions are required')
    if any(not math.isfinite(d) or d<=0 for d in box_angstrom):
        raise ValueError('Positive finite PME cell dimensions are required')
    return tuple(_axis(math.ceil(d/spacing)) for d in box_angstrom)
