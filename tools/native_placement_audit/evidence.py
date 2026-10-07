"""Small per-site coordinate evidence builder shared by placement regressions."""

import math


def coordinate_deltas(expected, actual, *, identities=None, tolerance_nm=1e-9):
    """Keep every expected/actual vector and displacement, not just an aggregate."""
    expected, actual = list(expected), list(actual)
    if len(expected) != len(actual):
        raise ValueError("Expected and actual coordinate counts differ")
    identities = list(range(len(expected))) if identities is None else list(identities)
    if len(identities) != len(expected):
        raise ValueError("Each coordinate needs one source identity")
    rows = []
    for identity, left, right in zip(identities, expected, actual):
        left, right = list(map(float, left)), list(map(float, right))
        if len(left) != 3 or len(right) != 3:
            raise ValueError("Coordinate evidence requires 3D vectors")
        delta = [r - l for l, r in zip(left, right)]
        norm = math.sqrt(sum(x * x for x in delta))
        rows.append({"identity": identity, "expected_nm": left, "actual_nm": right,
                     "displacement_nm": delta, "distance_nm": norm,
                     "matches": math.isfinite(norm) and norm <= tolerance_nm})
    return {"tolerance_nm": tolerance_nm, "sites": rows,
            "mismatched_sites": sum(not row["matches"] for row in rows),
            "maximum_displacement_nm": max((r["distance_nm"] for r in rows), default=0.0)}
