#!/usr/bin/env python3
"""
NAMD 3.0.2 comprehensive benchmark — AMD Ryzen 9 9950X + RTX 3080 Ti.

Sweeps:
  • Thread count × GPU mode (standard CUDA, GPU-resident) × system size
  • fullElectFrequency 1 vs 2 on B-tube 1×
  • CPU-only baseline on single helix

Systems start from validated restart files (not raw PDB) so minimization
is skipped and performance numbers are immediately representative.
"""

import os, re, json, time, subprocess
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

# ── Paths ──────────────────────────────────────────────────────────────────────
NAMD  = "/home/jojo/Applications/NAMD_3.0.2/namd3"
BASE  = Path("/home/jojo/Work/NADOC/experiments/exp23_periodic_cell_benchmark/results")
F013  = Path("/home/jojo/Work/NADOC/experiments/exp25_full_origami_relaxation"
             "/results/runs/F013_explicit_mg_full/B_tube_namd_solvated")
OUT   = Path("/home/jojo/Work/NADOC/experiments/exp26_hardware_benchmark")

THREAD_COUNTS = [4, 8, 16, 32]

# ── System definitions ─────────────────────────────────────────────────────────
# "restart" keys → start from binCoordinates/binVelocities/extendedSystem.
# None → start fresh with temperature initialisation + minimise.
SYSTEMS = {
    "single_helix": {
        "label":   "Single helix\n15,546 atoms",
        "atoms":   15_546,
        "sdir":    BASE / "single_helix_bridge_min",
        "psf":     "single_helix.psf",
        "pdb":     "single_helix.pdb",
        "cell":    (48.575, 47.700, 70.140),
        "origin":  (24.288, 23.850, 35.070),
        "ff":      ["forcefield/par_all36_na.prm",
                    "forcefield/toppar_water_ions_na.str"],
        "restart": None,             # start fresh — small system, fast to minimise
        "run_steps":  10_000,        # 20 ps
        "min_steps":     500,
        "timestep":      2.0,
        "fullElectFreq": 2,
        "timeout":     180,
        "thread_counts": THREAD_COUNTS,
    },
    "btube_1x": {
        "label":   "B-tube 1× periodic\n162,671 atoms",
        "atoms":   162_671,
        "sdir":    BASE / "hyp_runs/H012",
        "psf":     "B_tube_periodic_1x.psf",
        "pdb":     "B_tube_periodic_1x.pdb",
        "cell":    (155.602, 151.338, 70.140),
        "origin":  (80.513,  78.307,  35.070),
        "ff":      ["forcefield/par_all36_na.prm",
                    "forcefield/toppar_water_ions_na.str"],
        "restart": {
            "coor": str(BASE / "hyp_runs/H012/output/H012_k1_prod.restart.coor"),
            "vel":  str(BASE / "hyp_runs/H012/output/H012_k1_prod.restart.vel"),
            "xsc":  str(BASE / "hyp_runs/H012/output/H012_k1_prod.restart.xsc"),
        },
        "run_steps":  5_000,         # 10 ps
        "min_steps":      0,
        "timestep":      2.0,
        "fullElectFreq": 2,
        "timeout":     360,
        "thread_counts": THREAD_COUNTS,
    },
    "btube_2x": {
        "label":   "B-tube 2× periodic\n324,949 atoms",
        "atoms":   324_949,
        "sdir":    BASE / "periodic_cell_2x_run",
        "psf":     "B_tube_periodic_2x.psf",
        "pdb":     "B_tube_periodic_2x.pdb",
        "cell":    (161.061, 156.614, 140.280),
        "origin":  (80.531,  78.307,  70.140),
        "ff":      ["forcefield/par_all36_na.prm",
                    "forcefield/toppar_water_ions_na.str"],
        "restart": {
            "coor": str(BASE / "hyp_runs/H017/output/H017_k1_relax_100ps.restart.coor"),
            "vel":  str(BASE / "hyp_runs/H017/output/H017_k1_relax_100ps.restart.vel"),
            "xsc":  str(BASE / "hyp_runs/H017/output/H017_k1_relax_100ps.restart.xsc"),
        },
        "run_steps":  3_000,         # 6 ps
        "min_steps":      0,
        "timestep":      2.0,
        "fullElectFreq": 2,
        "timeout":     480,
        "thread_counts": THREAD_COUNTS,
    },
    "full_btube": {
        "label":   "Full B-tube explicit\n2,314,212 atoms",
        "atoms":   2_314_212,
        "sdir":    F013,
        "psf":     "B_tube.psf",
        "pdb":     "B_tube.pdb",
        "cell":    None,             # comes from extendedSystem
        "origin":  None,
        "ff":      ["forcefield/par_all36_na.prm",
                    "forcefield/toppar_water_ions_cufix_dna_only.str"],
        "restart": {
            "coor": str(F013 / "output/F014_20_k5_310K_NPT_20ps.restart.coor"),
            "vel":  str(F013 / "output/F014_20_k5_310K_NPT_20ps.restart.vel"),
            "xsc":  str(F013 / "output/F014_20_k5_310K_NPT_20ps.restart.xsc"),
        },
        "run_steps":   3000,         # 3 ps at 1 fs; needs ≥1000 steps for first PERFORMANCE line
        "min_steps":      0,
        "timestep":      1.0,        # production protocol uses 1 fs
        "fullElectFreq": 1,
        "timeout":     750,
        "thread_counts": [4, 8, 16, 32],   # skip p1/p2 — would take 15+ min each
    },
}


# ── Config generation ──────────────────────────────────────────────────────────
def make_conf(sname, nthreads, mode, fullElectFreq=None, label=None):
    s   = SYSTEMS[sname]
    sd  = s["sdir"]
    psf = str(sd / s["psf"])
    pdb = str(sd / s["pdb"])
    fef = fullElectFreq if fullElectFreq is not None else s["fullElectFreq"]
    ts  = s["timestep"]

    ff_lines = "\n".join(f"parameters         {sd / ff}" for ff in s["ff"])

    # PBC block — extendedSystem overrides cellBasisVector when restart present
    pbc_lines = ""
    if s["cell"] is not None:
        cx, cy, cz = s["cell"]
        ox, oy, oz = s["origin"]
        pbc_lines = (
            f"cellBasisVector1   {cx:.3f}  0.000    0.000\n"
            f"cellBasisVector2   0.000    {cy:.3f}  0.000\n"
            f"cellBasisVector3   0.000    0.000    {cz:.3f}\n"
            f"cellOrigin         {ox:.3f}  {oy:.3f}  {oz:.3f}"
        )

    soa_line = "CUDASOAintegrate    on" if mode == "gpu_resident" else ""

    out_stem = str(OUT / "bench_output" / (label or f"{sname}_{mode}_p{nthreads}_freq{fef}"))

    # Restart vs fresh start
    if s["restart"]:
        r = s["restart"]
        start_block = (
            f"binCoordinates     {r['coor']}\n"
            f"binVelocities      {r['vel']}\n"
            f"extendedSystem     {r['xsc']}"
        )
        run_block = f"run                {s['run_steps']}"
    else:
        start_block = "temperature        310"
        run_block   = (
            f"minimize           {s['min_steps']}\n"
            f"reinitvels         310\n"
            f"run                {s['run_steps']}"
        )

    conf = f"""\
# NAMD benchmark: {sname} | {mode} | +p{nthreads} | ts={ts} fs | fullElectFreq={fef}
structure          {psf}
coordinates        {pdb}

paraTypeCharmm     on
{ff_lines}

{pbc_lines}

wrapAll            on
wrapWater          on
wrapNearest        on

PME                yes
PMEGridSpacing     1.0

cutoff             12.0
switching          on
switchdist         10.0
pairlistdist       16.0
exclude            scaled1-4
oneFourScaling     1.0

rigidBonds         all
rigidTolerance     1.0e-8

langevin           on
langevinDamping    1.0
langevinTemp       310
langevinHydrogen   off

timestep           {ts}
nonbondedFreq      1
fullElectFrequency {fef}
stepspercycle      10
{soa_line}

{start_block}

outputName         {out_stem}
outputEnergies     1000
dcdFreq            999999999
xstFreq            999999999
restartfreq        999999999

{run_block}
"""
    return conf, out_stem


# ── Runner ─────────────────────────────────────────────────────────────────────
def run_namd(conf_str, nthreads, mode, timeout):
    cfg = OUT / "_tmp.conf"
    cfg.write_text(conf_str)
    cmd = [NAMD, f"+p{nthreads}", "+idlepoll"]
    if mode == "cpu_only":
        cmd += ["+devices", ""]
    t0 = time.time()
    try:
        r = subprocess.run(cmd + [str(cfg)], capture_output=True, text=True, timeout=timeout)
        elapsed = time.time() - t0
        return _parse_perf(r.stdout + r.stderr), elapsed
    except subprocess.TimeoutExpired:
        return None, time.time() - t0
    except Exception:
        return None, time.time() - t0


def _parse_perf(log):
    # Primary: PERFORMANCE lines (printed at each outputEnergies interval)
    matches = re.findall(r"PERFORMANCE:\s+\d+\s+averaging\s+([\d.]+)\s+ns/day", log)
    if matches:
        tail = [float(v) for v in matches[-min(5, len(matches)):]]
        return float(np.mean(tail))
    # Fallback: "Info: Initial time: N CPUs X.XXX s/step Y.YYY days/ns"
    init_matches = re.findall(r"Info: Initial time:.*?([\d.]+)\s+days/ns", log)
    if init_matches:
        tail = [1.0 / float(v) for v in init_matches[-min(5, len(init_matches)):]]
        return float(np.mean(tail))
    return None


# ── Benchmark suite ────────────────────────────────────────────────────────────
def run_all(force=False):
    rfile = OUT / "benchmark_results.json"
    results = json.loads(rfile.read_text()) if (rfile.exists() and not force) else {}

    (OUT / "bench_output").mkdir(exist_ok=True)

    def _run(key, sname, mode, nthreads, freq):
        if key in results and results[key].get("ns_per_day") is not None and not force:
            print(f"  skip (cached) {key}: {results[key]['ns_per_day']:.3f} ns/day")
            return
        print(f"  → {key} ...", end="", flush=True)
        conf, _ = make_conf(sname, nthreads, mode, freq, label=key)
        ns, elapsed = run_namd(conf, nthreads, mode, SYSTEMS[sname]["timeout"])
        results[key] = dict(system=sname, mode=mode, threads=nthreads,
                            fullElectFreq=freq, ns_per_day=ns,
                            elapsed_s=round(elapsed, 1))
        tag = f"{ns:.3f} ns/day" if ns else "FAILED"
        print(f" {tag} ({elapsed:.0f}s)")
        rfile.write_text(json.dumps(results, indent=2))

    # 1. Main thread sweep: all systems × standard CUDA + GPU-resident
    for sname in ["single_helix", "btube_1x", "btube_2x", "full_btube"]:
        tc = SYSTEMS[sname]["thread_counts"]
        fef = SYSTEMS[sname]["fullElectFreq"]
        print(f"\n[{sname}]")
        for mode in ["standard_cuda", "gpu_resident"]:
            for nt in tc:
                _run(f"{sname}__{mode}__p{nt}__freq{fef}", sname, mode, nt, fef)

    # 2. fullElectFrequency sweep on btube_1x (standard CUDA only)
    print("\n[btube_1x — fullElectFrequency 1 sweep]")
    for nt in SYSTEMS["btube_1x"]["thread_counts"]:
        _run(f"btube_1x__standard_cuda__p{nt}__freq1", "btube_1x", "standard_cuda", nt, 1)

    # (CPU-only skipped: NAMD build is CUDA-only, +devices "" has no effect)

    return results


# ── Figure ─────────────────────────────────────────────────────────────────────
SYS_COLOR  = {"single_helix": "#2196F3", "btube_1x": "#FF9800",
               "btube_2x": "#4CAF50",    "full_btube": "#9C27B0"}
SYS_MARKER = {"single_helix": "o", "btube_1x": "s", "btube_2x": "^", "full_btube": "D"}
MODE_LABEL = {"standard_cuda": "Standard CUDA", "gpu_resident": "GPU-resident",
              "cpu_only": "CPU-only"}
FREQ_COLOR = {1: "#C62828", 2: "#1565C0"}


def _get(results, sname, mode, nt, freq=None):
    fef = freq if freq is not None else SYSTEMS[sname]["fullElectFreq"]
    k = f"{sname}__{mode}__p{nt}__freq{fef}"
    r = results.get(k)
    return r["ns_per_day"] if (r and r.get("ns_per_day")) else None


def _best(results, sname, modes=("standard_cuda", "gpu_resident")):
    best_ns, best_nt, best_mode = 0, None, None
    for mode in modes:
        for nt in SYSTEMS[sname]["thread_counts"]:
            v = _get(results, sname, mode, nt)
            if v and v > best_ns:
                best_ns, best_nt, best_mode = v, nt, mode
    return best_ns, best_nt, best_mode


def make_figure(results):
    systems = ["single_helix", "btube_1x", "btube_2x", "full_btube"]

    fig = plt.figure(figsize=(20, 13))
    fig.patch.set_facecolor("white")
    gs = gridspec.GridSpec(2, 3, figure=fig,
                           hspace=0.40, wspace=0.30,
                           left=0.06, right=0.98, top=0.91, bottom=0.07)
    ax_A = fig.add_subplot(gs[0, 0])   # thread scaling — standard CUDA
    ax_B = fig.add_subplot(gs[0, 1])   # thread scaling — GPU-resident
    ax_C = fig.add_subplot(gs[0, 2])   # single-helix all modes (CPU-only vs GPU)
    ax_D = fig.add_subplot(gs[1, 0])   # size scaling at optimal threads
    ax_E = fig.add_subplot(gs[1, 1])   # GPU-resident / standard ratio
    ax_F = fig.add_subplot(gs[1, 2])   # fullElectFreq + summary

    # ── A: Standard CUDA thread scaling ───────────────────────────────────────
    for sname in systems:
        xs, ys = [], []
        for nt in SYSTEMS[sname]["thread_counts"]:
            v = _get(results, sname, "standard_cuda", nt)
            if v:
                xs.append(nt); ys.append(v)
        if xs:
            ax_A.plot(xs, ys, f"{SYS_MARKER[sname]}-",
                      color=SYS_COLOR[sname], lw=2, ms=8,
                      label=SYSTEMS[sname]["label"].replace("\n", "  "))
    ax_A.set_xlabel("CPU threads (+pN)", fontsize=10)
    ax_A.set_ylabel("Performance (ns/day)", fontsize=10)
    ax_A.set_title("A  Standard CUDA — thread scaling", fontweight="bold")
    ax_A.set_xticks(THREAD_COUNTS)
    ax_A.legend(fontsize=7.5, loc="upper left")
    ax_A.grid(True, alpha=0.3)
    ax_A.set_xlim(0, 34)

    # ── B: GPU-resident thread scaling ────────────────────────────────────────
    any_data = False
    for sname in systems:
        xs, ys = [], []
        for nt in SYSTEMS[sname]["thread_counts"]:
            v = _get(results, sname, "gpu_resident", nt)
            if v:
                xs.append(nt); ys.append(v)
        if xs:
            ax_B.plot(xs, ys, f"{SYS_MARKER[sname]}--",
                      color=SYS_COLOR[sname], lw=2, ms=8,
                      label=SYSTEMS[sname]["label"].replace("\n", "  "))
            any_data = True
    if not any_data:
        ax_B.text(0.5, 0.5, "GPU-resident mode\nnot supported\n(wrap-bond systems)",
                  ha="center", va="center", transform=ax_B.transAxes, fontsize=12)
    ax_B.set_xlabel("CPU threads (+pN)", fontsize=10)
    ax_B.set_ylabel("Performance (ns/day)", fontsize=10)
    ax_B.set_title("B  GPU-resident — thread scaling", fontweight="bold")
    ax_B.set_xticks(THREAD_COUNTS)
    ax_B.legend(fontsize=7.5, loc="upper left")
    ax_B.grid(True, alpha=0.3)
    ax_B.set_xlim(0, 34)

    # ── C: Standard CUDA vs GPU-resident on single helix ─────────────────────
    sname = "single_helix"
    for mode, (fmt, col) in [("standard_cuda", ("o-",  SYS_COLOR[sname])),
                               ("gpu_resident",  ("s--", "#7B1FA2"))]:
        xs, ys = [], []
        for nt in THREAD_COUNTS:
            v = _get(results, sname, mode, nt, freq=2)
            if v:
                xs.append(nt); ys.append(v)
        if xs:
            ax_C.plot(xs, ys, fmt, color=col, lw=2, ms=7, label=MODE_LABEL[mode])
    ax_C.set_xlabel("CPU threads (+pN)", fontsize=10)
    ax_C.set_ylabel("Performance (ns/day)", fontsize=10)
    ax_C.set_title("C  Single helix: std CUDA vs GPU-resident\n(15,546 atoms)",
                   fontweight="bold")
    ax_C.set_xticks(THREAD_COUNTS)
    ax_C.legend(fontsize=9)
    ax_C.grid(True, alpha=0.3)
    ax_C.set_xlim(0, 34)

    # ── D: System-size scaling at optimal threads (log-log) ───────────────────
    for mode in ["standard_cuda", "gpu_resident"]:
        xs, ys, annots = [], [], []
        for sname in systems:
            best_ns, best_nt, _ = _best(results, sname, modes=(mode,))
            if best_ns > 0:
                xs.append(SYSTEMS[sname]["atoms"])
                ys.append(best_ns)
                annots.append(f"+p{best_nt}")
        if xs:
            fmt = "o-" if mode == "standard_cuda" else "s--"
            col = "#1A237E" if mode == "standard_cuda" else "#880E4F"
            ax_D.loglog(xs, ys, fmt, color=col, lw=2, ms=9,
                        label=MODE_LABEL[mode])
            for x, y, a in zip(xs, ys, annots):
                ax_D.annotate(a, (x, y), textcoords="offset points",
                              xytext=(5, 3), fontsize=7.5, color=col)
    ax_D.set_xlabel("System size (atoms)", fontsize=10)
    ax_D.set_ylabel("Peak performance (ns/day)", fontsize=10)
    ax_D.set_title("D  Size scaling at optimal threads", fontweight="bold")
    ax_D.legend(fontsize=9)
    ax_D.grid(True, alpha=0.3, which="both")

    # ── E: GPU-resident / standard-CUDA speedup ratio ─────────────────────────
    x_pos = np.arange(len(THREAD_COUNTS))
    w = 0.2
    for i, sname in enumerate(systems):
        ratios = []
        for nt in THREAD_COUNTS:
            v_std = _get(results, sname, "standard_cuda", nt)
            v_gpu = _get(results, sname, "gpu_resident",  nt)
            if v_std and v_gpu:
                ratios.append(v_gpu / v_std)
            else:
                ratios.append(np.nan)
        valid = any(not np.isnan(r) for r in ratios)
        if valid:
            ax_E.bar(x_pos + i * w, ratios, w,
                     label=SYSTEMS[sname]["label"].split("\n")[0],
                     color=SYS_COLOR[sname], alpha=0.85)
    ax_E.axhline(1.0, color="red", lw=1.5, ls="--", label="Parity")
    ax_E.set_xlabel("CPU threads", fontsize=10)
    ax_E.set_ylabel("GPU-resident / Standard CUDA", fontsize=10)
    ax_E.set_title("E  GPU-resident speedup ratio\n(>1.0 = GPU-resident faster)",
                   fontweight="bold")
    ax_E.set_xticks(x_pos + 1.5 * w)
    ax_E.set_xticklabels(THREAD_COUNTS)
    ax_E.legend(fontsize=7.5)
    ax_E.grid(True, alpha=0.3, axis="y")

    # ── F: fullElectFrequency comparison + summary text ───────────────────────
    ax_F.axis("off")
    ax_Fa = ax_F.inset_axes([0.0, 0.44, 1.0, 0.56])
    ax_Fb = ax_F.inset_axes([0.0, 0.00, 1.0, 0.40])

    for freq in [2, 1]:
        xs, ys = [], []
        for nt in THREAD_COUNTS:
            v = _get(results, "btube_1x", "standard_cuda", nt, freq=freq)
            if v:
                xs.append(nt); ys.append(v)
        if xs:
            ax_Fa.plot(xs, ys, "o-" if freq == 2 else "s--",
                       color=FREQ_COLOR[freq], lw=2, ms=7,
                       label=f"fullElectFreq = {freq}")
    ax_Fa.set_xlabel("CPU threads", fontsize=9)
    ax_Fa.set_ylabel("ns/day", fontsize=9)
    ax_Fa.set_title("F  fullElectFrequency 1 vs 2\n(B-tube 1×, standard CUDA)",
                    fontweight="bold", fontsize=9)
    ax_Fa.set_xticks(THREAD_COUNTS)
    ax_Fa.tick_params(labelsize=8)
    ax_Fa.legend(fontsize=8)
    ax_Fa.grid(True, alpha=0.3)

    # Summary table
    lines = [
        "HARDWARE",
        "  CPU : AMD Ryzen 9 9950X (16c / 32t)",
        "  GPU : NVIDIA RTX 3080 Ti  12 GB",
        "  NAMD: 3.0.2  CUDA 13.0 build",
        "",
        "PEAK PERFORMANCE",
        f"  {'System':<24} {'ns/day':>8}  {'Threads':>8}  Mode",
        "  " + "─" * 54,
    ]
    for sname in systems:
        best_ns, best_nt, best_mode = _best(results, sname)
        val  = f"{best_ns:.1f}"  if best_ns  else "—"
        ntag = f"+p{best_nt}"   if best_nt  else "—"
        tag  = (MODE_LABEL.get(best_mode, "") or "—")[:16]
        short = SYSTEMS[sname]["label"].split("\n")[0][:24]
        lines.append(f"  {short:<24} {val:>8}  {ntag:>8}  {tag}")

    # fullElectFrequency summary
    lines += ["", "fullElectFreq impact (B-tube 1×, std CUDA)"]
    for freq in [2, 1]:
        vals = [_get(results, "btube_1x", "standard_cuda", nt, freq=freq)
                for nt in THREAD_COUNTS]
        vals = [v for v in vals if v]
        if vals:
            lines.append(f"  freq={freq}  peak {max(vals):.1f} ns/day")

    ax_Fb.text(0.03, 0.97, "\n".join(lines),
               transform=ax_Fb.transAxes, fontsize=7.5,
               fontfamily="monospace", va="top", ha="left",
               bbox=dict(boxstyle="round", facecolor="#f5f5f5", alpha=0.9))
    ax_Fb.axis("off")

    fig.suptitle(
        "NAMD 3.0.2 Performance Benchmark\n"
        "AMD Ryzen 9 9950X (16c/32t)  ·  NVIDIA RTX 3080 Ti 12 GB  ·  CUDA 13.0",
        fontsize=13, fontweight="bold", y=0.975,
    )

    out_png = OUT / "namd_benchmark.png"
    fig.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"\nFigure saved → {out_png}")
    return out_png


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--rerun",     action="store_true")
    ap.add_argument("--plot-only", action="store_true")
    args = ap.parse_args()

    rfile = OUT / "benchmark_results.json"
    if args.plot_only and rfile.exists():
        results = json.loads(rfile.read_text())
    else:
        results = run_all(force=args.rerun)

    make_figure(results)
    print("Done.")
