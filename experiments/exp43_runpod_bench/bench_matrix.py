"""RunPod 4090 benchmark matrix — pure logic (stdlib only).

Imported by BOTH ``prep_bundle.py`` (locally, has NADOC) and ``run_bench.py``
(on the pod, has nothing but python3). Keep it dependency-free.

WHAT THIS MEASURES
------------------
For each *design* x *execution config*, the throughput (ns/day) and cost ($/ns)
of NADOC's real relaxation protocol on a rented RTX 4090.

Configs are the three ways NADOC can run a NAMD segment:

  conservative   rigidBonds all + 2 fs, CUDA offload      (what NADOC ships today)
  fast_offload   HMR + rigidBonds all + 4 fs, CUDA offload
  fast_resident  the above + GPUresident on               (everything stays on the card)

`fast_offload` being viable at 4 fs WITHOUT residency was established 2026-07-12
(18.8 ns/day on carved 6hbx100_90deg, T flat, zero RATTLE failures) — so do NOT
"fix" it by halving the timestep. The 4->2 fs downgrade exists only for the
pinned-host-OOM case.

DESIGN LADDER
-------------
  6hb      6hb_sim_v2 — a package that COMPLETED a full 12-segment relaxation.
           The trusted control. If this is wrong, the harness is wrong.
  flat     A single-layer sheet: a wide, thin, highly anisotropic box. Stresses
           the PME grid and patch decomposition in a way a compact brick doesn't.
  voltron  VoltronCore. Currently UNRUNNABLE — its built structure has coincident
           atoms (min inter-atomic distance 0.000 A, 891k sub-2A heavy-atom pairs
           vs 3k for 6hb). Proven broken on the CPU build too, so it is not a GPU
           problem. Kept here so the matrix documents *why* it is excluded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# NAMD requires `run` to be a multiple of stepspercycle (12 in NADOC's confs).
BENCH_STEPS = 2400  # 200 cycles
STEPSPERCYCLE = 12


# --------------------------------------------------------------------------
# Designs (a "package" = one design's solvated NAMD package on the pod)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Package:
    key: str
    label: str
    why: str
    runnable: bool = True
    blocked_reason: str = ""


PACKAGES: dict[str, Package] = {
    "6hb": Package(
        key="6hb",
        label="6hb_sim_v2",
        why="Trusted control — completed a full 12-segment relaxation locally.",
    ),
    "flat": Package(
        key="flat",
        label="1x50 flat sheet",
        why="Wide, thin, anisotropic box — stresses PME grid + patch decomposition.",
    ),
    "voltron": Package(
        key="voltron",
        label="VoltronCore",
        why=(
            "The real target. 4.7M atoms — the only design here big enough to actually "
            "stress a 24 GB card. NOTE: this must be the FRESHLY REBUILT package. The "
            "package that shipped with job f702f4a3282f was corrupt (279 coincident "
            "atoms, min distance 0.000 A) and NaN'd the minimiser at step 0; a rebuild "
            "from the same design is clean (0 coincident, min 0.408 A). The design was "
            "never the problem."
        ),
    ),
}


# --------------------------------------------------------------------------
# Execution configs
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Config:
    key: str
    timestep_fs: float
    hmr: bool
    gpu_resident: bool
    build: str  # "cuda" | "cpu"
    purpose: str

    @property
    def integrator(self) -> str:
        base = "HMR + rigidBonds all" if self.hmr else "rigidBonds all"
        return f"{base} + {self.timestep_fs:g} fs"

    @property
    def mode(self) -> str:
        if self.build == "cpu":
            return "CPU (multicore)"
        return "CUDA (GPU-resident)" if self.gpu_resident else "CUDA (offload)"


CONFIGS: list[Config] = [
    Config(
        key="conservative",
        timestep_fs=2.0,
        hmr=False,
        gpu_resident=False,
        build="cuda",
        purpose="What NADOC ships today. The baseline every speedup is measured against.",
    ),
    Config(
        key="fast_offload",
        timestep_fs=4.0,
        hmr=True,
        gpu_resident=False,
        build="cuda",
        purpose="HMR + 4 fs without residency. Expect ~2x conservative.",
    ),
    Config(
        key="fast_resident",
        timestep_fs=4.0,
        hmr=True,
        gpu_resident=True,
        build="cuda",
        purpose=(
            "Everything resident on the card. The big win when it fits — and the "
            "thing that runs out of VRAM / pinned host RAM first."
        ),
    ),
]


# --------------------------------------------------------------------------
# Cells = designs x configs
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Cell:
    cid: str
    package: str
    config: str

    @property
    def cfg(self) -> Config:
        return next(c for c in CONFIGS if c.key == self.config)

    @property
    def pkg(self) -> Package:
        return PACKAGES[self.package]


def _build_matrix() -> list[Cell]:
    cells: list[Cell] = []
    for pkey, pkg in PACKAGES.items():
        if not pkg.runnable:
            continue
        for cfg in CONFIGS:
            cells.append(Cell(cid=f"{pkey}/{cfg.key}", package=pkey, config=cfg.key))
    return cells


MATRIX: list[Cell] = _build_matrix()

# The CUDA *offload* path leans on host cores and PCIe; Community-Cloud 4090s ship
# with very different vCPU allocations. Re-run these on a second pod before
# trusting them. (GPU-resident is immune — that is the point of residency.)
HOST_SENSITIVE = tuple(c.cid for c in MATRIX if not c.cfg.gpu_resident)


# --------------------------------------------------------------------------
# Conf rewriting (pure text)
# --------------------------------------------------------------------------


def _set_key(text: str, key: str, value: str) -> str:
    pat = re.compile(rf"(?im)^([ \t]*){re.escape(key)}\b[ \t]+.*$")
    if pat.search(text):
        return pat.sub(lambda m: f"{m.group(1)}{key:<18} {value}", text, count=1)
    if not text.endswith("\n"):
        text += "\n"
    return f"{text}{key:<18} {value}\n"


def _drop_key(text: str, key: str) -> str:
    return re.sub(rf"(?im)^[ \t]*{re.escape(key)}\b[ \t]+.*$\n?", "", text)


def make_bench_conf(
    conf_text: str,
    *,
    psf: str,
    timestep_fs: float,
    gpu_resident: bool,
    run_steps: int,
    out_stem: str,
    seed_stem: str,
) -> str:
    """Turn a shipped relax conf into a short, self-contained throughput probe.

    ONLY integrator/execution knobs move. Electrostatics (PME, cutoffs), the
    barostat and the ENM restraints stay exactly as NADOC wrote them — otherwise
    we would be benchmarking a simulation nobody would ever run.
    """
    t = conf_text
    # `run` MUST be the final directive. NAMD executes it, and any parameter that
    # appears after it is a *runtime* modification of an already-finished run —
    # setting GPUresident there dies with "Can't modify CUDASOAintegrate when that
    # mode was never enabled" AFTER silently running the whole segment in offload
    # mode. So: drop `run` up front, re-append it last.
    t = _drop_key(t, "run")
    t = _set_key(t, "structure", psf)
    t = _set_key(t, "timestep", f"{timestep_fs:g}")
    t = _set_key(t, "rigidBonds", "all")

    t = _set_key(t, "binCoordinates", f"{seed_stem}.coor")
    t = _set_key(t, "binVelocities", f"{seed_stem}.vel")
    t = _set_key(t, "extendedSystem", f"{seed_stem}.xsc")
    t = _drop_key(t, "temperature")  # mutually exclusive with binVelocities

    t = _set_key(t, "outputName", out_stem)
    t = _set_key(t, "dcdFile", f"{out_stem}.dcd")
    t = _set_key(t, "xstFile", f"{out_stem}.xst")

    t = _set_key(t, "dcdFreq", "0")  # measuring compute, not disk
    t = _set_key(t, "outputEnergies", str(STEPSPERCYCLE * 10))
    t = _set_key(t, "restartfreq", str(run_steps))
    t = _set_key(t, "xstFreq", str(run_steps))

    t = _set_key(t, "GPUresident", "on") if gpu_resident else _drop_key(t, "GPUresident")

    if not t.endswith("\n"):
        t += "\n"
    return f"{t}{'run':<18} {run_steps}\n"


# --------------------------------------------------------------------------
# NAMD log parsing
# --------------------------------------------------------------------------

# NAMD reports throughput in DIFFERENT UNITS depending on execution mode:
#   CUDA offload   -> "Benchmark time: 16 CPUs 0.048 s/step 0.1398 days/ns"
#   GPU-resident   -> "Benchmark time: 16 CPUs 0.052 s/step 6.6893 ns/day"
# Parsing only one of them silently drops every cell of the other mode (the
# GPU-resident cell came back rc=0 with "no throughput" and looked like a failure).
# Only "Benchmark time" counts — "Initial time" lines are pre-warmup.
_BENCH_DAYS_PER_NS = re.compile(
    r"Benchmark time:.*?([0-9.eE+-]+)\s+days/ns", re.IGNORECASE
)
_BENCH_NS_PER_DAY = re.compile(
    r"Benchmark time:.*?([0-9.eE+-]+)\s+ns/day", re.IGNORECASE
)
_ATOMS_RE = re.compile(r"Info:\s+(\d+)\s+ATOMS", re.IGNORECASE)

# Ordered: FIRST match wins. NAMD failures CASCADE — a pinned-host OOM is followed
# by a device OOM in sortTileLists, and reporting the second is exactly how job
# f702f4a3282f got mislabelled `vram_oom` and sent us hunting for a bigger card.
_FAILURE_SIGNATURES: list[tuple[str, str, str]] = [
    (
        "degenerate_structure",
        r"LINE MINIMIZER BRACKET.*?nan|DUDX\s+-?nan",
        "Minimiser hit NaN — the built structure has coincident/overlapping atoms. "
        "Not a hardware problem.",
    ),
    (
        "no_kernel_image",
        r"no kernel image is available",
        "The NAMD binary has no GPU code for this card's architecture. Rebuild for "
        "the right sm_XX (4090 = sm_89).",
    ),
    (
        "pinned_host_oom",
        r"cudaHostAlloc|reallocate_host_T|allocate_host_T",
        "Host PINNED memory exhausted — NOT the card. The ceiling is the host's "
        "pinned pool, which is a property of the machine.",
    ),
    (
        "carve_gpuresident_conflict",
        r"Low global CUDA exclusion count",
        "GPU-resident on a carved (vacuum-cornered) box. Expected and lawful.",
    ),
    (
        "tilelist_bug",
        r"buildTileLists|illegal memory access|cudaErrorIllegalAddress",
        "The NAMD empty-patch tile-list bug — THIS POD IS RUNNING STOCK NAMD. "
        "Use the patched 3.0.2p1 build.",
    ),
    (
        "device_oom",
        r"sortTileLists.*?out of memory|CUDA error.*?out of memory",
        "GPU device memory exhausted.",
    ),
    (
        "rattle",
        r"Constraint failure in RATTLE|Atoms moving too fast",
        "Integrator blew up — strained start or too large a timestep.",
    ),
    (
        "cell_shrink",
        r"Periodic cell has become too small",
        "Box shrank past the patch grid. Self-healing on restart.",
    ),
    ("fatal", r"FATAL ERROR", "Unclassified NAMD fatal error."),
]


def parse_days_per_ns(log_text: str) -> Optional[float]:
    m = _BENCH_DAYS_PER_NS.findall(log_text)
    if not m:
        return None
    try:
        return float(m[-1])
    except ValueError:
        return None


def ns_per_day(log_text: str) -> Optional[float]:
    """Throughput from the last `Benchmark time` line, in either of NAMD's two units."""
    direct = _BENCH_NS_PER_DAY.findall(log_text)
    if direct:
        try:
            v = float(direct[-1])
            if v > 0:
                return v
        except ValueError:
            pass
    dpn = parse_days_per_ns(log_text)
    return 1.0 / dpn if dpn and dpn > 0 else None


def parse_atom_count(log_text: str) -> Optional[int]:
    m = _ATOMS_RE.search(log_text)
    return int(m.group(1)) if m else None


def classify_failure(log_text: str) -> Optional[tuple[str, str]]:
    for kind, pattern, why in _FAILURE_SIGNATURES:
        if re.search(pattern, log_text, re.IGNORECASE | re.DOTALL):
            return kind, why
    return None


def cost_per_ns(nspd: Optional[float], usd_per_hour: float) -> Optional[float]:
    if not nspd or nspd <= 0:
        return None
    return (24.0 / nspd) * usd_per_hour


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------


@dataclass
class CellResult:
    cid: str
    ok: bool
    atoms: Optional[int] = None
    ns_per_day: Optional[float] = None
    usd_per_ns: Optional[float] = None
    wall_s: float = 0.0
    peak_vram_mb: Optional[int] = None
    failure_kind: Optional[str] = None
    failure_why: Optional[str] = None
    skipped: Optional[str] = None
    log_path: str = ""


@dataclass
class HostInfo:
    gpu: str = "?"
    vram_mb: Optional[int] = None
    vcpus: Optional[int] = None
    host_ram_gb: Optional[float] = None
    namd_build: str = "?"
    namd_is_patched: bool = False
    pod_id: str = "?"
    usd_per_hour: float = 0.34
    threads: Optional[int] = None


def _f(v, spec: str = "", dash: str = "—") -> str:
    return dash if v is None else (format(v, spec) if spec else str(v))


def render_report(host: HostInfo, results: list[CellResult]) -> str:
    """Markdown the user can paste straight into chat."""
    by = {r.cid: r for r in results}
    total_wall = sum(r.wall_s for r in results)
    total_cost = (total_wall / 3600.0) * host.usd_per_hour

    L: list[str] = []
    L.append("## RunPod RTX 4090 — NADOC NAMD benchmark")
    L.append("")
    L.append(
        f"**Host** {host.gpu} · {_f(host.vram_mb)} MB VRAM · {_f(host.vcpus)} vCPU · "
        f"{_f(host.host_ram_gb, '.0f')} GB RAM · NAMD {host.namd_build}"
        f"{' (patched ✓)' if host.namd_is_patched else ' **(STOCK — suspect)**'} · "
        f"+p{_f(host.threads)} · ${host.usd_per_hour:.2f}/hr"
    )
    L.append("")
    L.append(f"**Benchmark cost** {total_wall / 60:.1f} min ≈ **${total_cost:.2f}**")
    L.append("")

    L.append("| Design | Atoms | Config | Mode | Result | ns/day | Peak VRAM | $/ns |")
    L.append("|---|---|---|---|---|---|---|---|")
    for cell in MATRIX:
        r = by.get(cell.cid)
        cfg, pkg = cell.cfg, cell.pkg
        atoms = f"{r.atoms:,}" if r and r.atoms else "—"
        if r is None:
            res, nspd, vram, cost = "not run", "—", "—", "—"
        elif r.skipped:
            res, nspd, vram, cost = f"skipped — {r.skipped}", "—", "—", "—"
        elif r.ok:
            res = "**ran**"
            nspd = _f(r.ns_per_day, ".2f")
            vram = f"{r.peak_vram_mb:,} MB" if r.peak_vram_mb else "—"
            cost = f"${r.usd_per_ns:.2f}" if r.usd_per_ns else "—"
        else:
            res = f"**FAILED** — `{r.failure_kind or '?'}`"
            nspd = vram = cost = "—"
        L.append(
            f"| {pkg.label} | {atoms} | {cfg.integrator} | {cfg.mode} | {res} | "
            f"{nspd} | {vram} | {cost} |"
        )
    L.append("")

    # Excluded designs are part of the result, not a footnote.
    blocked = [p for p in PACKAGES.values() if not p.runnable]
    if blocked:
        L.append("### Excluded")
        for p in blocked:
            L.append(f"- **{p.label}** — {p.blocked_reason}")
        L.append("")

    L.append("### Findings")
    L.append("")

    for pkey, pkg in PACKAGES.items():
        if not pkg.runnable:
            continue
        cons = by.get(f"{pkey}/conservative")
        fast = by.get(f"{pkey}/fast_offload")
        resi = by.get(f"{pkey}/fast_resident")
        bits: list[str] = []
        if cons and fast and cons.ok and fast.ok and cons.ns_per_day:
            bits.append(
                f"HMR+4 fs gives **{fast.ns_per_day / cons.ns_per_day:.1f}x** over the shipped 2 fs config"
            )
        if fast and resi and fast.ok and resi.ok and fast.ns_per_day:
            bits.append(
                f"GPU-resident adds a further **{resi.ns_per_day / fast.ns_per_day:.1f}x**"
            )
        elif resi and not resi.ok:
            bits.append(f"GPU-resident **failed** (`{resi.failure_kind}`)")
        if bits:
            L.append(f"- **{pkg.label}**: " + "; ".join(bits) + ".")

    viable = [r for r in results if r.ok and r.usd_per_ns]
    if viable:
        best = min(viable, key=lambda r: r.usd_per_ns)  # type: ignore[arg-type]
        cell = next(c for c in MATRIX if c.cid == best.cid)
        L.append("")
        L.append(
            f"**Cheapest config: {cell.pkg.label} · {cell.cfg.integrator} · {cell.cfg.mode}** "
            f"→ **{_f(best.ns_per_day, '.2f')} ns/day at ${best.usd_per_ns:.2f}/ns**. "
            f"A 100 ns run costs **${best.usd_per_ns * 100:.0f}** "
            f"({100 / best.ns_per_day:.1f} days wall time)."  # type: ignore[operator]
        )

    if any(r.failure_kind == "tilelist_bug" for r in results):
        L.append("")
        L.append(
            "> ⚠️ **A cell hit the tile-list bug — this pod is running STOCK NAMD.** "
            "Every number above is suspect."
        )

    L.append("")
    L.append(
        f"> **Host-variance caveat.** Every non-resident cell uses the CUDA *offload* path, "
        f"which leans on host cores and PCIe. This pod had {_f(host.vcpus)} vCPU; "
        f"Community-Cloud 4090s vary a lot. Re-run on a second pod before trusting the "
        f"offload numbers. GPU-resident cells are immune."
    )
    return "\n".join(L) + "\n"
