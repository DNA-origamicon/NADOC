#!/usr/bin/env python3
"""PRE-FLIGHT GATE — refuse a RunPod run that is going to fail or overspend.

    python experiments/exp43_runpod_bench/preflight.py <job_id> [--budget 15]

Every check here was learned by burning a real, billing pod. NINE of the eleven bugs the
3x6x400 run found produced **no error of any kind** — the run simply cost 4x more, or
silently ran the wrong thing. A gate you must remember to run is not a gate; this one is
mechanical, and it exits non-zero.

See memory/REFERENCE_RUNPOD_RUNBOOK.md for the full protocol.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.md_cutoff import CutoffParams  # noqa: E402
from backend.core.md_job import MdJob  # noqa: E402
from backend.core.runpod_script import (  # noqa: E402
    GPU_TYPES,
    NAMD_BUILD_ARCHS,
    plan_execution,
)
from backend.core.runpod_supervisor import n_atoms_for  # noqa: E402

WORKSPACE = ROOT / "workspace"

# Measured on the RTX PRO 4500 Blackwell, 1.94M atoms, 2026-07-14. NOT the 4090
# extrapolation (20.9), which was 1.26x optimistic — the per-Matom fit does not transfer
# across architectures.
MEASURED_MS_PER_STEP_4FS = 26.4
MEASURED_MS_PER_STEP_SOFT = 51.5
SECURE_USD_PER_HR = 0.74


def _worst_intra_backbone_stretch(pdb: Path, psf: Path) -> tuple[float, str]:
    """Longest INTRA-residue covalent bond (Å) + a label. Catches the seed-builder
    phosphate-stranding bug (O5'-C5' at ~6 Å = fatal 4 fs RATTLE start) BEFORE renting
    a pod. Inter-residue O3'-P linkages wrap across the periodic box (benign), so only
    same-(seg,resid) bonds are measured. The 4 fs-proven 0xT control maxes at ~3.5 Å
    (normal crossover-junction geometry the ladder heals), so >5 Å = a real seed defect."""
    import numpy as np

    xyz, name, resid, seg = [], [], [], []
    for line in pdb.open():
        if line.startswith(("ATOM", "HETATM")):
            xyz.append((float(line[30:38]), float(line[38:46]), float(line[46:54])))
            name.append(line[12:16].strip()); resid.append(line[22:26].strip()); seg.append(line[72:76].strip())
    xyz = np.asarray(xyz)
    lines = psf.read_text().splitlines()
    bonds: list[tuple[int, int]] = []
    for i, ln in enumerate(lines):
        if "!NBOND" in ln:
            nb = int(ln.split()[0]); vals: list[int] = []; j = i + 1
            while len(vals) < nb * 2:
                vals += [int(x) for x in lines[j].split()]; j += 1
            it = iter(vals); bonds = list(zip(it, it)); break
    a = np.array([b[0] - 1 for b in bonds]); b = np.array([b[1] - 1 for b in bonds])
    d = np.linalg.norm(xyz[a] - xyz[b], axis=1)
    intra = np.array([(seg[a[k]], resid[a[k]]) == (seg[b[k]], resid[b[k]]) for k in range(len(d))])
    if not intra.any():
        return 0.0, ""
    di = np.where(intra, d, 0.0)
    k = int(di.argmax())
    return float(di[k]), f"{name[a[k]]}-{name[b[k]]} in {resid[a[k]]} {seg[a[k]]}"


class Gate:
    def __init__(self):
        self.failures: list[str] = []
        self.warnings: list[str] = []

    def check(self, ok: bool, label: str, detail: str = "", fatal: bool = True,
              on_pass: str = "") -> bool:
        """`detail` is the CONSEQUENCE of failing, so it is only shown when it applies —
        printing it next to a PASS reads as if the bad thing happened."""
        mark = "PASS" if ok else ("FAIL" if fatal else "WARN")
        note = on_pass if ok else detail
        print(f"  [{mark}] {label}" + (f"  — {note}" if note else ""))
        if not ok:
            (self.failures if fatal else self.warnings).append(f"{label}: {detail}")
        return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("job_id")
    ap.add_argument("--budget", type=float, default=15.0)
    args = ap.parse_args()

    job = MdJob.load(args.job_id, WORKSPACE)
    pkg = job.package_dir(WORKSPACE)
    g = Gate()

    print(f"\nPRE-FLIGHT  {job.job_id}  ({job.design_name})\n")

    # ── 1. The package is not degenerate ────────────────────────────────────
    # VoltronCore shipped a package with 279 coincident atoms and NAMD died with an
    # uninterpretable NaN after HOURS. The design was never at fault; the PACKAGE was.
    print("package")
    pdb = pkg / f"{job.name_stem}.pdb"
    if g.check(pdb.exists(), "structure present", str(pdb.name)):
        import numpy as np
        from scipy.spatial import cKDTree

        xyz, heavy = [], []
        with pdb.open() as fh:
            for line in fh:
                if line.startswith(("ATOM", "HETATM")):
                    xyz.append((float(line[30:38]), float(line[38:46]), float(line[46:54])))
                    el = line[76:78].strip() or line[12:16].strip().lstrip("0123456789")[:1]
                    heavy.append(el.upper() != "H")
        hv = np.asarray(xyz)[np.asarray(heavy, dtype=bool)]
        tree = cKDTree(hv)
        n_coincident = len(tree.query_pairs(r=0.05, output_type="ndarray"))
        d, _ = tree.query(hv, k=2)
        min_d = float(d[:, 1].min())
        g.check(n_coincident == 0, "0 coincident heavy pairs (<0.05 A)",
                f"{n_coincident} found — INFINITE VDW, NAMD will NaN", on_pass="0")
        g.check(min_d > 0.05, "min heavy-atom distance > 0.05 A",
                f"{min_d:.4f} A — DEGENERATE", on_pass=f"{min_d:.4f} A")

        # Seed-builder health: a catastrophic intra-residue backbone stretch (the
        # phosphate-stranding bug — O5'-C5' ~6 A on oxDNA-seeded extra bases) is a fatal
        # 4 fs RATTLE start no minimisation escapes. The 4 fs-proven 0xT control maxes at
        # ~3.5 A, so >5 A is a real defect. See NAMD_4FS_RATTLE_RESEARCH.md.
        psf = pkg / f"{job.name_stem}.psf"
        if psf.exists():
            worst, where = _worst_intra_backbone_stretch(pdb, psf)
            g.check(worst <= 5.0, "no catastrophic intra-residue backbone stretch (<5 A)",
                    f"{worst:.2f} A ({where}) — SEED DEFECT; extra-base phosphate stranded, "
                    f"4 fs will die at step 0. Re-seed (oxDNA) / check the seed builder.",
                    on_pass=f"worst {worst:.2f} A")

    manifest = json.loads((pkg / "manifest.json").read_text())

    # ── 1b. DNA sequences assigned (no poly-T scaffold) ─────────────────────
    # The 6hbx100_90deg incident: an unassigned scaffold builds as 100% thymine (atomistic
    # 'N'->'DT' default) and a full GPU run is wasted on a physically meaningless reference.
    # The build-time guard (backend.core.md_sequence_guard, in prepare_mgh_slow_release)
    # blocks NEW builds; this re-inspects the SHIPPED psf so a stale/pre-guard package can
    # never rent.
    print("\nsequences")
    psf_seq = pkg / f"{job.name_stem}.psf"
    if g.check(psf_seq.exists(), "psf present for sequence check", str(psf_seq.name)):
        import sys as _sys
        _root = str(Path(__file__).resolve().parents[2])
        if _root not in _sys.path:
            _sys.path.insert(0, _root)
        from backend.core.md_sequence_guard import psf_polyt_problems  # noqa: PLC0415
        polyt = psf_polyt_problems(psf_seq)
        g.check(not polyt, "no poly-T DNA segment (scaffold sequenced)",
                "; ".join(polyt) + " — UNSEQUENCED SCAFFOLD; assign the sequence + rebuild",
                on_pass="DNA segments mixed-sequence")

    # ── 2. The fast path is actually ON ─────────────────────────────────────
    # `fast` is a PREP-TIME flag. Without it the confs are 2 fs + offload and the HMR PSF
    # is written but referenced by NOTHING: ~4x the money for identical science.
    print("\nfast path (4 fs + HMR + GPUresident)")
    confs = sorted(pkg.glob(f"{job.name_stem}_0[1-9]*.conf"))
    fast_confs = [c for c in confs if "GPUresident" in c.read_text()]
    g.check(len(fast_confs) >= len(confs) - 1,          # the soft first chunk is exempt
            "segments use GPUresident + 4 fs",
            f"{len(fast_confs)}/{len(confs)} (the soft first chunk is correctly exempt)")
    g.check((pkg / f"{job.name_stem}_hmr.psf").exists()
            and any(f"{job.name_stem}_hmr.psf" in c.read_text() for c in confs),
            "HMR PSF exists AND is referenced",
            "written but referenced by nothing => prepped without fast=True")

    # ── 2b. GPUresident production dt must be a sanctioned value (4 or manual 2 fs) ──
    # A prior session drifted toward "accept 3.0/3.5 fs and match it" to dodge a RATTLE clash
    # on the extra-base sugars. That is forbidden: the fix for a 4 fs instability is to remove
    # the clash (oxDNA-seed the design), not to shave the timestep. 4.0 fs is the default; 2.0
    # fs is allowed ONLY as a deliberate user choice in the Advanced card (rigidBonds all,
    # GPUresident, no HMR) — never an auto downgrade. Intermediate values (2.5/3/3.5 fs) stay
    # banned. Lower dt is otherwise legitimate ONLY in the soft ramp chunk (1 fs, offload).
    # See memory/feedback_namd_4fs_production_only.md.
    _SANCTIONED_GPU_DT = (2.0, 4.0)   # 1 fs conservative runs are never GPUresident
    print("\ntimestep — GPUresident production dt must be 4 fs (or a manual 2 fs); no 2.5/3/3.5")
    bad_dt = []
    for c in confs:
        txt = c.read_text()
        m = re.search(r"^\s*timestep\s+([0-9.]+)", txt, re.M)
        if not m:
            continue
        dt = float(m.group(1))
        # The soft/declash ramp chunk (offload, no GPUresident) is exempt — it is a 1 fs
        # relaxation stage feeding production, not a production run itself.
        if "GPUresident" not in txt:
            continue
        if not any(abs(dt - v) < 1e-6 for v in _SANCTIONED_GPU_DT):
            bad_dt.append(f"{c.stem}={dt:g}fs")
    g.check(not bad_dt, "every GPUresident (production/fast) conf runs timestep 4.0 or 2.0",
            f"UNSANCTIONED PRODUCTION dt: {', '.join(bad_dt)} — only 4.0 fs (default) or a "
            f"deliberate 2.0 fs manual choice are allowed on GPUresident. Fix the clash "
            f"(oxDNA-seed the extra bases); do NOT drift to 2.5/3/3.5 fs. See "
            f"memory/feedback_namd_4fs_production_only.md",
            on_pass="all 4.0/2.0 fs")

    # ── 3. Early-stop can actually FIRE ─────────────────────────────────────
    # THE silent 4x bug. outputEnergies was a hardcoded 9600 STEPS; enabling `fast` halves
    # every chunk's step count for identical physics, so frames/chunk fell 25 -> 12, under
    # min_frames=20. The evaluator then reported HOLD for every p10 in the ladder. No error.
    print("\nearly-stop (Tier A) — the thing that makes a big ladder affordable")
    min_frames = CutoffParams().min_frames
    g.check(bool(job.early_stop_relax), "early_stop_relax is ON",
            "OFF => the full ladder: ~35 h, ~$26")
    g.check(str(getattr(job, "early_stop_tier", "B")).upper() == "A",
            "tier is A (not B)",
            "Tier B may not skip k<0.1 — HALF the ladder — and cannot fit any real budget")


    starved = []
    for c in confs:
        txt = c.read_text()
        oe = re.search(r"^outputEnergies\s+(\d+)", txt, re.M)
        run = re.search(r"^run\s+(\d+)", txt, re.M)
        if oe and run:
            frames = int(run.group(1)) // int(oe.group(1))
            if frames < min_frames:
                starved.append(f"{c.stem}={frames}")
    g.check(not starved, f"every chunk yields >= {min_frames} ENERGY frames",
            f"STARVED: {', '.join(starved)} — these will report HOLD forever and never bridge",
            on_pass=f"{len(confs)} chunks, all judgeable")

    # ── 4. Nothing will land on the system disk ─────────────────────────────
    print("\narchive")
    g.check(bool(job.archived and job.archive_path), "job is archived",
            "job_dir() would resolve to the SYSTEM DISK")
    if job.archive_path:
        g.check(not str(job.archive_path).startswith(str(WORKSPACE)),
                "archive is off the workspace", str(job.archive_path))

    # ── 5. The card can actually run the binary ─────────────────────────────
    # A wrong-arch card rents FINE and dies at step 0: "no kernel image is available".
    print("\nGPU")
    n_atoms = n_atoms_for(job, WORKSPACE)
    plan = plan_execution(n_atoms)
    bad_arch = [g_.label for g_ in GPU_TYPES if g_.sm not in NAMD_BUILD_ARCHS]
    g.check(not bad_arch, "every offered card is an arch the binary can run",
            f"{bad_arch} would rent fine and die at step 0",
            on_pass=f"{', '.join(NAMD_BUILD_ARCHS)}")
    g.check(plan["gpu"] is not None, "a card fits this system",
            plan.get("reason", ""))
    if plan["gpu"]:
        print(f"         sizing: {plan['gpu'].label}  ${plan['gpu'].usd_per_hour}/hr  "
              f"resident={plan['gpu_resident']}  ({n_atoms:,} atoms)")

    # ── 6. It fits the budget at the MEASURED rate ──────────────────────────
    print("\nbudget (at the MEASURED rate, never the predicted one)")
    segs = manifest.get("segments", [])
    soft = next((s for s in segs if s.get("soft")), None)
    # Best case: every stage bridges at its first chunk (what actually happened).
    stages = {}
    for s in segs:
        stages.setdefault(re.sub(r"_p\d+$", "", s["name"]), []).append(s)
    best_steps_fast = sum(sorted(v, key=lambda x: x["steps"])[0]["steps"]
                          for k, v in stages.items() if not (soft and soft["name"].startswith(k)))
    soft_steps = soft["steps"] if soft else 0
    best_h = (soft_steps * MEASURED_MS_PER_STEP_SOFT
              + best_steps_fast * MEASURED_MS_PER_STEP_4FS) / 1000 / 3600
    full_h = sum(s["steps"] for s in segs) * MEASURED_MS_PER_STEP_4FS / 1000 / 3600
    print(f"         ladder if every stage bridges at p10 : {best_h:5.1f} h  "
          f"${best_h * SECURE_USD_PER_HR:5.2f}")
    print(f"         ladder with NO early-stop at all     : {full_h:5.1f} h  "
          f"${full_h * SECURE_USD_PER_HR:5.2f}")
    g.check(best_h * SECURE_USD_PER_HR < args.budget,
            f"best case fits ${args.budget:.0f}",
            f"${best_h * SECURE_USD_PER_HR:.2f}")
    g.check(full_h * SECURE_USD_PER_HR < args.budget,
            f"WORST case (no bridge ever) fits ${args.budget:.0f}",
            f"${full_h * SECURE_USD_PER_HR:.2f} — the kill-switch would TRUNCATE the ladder",
            fatal=False)

    # ── verdict ─────────────────────────────────────────────────────────────
    print()
    if g.failures:
        print("*** REFUSING TO LAUNCH ***")
        for f in g.failures:
            print("  -", f)
        return 1
    if g.warnings:
        print("LAUNCH OK, with warnings:")
        for w in g.warnings:
            print("  -", w)
    else:
        print("ALL GATES PASS — clear to launch.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
