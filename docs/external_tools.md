# External simulation tools — environment variables

NADOC's **core** (design, editing, validation, geometry, exports) needs **no**
external tools — `./setup.sh` installs everything for that. This page is only for
the **heavy simulation back-ends** (oxDNA, NAMD, GROMACS,
mrdna), which you install yourself, once per machine.

Every external binary is found the same way:

> **`$ENV_VAR` override → the tool on `$PATH` → a conventional location under
> your home directory.**

So in most cases you set **nothing**: drop the binary in the conventional spot
(or put it on `PATH`) and NADOC finds it. The environment variables below are the
escape hatch for non-standard locations — set them when "tool not found" persists
even though you've installed it.

This is the single source of truth for these variables. The per-tool guides
([oxdna_setup.md](oxdna_setup.md), [namd_setup.md](namd_setup.md),
[mrdna_setup.md](mrdna_setup.md)) cover the actual install steps.

---

## Quick reference

| Variable | Tool | Overrides | If unset, NADOC looks for… |
|---|---|---|---|
| `OXDNA_BIN` | upstream oxDNA (DNA/RNA/DNANM) | path to the `oxDNA` binary | managed NADOC build → `oxDNA` on PATH → conventional `~/oxDNA` builds |
| `DNANALYSIS_BIN` | `DNAnalysis` (H-bond health oracle) | path to `DNAnalysis` | sibling of the resolved oxDNA binary → `DNAnalysis` on PATH |
| `OXDNA_DEVICE` | oxDNA CUDA device id | default GPU index | `0` |
| `NADOC_NAMD_BIN` | NAMD 3 | path to `namd3` | `namd3` on PATH → `~/Applications/NAMD_*/namd3` (CUDA build preferred; CPU build used for GBIS) |
| `NADOC_PSFGEN_BIN` | psfgen (ships inside NAMD) | path to `psfgen` | `psfgen` on PATH → `~/Applications/NAMD_*/psfgen` (CUDA build preferred) |
| `NADOC_NAMD_CORES` | NAMD CPU affinity | `taskset` core spec, e.g. `0-7` | unset → NAMD auto-binds the first N cores |
| `GMXLIB` | GROMACS force-field dir | force-field directory | queried from `gmx --version`, else `/usr/share/gromacs/top`, `/usr/local/share/gromacs/top` |
| `GMXDATA` | GROMACS data prefix | parent of the force-field dir | queried from `gmx --version` |
| `MRDNA_TOOL_PATH` | mrdna source checkout | path to the editable mrdna checkout | `~/mrdna-tool` (auto-cloned here on first coarse-relax if missing) |
| `NADOC_WORKSPACE` | assembly job workspace | scratch dir for assembly jobs | `<repo>/workspace` |

`gmx` (the GROMACS binary itself) is found only on `$PATH` — there is no override
variable; install it so `gmx` runs (`sudo apt-get install -y gromacs`, or conda).

`NADOC_GEAR_DEBUG` also exists but is a debug-logging flag (`0` to silence
assembly gear/joint logging; defaults on), not a tool path — listed here only so
it's not mistaken for one.

---

## Conventional install locations (no env var needed)

Put the binaries here and NADOC auto-detects them:

| Tool | Conventional location |
|---|---|
| oxDNA | `~/.local/share/nadoc/engines/oxdna/current/bin/oxDNA` (preferred), or `~/oxDNA/build/bin/oxDNA` |
| NAMD 3 + psfgen | `~/Applications/NAMD_*/` (any version; the `*-CUDA` build is preferred) |
| mrdna | `~/mrdna-tool` (or `$MRDNA_TOOL_PATH`) |

The NAMD path is **globbed**, not version-pinned — `NAMD_3.0.2…`, `NAMD_3.0.3…`,
etc. all match, and a CUDA/GPU build sorts ahead of a CPU-only build. Upgrading
NAMD needs no code change. Install both variants if you want both normal GPU jobs and
NADOC's current GBIS protocol: explicit solvent uses the CUDA build where available,
whereas GBIS is routed to the plain multicore build because it cannot run GPU-resident.

---

## Setting variables persistently

Set the variable **before** launching the backend, and persist it in your shell
profile so the backend process inherits it on every login:

```bash
# ~/.bashrc  (or ~/.zshrc on macOS)
export NADOC_NAMD_BIN=/opt/namd/namd3
export OXDNA_BIN=/usr/local/bin/oxDNA
export MRDNA_TOOL_PATH=$HOME/src/mrdna
```

Then open a new terminal (or `source ~/.bashrc`) and start NADOC with `./start.sh`
or `just dev`. A change only takes effect after the backend is restarted.

> An override that points at a **non-executable / missing** path is silently
> skipped — resolution falls through to PATH and the conventional locations. If
> an override "isn't working," confirm the path exists and is `chmod +x`.

---

## Checking what resolved

To see which binaries NADOC currently finds on this machine:

```bash
uv run python -c "
from backend.core.oxdna_runner import find_oxdna, find_dnanalysis
from backend.core.namd_runner import find_namd, find_gmx
from backend.core.namd_topology import find_psfgen
from backend.core.mrdna_bridge import mrdna_tool_path
def show(name, fn):
    try: print(f'{name:12} {fn() or \"(not found)\"}')
    except Exception as e: print(f'{name:12} (not found: {e})')
show('oxDNA',     find_oxdna)
show('DNAnalysis',find_dnanalysis)
show('namd3',     find_namd)
show('psfgen',    find_psfgen)
show('gmx',       find_gmx)
print(f'{\"mrdna\":12} {mrdna_tool_path()}')
"
```

The MD / Dynamics sidebars in the app also report when a back-end is missing.

---

## Testing the install UX without a fresh machine

The **MD Engines** panel (Help ▸ MD Engines) and the sidebar install gates only
appear when an engine is *missing* — so on a machine that already has everything
you can't see them. Two ways to exercise that UI:

### 1. Simulate a missing engine on your own machine (no side effects)

Set `NADOC_ENGINES_FORCE_MISSING` to a comma-separated list of engine keys before
starting the backend. Those engines then **report as not installed** even though
they're present, so the gates, status panel, popups, and the auto-build progress
bar all render. The auto-build runs a **dry-run** (streams fake progress, then
declines and shows the manual commands) — nothing is actually cloned or compiled.

```bash
# See the whole install UX as a new user would, then revert by unsetting it.
NADOC_ENGINES_FORCE_MISSING=oxdna,namd,gromacs just dev
```

Engine keys include `oxdna`, `namd`, `gromacs`, `psfgen`, and `dnanalysis`.

### 2. Test the *real* build on a genuinely clean machine

To verify the actual `git clone → cmake → make` works from scratch, use a clean
throwaway environment — **not** git (git is version control; it never makes a
clean machine). The options, cleanest first:

- **A Docker container** — a fresh Ubuntu with no engines installed. Run the
  backend inside it and drive the install. A CPU build needs nothing special; a
  GPU build needs the host's NVIDIA driver exposed via `nvidia-container-toolkit`
  (`docker run --gpus all`).
- **Your CI runner** — GitHub Actions already boots a clean Ubuntu VM on every
  push (`.github/workflows/ci.yml`). An install-smoke job there is the same idea
  as a fresh VM, for free.
- **A throwaway VM** (VirtualBox / cloud instance) — heaviest, but closest to a
  real end-user box if you also want to test GPU + the NAMD license download.

The status model, GPU-aware planning, the build orchestration, and the full
`/ws/engines/install` round-trip are covered by `tests/test_engines.py`,
`tests/test_engine_install.py`, and `tests/test_engines_ws.py` (the last drives
the install WebSocket end-to-end under the simulation switch).
