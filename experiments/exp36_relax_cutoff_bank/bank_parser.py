#!/usr/bin/env python3
"""exp36 relaxation-cutoff reference-bank parser.

Turns one NAMD job's on-disk artifacts (job.json + package/.../*.log +
output/health.jsonl) into three tidy TSV tables:

  frames.tsv   - one row per ENERGY frame (the dense clock), global step axis,
                 decoded k/ensemble, POTENTIAL/VOLUME/TEMP, per-atom energy,
                 joined structural WC/C1'.
  segments.tsv - one row per ladder segment (coarse index + gate scalars).
  manifest.tsv - one row for the job (design/size/coverage/data-completeness).

Stdlib only. Format-driven: point --job at any workspace/md_jobs/<id> tree
(local or an archived copy, e.g. the 18hb) and it runs unchanged.
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path


# ---- stage / k decode --------------------------------------------------------
def decode_stage(stage: str, seg_name: str) -> dict:
    s = f"{stage} {seg_name}"
    is_min = bool(re.search(r"_00_min|minimi", s, re.I))
    ens = "min" if is_min else ("NPT" if "NPT" in s else ("NVT" if "NVT" in s else "?"))
    # k value: numeric match first ("k=0.5", "k=0", "_k0p01_"), MGHH fallback -> 0.0
    k = None
    m = re.search(r"k\s*=\s*([0-9]+(?:\.[0-9]+)?)", stage) or re.search(r"_k([0-9p]+?)_", seg_name)
    if m:
        k = float(m.group(1).replace("p", "."))
    elif re.search(r"MGHH_only|k=0(?!\.)", s):
        k = 0.0
    if is_min:
        k = None
    tm = re.search(r"(\d{3})K", s)
    temp = int(tm.group(1)) if tm else None
    return {"k": k, "ensemble": ens, "temp_target_k": temp, "is_min": is_min}


# ---- ENERGY-frame parsing (all frames; name-indexed columns) -----------------
def parse_energy_frames(log_path: Path) -> list[dict]:
    cols: list[str] | None = None
    out: list[dict] = []
    last_ts = None
    for line in log_path.read_text(errors="replace").splitlines():
        if line.startswith("ETITLE:"):
            cols = line.split()[1:]          # names; index aligns with ENERGY vals
        elif line.startswith("ENERGY:") and cols:
            vals = line.split()[1:]
            if len(vals) < len(cols):
                continue
            row = {}
            for name, v in zip(cols, vals):
                try:
                    row[name] = float(v)
                except ValueError:
                    row[name] = None
            ts = row.get("TS")
            # drop restart-replayed duplicate frame at a resume seam
            if last_ts is not None and ts is not None and ts <= last_ts:
                continue
            last_ts = ts
            out.append(row)
    return out


def segment_logs(pkg: Path, seg_name: str) -> list[Path]:
    """Primary log + any resumeN logs, in order."""
    main = pkg / f"{seg_name}.log"
    logs = [main] if main.exists() else []
    logs += sorted(pkg.glob(f"{seg_name}.resume*.log"))
    return logs


# ---- health join -------------------------------------------------------------
def load_health(output_dir: Path) -> dict[str, dict]:
    h: dict[str, dict] = {}
    p = output_dir / "health.jsonl"
    if not p.exists():
        return h
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        h[d["segment"]] = d          # last occurrence wins (dedup logging glitches)
    return h


# ---- main build --------------------------------------------------------------
def find_package(job_dir: Path) -> Path:
    cands = list(job_dir.glob("package/*_namd_solvated"))
    if not cands:
        cands = list(job_dir.glob("package/*"))
    return cands[0] if cands else job_dir


def natoms_from_psf(pkg: Path) -> int | None:
    for psf in list(pkg.glob("*.psf")) + list(pkg.glob("output/*.psf")):
        with psf.open(errors="replace") as fh:
            for _ in range(500):            # NATOM lives in the header; don't slurp a 400MB psf
                line = fh.readline()
                if not line:
                    break
                if "!NATOM" in line:
                    try:
                        return int(line.split()[0])
                    except (ValueError, IndexError):
                        pass
    return None


def build(job_dir: Path):
    job = json.loads((job_dir / "job.json").read_text())
    pkg = find_package(job_dir)
    outdir = pkg / "output"
    health = load_health(outdir)
    natoms = natoms_from_psf(pkg)
    design = job.get("design_source_path") or job.get("name")
    segs = job.get("segments", [])
    # infer design tag from segment prefix if missing
    if not design and segs:
        design = re.sub(r"_\d\d_.*", "", segs[0]["name"])
    design_inferred = not (job.get("design_source_path") or job.get("name"))
    lattice = "SQ" if re.search(r"SQ|square", str(design), re.I) else "HC"

    frames, seg_rows = [], []
    step_offset = 0
    min_k_reached = None
    for i, seg in enumerate(segs):
        name = seg["name"]
        dec = decode_stage(seg.get("stage", ""), name)
        span = seg.get("steps") or 0
        efr = []
        for lg in segment_logs(pkg, name):
            efr += parse_energy_frames(lg)
        hd = health.get(name, {})
        wc_pf = hd.get("wc_per_frame") or []
        n_wc = len(wc_pf)
        for fr in efr:
            ts = fr.get("TS") or 0
            gstep = step_offset + ts
            frac = (ts / span) if span else 0.0
            pot = fr.get("POTENTIAL")
            # as-of join WC by fractional position within the segment
            wc = None
            if n_wc:
                j = min(n_wc - 1, int(frac * n_wc))
                wc = wc_pf[j]
            frames.append({
                "job_id": job_dir.name, "design": design, "lattice": lattice,
                "seg_index": i, "segment": name, "stage": seg.get("stage", ""),
                "k": dec["k"], "restrained": (dec["k"] or 0) > 0,
                "ensemble": dec["ensemble"], "temp_target_k": dec["temp_target_k"],
                "ts_local": ts, "step_global": gstep, "frac_seg": round(frac, 4),
                "POTENTIAL": pot, "KINETIC": fr.get("KINETIC"),
                "TOTAL": fr.get("TOTAL"), "TEMP": fr.get("TEMP"),
                "VOLUME": fr.get("VOLUME"),
                "pot_per_atom": (pot / natoms) if (pot is not None and natoms) else None,
                "wc_ref_relative": wc,
                "c1_paired": hd.get("c1_paired_fraction"),
            })
        if dec["k"] is not None and (min_k_reached is None or dec["k"] < min_k_reached):
            min_k_reached = dec["k"]
        seg_rows.append({
            "job_id": job_dir.name, "seg_index": i, "segment": name,
            "stage": seg.get("stage", ""), "k": dec["k"], "ensemble": dec["ensemble"],
            "steps": span, "status": seg.get("status"), "n_energy_frames": len(efr),
            "step_start": step_offset, "step_end": step_offset + (efr[-1]["TS"] if efr else 0),
            "c1_paired_final": hd.get("c1_paired_fraction"),
            "wc_ref_relative_final": hd.get("wc_ref_relative_fraction"),
        })
        step_offset += span

    manifest = [{
        "job_id": job_dir.name, "design": design, "design_inferred": design_inferred,
        "lattice": lattice, "engine": "namd", "n_atoms": natoms,
        "status": job.get("status"), "n_segments": len(segs),
        "min_k_reached": min_k_reached, "total_steps": step_offset,
        "has_energy": any(r["n_energy_frames"] for r in seg_rows),
        "has_health": bool(health),
        "energy_frames_total": sum(r["n_energy_frames"] for r in seg_rows),
        "source": str(job_dir),
    }]
    return frames, seg_rows, manifest


def write_tsv(rows: list[dict], path: Path):
    if not rows:
        path.write_text("")
        return
    cols = list(rows[0].keys())
    with path.open("w") as f:
        f.write("\t".join(cols) + "\n")
        for r in rows:
            f.write("\t".join("" if r.get(c) is None else str(r.get(c)) for c in cols) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True, type=Path)
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "bank")
    a = ap.parse_args()
    frames, segs, manifest = build(a.job)
    a.out.mkdir(parents=True, exist_ok=True)
    write_tsv(frames, a.out / "frames.tsv")
    write_tsv(segs, a.out / "segments.tsv")
    write_tsv(manifest, a.out / "manifest.tsv")
    print(f"frames={len(frames)} segments={len(segs)} -> {a.out}")
    print(f"design={manifest[0]['design']} n_atoms={manifest[0]['n_atoms']} "
          f"min_k={manifest[0]['min_k_reached']} status={manifest[0]['status']}")


if __name__ == "__main__":
    main()
