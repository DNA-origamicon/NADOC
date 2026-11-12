"""Read-only image/table recovery benchmark. Never constructs molecular documents.

Run with NADOC's .venv/bin/python. Inputs are publisher PDFs only. Output records
figure measurements, extracted table rows, matching checks and authoring gaps.
The vector profile is explicitly specific to the 2009 supporting figure export.
"""

import collections
import hashlib
import math
import re
import statistics

import pymupdf

CASES = [
    ("D001", "cargo-sorting.pdf", 21, range(22, 27)),
    ("D002", "tilings.pdf", 80, range(82, 86)),
    ("D003", "tilings.pdf", 81, (*range(86, 90), 91)),
    ("D005", "twist-supp.pdf", 19, range(37, 38)),
    ("D006", "twist-supp.pdf", 20, range(39, 40)),
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def vector_2009(page, *, rotated=False):
    """Measure paths and insertion marks, with no topology or placement guesses."""
    drawings = page.get_drawings()
    scaffold = [d for d in drawings if d["color"] and
                abs(d["color"][0]) < .001 and abs(d["color"][1] - .48746) < .001]
    assert len(scaffold) == 1, "Ambiguous scaffold vector selection"
    scaffold = scaffold[0]
    uv = lambda p: pymupdf.Point(-p.y, p.x) if rotated else p

    def straight(item):
        return item[0] == "l" and abs(uv(item[1]).y - uv(item[-1]).y) < .01 and abs(uv(item[1]).x - uv(item[-1]).x) > .01

    positions = sorted({round(uv(item[1]).y, 3) for item in scaffold["items"] if straight(item)})
    labels = [19, *range(len(positions) - 1)] if rotated else list(range(len(positions)))
    rows = dict(zip(labels, positions))
    guides = sorted(uv(d["items"][0][1]).x for d in drawings if d["color"] and
                    abs(d["color"][0] - .57) < .01 and len(d["items"]) == 1 and
                    d["items"][0][0] == "l" and abs(uv(d["items"][0][1]).x - uv(d["items"][0][-1]).x) < .01)
    pitch = statistics.median(b - a for a, b in zip(guides, guides[1:])) / 7
    origin = guides[0]

    def bp(x):
        return math.floor((x - origin) / pitch + 1e-4)

    def path(drawing, kind):
        measured = []
        for item in drawing["items"]:
            if not straight(item):
                continue
            a, b = uv(item[1]), uv(item[-1])
            track = lambda h: rows[h] + (pitch if h % 2 == 0 else -pitch) if kind == "staple" else rows[h]
            h = min(labels, key=lambda h: abs(a.y - track(h)))
            if abs(a.y - track(h)) > .02:
                return None
            start, end = bp(a.x), bp(b.x)
            assert (end > start) == ((h % 2 == 0) == (kind == "scaffold")), "Unresolved path orientation"
            measured.append([h, start, end])
        if measured:
            return {"kind": kind, "pdf_seqno": drawing["seqno"], "measured_segments": measured}

    paths = [path(scaffold, "scaffold")]
    for d in drawings:
        if d is scaffold or not d["color"]:
            continue
        if not any(item[0] == "c" for item in d["items"]) and len(d["items"]) != 1:
            continue
        if not any(straight(item) for item in d["items"]):
            continue
        candidate = path(d, "staple")
        if candidate:
            paths.append(candidate)
    assert paths[0], "Missing scaffold path"
    spans = [span for block in page.get_text("rawdict")["blocks"]
             for line in block.get("lines", []) for span in line["spans"]]
    insertions = []
    for d in drawings:
        if not d["color"] or not (.25 < d["color"][0] < .27 and .48 < d["color"][1] < .50):
            continue
        if len(d["items"]) != 2 or any(item[0] != "c" for item in d["items"]):
            continue
        point = uv(d["items"][0][1])
        h = min(labels, key=lambda h: abs(point.y - rows[h]))
        assert abs(point.y - rows[h]) < pitch * .2
        label = min((s for s in spans if s["font"] == "Verdana"),
                    key=lambda s: abs(uv(pymupdf.Point(s["origin"])).x - point.x) + abs(uv(pymupdf.Point(s["origin"])).y - point.y))
        glyphs = "".join(c["c"] for c in label["chars"])
        count = int(glyphs.translate(str.maketrans({'!': '1', '"': '4'})))
        insertions.append({"helix_label": h, "bp": bp(point.x), "count": count,
                           "pdf_seqno": d["seqno"], "label_glyphs": glyphs})
    lookup = {(r["helix_label"], r["bp"]): r["count"] for r in insertions}
    assert len(lookup) == len(insertions)
    occupied = {"scaffold": set(), "staple": set()}
    for p in paths:
        cells = [(h, b) for h, a, z in p["measured_segments"]
                 for b in range(a, z + (1 if z > a else -1), 1 if z > a else -1)]
        assert len(cells) == len(set(cells)), "Self-overlapping vector path"
        assert not (set(cells) & occupied[p["kind"]]), "Overlapping paths"
        occupied[p["kind"]].update(cells)
        p.update(start=cells[0], end=cells[-1], measured_nt=len(cells) + sum(lookup.get(c, 0) for c in cells))
    circles = [d for d in drawings if d["color"] and len(d["items"]) == 4 and all(item[0] == "c" for item in d["items"])]
    return {"profile": "Dietz-2009-vector-export", "row_count": len(rows), "slice_circle_count": len(circles),
            "row_labels": labels, "rotation_to_horizontal": rotated,
            "bp_origin_pdf_points": origin, "pdf_points_per_bp": pitch,
            "paths": paths, "insertions": insertions,
            "profile_judgments": [
                "Scaffold color and seven-base gray guide spacing selected for this export.",
                "Row order is interpreted as visible labels: 19 then 0–17 on Fig10; 0–59 on Fig9.",
                "Directed PDF path traversal checked against alternating scaffold/staple directions.",
                "Verdana subset glyphs ! and double-quote decoded as 1 and 4 from visible labels.",
                "Nearest insertion label selected geometrically; this is not a general OCR pipeline.",
            ]}


def tables(doc, pages, ident):
    text = "\n".join(doc[p - 1].get_text() for p in pages)
    if ident in {"D005", "D006"}:
        pattern = r"(\d+)\[(\d+)\]\s+(\d+)\[(\d+)\]\s+([ACGT\s]+?)\s+(\d+)\s+(#[a-fA-F0-9]{6})"
        return [{"start": [int(h), int(a)], "end": [int(k), int(b)],
                 "sequence": "".join(s.split()), "length": int(n), "color": color}
                for h, a, k, b, s, n, color in re.findall(pattern, text)]
    if ident == "D001":
        pattern = r"([TB]\s+C\d+\s+R\d+)\s+([ACGT]+)"
    elif ident == "D003":
        pattern = r"((?:Bri|Reg|Edg)-T[1-4]R\d+C\d+)\s+([ACGT]+)"
    elif ident == "D002":
        pattern = r"((?:Bri|Reg)-[A-Za-z0-9]+)\s+([ACGT]+)"
    else:
        return []  # No verified complete variant assignment; never guess one.
    return [{"name": " ".join(name.split()), "sequence": seq, "length": len(seq)}
            for name, seq in re.findall(pattern, text)]


def stroke_graph(page):
    """Generic colored-stroke connectivity diagnostic, not a strand graph.

    Excludes grayscale grid/text. A component is not declared to be a strand:
    same-color arrowheads, crossings and split PDF strokes remain ambiguous.
    """
    edges = collections.defaultdict(list)
    for drawing in page.get_drawings():
        color = drawing["color"]
        if not color or max(color) - min(color) < .15:
            continue
        key = tuple(round(c, 3) for c in color)
        for item in drawing["items"]:
            if item[0] not in {"l", "c"}:
                continue
            a, b = item[1], item[-1]
            point = lambda p: (round(p.x, 2), round(p.y, 2))
            if point(a) != point(b):
                edges[key].append((point(a), point(b)))
    result = []
    for color, segments in sorted(edges.items()):
        adjacency = collections.defaultdict(set)
        for a, b in segments:
            adjacency[a].add(b)
            adjacency[b].add(a)
        remaining = set(adjacency)
        components = []
        while remaining:
            pending = [min(remaining)]
            visited = set()
            while pending:
                point = pending.pop()
                if point in visited:
                    continue
                visited.add(point)
                pending.extend(adjacency[point] - visited)
            remaining.difference_update(visited)
            degrees = collections.Counter(len(adjacency[p]) for p in visited)
            components.append({"vertices": len(visited), "open_ends": degrees[1],
                               "branch_vertices": sum(n for degree, n in degrees.items() if degree > 2)})
        result.append({"rgb": color, "stroke_segments": len(segments),
                       "components": len(components), "component_diagnostics": components})
    return {"coordinate_rounding_pdf_points": .01, "minimum_rgb_range": .15,
            "colors": result, "interpretation": "PDF stroke components only; not validated molecular routing"}
