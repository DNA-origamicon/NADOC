"""Figure-only tracing of D003 square-tile Fig.S71, with no native reference input.

Specific documented crop/legend selection; not a generic figure recognizer.
"""

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from statistics import median

import numpy as np
import pymupdf


def derive(pdf, output):
    output = Path(output)
    names = ('figure-derived.cadnano.json', 'registered.cadnano.json',
             'image-only-register-hypotheses.json', 'provenance.json')
    if any((output / name).exists() for name in names):
        raise FileExistsError('Preserve existing extraction evidence; select a new run directory')
    output.mkdir(parents=True, exist_ok=True)
    source = Path(pdf).read_bytes()
    with pymupdf.open(stream=source, filetype="pdf") as doc:
        page = doc[80]
        paths = page.get_drawings()
        words = page.get_text("words")
        labels = {
            int(w[4]): (w[1] + w[3]) / 2
            for w in words
            if w[4].isdigit() and 175 < w[0] < 187
        }
        assert set(labels) == set(range(88))
        # The printed slice view is one column of 88 numbered helices.
        cells = {n: (n, 0) for n in labels}
        chosen = [
            (i, p)
            for i, p in enumerate(paths)
            if p["type"] == "s"
            and p["color"]
            and p["rect"].x0 > 190
            and p["rect"].y0 > 108
            and p["rect"].y1 < 670
        ]
        direct = [
            (i, p)
            for i, p in chosen
            if len(p["items"]) == 1
            and p["items"][0][0] == "l"
            and abs(p["items"][0][1].y - p["items"][0][2].y) < 0.02
        ]
        redx = [
            (i, p)
            for i, p in chosen
            if "".join(q[0] for q in p["items"]) == "ll"
            and p["color"][0] > 0.79
            and p["color"][1] < 0.01
        ]
        rawstep = median(abs(p["items"][0][2].x - p["items"][0][1].x) for i, p in redx)
        xs = np.array(
            [q.x for i, p in direct for q in (p["items"][0][1], p["items"][0][2])]
        )
        origin = float(xs.min())
        candidates = np.linspace(rawstep * 0.995, rawstep * 1.005, 1001)
        rawstep = min(
            candidates,
            key=lambda s: np.mean(
                ((xs - origin) / s - np.round((xs - origin) / s)) ** 2
            ),
        )
        indices = np.round((xs - origin) / rawstep)
        step, origin = np.polyfit(indices, xs, 1)
        residual = np.abs((xs - origin) / step - indices)
        if residual.max() > 0.05:
            raise ValueError(
                "Nonuniform drawing scale: explicit piecewise calibration required"
            )
        origin -= step  # reserve the terminal base before the leftmost line edge
        # Learn label-to-track offset from observed strokes, not helix-number parity.
        offsets = [
            q.y - labels[min(labels, key=lambda n: abs(labels[n] - q.y))]
            for i, p in direct
            for q in [p["items"][0][1]]
        ]
        mid = (min(offsets) + max(offsets)) / 2
        upper = median(x for x in offsets if x < mid)
        lower = median(x for x in offsets if x > mid)
        rejected = []
        edges = defaultdict(dict)
        prev = defaultdict(dict)
        occupied = defaultdict(set)
        colors = {}
        path_ids = set()

        def address(point, center=False):
            n = min(labels, key=lambda n: abs(labels[n] - point.y))
            off = point.y - labels[n]
            rail = 0 if abs(off - upper) < abs(off - lower) else 1
            if abs(off - (upper if rail == 0 else lower)) > 0.05:
                raise ValueError("Off-track point")
            value = (point.x - origin) / step - (0.5 if center else 0)
            bp = round(value)
            if abs(value - bp) > 0.05 or bp < 0:
                raise ValueError(f"Off-grid point {point}: bp={value}")
            return (n, bp), (1 if rail == 0 else -1)

        def connect(kind, a, b, pid):
            if a in edges[kind] and edges[kind][a] != b:
                raise ValueError(f"Conflicting outgoing edges {kind} {a}")
            if b in prev[kind] and prev[kind][b] != a:
                raise ValueError(f"Conflicting incoming edges {kind} {b}")
            edges[kind][a] = b
            prev[kind][b] = a
            occupied[kind].update((a, b))
            path_ids.add(pid)

        for pid, p in chosen:
            color = p["color"]
            kind = (
                "scaf"
                if max(abs(a - b) for a, b in zip(color, [0, 0.4, 0.8])) < 0.02
                else "stap"
            )
            items = p["items"]
            shape = "".join(q[0] for q in items)
            if shape == "l" and abs(items[0][1].y - items[0][2].y) < 0.02:
                try:
                    a, da = address(items[0][1])
                    b, db = address(items[0][2])
                except ValueError as exc:
                    rejected.append([pid, shape, str(exc)])
                    continue
                if a[0] != b[0] or da != db:
                    raise ValueError("Ambiguous line traversal")
                lo, hi = sorted([a[1], b[1]])
                lo -= 1
                walk = [(a[0], x) for x in range(lo, hi + 1)]
                if da < 0:
                    walk.reverse()
                for u, v in zip(walk, walk[1:]):
                    connect(kind, u, v, pid)
                for u in walk:
                    colors[(kind, u)] = sum(
                        round(c * 255) << shift for c, shift in zip(color, [16, 8, 0])
                    )
            elif shape == "llcll":
                try:
                    a, da = address(items[0][2], center=True)
                    b, db = address(items[-1][1], center=True)
                except ValueError as exc:
                    rejected.append([pid, shape, str(exc)])
                    continue
                # The first attachment exits toward its curve, so it is 3-prime
                # iff that exit matches the independently inferred rail direction.
                exit_sign = 1 if items[0][2].x > items[0][1].x else -1
                enter_sign = 1 if items[-1][-1].x > items[-1][1].x else -1
                if (da == exit_sign) != (db == enter_sign):
                    raise ValueError("Crossover orientation conflict")
                connect(kind, a, b, pid) if da == exit_sign else connect(
                    kind, b, a, pid
                )
        indels = {}
        for pid, p in redx:
            a, b = p["items"][0][1:]
            point = pymupdf.Point((a.x + b.x) / 2, (a.y + b.y) / 2)
            site, _ = address(point, center=True)
            indels[site] = -1
        loop_symbols = []
        for pid, p in chosen:
            if "".join(q[0] for q in p["items"]) != "cc":
                continue
            anchor = p["items"][0][1]
            # caDNAno insertion glyph starts at 0.75 cell widths, not its center.
            point = pymupdf.Point(anchor.x - step * 0.25, anchor.y)
            try:
                site, _ = address(point, center=True)
            except ValueError as exc:
                rejected.append([pid, "insertion", str(exc)])
                continue
            numerals = [
                w
                for w in words
                if w[4].isdigit()
                and p["rect"].contains(
                    pymupdf.Point((w[0] + w[2]) / 2, (w[1] + w[3]) / 2)
                )
            ]
            if len(numerals) != 1:
                raise ValueError("Ambiguous insertion numeral")
            delta = int(numerals[0][4])
            loop_symbols.append([pid, site, delta])
            if site in indels and indels[site] != delta:
                raise ValueError("Conflicting indel")
            indels[site] = delta
        width = (
            (max(bp for sites in occupied.values() for n, bp in sites) + 32) // 32
        ) * 32
        v = {
            n: dict(
                num=n,
                row=cells[n][0],
                col=cells[n][1],
                scaf=[[-1] * 4 for _ in range(width)],
                stap=[[-1] * 4 for _ in range(width)],
                loop=[0] * width,
                skip=[0] * width,
                stap_colors=[],
            )
            for n in labels
        }
        for kind, sites in occupied.items():
            for site in sites:
                n, bp = site
                v[n][kind][bp] = list(prev[kind].get(site, (-1, -1))) + list(
                    edges[kind].get(site, (-1, -1))
                )
                if kind == "stap" and site not in prev[kind]:
                    v[n]["stap_colors"].append([bp, colors.get((kind, site), 0x949494)])
        for (n, bp), delta in indels.items():
            v[n]["skip" if delta == -1 else "loop"][bp] = delta
        draft = {
            "name": "D003_square_tile_image_derived_DRAFT",
            "vstrands": [v[n] for n in sorted(labels, key=labels.get)],
        }
        (output / "figure-derived.cadnano.json").write_text(json.dumps(draft, indent=2))
        provenance = {
            "extractor_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "process": [
                "Select PDF page 81 and helix labels in the declared x interval",
                "Select colored routing strokes inside the figure crop",
                "Fit base pitch from deletion marks and straight stroke endpoints",
                "Classify rails, trace directed lines/crossover curves, reject conflicting links",
                "Extract deletion/insertion marks and emit the image-derived graph",
                "Score all 32 square-register translations; require a unique winner and 90 percent support",
            ],
            "case_specific_selections": {
                "helix_label_x_interval": [175, 187], "helix_labels": [0, 87],
                "stroke_bounds": {"x0_gt": 190, "y0_gt": 108, "y1_lt": 670},
                "scaffold_rgb": [0, 0.4, 0.8], "color_tolerance": 0.02,
                "grid_fit_tolerance_bp": 0.05,
                "rail_direction_rule": "upper forward; lower reverse",
                "slice_rule": "one column; cell (printed helix label, 0)",
            },
            "source_sha256": hashlib.sha256(source).hexdigest(),
            "source_page": 81,
            "source_pdf": str(pdf),
            "native_reference_used": False,
            "selected_figure": "D003 square tile, Fig.S71",
            "x_origin": float(origin),
            "drawing_units_per_bp": float(step),
            "max_bp_fit_residual": float(residual.max()),
            "label_to_upper_track": upper,
            "label_to_lower_track": lower,
            "lattice": "square from printed cross-section",
            "cells": cells,
            "traced_path_ids": sorted(path_ids),
            "rejected_paths": rejected,
            "indels": [[*k, val] for k, val in indels.items()],
            "loop_symbols": loop_symbols,
            "occupied_sites": {k: len(v) for k, v in occupied.items()},
            "limitations": [
                "BP zero is a figure-relative origin; original absolute register is not established.",
                "Sequence and chemical functionalization are not recovered.",
                "Cross-section coordinates have a freely chosen translation.",
                "Draft requires manual inspection; not simulation validated.",
            ],
        }
        from backend.core.image_crossover_register import (
            square_register_scores,
            translate_square_indices,
        )

        scores = square_register_scores(draft)
        (output / "image-only-register-hypotheses.json").write_text(
            json.dumps(scores, indent=2)
        )
        if (
            scores[0]["total"] <= scores[1]["total"]
            or scores[0]["total"] < 0.9 * scores[0]["tested"]
        ):
            raise ValueError(
                "BP register remains ambiguous; do not create registered draft"
            )
        registered = translate_square_indices(draft, scores[0]["shift"])
        registered["name"] = "D003_square_tile_image_derived_DRAFT"
        (output / "registered.cadnano.json").write_text(
            json.dumps(registered, indent=2)
        )
        provenance["register_inference"] = {
            "selected": scores[0],
            "runner_up": scores[1],
            "method": "All32 offsets tested against generic scaffold/staple crossover tables; no deposited file input",
            "absolute_origin": "Smallest nonnegative compatible register; multiples of32 remain undetermined",
        }
        (output / "provenance.json").write_text(json.dumps(provenance, indent=2))
        print(
            json.dumps(
                {
                    k: provenance[k]
                    for k in ("occupied_sites", "max_bp_fit_residual", "rejected_paths")
                },
                indent=2,
            )
        )


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--relax', action='store_true', help='Fit the registered draft as rigid bodies with clash prevention')
    args = parser.parse_args()
    derive(args.pdf, args.output)
    if args.relax:
        from tools.design_archive.relax_image_import import write_relaxed_image_import
        report = write_relaxed_image_import(json.loads((args.output / 'registered.cadnano.json').read_text()), args.output)
        print(json.dumps(report, indent=2))
