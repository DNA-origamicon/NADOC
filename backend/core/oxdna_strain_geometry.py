"""Read-only display reconstruction fallback for strain trajectories."""


def backbone_unwrap_plan(frame, design):
    """Keep covalent chains whole when designed WC edges tear an unwrap tree.

    Melted designed partners can be many periodic images apart. Their assumed
    pairing must not split a real backbone. Independently place each covalent
    component near its reference, using the existing unwrap/alignment machinery.
    Scalar measurements are taken separately from minimum-image raw sites.
    """
    from backend.physics.oxdna_interface import (
        _backbone_adjacency_pairs,
        _build_unwrap_plan,
    )

    adjacent = {key: [] for key in frame}
    for a, b in _backbone_adjacency_pairs(design):
        if a in adjacent and b in adjacent:
            adjacent[a].append(b)
            adjacent[b].append(a)
    return _build_unwrap_plan(frame, design, adj=adjacent)
