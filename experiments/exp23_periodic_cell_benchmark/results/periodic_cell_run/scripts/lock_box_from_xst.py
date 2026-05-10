#!/usr/bin/env python3
"""Patch locked-Z production config using averaged X/Y from an NPT XST tail."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _rows(path: Path):
    rows = []
    for line in path.read_text(errors="replace").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 13:
            continue
        try:
            rows.append([float(x) for x in parts[:13]])
        except ValueError:
            pass
    return rows


def _replace_cell(text: str, ax: float, by: float, z: float, ox: float, oy: float, oz: float) -> str:
    out = []
    for line in text.splitlines():
        key = line.split()[0] if line.split() else ""
        if key == "cellBasisVector1":
            out.append(f"cellBasisVector1   {ax:.3f}  0.000    0.000")
        elif key == "cellBasisVector2":
            out.append(f"cellBasisVector2   0.000    {by:.3f}  0.000")
        elif key == "cellBasisVector3":
            out.append(f"cellBasisVector3   0.000    0.000    {z:.3f}")
        elif key == "cellOrigin":
            out.append(f"cellOrigin         {ox:.3f}   {oy:.3f}   {oz:.3f}")
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xst", type=Path, required=True)
    ap.add_argument("--template", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--z-angstrom", type=float, required=True)
    ap.add_argument("--tail-fraction", type=float, default=0.25)
    ap.add_argument("--tail-frames", type=int, default=0)
    ap.add_argument("--json-out", type=Path, default=None)
    args = ap.parse_args()

    rows = _rows(args.xst)
    if not rows:
        raise SystemExit(f"No numeric XST rows found in {args.xst}")

    if args.tail_frames > 0:
        tail = rows[-args.tail_frames:]
    else:
        n = max(1, int(len(rows) * args.tail_fraction))
        tail = rows[-n:]

    ax = sum(r[1] for r in tail) / len(tail)
    by = sum(r[5] for r in tail) / len(tail)
    ox = sum(r[10] for r in tail) / len(tail)
    oy = sum(r[11] for r in tail) / len(tail)
    oz = sum(r[12] for r in tail) / len(tail)

    patched = _replace_cell(args.template.read_text(), ax, by, args.z_angstrom, ox, oy, oz)
    args.out.write_text(patched)
    json_out = args.json_out or args.out.with_suffix(args.out.suffix + ".lock.json")
    json_out.write_text(json.dumps({
        "xst": str(args.xst),
        "template": str(args.template),
        "out": str(args.out),
        "tail_fraction": args.tail_fraction,
        "tail_frames_requested": args.tail_frames,
        "tail_frames_used": len(tail),
        "rows_total": len(rows),
        "locked_box_angstrom": {"x": ax, "y": by, "z": args.z_angstrom},
        "origin_angstrom": {"x": ox, "y": oy, "z": oz},
        "source_tail_mean_z_angstrom": sum(r[9] for r in tail) / len(tail),
    }, indent=2))
    print(f"Wrote {args.out}")
    print(f"Wrote {json_out}")
    print(f"Tail frames: {len(tail)} / {len(rows)}")
    print(f"Locked box: X={ax:.3f} Å  Y={by:.3f} Å  Z={args.z_angstrom:.3f} Å")
    print(f"Origin:     X={ox:.3f} Å  Y={oy:.3f} Å  Z={oz:.3f} Å")


if __name__ == "__main__":
    main()
