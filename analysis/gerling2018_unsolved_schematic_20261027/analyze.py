"""Compare unresolved sequence fragments with wide schematic intervals.

The global projection is a diagnostic of the existing, unverified 5292-base
route at offset17, NOT a recovered 7560-base helix map. Whole-staple IDs are
published workbook IDs; displayed helices use the viewer labels.
"""
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle
import numpy as np
import pymupdf

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
PREV = ROOT / "analysis/gerling2018_revnano_variations_20261027"
ARCHIVE = Path("/media/jojo/Archive/NADOC_archive/design_reconstruction/gerling2018")
SOURCE = ROOT / "workspace/Gerling2018_FigS1_42hb_CONTROL_traced_staples_v4.nadoc"
N, OFFSET = 7560, 17


def save_csv(filename, rows):
    with (OUT / filename).open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    source_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    design = json.loads(SOURCE.read_text())
    scaffold = next(s for s in design["strands"] if s["strand_type"] == "scaffold")
    helix_index = {h["id"]: i for i, h in enumerate(design["helices"])}
    labels = [str(h["label"] if h["label"] is not None else i) for i, h in enumerate(design["helices"])]
    walk = []
    for domain in scaffold["domains"]:
        a, b = domain["start_bp"], domain["end_bp"]
        step = 1 if a <= b else -1
        walk.extend((helix_index[domain["helix_id"]], bp) for bp in range(a, b+step, step))
    assert len(walk) == len(set(walk)) == 5292
    projection = {(i+OFFSET) % N: location for i, location in enumerate(walk)}
    calibration = json.loads((ARCHIVE / "staples_v4/figure_mapping.json").read_text())
    xs, bs = calibration["x_anchors"], calibration["bp_anchors"]
    gaps = np.diff(xs)
    baseline = float(np.median(sorted(gaps)[:(len(gaps)+1)//2]))
    bands = [{"start_bp": bs[i]+1, "end_bp": bs[i+1],
              "left_anchor_bp": bs[i], "right_anchor_bp": bs[i+1],
              "left_pdf_x": xs[i], "right_pdf_x": xs[i+1],
              "drawing_gap_ratio": float(gap/baseline)}
             for i, gap in enumerate(gaps) if gap > 1.65*baseline]
    assert [(b["start_bp"], b["end_bp"]) for b in bands] == [(28,34),(49,55),(70,76),(91,97)]

    def in_band(bp):
        return any(b["start_bp"] <= bp <= b["end_bp"] for b in bands)

    best = json.loads((PREV / "selected_best.json").read_text())["42hb13"]
    trial = ROOT / best["path"]
    annotations = json.loads((trial / "annotations.json").read_text())
    reference = json.loads((ROOT / "backend/data/gerling2018_42hb13.json").read_text())["sequences"]
    st, sc, circular = json.loads((PREV / "42hb13_best_contactmap.json").read_text())
    assert circular
    diagnosis = list(csv.DictReader((PREV / "42hb13_fragment_diagnosis.csv").open()))
    scaffold_sequence = (ROOT / "backend/core/p7560.txt").read_text().strip()
    complement = scaffold_sequence.translate(str.maketrans("ACGT", "TGCA"))
    mask = np.zeros(N, dtype=int)
    owners = {}
    source_blocks = []
    for row in diagnosis:
        status = "placed" if row["whole_staple_placed"] == "True" else "unresolved"
        route = json.loads(row["scaffold_route_0based"])
        indices = [(first-k) % N for first, length in route for k in range(length)]
        if indices:
            assert "".join(complement[p] for p in indices) == row["sequence"]
        for p in indices:
            assert p not in owners
            mask[p] = 1 if status == "placed" else 2
            owners[p] = int(row["published_id"])
        source_blocks.append((row, status, indices))
    assert sum(mask == 1) == 6071 and sum(mask == 2) == 910
    for sid, staple in st.items():
        for p in staple["base_i53"]:
            if p >= 0:
                assert mask[p] == 1 and owners[p] == reference[int(sid)]["index"]
    statistics, by_staple = Counter(), {}
    for i, r in enumerate(reference):
        by_staple[r["index"]] = {"published_id": r["index"],
            "whole_staple_status": "placed" if str(i) in st else "unresolved",
            "candidate_paired_nt": sum(s["length"] for s in annotations[i]["segments"] if s["kind"] == "paired_candidate"),
            "fragment_mapped_nt": 0, "projected_inside_nt": 0, "projected_outside_nt": 0,
            "fragment_nt_outside_native_route": 0, "projected_helix_labels": set()}
    projected_rows = []
    for row, status, indices in source_blocks:
        record = by_staple[int(row["published_id"])]
        record["fragment_mapped_nt"] += len(indices)
        for k, p in enumerate(indices):
            if p not in projection:
                record["fragment_nt_outside_native_route"] += 1
                continue
            h, bp = projection[p]
            region = "inside" if in_band(bp) else "outside"
            statistics[status, region] += 1
            record[f"projected_{region}_nt"] += 1
            record["projected_helix_labels"].add(labels[h])
            projected_rows.append({"published_id": row["published_id"], "status": status,
                "staple_base_1based": int(row["paired_block_start_1based"])+k,
                "scaffold_index_0based": p, "helix_label": labels[h], "bp": bp,
                "in_wide_interval": in_band(bp), "evidence": "unverified_native_route_offset17_projection"})
    for r in by_staple.values():
        r["projected_helix_labels"] = ";".join(sorted(r["projected_helix_labels"], key=int))
        r["candidate_nt_without_fragment_route"] = r["candidate_paired_nt"]-r["fragment_mapped_nt"]
    save_csv("published_staple_projection.csv", list(by_staple.values()))
    save_csv("projected_bases.csv", projected_rows)
    band_rows = []
    for band in bands:
        positions = [p for p, (_, bp) in projection.items() if band["start_bp"] <= bp <= band["end_bp"]]
        counts = Counter(mask[p] for p in positions)
        band_rows.append({**band, "native_scaffold_sites": len(positions),
                          "placed_nt": counts[1], "unresolved_fragment_nt": counts[2],
                          "no_fragment_route_nt": counts[0],
                          "unresolved_share_of_sequence_mapped_nt": counts[2]/(counts[1]+counts[2])})
    save_csv("wide_interval_counts.csv", band_rows)
    summary = {"source_sha256": source_hash, "scaffold_offset": OFFSET,
               "projection_status": "hypothesis; global 7560-base helix routing is not reconstructed",
               "native_routed_bases": len(walk), "native_bases_in_wide_intervals": sum(in_band(bp) for _, bp in walk),
               "bands": band_rows, "by_status": {},
               "independent_path_evidence": [
                   {"published_id": 46, "path_0based": 203, "status": "unresolved",
                    "helix_labels": ["40", "41"], "bp_span_after_local_nick_correction": [21,37],
                    "overlaps_wide_interval": True,
                    "evidence": "previous whole-oligo local reconstruction, three scaffold-junction alternatives"},
                   {"published_id": 142, "path_0based": 208, "status": "unresolved",
                    "helix_labels_in_path_order": ["41","40","31","30"], "bp_span": [14,27],
                    "overlaps_wide_interval": False,
                    "evidence": "previous two-domain prefix identifies path; remaining sequence-to-domain assignments unverified"}
               ]}
    for status in ("placed", "unresolved"):
        records = [r for r in by_staple.values() if r["whole_staple_status"] == status]
        inside, outside = statistics[status, "inside"], statistics[status, "outside"]
        summary["by_status"][status] = {
            "staples_total": len(records), "staples_with_projected_fragments": sum(r["projected_inside_nt"]+r["projected_outside_nt"] > 0 for r in records),
            "staples_touching_wide_intervals": sum(r["projected_inside_nt"] > 0 for r in records),
            "inside_nt": inside, "outside_nt": outside, "projected_nt": inside+outside,
            "fraction_inside": inside/(inside+outside),
            "candidate_paired_nt": sum(r["candidate_paired_nt"] for r in records),
            "fragment_mapped_nt": sum(r["fragment_mapped_nt"] for r in records)}
    summary["inside_fraction_ratio_unresolved_vs_placed"] = summary["by_status"]["unresolved"]["fraction_inside"]/summary["by_status"]["placed"]["fraction_inside"]
    # Offset sensitivity is a diagnostic, not a null-hypothesis significance test.
    template = np.zeros(N)
    for i, (_, bp) in enumerate(walk):
        template[i] = in_band(bp)
    route_template = np.zeros(N)
    route_template[:len(walk)] = 1
    fractions = {}
    sensitivity = []
    for code, status in ((1, "placed"), (2, "unresolved")):
        m = (mask == code).astype(float)
        inside = np.rint(np.fft.ifft(np.conj(np.fft.fft(template))*np.fft.fft(m)).real).astype(int)
        total = np.rint(np.fft.ifft(np.conj(np.fft.fft(route_template))*np.fft.fft(m)).real).astype(int)
        assert inside[OFFSET] == statistics[status, "inside"] and total[OFFSET] == sum(statistics[status, r] for r in ("inside", "outside"))
        fractions[status] = inside/total
    for offset in range(OFFSET-7, OFFSET+8):
        sensitivity.append({"offset": offset,
            "unresolved_inside_fraction": fractions["unresolved"][offset],
            "placed_inside_fraction": fractions["placed"][offset],
            "fraction_ratio": fractions["unresolved"][offset]/fractions["placed"][offset]})
    save_csv("offset_sensitivity.csv", sensitivity)
    summary["nearby_offset_sensitivity_ratio_range"] = [min(r["fraction_ratio"] for r in sensitivity), max(r["fraction_ratio"] for r in sensitivity)]
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2)+"\n")

    # Scientific visualization of the provisional projection, with observed wide
    # intervals outlined and unassigned sequence evidence kept visibly separate.
    lo, hi = min(b for _, b in walk), max(b for _, b in walk)
    grid = np.full((42, hi-lo+1), -1)
    for p, (h, bp) in projection.items():
        grid[h, bp-lo] = mask[p]
    colors = ListedColormap(["white", "#dde2e6", "#668ba8", "#d76b25"])
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(14, 9), gridspec_kw={"width_ratios": [3.2, 1]})
    fig.subplots_adjust(left=.055, right=.98, top=.82, bottom=.22, wspace=.23)
    ax.imshow(grid, cmap=colors, norm=BoundaryNorm([-1.5,-.5,.5,1.5,2.5], colors.N),
              aspect="auto", interpolation="nearest", extent=(lo-.5,hi+.5,41.5,-.5))
    for band in bands:
        ax.add_patch(Rectangle((band["start_bp"]-.5,-.5), 7, 42, fill=False, edgecolor="#9b7509", linewidth=1.8))
        ax.text((band["start_bp"]+band["end_bp"])/2, -1.35,
                f"{band['start_bp']}–{band['end_bp']}", ha="center", fontsize=9, color="#886400")
    ax.set_yticks(range(42), labels=labels, fontsize=8)
    ax.set_xticks(range(0, 121, 7))
    ax.tick_params(axis="x", rotation=90)
    ax.set(xlabel="Provisional schematic BP coordinate", ylabel="Visible helix label")
    ax.set_title("Projected sequence evidence; outlines mark wide drawing intervals", pad=28)
    ax.legend(handles=[Patch(color="#668ba8",label="Placed whole staple"),
                       Patch(color="#d76b25",label="Mapped fragment of unresolved staple"),
                       Patch(color="#dde2e6",label="No mapped fragment")],
              loc="upper center", bbox_to_anchor=(.5,-.17), ncol=1, fontsize=9)
    values = [100*summary["by_status"][s]["fraction_inside"] for s in ("unresolved", "placed")]
    bx.bar([0,1], values, color=["#d76b25", "#668ba8"], width=.65)
    bx.axhline(100*summary["native_bases_in_wide_intervals"]/len(walk), color="#9b7509", ls="--", lw=1.5)
    for x, value in enumerate(values):
        bx.text(x, value+1, f"{value:.1f}%", ha="center", fontsize=13)
    bx.set(xticks=[0,1], xticklabels=["Unresolved\nfragments", "Placed\nstaples"], ylim=(0,40),
           ylabel="Projected bases inside wide intervals (%)", title="Small difference")
    bx.text(.5, -.13, "700 / 1,388 candidate bases\nof unresolved staples can\nbe projected in this test.\n\nDashed: 22.2% of native\nrouted sites lie in the bands.",
            transform=bx.transAxes, ha="center", va="top", fontsize=10, color="#536275", linespacing=1.5)
    fig.suptitle("Gerling Fig. S1 — provisional projection of unresolved staples\nAssumes the existing 5,292-base route and p7560 offset 17; geometry is unverified", fontsize=15)
    for suffix in ("png", "svg"):
        fig.savefig(OUT / f"provisional_projection.{suffix}", dpi=170)
    plt.close(fig)

    # Actual figure paths give a separate, better grounded local cross-check.
    pdf = pymupdf.open(ARCHIVE / "aau1157_SM.pdf")
    gray = [d for d in pdf[2].get_drawings() if d["color"] and .53 < d["color"][0] < .54]
    assert len(gray) == 213
    ys = sorted({round(p.y,3) for d in gray for item in d["items"] for p in (item[1], item[-1])})
    assert len(ys) == 42
    fig, ax = plt.subplots(figsize=(13, 5.4))
    fig.subplots_adjust(left=.06, right=.99, top=.81, bottom=.19)
    for band in bands:
        ax.axvspan(band["left_pdf_x"], band["right_pdf_x"], color="#e0bb54", alpha=.22)
        ax.text((band["left_pdf_x"]+band["right_pdf_x"])/2, ys[29]-.7,
                f"BP {band['start_bp']}–{band['end_bp']}", ha="center", va="bottom", fontsize=10)
    for index, drawing in enumerate(gray):
        highlighted = index in (203, 208)
        color = {203: "#d76b25", 208: "#078087"}.get(index, "#c4cbd1")
        for item in drawing["items"]:
            points = item[1:]
            if item[0] == "l":
                arr = np.array([[p.x, p.y] for p in points])
            elif item[0] == "c":
                points = np.array([[p.x,p.y] for p in points])
                t = np.linspace(0,1,30)[:,None]
                arr = (1-t)**3*points[0]+3*(1-t)**2*t*points[1]+3*(1-t)*t*t*points[2]+t**3*points[3]
            else:
                continue
            ax.plot(arr[:,0], arr[:,1], color=color, lw=2 if highlighted else .6, zorder=3 if highlighted else 1)
    ax.set_ylim(ys[41]+1.4,ys[29]-1.5)
    ax.set_xlim(115,405)
    ax.set_yticks(ys[30:42], labels=labels[30:42])
    ax.set_xticks(xs[:-2], labels=bs[:-2])
    ax.set(xlabel="Current BP labels at calibration anchors (unequal drawing scale)", ylabel="Visible helix label")
    fig.suptitle("Two locally anchored unresolved staples on the actual Fig. S1 paths", y=.97, fontsize=14)
    ax.legend(handles=[Line2D([0],[0],color="#d76b25",lw=2,label="46: overlaps the first wide interval"),
                       Line2D([0],[0],color="#078087",lw=2,label="142: traced path lies before it (BP 14–27)")],
              loc="upper right", fontsize=9)
    fig.text(.5, .025, "Path identities come from prior local sequence reconstruction. Exact nick positions and the remaining domains of 142 remain provisional.",
             ha="center", fontsize=8)
    for suffix in ("png", "svg"):
        fig.savefig(OUT / f"anchored_paths.{suffix}", dpi=170)
    plt.close(fig)
    pdf.close()
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == source_hash
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
