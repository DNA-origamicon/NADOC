"""Cross-reference domain-end locations and helix label sprite locations.

Example:
    uv run python scripts/domain_end_label_audit.py \
      "Examples/cadnano/Ultimate Polymer Hinge 191016.json" \
      --labels 28-33,42-45 --overhangs-only
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.blunt_ends_report import RISE, compute_domain_ends, load_design

CADNANO_TRACK_OFFSET = 0.5


def _parse_labels(text: str | None) -> set[str] | None:
    if not text:
        return None
    labels: set[str] = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            labels.update(str(i) for i in range(int(a), int(b) + 1))
        else:
            labels.add(part)
    return labels


def _label_for_helix(design, helix_id: str) -> str:
    for i, h in enumerate(design.helices):
        if h.id == helix_id:
            return str(h.label if h.label is not None else i)
    return "?"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("design_path", type=Path)
    ap.add_argument("--labels", help="Comma/range filter, e.g. 28-33,42-45")
    ap.add_argument("--overhangs-only", action="store_true")
    ap.add_argument("--spacing", type=float, default=2.5)
    args = ap.parse_args()

    design = load_design(str(args.design_path))
    label_filter = _parse_labels(args.labels)
    row_map = {h.id: i for i, h in enumerate(design.helices)}
    mid_x = sum((h.axis_start.x + h.axis_end.x) * 0.5 for h in design.helices) / max(1, len(design.helices))

    rows = []
    for e in compute_domain_ends(design):
        helix_label = _label_for_helix(design, e["helix_id"])
        if label_filter and helix_label not in label_filter:
            continue
        if args.overhangs_only and not e["overhang_id"]:
            continue

        row = row_map[e["helix_id"]]
        is_scaffold = e["strand_type"] == "scaffold"
        scaffold_is_forward = e.get("scaffold_dir", "FORWARD") == "FORWARD"
        track_offset = CADNANO_TRACK_OFFSET if is_scaffold == scaffold_is_forward else -CADNANO_TRACK_OFFSET
        cad_y = -row * args.spacing + track_offset
        ring_z = e["disk_bp"] * RISE
        label_z = ring_z + e["open_side"] * RISE
        rows.append((int(helix_label), e["disk_bp"], e, cad_y, ring_z, label_z))

    rows.sort(key=lambda r: (r[0], r[1], r[2]["overhang_id"] or ""))

    print("helix,helix_id,overhang_id,bp,disk_bp,open_side,domain_xyz,cadnano_ring_xyz,cadnano_label_xyz,label_delta_bp")
    for _, _, e, cad_y, ring_z, label_z in rows:
        domain_xyz = f"{e['x']:.3f};{e['y']:.3f};{e['z']:.3f}"
        ring_xyz = f"{mid_x:.3f};{cad_y:.3f};{ring_z:.3f}"
        label_xyz = f"{mid_x:.3f};{cad_y:.3f};{label_z:.3f}"
        print(
            f"{_label_for_helix(design, e['helix_id'])},"
            f"{e['helix_id']},"
            f"{e['overhang_id'] or ''},"
            f"{e['bp']},"
            f"{e['disk_bp']},"
            f"{e['open_side']},"
            f"{domain_xyz},"
            f"{ring_xyz},"
            f"{label_xyz},"
            f"{e['open_side']:+d}"
        )


if __name__ == "__main__":
    main()
