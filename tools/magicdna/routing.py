"""Validate simple-bundle caDNAno graphs before any native authoring occurs.

The interchange contract is directed routing in an explicitly supplied lattice.
It does not infer a spatial pose or molecular geometry from caDNAno JSON.
"""

import hashlib
import json
from collections import Counter

from backend.core.models import LatticeType
from backend.core.part_cadnano_source import parse_source
from backend.core.part_input_sources import describe


class UnsupportedBundle(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise UnsupportedBundle(message)


def read_graph(raw, lattice):
    """Return validated JSON and complete 5′→3′ walks, without making a Design."""
    lattice = LatticeType(lattice)
    source = describe(raw, format="cadnano-v2", media_type="application/json")
    data, _ = parse_source(raw, source)
    helices = {h["num"]: h for h in data["vstrands"]}
    require(
        len(helices) in (6, 18),
        "Only honeycomb 6HB and square 3x6 bundles are supported",
    )
    cells = {(h["row"], h["col"]) for h in helices.values()}
    require(len(cells) == len(helices), "Duplicate lattice cells")
    from backend.core.lattice import _lattice_position

    if lattice == LatticeType.SQUARE:
        rows, cols = sorted({r for r, c in cells}), sorted({c for r, c in cells})
        require(
            sorted((len(rows), len(cols))) == [3, 6]
            and rows == list(range(rows[0], rows[-1] + 1))
            and cols == list(range(cols[0], cols[-1] + 1))
            and cells == {(r, c) for r in rows for c in cols},
            "Expected a contiguous square 3x6 footprint",
        )
    else:
        import math
        from backend.core.constants import HONEYCOMB_HELIX_SPACING

        points = [_lattice_position(r, c, lattice) for r, c in cells]
        require(
            len(points) == 6
            and all(
                sum(
                    math.isclose(math.dist(p, q), HONEYCOMB_HELIX_SPACING, abs_tol=1e-8)
                    for q in points
                )
                == 2
                for p in points
            ),
            "Expected a honeycomb six-helix ring",
        )
    width = len(next(iter(helices.values()))["scaf"])
    require(
        width % (21 if lattice == LatticeType.HONEYCOMB else 32) == 0,
        "Array width does not match the explicitly selected lattice",
    )
    for h in helices.values():
        require(
            h["num"] % 2 == (h["row"] + h["col"]) % 2,
            "Source numbering contradicts lattice polarity",
        )
        require(
            all(v in (0, 1) for v in h["loop"]),
            "Only single-base insertions are supported",
        )
        require(all(v in (0, -1) for v in h["skip"]), "Unsupported deletion encoding")
        require(
            not any(a and b for a, b in zip(h["loop"], h["skip"])),
            "Insertion and deletion overlap",
        )
    walks = []
    for kind in ("scaf", "stap"):
        occupied = {
            (n, bp)
            for n, h in helices.items()
            for bp, e in enumerate(h[kind])
            if e != [-1] * 4
        }
        starts = []
        for n, bp in sorted(occupied):
            entry = helices[n][kind][bp]
            for offset, reverse in ((0, 2), (2, 0)):
                target = tuple(entry[offset : offset + 2])
                if target == (-1, -1):
                    if offset == 0:
                        starts.append((n, bp))
                    continue
                require(target in occupied, "Dangling routing pointer")
                require(
                    tuple(helices[target[0]][kind][target[1]][reverse : reverse + 2])
                    == (n, bp),
                    "Nonreciprocal routing pointer",
                )
            successor = tuple(entry[2:])
            if successor in occupied and successor[0] == n:
                step = 1 if (n % 2 == 0) == (kind == "scaf") else -1
                require(
                    successor[1] == bp + step,
                    "Nonconsecutive or reversed same-helix route",
                )
        seen = set()
        for start in starts:
            walk, current = [], start
            while current != (-1, -1):
                require(current not in seen, "Cycle or multiply visited nucleotide")
                seen.add(current)
                walk.append(current)
                current = tuple(helices[current[0]][kind][current[1]][2:])
            require(
                len(walk) > 1, "Isolated single-nucleotide strands cannot round-trip"
            )
            walks.append((kind, walk))
        require(
            seen == occupied,
            "Circular molecules require a dedicated topology-preserving operation",
        )
    require(
        sum(kind == "scaf" for kind, _ in walks) == 1,
        "Basic converter requires exactly one linear scaffold",
    )
    require(any(kind == "stap" for kind, _ in walks), "Bundle has no staple routing")
    for kind, walk in walks:
        for (an, ab), (bn, bb) in zip(walk, walk[1:]):
            if an == bn:
                continue
            from backend.core.crossover_positions import crossover_neighbor

            a, b = helices[an], helices[bn]
            valid = ab == bb and any(
                crossover_neighbor(lattice, x["row"], x["col"], ab, is_scaffold=sc)
                == (y["row"], y["col"])
                for x, y in ((a, b), (b, a))
                for sc in (False, True)
            )
            require(
                valid,
                "Noncanonical junction: no forced-ligation substitution is permitted",
            )
    return data, walks, source


def signature(data):
    """Identity independent of helix numbering, order, colors and empty padding."""
    hs = {h["num"]: h for h in data["vstrands"]}
    cell = lambda n: (hs[n]["row"], hs[n]["col"])
    sites, edges, marks = [], [], []
    for n, h in hs.items():
        for kind in ("scaf", "stap"):
            for bp, e in enumerate(h[kind]):
                if e == [-1] * 4:
                    continue
                sites.append((kind, cell(n), bp))
                if e[2] != -1:
                    edges.append((kind, cell(n), bp, cell(e[2]), e[3]))
        marks.extend(
            (cell(n), bp, loop, skip)
            for bp, (loop, skip) in enumerate(zip(h["loop"], h["skip"]))
            if loop or skip
        )
    return {"sites": sorted(sites), "edges": sorted(edges), "indels": sorted(marks)}


def digest(data):
    return hashlib.sha256(
        json.dumps(signature(data), sort_keys=True).encode()
    ).hexdigest()


def inventory(data, walks):
    h = {v["num"]: v for v in data["vstrands"]}
    counts = Counter(kind for kind, _ in walks)
    return {
        "helices": len(h),
        "scaffolds": counts["scaf"],
        "staples": counts["stap"],
        "nucleotides": sum(
            1 + h[n]["loop"][bp] + h[n]["skip"][bp] for _, w in walks for n, bp in w
        ),
        "routing_sha256": digest(data),
    }
