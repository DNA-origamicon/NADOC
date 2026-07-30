"""
NAMD Explicit-Solvent Package Builder
======================================
Builds a self-contained NAMD simulation package with TIP3P explicit water
and NaCl/MgCl2 ions from a NADOC design.

Physics:
  - Explicit TIP3P water + NaCl/MgCl2 ions (adjustable)
  - Standard CUDA by default; benchmark GPU-resident separately
  - PME electrostatics, 12 Å cutoff
  - rigidBonds all (SHAKE on all H-bonds, required for 2 fs DNA; see Pan 2014 JCTC)
  - Langevin thermostat 310 K / barostat 1 atm (NPT)

Solvation pipeline:
  1. Export atomistic PDB (heavy atoms, CHARMM36 naming)
  2. gmx editconf  → rectangular box with padding
  3. gmx solvate   → TIP3P water from spc216.gro template
  4. Parse solvated GRO → water positions (nm)
  5. Python ion placement → replace random waters with Na+/Mg2+/Cl-
  6. Merge water/ions into PSF (extend NATOM/NBOND/NTHETA sections)
  7. Build solvated PDB (DNA ATOM + water/ion HETATM)
  8. Emit NAMD conf + ZIP

ZIP layout::

    {name}_namd_solvated/
    ├── {name}.pdb          ← DNA + water + ions (CHARMM36 naming)
    ├── {name}.psf          ← complete topology (atoms/bonds/angles/dihedrals)
    ├── namd.conf
    ├── forcefield/
    │   ├── top_all36_na.rtf
    │   ├── par_all36_na.prm
    │   └── toppar_water_ions_cufix.str
    ├── scripts/monitor.py
    ├── README.txt
    └── AI_ASSISTANT_PROMPT.txt
"""

from __future__ import annotations

import dataclasses
import io
import logging
import json
import math
import random
import re
import shutil
import stat
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

# progress(phase_key, frac_within_phase | None, message) — see md_prep_progress.
# frac=None just enters/holds an opaque phase that the heartbeat time-fills.
ProgressCb = Callable[[str, Optional[float], str], None]


def _emit(progress: Optional[ProgressCb], key: str, frac: Optional[float], msg: str = "") -> None:
    """Call the optional progress callback, swallowing any callback error."""
    if progress is None:
        return
    try:
        progress(key, frac, msg)
    except Exception:
        pass

if TYPE_CHECKING:
    import numpy as np

    from backend.core.atomistic import AtomisticModel

from backend.core.models import Design
from backend.core.md_charge import audit_psf
from backend.core.md_protocols import write_hmr_psf
from backend.core.pdb_export import export_pdb
from backend.core.namd_package import complete_psf
from backend.core.namd_topology import build_charmm_psfgen_topology

_FF_DIR = Path(__file__).parent.parent / "data" / "forcefield"
_FF_FILES = [
    "top_all36_na.rtf",
    "par_all36_na.prm",
    "toppar_water_ions_cufix.str",   # includes Yoo/Aksimentiev Na+/Mg2+ CUFIX terms
    "par_stub_ions_nbfix.str",       # stub vdW for protein/lipid types in cufix NBFIX
]

# ── Ion parameters (CHARMM36 / toppar_water_ions_cufix.str) ───────────────────
# SOD: Na+  type SOD  charge +1.00  mass 22.98977
# MG:  Mg2+ type MG   charge +2.00  mass 24.30500
# CLA: Cl-  type CLA  charge -1.00  mass 35.45000
_ION_PARAMS = {
    "SOD": ("SOD",  1.00, 22.98977),   # (atomtype, charge, mass)
    "MG":  ("MG",   2.00, 24.30500),
    "CLA": ("CLA", -1.00, 35.45000),
}

# TIP3P water parameters (CHARMM36 / toppar_water_ions_cufix.str)
_TIP3_PARAMS = {
    "OH2": ("OT",  -0.834, 15.99940),
    "H1":  ("HT",  +0.417,  1.00800),
    "H2":  ("HT",  +0.417,  1.00800),
}

_MGH_PARAMS = {
    "MG": ("MG", 2.00, 24.30500),
    "O":  ("OTMG", -1.190, 15.99940),
    "H":  ("HT", +0.595, 1.00800),
}

_MGH_WATER_NAMES = (
    ("OHA", "H1A", "H2A"),
    ("OHB", "H1B", "H2B"),
    ("OHC", "H1C", "H2C"),
    ("OHD", "H1D", "H2D"),
    ("OHE", "H1E", "H2E"),
    ("OHF", "H1F", "H2F"),
)

_MGH_DIRECTIONS = (
    (1.0, 0.0, 0.0),
    (-1.0, 0.0, 0.0),
    (0.0, 1.0, 0.0),
    (0.0, -1.0, 0.0),
    (0.0, 0.0, 1.0),
    (0.0, 0.0, -1.0),
)

# Avogadro constant for ion count calculation
_NA = 6.02214076e23

# Bulk TIP3P number density (water molecules per nm³): 997 kg/m³ ÷ 18.015 g/mol.
# Used to convert a carved water *count* back to an effective solvent volume so
# the salt concentration stays correct after a water-shell carve (the full box
# volume would over-count ions once the empty corners are removed).
_WATER_NUMBER_DENSITY_NM3 = 33.4

# Atoms in one Mg(H₂O)₆ residue: the Mg plus six waters at three atoms each.
MGH_ATOMS = 19
# Waters removed from the box to make room for one Mg(H₂O)₆ octahedron: the site
# the Mg takes plus its five nearest neighbours (_place_ions_mixed_mgh).
MGH_WATERS_CONSUMED = 6


# ══════════════════════════════════════════════════════════════════════════════
# §1  DATA TYPES
# ══════════════════════════════════════════════════════════════════════════════

@dataclasses.dataclass
class _Water:
    """TIP3P water molecule with atom positions in nm."""
    ox: float;  oy: float;  oz: float   # OW → OH2
    h1x: float; h1y: float; h1z: float  # HW1 → H1
    h2x: float; h2y: float; h2z: float  # HW2 → H2


@dataclasses.dataclass
class _MgHexahydrate:
    """Idealized Mg(H2O)6 cluster with positions in nm."""
    mg: tuple[float, float, float]
    waters: list[_Water]


# ══════════════════════════════════════════════════════════════════════════════
# §2  GROMACS SOLVATION
# ══════════════════════════════════════════════════════════════════════════════

def _find_gmx() -> str:
    """Return the gmx binary path, or raise RuntimeError."""
    for name in ("gmx", "gmx_mpi", "gmx_d"):
        p = shutil.which(name)
        if p:
            return p
    raise RuntimeError(
        "GROMACS not found in PATH.  Install with:\n"
        "    sudo apt-get install -y gromacs"
    )


def _run(cmd: list, cwd: Optional[Path] = None, stdin: str = "") -> subprocess.CompletedProcess:
    """Run a subprocess; raise RuntimeError if it fails."""
    result = subprocess.run(
        cmd,
        input=stdin,
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(str(c) for c in cmd)}\n"
            f"stderr:\n{result.stderr[-3000:]}"
        )
    return result


def _run_watched(
    cmd: list,
    cwd: Optional[Path] = None,
    *,
    hard_timeout_s: Optional[float] = None,
) -> subprocess.CompletedProcess:
    """Like :func:`_run` but enforces a hard wall-clock cap.

    If the process runs longer than ``hard_timeout_s`` it is killed and a
    RuntimeError is raised — this is the "gone on longer than it should have"
    safety net for a hung GROMACS step (the prep job is then marked failed with
    a clear message instead of blocking forever).
    """
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    t0 = time.monotonic()
    out = err = ""
    try:
        while True:
            try:
                out, err = proc.communicate(timeout=2.0)
                break
            except subprocess.TimeoutExpired:
                if hard_timeout_s is not None and (time.monotonic() - t0) > hard_timeout_s:
                    proc.kill()
                    try:
                        proc.communicate(timeout=10)
                    except Exception:
                        pass
                    raise RuntimeError(
                        f"GROMACS step exceeded {hard_timeout_s:.0f} s and was aborted "
                        f"(likely hung): {' '.join(str(c) for c in cmd)}"
                    )
    finally:
        if proc.poll() is None:
            proc.kill()
    if proc.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(str(c) for c in cmd)}\n"
            f"stderr:\n{(err or '')[-3000:]}"
        )
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def _gmx_hard_timeout_s(pdb_text: str) -> float:
    """Generous wall cap for a GROMACS solvation step, scaled by DNA atom count.

    Legitimate large-box solvation can take a minute or two; the cap only exists
    to catch a truly stuck process, so it sits well above any realistic runtime.
    """
    n_atoms = sum(1 for ln in pdb_text.splitlines() if ln.startswith(("ATOM", "HETATM")))
    return max(600.0, n_atoms * 0.05)


def _parse_gro(
    gro_text: str,
    progress: Optional[ProgressCb] = None,
) -> tuple[list[_Water], tuple[float, float, float]]:
    """Parse a GROMACS GRO file; return (water_list, (bx, by, bz) in nm).

    Only SOL residues are collected; DNA residues are ignored.
    Assumes GROMACS atom names: OW / HW1 / HW2.

    Uses sequential parsing (not grouped by resnum) to handle GRO's
    residue-number wraparound at 100,000 for large systems.
    """
    lines = gro_text.splitlines()
    # Last non-empty line is the box vector line
    box_line = lines[-1].strip()
    parts = box_line.split()
    box_nm = (float(parts[0]), float(parts[1]), float(parts[2]))

    # GRO atom line format (fixed-width):
    #   cols  0- 4: residue number (wraps at 100000 for large systems)
    #   cols  5- 9: residue name
    #   cols 10-14: atom name
    #   cols 15-19: atom number
    #   cols 20-27: x (nm, 8.3f)
    #   cols 28-35: y (nm, 8.3f)
    #   cols 36-43: z (nm, 8.3f)
    #
    # Collect SOL atoms sequentially; group into triplets (OW, HW1, HW2).
    # This avoids the residue-number wraparound issue that occurs at ~100k atoms.
    sol_buf: dict[str, tuple[float, float, float]] = {}
    waters: list[_Water] = []

    body = lines[2:-1]
    n_body = len(body) or 1
    for li, line in enumerate(body):
        if progress is not None and (li & 0x3FFFF) == 0:  # every ~262k lines
            _emit(progress, "assemble", 0.4 * (li / n_body),
                  "Reading solvated water positions…")
        if len(line) < 44:
            continue
        resname  = line[5:10].strip()
        atomname = line[10:15].strip()
        if resname != "SOL":
            # Flush any incomplete water on transition out of SOL (edge case)
            if sol_buf:
                sol_buf = {}
            continue
        x = float(line[20:28])
        y = float(line[28:36])
        z = float(line[36:44])
        sol_buf[atomname] = (x, y, z)
        if len(sol_buf) == 3:
            try:
                ox, oy, oz     = sol_buf["OW"]
                h1x, h1y, h1z  = sol_buf["HW1"]
                h2x, h2y, h2z  = sol_buf["HW2"]
                waters.append(_Water(ox, oy, oz, h1x, h1y, h1z, h2x, h2y, h2z))
            except KeyError:
                pass  # unexpected atom names — skip molecule
            sol_buf = {}

    return waters, box_nm


def _dna_atom_positions_nm(pdb_text: str,
                           atom_name: "str | None" = None
                           ) -> "list[tuple[float, float, float]]":
    """Return DNA heavy-atom (x, y, z) in nm from ATOM records of a PDB string.

    ``atom_name`` restricts to one atom type — pass ``"P"`` for the phosphate
    backbone, which is a ~32x smaller point set and the right reference for where
    divalent counterions condense.
    """
    pts: list[tuple[float, float, float]] = []
    for line in pdb_text.splitlines():
        if line.startswith("ATOM"):
            if atom_name is not None and line[12:16].strip() != atom_name:
                continue
            try:
                pts.append((
                    float(line[30:38]) / 10.0,   # Å → nm
                    float(line[38:46]) / 10.0,
                    float(line[46:54]) / 10.0,
                ))
            except ValueError:
                pass
    return pts


def _carve_water_shell(
    waters: list[_Water],
    dna_pdb_text: str,
    shell_nm: float,
    progress: Optional[ProgressCb] = None,
) -> list[_Water]:
    """Drop water molecules whose oxygen is farther than *shell_nm* from any DNA atom.

    GROMACS fills the whole rectangular box, but for a non-globular structure
    (e.g. a plate- or cross-shaped origami) most of that box is bulk water sitting
    far from the DNA in the empty corners.  Removing it keeps a hydration shell of
    thickness ``shell_nm`` around the solute and roughly halves the atom count for
    large designs — enough to fit GPU-resident NAMD on a 12 GB card.

    The box dimensions are unchanged, so the periodic cell (and PME grid) stay the
    same; only particle count drops.  The carved cell has vacuum in its corners, so
    downstream stages must run NVT (barostat off) — an NPT piston would collapse
    the cell.  Minimum-image validity needs ``2 * shell_nm`` ≥ the nonbonded cutoff.
    """
    import numpy as np  # noqa: PLC0415
    from scipy.spatial import cKDTree  # noqa: PLC0415

    if not waters:
        return waters

    dna = _dna_atom_positions_nm(dna_pdb_text)
    if not dna:
        return waters  # no DNA reference → cannot carve safely; keep all water

    _emit(progress, "assemble", 0.45,
          f"Carving {shell_nm * 10:.0f} Å hydration shell (removing bulk water)…")

    tree = cKDTree(np.asarray(dna, dtype=float))
    w_o = np.empty((len(waters), 3), dtype=float)
    for i, w in enumerate(waters):
        w_o[i, 0] = w.ox
        w_o[i, 1] = w.oy
        w_o[i, 2] = w.oz

    # Nearest-DNA distance for every water oxygen (parallel over all cores).
    dist, _ = tree.query(w_o, k=1, workers=-1)
    keep_mask = dist <= shell_nm
    kept = [w for w, k in zip(waters, keep_mask) if k]
    return kept


# Default cell-sizing rule.  "rotation" sizes the cell so the padding survives ANY
# reorientation of the solute (cubic, 2*r_max + 2*pad) rather than only the pose it was
# built in.  An unrestrained solute rotates: the 2hb built as 20.2 x 42.6 x 88.1 A reached
# 59.7 x 70.3 x 107.0 A over 200 ns and overran its "bbox"-sized cell on every axis,
# spending most of the run within 3-9 A of its own periodic image.  "bbox" (the historical
# rule) remains available and is the automatic fallback when "rotation" would not fit the
# hardware.  See experiments/exp47_protocol_delta/RESULTS.md.
logger = logging.getLogger(__name__)

DEFAULT_BOX_MODE = "rotation"
# Bulk TIP3P number density (waters per Å³) — 1 g/cm³ is 29.9 Å³ per water.
_WATER_PER_ANG3 = 1.0 / 29.91
# Partial specific volume of DNA, ~0.55 cm³/g, as Å³ per heavy+H atom (≈ 310 Da / 32
# atoms per nucleotide → ~8.8 Å³/atom).
_DNA_ANG3_PER_ATOM = 8.8


def estimate_box_atoms(box_nm, n_dna_atoms: int, n_phosphates: int = 0) -> int:
    """Rough solvated atom count for a cell of this size (pure).

    Water fills whatever the solute does not occupy, at bulk density.  Used to decide
    whether a rotation-sized cell is affordable before paying to build it.

    ``n_phosphates`` adds the ion census.  It is a small correction (an Mg(H₂O)₆
    cluster is 19 atoms but vacates 6 waters, so each is only ~+1 atom net), but this
    is the function that picks rotation-vs-bbox, so it should not silently model a
    cell as pure water.  Zero keeps the historical water-only estimate.
    """
    v_box = float(box_nm[0]) * float(box_nm[1]) * float(box_nm[2]) * 1000.0  # nm³→Å³
    v_dna = n_dna_atoms * _DNA_ANG3_PER_ATOM
    waters = max(0.0, v_box - v_dna) * _WATER_PER_ANG3
    total = waters * 3 + n_dna_atoms
    if n_phosphates > 0:
        ions = ion_counts(int(waters), -float(n_phosphates), nacl_mM=0.0,
                          mgcl2_mM=12.5, box_nm=box_nm, mg_hexahydrate=True)
        displaced = ions.n_mg * MGH_WATERS_CONSUMED + ions.n_na + ions.n_cl
        total += ions.n_mg * MGH_ATOMS + ions.n_na + ions.n_cl - displaced * 3
    return int(round(total))


def _box_mode_atom_cap(devices: "str | None") -> "int | None":
    """Atom ceiling the box sizer must respect — the same VRAM/host-RAM cap the
    water-shell auto-sizer uses, so the two agree about what "fits"."""
    try:
        from backend.core.md_vram import (detect_host_ram_mb, detect_vram_mb,  # noqa: PLC0415
                                          max_atoms_for_host_ram, max_atoms_for_vram)
        host = detect_host_ram_mb()
        host_cap = max_atoms_for_host_ram(host) if host else None
        if (devices or "").strip().lower() in ("cpu", "none"):
            return host_cap
        vram = detect_vram_mb(devices or "0")
        vram_cap = max_atoms_for_vram(vram) if vram else None
        caps = [c for c in (vram_cap, host_cap) if c]
        return min(caps) if caps else None
    except Exception:  # noqa: BLE001 — sizing must never break a build
        return None


#: The tutorial's solvation padding: ``solvate -minmax`` at the DNA bbox ± 20 Å.
TUTORIAL_PADDING_NM = 2.0
#: What to fall back to when the tutorial's padding will not fit the hardware.  NADOC's
#: historical default — 40 % tighter than the reference, but proven on this box.
FALLBACK_PADDING_NM = 1.2


def resolve_padding_nm(pdb_text: str, requested_nm: float, *,
                       max_atoms: "int | None",
                       fallback_nm: float = FALLBACK_PADDING_NM,
                       ) -> tuple[float, "str | None"]:
    """Trim the requested padding when the resulting cell would not fit (pure).

    The protocol asks for bbox ± 20 Å and that is the default, but honouring it is not
    free: the extra water can push a large design past the hardware's atom cap, which
    triggers an automatic water-shell carve — and a carved cell runs NVT throughout,
    which silently deletes BOTH the Note-4 settle stage and the box-trace criterion, on
    exactly the designs where they matter most.  A slightly tight box that keeps the
    barostat beats a faithful one that cannot use it.

    Returns ``(padding_nm, note)``; ``note`` is set only when the request was trimmed.
    """
    if not max_atoms or requested_nm <= fallback_nm:
        return requested_nm, None
    n_dna = 0
    n_p = 0
    for ln in pdb_text.splitlines():
        if not ln.startswith(("ATOM", "HETATM")):
            continue
        n_dna += 1
        if ln[12:16].strip() == "P":
            n_p += 1
    try:
        _, box = _recenter_pdb_in_padded_box(pdb_text, requested_nm, DEFAULT_BOX_MODE)
        atoms = estimate_box_atoms(box, n_dna, n_p)
    except Exception:  # noqa: BLE001 — sizing must never break a build
        return requested_nm, None
    if atoms <= max_atoms:
        return requested_nm, None
    return fallback_nm, (
        f"trimmed padding {requested_nm:g} -> {fallback_nm:g} nm: the requested cell "
        f"would be ~{atoms:,} atoms against a {max_atoms:,} cap, which forces a "
        f"water-shell carve — and a carved cell runs NVT throughout, losing the "
        f"fixed-DNA settle stage and the box-trace criterion.")


#: Unrestrained nanoseconds below which rotation sizing buys nothing.
#:
#: Rotation sizing exists because a FREE solute reorients into its own periodic image —
#: measured on VoltronCore, which overran a bbox cell over 200 ns (exp47).  A relaxation
#: ladder is not that: it is ~19 ns of which only the k=0 stage is unrestrained, and
#: rotational diffusion over a few ns is negligible.  For a 2hb rod (L ≈ 11.4 nm) the
#: Stokes-Einstein-Debye estimate is D_rot ≈ 4.5e5 s⁻¹, so ⟨θ²⟩ = 2·D_rot·t gives
#: θ_rms ≈ 4° over 4.8 ns against ≈ 24° over 200 ns.  Four degrees cannot walk a solute
#: into its image; twenty-four can.
#:
#: The cost of getting this wrong is not small.  A 2hb's bbox cell is 4.4 × 6.7 × 11.4 nm
#: (336 nm³); the rotation cell is a 11.9 nm cube (1,698 nm³) — 5x the water, and gmx
#: FILLS it, so 32.6k atoms becomes 166k and every stage runs ~4x slower.  Paying that
#: through a ladder that never turns is pure waste.
ROTATION_FREE_NS_THRESHOLD = 20.0


def resolve_box_mode(pdb_text: str, padding_nm: float, *,
                     max_atoms: "int | None",
                     free_ns: "float | None" = None,
                     preferred: str = DEFAULT_BOX_MODE) -> tuple[str, "str | None"]:
    """Pick a cell-sizing rule that is both correct and affordable (pure).

    Two independent reasons to decline rotation sizing:

    * **It is not needed.** ``free_ns`` is how long this package will run UNRESTRAINED.
      Below :data:`ROTATION_FREE_NS_THRESHOLD` the solute cannot turn far enough for the
      minimum-image problem to arise, so a bbox cell is both correct and far cheaper.
      Pass ``None`` to size for an arbitrarily long free run (the safe default).
    * **It does not fit.** A too-big cell is not a safer choice than a too-small one: it
      forces a water-shell carve, which forces NVT, which rules out the free NPT stage
      rotation sizing existed to protect.

    Returns ``(mode, note)``; ``note`` is set whenever rotation was declined, so the
    caller can record WHY a package is bbox-sized — which the production path then reads
    back to decide whether a long free run is safe in it.
    """
    if preferred != "rotation":
        return preferred, None
    if free_ns is not None and free_ns <= ROTATION_FREE_NS_THRESHOLD:
        return "bbox", (
            f"bbox sizing: this package runs {free_ns:g} ns unrestrained, under the "
            f"{ROTATION_FREE_NS_THRESHOLD:g} ns at which a solute can rotate into its own "
            f"periodic image. A rotation-sized cell would cost several times the water "
            f"for no benefit. A LONG free run (production) in this cell is NOT "
            f"trustworthy — re-solvate for one.")
    if not max_atoms:
        return preferred, None
    n_dna = 0
    n_p = 0
    for ln in pdb_text.splitlines():
        if not ln.startswith(("ATOM", "HETATM")):
            continue
        n_dna += 1
        if ln[12:16].strip() == "P":
            n_p += 1
    _, rot_box = _recenter_pdb_in_padded_box(pdb_text, padding_nm, "rotation")
    rot_atoms = estimate_box_atoms(rot_box, n_dna, n_p)
    if rot_atoms <= max_atoms:
        return "rotation", None
    _, bb_box = _recenter_pdb_in_padded_box(pdb_text, padding_nm, "bbox")
    return "bbox", (
        f"rotation-sized cell would be ~{rot_atoms:,} atoms (cap {max_atoms:,}); "
        f"fell back to bbox sizing (~{estimate_box_atoms(bb_box, n_dna, n_p):,} atoms). "
        f"A free (unrestrained) stage in this box is NOT trustworthy — the solute can "
        f"rotate into its own periodic image. Use a cluster target for a free run.")


def _recenter_pdb_in_padded_box(
    pdb_text: str, padding_nm: float, box_mode: str = DEFAULT_BOX_MODE
) -> tuple[str, tuple[float, float, float]]:
    """Translate every ATOM/HETATM so the structure's bounding box is centred in a
    rectangular ``[0, L]`` cell of size ``span + 2·padding`` per axis.

    Returns ``(recentred_pdb_text, (bx, by, bz) in nm)``.

    WHY: the DNA model's native coordinate frame is arbitrary (its centroid can sit
    hundreds of Å off the box centre — e.g. a plate symmetric about Y=0).  We must
    write the DNA to the final solvated PDB in the SAME frame as the water gmx
    places, and with a ``cellOrigin`` (= box/2) that actually encloses it.  Centring
    here — then telling ``gmx editconf`` NOT to re-centre (``-noc``) — guarantees one
    shared frame for DNA + water; otherwise editconf's own ``-c`` shift is applied to
    the water only, leaving the DNA far outside the periodic cell → NAMD's GPU
    tile-list kernel hits an illegal memory access at startup (buildTileLists).
    """
    import numpy as np  # noqa: PLC0415

    pad_a = padding_nm * 10.0  # nm → Å

    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    for ln in pdb_text.splitlines():
        if ln.startswith(("ATOM", "HETATM")):
            try:
                xs.append(float(ln[30:38]))
                ys.append(float(ln[38:46]))
                zs.append(float(ln[46:54]))
            except ValueError:
                pass
    if not xs:
        raise RuntimeError("No ATOM/HETATM records found in PDB for solvation.")

    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    zmin, zmax = min(zs), max(zs)

    # ``rotation`` sizes the cell so the padding survives ANY reorientation of the solute
    # (cubic, 2*r_max + 2*pad) instead of only the pose it was built in.  An unrestrained
    # run rotates: the 2hb built as 20.2 x 42.6 x 88.1 A reached 59.7 x 70.3 x 107.0 A and
    # overran its cell on every axis.  ``bbox`` is the historical rule and stays the
    # default so existing packages reproduce byte-for-byte.
    half = np.array([(xmax - xmin), (ymax - ymin), (zmax - zmin)], dtype=float) / 2.0
    centre = np.array([(xmax + xmin), (ymax + ymin), (zmax + zmin)], dtype=float) / 2.0
    if box_mode == "rotation":
        r_max = max(
            float(np.linalg.norm(np.array([x, y, z]) - centre))
            for x, y, z in zip(xs, ys, zs)
        )
        span = np.array([2.0 * r_max] * 3)
    elif box_mode == "bbox":
        span = 2.0 * half
    else:
        raise ValueError(f"unknown box_mode {box_mode!r} (expected 'bbox' or 'rotation')")

    # Translation that centres the structure in a cell of ``span + 2*padding``.
    tx, ty, tz = (pad_a + span / 2.0) - centre

    out: list[str] = []
    for ln in pdb_text.splitlines():
        if ln.startswith(("ATOM", "HETATM")):
            try:
                x = float(ln[30:38]) + tx
                y = float(ln[38:46]) + ty
                z = float(ln[46:54]) + tz
            except ValueError:
                out.append(ln)
                continue
            out.append(f"{ln[:30]}{x:8.3f}{y:8.3f}{z:8.3f}{ln[54:]}")
        else:
            out.append(ln)

    bx, by, bz = (span + 2 * pad_a) / 10.0  # Å → nm
    return "\n".join(out) + "\n", (float(bx), float(by), float(bz))


def _gmx_solvate(
    pdb_text: str,
    padding_nm: float,
    tmpdir: Path,
    progress: Optional[ProgressCb] = None,
    *,
    water_shell_nm: Optional[float] = None,
    box_mode: str = DEFAULT_BOX_MODE,
) -> tuple[list[_Water], tuple[float, float, float], str]:
    """Place TIP3P water around the DNA using GROMACS.

    Returns ``(waters, (bx, by, bz) in nm, recentred_pdb_text)``.  The returned PDB
    is the DNA translated into the SAME ``[0, L]`` frame as the water (see
    :func:`_recenter_pdb_in_padded_box`); callers MUST write *this* text (not the
    original ``pdb_text``) so DNA and water co-register and every atom sits inside
    the periodic cell.

    If ``water_shell_nm`` is set, GROMACS places ONLY a hydration layer of that
    thickness around the DNA (``gmx solvate -shell``) instead of filling the whole
    box.  For a large sparse origami (e.g. a 121 nm plate) filling the box then
    trimming generated ~6 M waters just to keep the shell — a multi-GB peak in gmx
    AND again when Python parses the full ``.gro`` (the parse hit 22 GB and OOM-crashed
    WSL on GT_corner_v2).  ``-shell`` writes only the shell waters, so the box stays
    the same size (unchanged PME/cellOrigin) but the intermediate never materialises.
    """
    gmx = _find_gmx()
    hard_timeout = _gmx_hard_timeout_s(pdb_text)

    # Centre the DNA ourselves in a rectangular box, then tell editconf NOT to move
    # it (-noc) — so the DNA we hand back and the water gmx places share one frame.
    pdb_text, box_nm = _recenter_pdb_in_padded_box(pdb_text, padding_nm, box_mode)
    bx, by, bz = box_nm

    (tmpdir / "dry.pdb").write_text(pdb_text)

    # editconf: set the explicit box; do NOT centre (coords are already centred).
    _emit(progress, "solvate", None, "Building solvation box (gmx editconf)…")
    _run_watched([
        gmx, "editconf",
        "-f", "dry.pdb",
        "-o", "dry.gro",
        "-noc",
        "-box", f"{bx:.4f}", f"{by:.4f}", f"{bz:.4f}",
        "-bt", "triclinic",
        "-nobackup",
    ], cwd=tmpdir, hard_timeout_s=hard_timeout)

    # solvate.  With a shell request, pass -shell so gmx places ONLY a hydration
    # layer around the DNA (no full-box fill → no multi-GB memory spike); otherwise
    # fill the box (small designs that fit).  TIP3P geometry comes from spc216.gro.
    shell_native = bool(water_shell_nm and water_shell_nm > 0)
    msg = (f"Adding TIP3P hydration shell ({water_shell_nm:.2f} nm, gmx solvate -shell)…"
           if shell_native else "Adding TIP3P water (gmx solvate)…")
    _emit(progress, "solvate", None, msg)
    solvate_cmd = [
        gmx, "solvate",
        "-cp", "dry.gro",
        "-cs", "spc216.gro",
        "-o", "solvated.gro",
        "-nobackup",
    ]
    if shell_native:
        solvate_cmd += ["-shell", f"{water_shell_nm:.4f}"]
    _run_watched(solvate_cmd, cwd=tmpdir, hard_timeout_s=hard_timeout)

    gro_text = (tmpdir / "solvated.gro").read_text()
    waters, _box_from_gro = _parse_gro(gro_text, progress=progress)
    # gmx -shell already restricted the water to the hydration shell — no Python carve
    # (a KD-tree over every water) needed.  The non-shell path keeps the full box.
    # Use OUR explicit box (matches the centred DNA + cellOrigin=box/2), not gmx's.
    return waters, box_nm, pdb_text


def _gmx_solvate_periodic(
    pdb_text: str,
    padding_nm: float,
    periodic_z_nm: float,
    tmpdir: Path,
) -> tuple[list[_Water], tuple[float, float, float]]:
    """Place TIP3P water in a box whose Z dimension is exactly periodic_z_nm.

    Unlike _gmx_solvate (which uses -d padding to auto-size the box), this
    function computes bx/by from the atom bounding box + 2*padding and forces
    bz = periodic_z_nm so the box matches the crossover repeat period exactly.

    Returns (waters, (bx, by, bz)) — same type as _gmx_solvate.
    """
    gmx = _find_gmx()

    (tmpdir / "dry.pdb").write_text(pdb_text)

    # Parse atom positions from the PDB to compute XY bounding box
    xs, ys = [], []
    for line in pdb_text.splitlines():
        if line.startswith(("ATOM", "HETATM")):
            try:
                xs.append(float(line[30:38]) / 10.0)  # Å → nm
                ys.append(float(line[38:46]) / 10.0)
            except ValueError:
                pass

    if not xs:
        raise RuntimeError("No ATOM/HETATM records found in PDB for periodic solvation.")

    bx = (max(xs) - min(xs)) + 2 * padding_nm
    by = (max(ys) - min(ys)) + 2 * padding_nm
    bz = periodic_z_nm

    # editconf: centre structure in the explicit box (no auto-padding)
    _run([
        gmx, "editconf",
        "-f", "dry.pdb",
        "-o", "dry.gro",
        "-c",
        "-box", f"{bx:.4f}", f"{by:.4f}", f"{bz:.4f}",
        "-nobackup",
    ], cwd=tmpdir)

    # solvate: fill box with pre-equilibrated TIP3P water
    _run([
        gmx, "solvate",
        "-cp", "dry.gro",
        "-cs", "spc216.gro",
        "-o", "solvated.gro",
        "-nobackup",
    ], cwd=tmpdir)

    gro_text = (tmpdir / "solvated.gro").read_text()
    waters, box_from_gro = _parse_gro(gro_text)
    # Use the explicit box dimensions we set, not whatever gmx reports
    return waters, (bx, by, bz)


def _periodic_cell_header(
    name: str,
    box_nm: tuple[float, float, float],
    n_atoms: int,
    periodic_z_nm: float,
    *,
    mode: str,
    langevin_damping: float = 1.0,
) -> str:
    bx, by, bz = box_nm
    bx_a, by_a = bx * 10, by * 10
    bz_a = periodic_z_nm * 10   # exact period in Å
    cx, cy, cz = bx_a / 2, by_a / 2, bz_a / 2
    return f"""\
# NAMD periodic unit-cell configuration generated by NADOC
# System: {name}  ({n_atoms:,} atoms, TIP3P water + 150 mM NaCl)
# Mode:   {mode}
# Cell:   initial Z = {periodic_z_nm:.4f} nm crossover period

structure          {name}.psf
coordinates        {name}.pdb

paraTypeCharmm     on
parameters         forcefield/par_all36_na.prm
parameters         forcefield/toppar_water_ions_na.str

# ── Periodic boundary conditions ──────────────────────────────────────────────
cellBasisVector1   {bx_a:.3f}  0.000    0.000
cellBasisVector2   0.000    {by_a:.3f}  0.000
cellBasisVector3   0.000    0.000    {bz_a:.3f}
cellOrigin         {cx:.3f}   {cy:.3f}   {cz:.3f}

wrapAll            on
wrapWater          on
wrapNearest        on

# ── PME electrostatics ────────────────────────────────────────────────────────
PME                yes
PMEGridSpacing     1.0

# ── Nonbonded ─────────────────────────────────────────────────────────────────
cutoff             12.0
switching          on
switchdist         10.0
pairlistdist       16.0
exclude            scaled1-4
oneFourScaling     1.0

# ── Constraints ───────────────────────────────────────────────────────────────
# rigidBonds all: constrain all H-bonds (N-H ω~3300 cm⁻¹, C-H ω~2950 cm⁻¹).
# Required for 2 fs integration of DNA; see Pan et al. (2014) JCTC 10:2906.
rigidBonds         all
rigidTolerance     1.0e-8

# ── Thermostat — Langevin 310 K ────────────────────────────────────────────────
temperature        310
langevin           on
langevinDamping    {langevin_damping}
langevinTemp       310
langevinHydrogen   off
"""


def _periodic_output_block(name: str, suffix: str, *, dcd_freq: int = 5000) -> str:
    out = f"output/{name}_{suffix}"
    return f"""\
# ── Output ────────────────────────────────────────────────────────────────────
outputName         {out}
outputEnergies     500
dcdFreq            {dcd_freq}
dcdFile            {out}.dcd
xstFreq            5000
xstFile            {out}.xst
restartfreq        50000
binaryrestart      yes
"""


def _render_periodic_equilibrate_npt_conf(
    name: str,
    box_nm: tuple[float, float, float],
    n_atoms: int,
    periodic_z_nm: float,
) -> str:
    """Restrained NPT box-discovery phase for a periodic unit cell.

    This phase is intentionally conservative: DNA heavy atoms are restrained so
    water/ions and lateral box dimensions can relax before the locked-Z
    production run. Z may fluctuate here; downstream scripts only harvest stable
    tail X/Y and restore Z to the exact crossover period.
    """
    header = _periodic_cell_header(
        name, box_nm, n_atoms, periodic_z_nm,
        mode="standard CUDA, restrained NPT box discovery",
        langevin_damping=5.0,  # stronger coupling during box discovery is fine
    )
    return header + f"""\

# ── Barostat — restrained NPT box discovery ──────────────────────────────────
useGroupPressure   yes
useFlexibleCell    no
useConstantArea    no
langevinPiston     on
langevinPistonTarget  1.01325
langevinPistonPeriod  200.0
langevinPistonDecay   100.0
langevinPistonTemp    310

# ── Integrator ────────────────────────────────────────────────────────────────
timestep           2.0        ;# 2 fs — safe with rigidBonds all
nonbondedFreq      1
fullElectFrequency 2
stepspercycle      10

# ── GPU acceleration (standard CUDA, not GPU-resident) ────────────────────────
# CUDASOAintegrate (GPU-resident) is disabled: wrap bonds span the periodic cell
# (O3' at z_end bonded to P at z_start, 7 nm apart in real space).  GPU-resident
# mode builds its exclusion list from pairlist distances and cannot find those
# partners → "Low global CUDA exclusion count" abort.  Standard CUDA mode handles
# PBC-wrapped bonded exclusions correctly via CPU bonded-force path.

{_periodic_output_block(name, "equilibrate_npt")}

# ── DNA restraints: B-factor column stores force constant kcal/mol/Å² ─────────
constraints        on
consref            {name}_restraints.pdb
conskfile          {name}_restraints.pdb
conskcol           B

# ── Run ───────────────────────────────────────────────────────────────────────
minimize           2000       ;# brief EM to relieve any solvation clashes
reinitvels         310
constraintScaling  1.0        ;# DNA heavy atoms restrained at k=1 kcal/mol/Å²
run                250000     ;# 500 ps restrained NPT box discovery
"""


def _render_periodic_locked_nvt_conf(
    name: str,
    box_nm: tuple[float, float, float],
    n_atoms: int,
    periodic_z_nm: float,
    *,
    suffix: str = "production_locked_nvt",
    run_steps: int = 25_000_000,
    restart_from: str | None = None,
    restraint_scaling: float | None = None,
) -> str:
    """Fixed-box locked-Z NVT phase.

    `scripts/lock_box_from_xst.py` patches X/Y from the stable NPT tail while
    preserving the exact Z period. The unpatched template starts from the
    generated box and PDB coordinates.
    """
    header = _periodic_cell_header(
        name, box_nm, n_atoms, periodic_z_nm,
        mode="standard CUDA, fixed-box locked-Z NVT",
    )
    if restart_from:
        start_block = f"""\
binCoordinates     output/{name}_{restart_from}.restart.coor
minimize           2000       ;# relax after restoring exact locked-Z cell
reinitvels         310        ;# do not reuse NPT velocities after box reset
"""
    else:
        start_block = "reinitvels         310\n"
    restraint_block = ""
    if restraint_scaling is not None:
        restraint_block = f"""\
# ── DNA restraints: B-factor column stores force constant kcal/mol/Å² ─────────
constraints        on
consref            {name}_restraints.pdb
conskfile          {name}_restraints.pdb
conskcol           B
constraintScaling  {restraint_scaling:.3f}

"""

    return header + f"""\

# ── Barostat — disabled for locked-Z production ──────────────────────────────
# Pressure is handled by the preceding NPT box-discovery phase. This phase fixes
# X/Y from the stable NPT tail and forces Z back to the exact 21 bp period.

# ── Integrator ────────────────────────────────────────────────────────────────
timestep           2.0        ;# 2 fs — safe with rigidBonds all
nonbondedFreq      1
fullElectFrequency 2
stepspercycle      10

# ── GPU acceleration (standard CUDA, not GPU-resident) ────────────────────────
# See benchmark_gpu_resident.conf for the experimental CUDASOA probe.

{_periodic_output_block(name, suffix)}

{restraint_block}\
# ── Run ───────────────────────────────────────────────────────────────────────
{start_block}run                {run_steps}
"""


def _render_periodic_benchmark_conf(
    name: str,
    box_nm: tuple[float, float, float],
    n_atoms: int,
    periodic_z_nm: float,
    *,
    gpu_resident: bool,
    n_steps: int = 5000,
) -> str:
    """Short benchmark config for standard CUDA or experimental CUDASOA."""
    suffix = "bench_gpu_resident" if gpu_resident else "bench_standard_cuda"
    mode = (
        "EXPERIMENTAL CUDASOAintegrate, fixed-box NVT"
        if gpu_resident else
        "standard CUDA, fixed-box NVT benchmark"
    )
    header = _periodic_cell_header(name, box_nm, n_atoms, periodic_z_nm, mode=mode)
    pairlist = 16.0
    gpu_block = ""
    if gpu_resident:
        gpu_block = """\

# ── GPU-resident integration probe ────────────────────────────────────────────
# Periodic wrap bonds are ~70 Å apart in real-space coordinates. NAMD 3.0.2
# GPUresident currently builds bonded exclusions from local CUDA tile/pair lists,
# so this topology is expected to fail unless NAMD gains PBC-aware GPUresident
# bonded exclusions or NADOC changes the topology representation. Kept as an
# explicit benchmark probe, not as a production recommendation.
GPUresident        on
"""
    return header.replace("pairlistdist       16.0", f"pairlistdist       {pairlist:.1f}") + f"""\

# ── Barostat — disabled for benchmark ────────────────────────────────────────

# ── Integrator ────────────────────────────────────────────────────────────────
timestep           2.0
nonbondedFreq      1
fullElectFrequency 2
stepspercycle      10
{gpu_block}
{_periodic_output_block(name, suffix, dcd_freq=999999999)}

# ── Run ───────────────────────────────────────────────────────────────────────
minimize           500
reinitvels         310
run                {n_steps}
"""


def _render_periodic_namd_conf(
    name: str,
    box_nm: tuple[float, float, float],
    n_atoms: int,
    periodic_z_nm: float,
) -> str:
    """Backward-compatible default config: restrained NPT box discovery."""
    return _render_periodic_equilibrate_npt_conf(name, box_nm, n_atoms, periodic_z_nm)


def _build_constraint_pdb_from_solvated(
    solvated_pdb: str,
    *,
    dna_k: float = 1.0,
) -> str:
    """Return a NAMD constraints PDB matching the solvated atom order.

    DNA ATOM records get B-factor `dna_k`; water and ions get B-factor 0.
    """
    out: list[str] = []
    for line in solvated_pdb.splitlines():
        if line.startswith("ATOM  "):
            out.append(f"{line[:60]}{dna_k:6.2f}{line[66:]}")
        elif line.startswith("HETATM"):
            out.append(f"{line[:60]}{0.0:6.2f}{line[66:]}")
        else:
            out.append(line)
    return "\n".join(out) + "\n"


_LOCK_BOX_FROM_XST_PY = r'''#!/usr/bin/env python3
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
'''

# ══════════════════════════════════════════════════════════════════════════════
# §3  ION PLACEMENT
# ══════════════════════════════════════════════════════════════════════════════

def _count_dna_charge(pdb_text: str) -> float:
    """Return the net DNA charge by counting backbone phosphate atoms.

    Each phosphate group carries -1 charge in solution (one charge per P atom).
    Heavy-atom PSF partial charges are NOT used because they omit H charges,
    making their sum meaningless for neutralisation purposes.
    """
    n_p = sum(
        1 for line in pdb_text.splitlines()
        if line.startswith("ATOM") and line[12:16].strip() == "P"
    )
    return float(-n_p)


def _ion_counts(
    n_waters: int,
    dna_charge: float,
    ion_conc_mM: float,
    box_nm: tuple[float, float, float],
) -> tuple[int, int]:
    """Return (n_Na, n_Cl) to neutralise DNA and reach target NaCl concentration."""
    n_na, _n_mg, n_cl = _ion_counts_mixed(
        n_waters=n_waters,
        dna_charge=dna_charge,
        nacl_mM=ion_conc_mM,
        mgcl2_mM=0.0,
        box_nm=box_nm,
    )
    return n_na, n_cl


@dataclasses.dataclass(frozen=True)
class IonCounts:
    """The ion census for one solvated cell, plus how it was arrived at."""
    n_na: int
    n_mg: int
    n_cl: int
    #: "mg" — the origami is neutralised by Mg(H₂O)₆²⁺ (the Aksimentiev recipe);
    #: "na" — neutralised by Na⁺ (only when no magnesium was requested).
    counterion: str
    #: Magnesium needed purely to neutralise the backbone.
    n_mg_neutralising: int
    #: Magnesium implied by the requested bulk concentration alone.
    n_mg_bulk: int
    #: Solvent volume (nm³) the bulk-concentration terms were computed over.
    volume_nm3: float
    #: |q_DNA| as an integer, for the neutrality assertion downstream.
    dna_neg_charge: int

    def as_tuple(self) -> tuple[int, int, int]:
        return self.n_na, self.n_mg, self.n_cl


def ion_counts(
    n_waters: int,
    dna_charge: float,
    *,
    nacl_mM: float,
    mgcl2_mM: float,
    box_nm: tuple[float, float, float],
    volume_nm3: Optional[float] = None,
    mg_hexahydrate: bool = True,
) -> IonCounts:
    """The canonical ion recipe.  ONE implementation, every caller.

    Follows the Aksimentiev origami protocol (Yoo, Li, Slone, Maffeo & Aksimentiev,
    Methods Mol Biol 1811, §3.3): the origami is neutralised by **Mg(H₂O)₆²⁺**, and
    Cl⁻ is then added to neutralise the *system* — which implies Mg in excess of the
    DNA charge whenever the requested bulk concentration exceeds what neutralisation
    alone needs.  **No Na⁺ is involved at all.**  That is the whole point of the
    published protocol: the standard monovalent parameterisation gets DNA-DNA forces
    in dense origami wrong, and MGHH²⁺ is what brings them back in line with
    experiment (Yoo & Aksimentiev, JPCL 3:45, JPCB 116:12946, NAR 44:2036).

    NADOC neutralised with Na⁺ until 2026-07-30 and treated Mg purely as a bulk
    bath, so the preset labelled "Standard (Aksimentiev)" was running a
    monovalent-screened system with a trace of magnesium.

    ``counterion`` is derived, not passed: magnesium neutralises whenever
    hexahydrate placement is on AND a nonzero Mg concentration was asked for.
    Setting Mg to 0 is an explicit request for no magnesium, and falls back to the
    legacy Na⁺ neutralisation so a deliberate monovalent-screening experiment still
    works.

    ``volume_nm3`` overrides the solvent volume used for the bulk-concentration
    terms.  The default is derived from the actual water count rather than the box:
    a rotation-sized (cubic) cell around an anisotropic origami is mostly empty
    corner, and charging bulk salt for that volume inflates the ion count.
    """
    # 1 nm³ = 1e-27 m³ = 1e-24 L  (since 1 m³ = 1000 L)
    if volume_nm3 is not None:
        vol_nm3 = float(volume_nm3)
    elif n_waters > 0:
        vol_nm3 = n_waters / _WATER_NUMBER_DENSITY_NM3
    else:
        bx, by, bz = box_nm
        vol_nm3 = bx * by * bz
    vol_L = vol_nm3 * 1e-24  # nm³ → L

    n_nacl = int(round(nacl_mM * 1e-3 * _NA * vol_L))
    n_mg_bulk = int(round(mgcl2_mM * 1e-3 * _NA * vol_L))
    dna_neg_charge = max(0, -int(round(dna_charge)))

    use_mg = bool(mg_hexahydrate and mgcl2_mM > 0)
    if use_mg:
        # ceil(|q|/2): an odd backbone charge leaves one unit over, which the Cl⁻
        # term below absorbs (2*n_mg - |q| == 1).
        n_mg_neutralising = -(-dna_neg_charge // 2)
        n_mg = max(n_mg_neutralising, n_mg_bulk)
        n_na = n_nacl
        # 2*n_mg >= |q| by construction, so this can never go negative.
        n_cl = 2 * n_mg - dna_neg_charge + n_nacl
    else:
        # Legacy monovalent path — kept for an explicit no-magnesium request.
        n_mg_neutralising = 0
        n_mg = n_mg_bulk
        n_na = dna_neg_charge + n_nacl
        n_cl = n_nacl + 2 * n_mg

    return IonCounts(
        n_na=n_na, n_mg=n_mg, n_cl=n_cl,
        counterion="mg" if use_mg else "na",
        n_mg_neutralising=n_mg_neutralising,
        n_mg_bulk=n_mg_bulk,
        volume_nm3=vol_nm3,
        dna_neg_charge=dna_neg_charge,
    )


def waters_needed_for_ions(ions: IonCounts, *, mg_hexahydrate: bool = True) -> int:
    """Water molecules the ion recipe will consume (pure).

    Every monatomic ion takes one water site; every Mg(H₂O)₆ takes six.  Neutralising
    a backbone with magnesium therefore costs ~3 waters per phosphate — enough that a
    tight hydration-shell carve can genuinely run out, which is why this is checked in
    the pre-flight rather than discovered an hour into solvation.
    """
    per_mg = MGH_WATERS_CONSUMED if mg_hexahydrate else 1
    return ions.n_na + ions.n_cl + ions.n_mg * per_mg


def _ion_counts_mixed(
    n_waters: int,
    dna_charge: float,
    nacl_mM: float,
    mgcl2_mM: float,
    box_nm: tuple[float, float, float],
    *,
    volume_nm3: Optional[float] = None,
    mg_hexahydrate: bool = True,
) -> tuple[int, int, int]:
    """(n_Na, n_Mg, n_Cl) — thin tuple wrapper over :func:`ion_counts`."""
    return ion_counts(
        n_waters, dna_charge, nacl_mM=nacl_mM, mgcl2_mM=mgcl2_mM, box_nm=box_nm,
        volume_nm3=volume_nm3, mg_hexahydrate=mg_hexahydrate,
    ).as_tuple()


def _place_ions(
    waters: list[_Water],
    n_na: int,
    n_cl: int,
    seed: int = 42,
) -> tuple[list[_Water], list[tuple[float, float, float]], list[tuple[float, float, float]]]:
    """Replace n_na + n_cl randomly selected water molecules with ions.

    Returns (remaining_waters, na_positions, cl_positions).
    Positions are (x, y, z) in nm at the former oxygen site.
    """
    rng = random.Random(seed)
    total_ions = n_na + n_cl
    if total_ions > len(waters):
        raise RuntimeError(
            f"Not enough water molecules ({len(waters)}) to place {total_ions} ions."
        )
    chosen_idx = rng.sample(range(len(waters)), total_ions)
    na_idx = set(chosen_idx[:n_na])
    cl_idx = set(chosen_idx[n_na:])

    remaining: list[_Water] = []
    na_pos: list[tuple[float, float, float]] = []
    cl_pos: list[tuple[float, float, float]] = []

    for i, w in enumerate(waters):
        if i in na_idx:
            na_pos.append((w.ox, w.oy, w.oz))
        elif i in cl_idx:
            cl_pos.append((w.ox, w.oy, w.oz))
        else:
            remaining.append(w)

    return remaining, na_pos, cl_pos


def _place_ions_mixed(
    waters: list[_Water],
    n_na: int,
    n_mg: int,
    n_cl: int,
    seed: int = 42,
    mg_hexahydrate: bool = False,
    progress: Optional[ProgressCb] = None,
    dna_pdb_text: "str | None" = None,
) -> tuple[
    list[_Water],
    list[tuple[float, float, float]],
    list[tuple[float, float, float]],
    list[tuple[float, float, float]],
    list[_MgHexahydrate],
]:
    """Replace waters with Na+, Mg2+/MGH, and Cl- ions."""
    if mg_hexahydrate:
        return _place_ions_mixed_mgh(waters, n_na, n_mg, n_cl, seed=seed,
                                     progress=progress, dna_pdb_text=dna_pdb_text)

    rng = random.Random(seed)
    total_ions = n_na + n_mg + n_cl
    if total_ions > len(waters):
        raise RuntimeError(
            f"Not enough water molecules ({len(waters)}) to place {total_ions} ions."
        )
    chosen_idx = rng.sample(range(len(waters)), total_ions)
    na_idx = set(chosen_idx[:n_na])
    mg_idx = set(chosen_idx[n_na:n_na + n_mg])
    cl_idx = set(chosen_idx[n_na + n_mg:])

    remaining: list[_Water] = []
    na_pos: list[tuple[float, float, float]] = []
    mg_pos: list[tuple[float, float, float]] = []
    cl_pos: list[tuple[float, float, float]] = []

    for i, w in enumerate(waters):
        if i in na_idx:
            na_pos.append((w.ox, w.oy, w.oz))
        elif i in mg_idx:
            mg_pos.append((w.ox, w.oy, w.oz))
        elif i in cl_idx:
            cl_pos.append((w.ox, w.oy, w.oz))
        else:
            remaining.append(w)

    return remaining, na_pos, mg_pos, cl_pos, []


#: How far from the phosphate backbone a Mg(H₂O)₆ may be seeded (nm).  1.2 nm spans
#: the first and second hydration shells, where divalent counterions actually condense;
#: wide enough that a large origami has far more candidate sites than clusters to place,
#: so the selection stays a random draw from the shell rather than a rank-ordered pile-up
#: on the very closest waters.
MGH_SEED_SHELL_NM = 1.2


def _shell_biased_order(pos, dna_pdb_text: "str | None", n_mg: int,
                        fallback_order: list, rng) -> list:
    """Shuffled water indices lying within :data:`MGH_SEED_SHELL_NM` of the backbone.

    Returns ``[]`` when there is no solute to condense on, or when the shell holds
    too few waters to be worth a separate pass — the caller then falls back to the
    uniform draw, which is the old behaviour.

    Cost is one KD-tree over **P atoms only** (~1/32 of the DNA atoms) plus one
    bounded query per water.  Querying with ``distance_upper_bound`` lets SciPy prune
    aggressively, so this stays well inside the placement budget that
    ``tests/test_md_ion_placement.py`` pins.
    """
    if not dna_pdb_text or n_mg <= 0:
        return []
    try:
        import numpy as np  # noqa: PLC0415
        from scipy.spatial import cKDTree  # noqa: PLC0415

        p_atoms = _dna_atom_positions_nm(dna_pdb_text, "P")
        if not p_atoms:
            return []
        dist, _ = cKDTree(np.asarray(p_atoms, dtype=float)).query(
            pos, k=1, distance_upper_bound=MGH_SEED_SHELL_NM, workers=-1)
        shell = np.flatnonzero(np.isfinite(dist))
        if shell.size < n_mg:
            # Not enough shell sites to seed every cluster — let the caller mix shell
            # first, bulk after, rather than pretending the shell is sufficient.
            logger.info("Mg seeding: shell holds %d waters for %d clusters; "
                        "the remainder will be placed in bulk", shell.size, n_mg)
        idx = shell.tolist()
        rng.shuffle(idx)
        return idx
    except Exception as exc:  # noqa: BLE001 — biasing is an improvement, not a gate
        logger.warning("Mg shell biasing unavailable (%s); placing uniformly", exc)
        return []


def _ideal_mgh_cluster(mg: tuple[float, float, float]) -> _MgHexahydrate:
    """Build an ideal octahedral Mg(H2O)6 cluster around *mg* in nm."""
    import numpy as np

    mg_vec = np.asarray(mg, dtype=float)
    mg_o_nm = 0.1940
    oh_nm = 0.09572
    half_angle = math.radians(104.52 / 2.0)
    waters: list[_Water] = []

    for direction in _MGH_DIRECTIONS:
        radial = np.asarray(direction, dtype=float)
        radial /= np.linalg.norm(radial)
        if abs(float(np.dot(radial, np.array([0.0, 0.0, 1.0])))) < 0.9:
            tangent = np.cross(radial, np.array([0.0, 0.0, 1.0]))
        else:
            tangent = np.cross(radial, np.array([0.0, 1.0, 0.0]))
        tangent /= np.linalg.norm(tangent)
        oxygen = mg_vec + radial * mg_o_nm
        h_mid = radial * math.cos(half_angle)
        h_spread = tangent * math.sin(half_angle)
        h1 = oxygen + oh_nm * (h_mid + h_spread)
        h2 = oxygen + oh_nm * (h_mid - h_spread)
        waters.append(_Water(
            float(oxygen[0]), float(oxygen[1]), float(oxygen[2]),
            float(h1[0]), float(h1[1]), float(h1[2]),
            float(h2[0]), float(h2[1]), float(h2[2]),
        ))
    return _MgHexahydrate(mg=mg, waters=waters)


def _place_ions_mixed_mgh(
    waters: list[_Water],
    n_na: int,
    n_mg: int,
    n_cl: int,
    seed: int = 42,
    progress: Optional[ProgressCb] = None,
    dna_pdb_text: "str | None" = None,
) -> tuple[
    list[_Water],
    list[tuple[float, float, float]],
    list[tuple[float, float, float]],
    list[tuple[float, float, float]],
    list[_MgHexahydrate],
]:
    """Replace waters with Na+, MGH clusters, and Cl- ions.

    Each MGH cluster takes one water site as the Mg center plus (up to) five
    nearby waters that are removed to vacate room for the idealized Mg(H2O)6
    residue — six waters per cluster.  Na+/Cl- then take random remaining sites.

    ``dna_pdb_text`` turns on **solute-biased Mg placement**: cluster centres are
    drawn from waters within :data:`MGH_SEED_SHELL_NM` of the phosphate backbone
    before falling back to the bulk.  The tutorial does this explicitly — it inserts
    MGHH into the DRY system before solvating, *"because MGHH2+ molecules diffuse
    slowly, it is beneficial to place them initially in proximity to the DNA origami
    structure"* (Methods Mol Biol 1811 §3.3).  Placing them uniformly through the box
    (what NADOC did until 2026-07-30) means the divalent atmosphere has to form by
    diffusion, which will not happen over a 19 ns ladder.  Omit it for a bulk
    electrolyte with no solute to condense on.

    Performance: a single shuffled draw order + one cKDTree drives selection in
    ~O(n_ions·log n_water).  The previous implementation rebuilt a ``tuple`` of
    the entire (millions-strong) available-water set on *every* ion and sorted
    all waters per Mg cluster — quadratic, taking tens of minutes and freezing
    the progress bar on origami-scale systems (e.g. VoltronCore, ~1.5 M waters).
    """
    import numpy as np  # noqa: PLC0415
    from scipy.spatial import cKDTree  # noqa: PLC0415

    n = len(waters)
    total_replaced = n_na + n_cl + MGH_WATERS_CONSUMED * n_mg
    if total_replaced > n:
        raise RuntimeError(
            f"Not enough water molecules ({n}) to place {n_mg} MGH "
            f"clusters plus {n_na + n_cl} monatomic ions."
        )

    _emit(progress, "assemble", 0.5, "Placing Mg(H₂O)₆ clusters + ions…")

    pos = np.empty((n, 3), dtype=float)
    for i, w in enumerate(waters):
        pos[i, 0] = w.ox
        pos[i, 1] = w.oy
        pos[i, 2] = w.oz
    tree = cKDTree(pos) if n_mg else None

    rng = random.Random(seed)
    order = list(range(n))
    rng.shuffle(order)
    # Mg centres come from the hydration shell first; everything else (and any
    # overflow) uses the plain shuffled order.
    mg_order = _shell_biased_order(pos, dna_pdb_text, n_mg, order, rng) if n_mg else []
    mg_cursor = 0
    cursor = 0
    claimed = bytearray(n)   # 0/1 flag per water; O(1) membership, no giant tuples

    def next_unclaimed() -> int:
        nonlocal cursor
        while claimed[order[cursor]]:
            cursor += 1
        idx = order[cursor]
        cursor += 1
        claimed[idx] = 1
        return idx

    def next_mg_center() -> int:
        """A cluster centre from the hydration shell, else from the bulk."""
        nonlocal mg_cursor
        while mg_cursor < len(mg_order):
            idx = mg_order[mg_cursor]
            mg_cursor += 1
            if not claimed[idx]:
                claimed[idx] = 1
                return idx
        return next_unclaimed()          # shell exhausted → bulk

    def water_xyz(idx: int) -> tuple[float, float, float]:
        return (float(pos[idx, 0]), float(pos[idx, 1]), float(pos[idx, 2]))

    # ── Mg(H2O)6 clusters: center water + 5 nearest unclaimed waters ──────────
    _K = 16   # query margin so 5 unclaimed neighbours are virtually always found
    mgh_clusters: list[_MgHexahydrate] = []
    for m in range(n_mg):
        center = next_mg_center()
        removed = 0
        if tree is not None:
            _, idxs = tree.query(pos[center], k=min(n, _K))
            for j in np.atleast_1d(idxs):
                j = int(j)
                if j == center or claimed[j]:
                    continue
                claimed[j] = 1
                removed += 1
                if removed == 5:
                    break
        # Top up from the shuffled order if the local cloud was already crowded.
        while removed < 5 and cursor < n:
            next_unclaimed()
            removed += 1
        mgh_clusters.append(_ideal_mgh_cluster(water_xyz(center)))
        if progress is not None and n_mg and (m & 0xFF) == 0:
            _emit(progress, "assemble", 0.5 + 0.02 * (m / n_mg), "Placing Mg(H₂O)₆ clusters…")

    # ── Monatomic Na+ / Cl- from the remaining sites ──────────────────────────
    na_pos = [water_xyz(next_unclaimed()) for _ in range(n_na)]
    cl_pos = [water_xyz(next_unclaimed()) for _ in range(n_cl)]

    _emit(progress, "assemble", 0.54, "Finalising ion placement…")
    remaining = [w for i, w in enumerate(waters) if not claimed[i]]
    return remaining, na_pos, [], cl_pos, mgh_clusters


# ══════════════════════════════════════════════════════════════════════════════
# §4  PSF MERGING
# ══════════════════════════════════════════════════════════════════════════════

# NAMD matches PSF atoms to PDB atoms by (segid, resid, atomname).
# PDB resid is a 4-char field: values > 9999 are not parseable as plain integers
# by NAMD's PDB reader (atoi fails on hybrid-36 strings like "A001"), causing
# false key collisions and "atoms not the same" errors.  Cap at _MAX_RESID per
# segment and spread water across SOLV/SOL1/SOL2/… segments to stay within limit.
_MAX_RESID = 9000


def _water_seg_info(wi: int) -> tuple[str, int]:
    """Return (segid, local_resid) for the wi-th water molecule (0-based)."""
    seg_num   = wi // _MAX_RESID
    local_rid = (wi % _MAX_RESID) + 1
    return f"W{seg_num:03d}", local_rid


def _ion_seg_info(ii: int) -> tuple[str, int]:
    """Return (segid, local_resid) for the ii-th ion (0-based)."""
    seg_num   = ii // _MAX_RESID
    local_rid = (ii % _MAX_RESID) + 1
    return f"I{seg_num:03d}", local_rid


# PSF atom line format (same extended layout as pdb_export.export_psf):
# %10d %-8s %-8s %-8s %-8s %-6s %14.6f%14.6f%9d
def _psf_atom_line(
    serial: int,
    segid: str,
    resid: int,
    resname: str,
    atomname: str,
    atomtype: str,
    charge: float,
    mass: float,
) -> str:
    return (
        f"{serial:>10d} "
        f"{segid:<8s} "
        f"{str(resid):<8s} "
        f"{resname:<8s} "
        f"{atomname:<8s} "
        f"{atomtype:<6s} "
        f"{charge:>14.6f}"
        f"{mass:>14.6f}"
        f"{'0':>9s}"
    )


def _psf_bond_lines(bonds: list[tuple[int, int]]) -> list[str]:
    """Format PSF NBOND data lines (4 pairs per line, 8-char serial cols)."""
    lines = []
    for i in range(0, len(bonds), 4):
        chunk = bonds[i:i + 4]
        lines.append("".join(f"{a:8d}{b:8d}" for a, b in chunk))
    return lines


def _psf_angle_lines(angles: list[tuple[int, int, int]]) -> list[str]:
    """Format PSF NTHETA data lines (3 triplets per line, 8-char serial cols)."""
    lines = []
    for i in range(0, len(angles), 3):
        chunk = angles[i:i + 3]
        lines.append("".join(f"{a:8d}{b:8d}{c:8d}" for a, b, c in chunk))
    return lines


def _find_last_atom_serial(psf_text: str) -> int:
    """Return the highest serial number in the !NATOM section."""
    in_natom = False
    last_serial = 0
    for line in psf_text.splitlines():
        if "!NATOM" in line:
            in_natom = True
            continue
        if in_natom:
            stripped = line.strip()
            if not stripped or stripped.startswith("!"):
                break
            try:
                serial = int(line.split()[0])
                last_serial = max(last_serial, serial)
            except (ValueError, IndexError):
                pass
    return last_serial


def _extend_psf(
    dna_psf: str,
    waters: list[_Water],
    na_pos: list[tuple[float, float, float]],
    cl_pos: list[tuple[float, float, float]],
    mg_pos: list[tuple[float, float, float]] | None = None,
    mgh_clusters: list[_MgHexahydrate] | None = None,
    progress: Optional[ProgressCb] = None,
) -> str:
    """Extend a complete DNA PSF with TIP3P water and ions.

    Modifies NATOM, NBOND, NTHETA section counts and appends new entries.
    Water angles (H1-OH2-H2) and bonds (OH2-H1, OH2-H2, H1-H2) are added.
    Ions have no bonds or angles.
    """
    base_serial = _find_last_atom_serial(dna_psf)

    # ── Build new atom lines and bond/angle tables ────────────────────────────
    new_atom_lines: list[str] = []
    new_bonds: list[tuple[int, int]] = []
    new_angles: list[tuple[int, int, int]] = []

    serial = base_serial

    n_waters = len(waters) or 1
    for wi, w in enumerate(waters):
        if progress is not None and (wi & 0x1FFFF) == 0:  # every ~131k waters
            _emit(progress, "assemble", 0.55 + 0.2 * (wi / n_waters),
                  "Building solvated topology (PSF)…")
        s_oh2 = serial + 1
        s_h1  = serial + 2
        s_h2  = serial + 3
        serial += 3
        segid, resid = _water_seg_info(wi)

        new_atom_lines.append(
            _psf_atom_line(s_oh2, segid, resid, "TIP3", "OH2", *_TIP3_PARAMS["OH2"])
        )
        new_atom_lines.append(
            _psf_atom_line(s_h1,  segid, resid, "TIP3", "H1",  *_TIP3_PARAMS["H1"])
        )
        new_atom_lines.append(
            _psf_atom_line(s_h2,  segid, resid, "TIP3", "H2",  *_TIP3_PARAMS["H2"])
        )
        # Bonds: OH2-H1, OH2-H2, H1-H2 (H1-H2 needed for SHAKE in NAMD)
        new_bonds.extend([(s_oh2, s_h1), (s_oh2, s_h2), (s_h1, s_h2)])
        # Angle: H1-OH2-H2
        new_angles.append((s_h1, s_oh2, s_h2))

    mg_pos = mg_pos or []
    mgh_clusters = mgh_clusters or []

    ion_idx = 0
    for i, (x, y, z) in enumerate(na_pos):
        serial += 1
        segid, resid = _ion_seg_info(ion_idx)
        ion_idx += 1
        new_atom_lines.append(
            _psf_atom_line(serial, segid, resid, "SOD", "SOD", *_ION_PARAMS["SOD"])
        )

    for i, (x, y, z) in enumerate(mg_pos):
        serial += 1
        segid, resid = _ion_seg_info(ion_idx)
        ion_idx += 1
        new_atom_lines.append(
            _psf_atom_line(serial, segid, resid, "MG", "MG", *_ION_PARAMS["MG"])
        )

    for cluster in mgh_clusters:
        segid, resid = _ion_seg_info(ion_idx)
        ion_idx += 1
        s_mg = serial + 1
        serial += 1
        new_atom_lines.append(
            _psf_atom_line(s_mg, segid, resid, "MGH", "MG", *_MGH_PARAMS["MG"])
        )
        for water_idx, (oname, h1name, h2name) in enumerate(_MGH_WATER_NAMES):
            s_o = serial + 1
            s_h1 = serial + 2
            s_h2 = serial + 3
            serial += 3
            new_atom_lines.append(
                _psf_atom_line(s_o, segid, resid, "MGH", oname, *_MGH_PARAMS["O"])
            )
            new_atom_lines.append(
                _psf_atom_line(s_h1, segid, resid, "MGH", h1name, *_MGH_PARAMS["H"])
            )
            new_atom_lines.append(
                _psf_atom_line(s_h2, segid, resid, "MGH", h2name, *_MGH_PARAMS["H"])
            )
            new_bonds.extend([(s_o, s_h1), (s_o, s_h2), (s_h1, s_h2)])
            new_angles.append((s_h1, s_o, s_h2))

    for i, (x, y, z) in enumerate(cl_pos):
        serial += 1
        segid, resid = _ion_seg_info(ion_idx)
        ion_idx += 1
        new_atom_lines.append(
            _psf_atom_line(serial, segid, resid, "CLA", "CLA", *_ION_PARAMS["CLA"])
        )

    # ── Patch PSF sections ────────────────────────────────────────────────────
    # We scan the PSF line by line, update each !NXXX count, and append data.

    n_new_atoms  = len(new_atom_lines)
    n_new_bonds  = len(new_bonds)
    n_new_angles = len(new_angles)

    natom_re  = re.compile(r"^(\s*)(\d+)(\s+!NATOM.*)")
    nbond_re  = re.compile(r"^(\s*)(\d+)(\s+!NBOND.*)")
    ntheta_re = re.compile(r"^(\s*)(\d+)(\s+!NTHETA.*)")

    out: list[str] = []
    lines = dna_psf.splitlines()
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]

        m = natom_re.match(line)
        if m:
            old_count = int(m.group(2))
            out.append(f"{old_count + n_new_atoms:>8d}{m.group(3)}")
            i += 1
            # Copy existing atom data lines
            while i < n and lines[i].strip() and not lines[i].strip().startswith("!"):
                out.append(lines[i])
                i += 1
            # Append new atoms
            out.extend(new_atom_lines)
            out.append("")   # blank separator
            continue

        m = nbond_re.match(line)
        if m:
            old_count = int(m.group(2))
            out.append(f"{old_count + n_new_bonds:>8d}{m.group(3)}")
            i += 1
            # Copy existing bond data lines
            while i < n and lines[i].strip() and not lines[i].strip().startswith("!"):
                out.append(lines[i])
                i += 1
            # Append new bonds
            out.extend(_psf_bond_lines(new_bonds))
            out.append("")
            continue

        m = ntheta_re.match(line)
        if m:
            old_count = int(m.group(2))
            out.append(f"{old_count + n_new_angles:>8d}{m.group(3)}")
            i += 1
            # Copy existing angle data lines
            while i < n and lines[i].strip() and not lines[i].strip().startswith("!"):
                out.append(lines[i])
                i += 1
            # Append new angles
            out.extend(_psf_angle_lines(new_angles))
            out.append("")
            continue

        out.append(line)
        i += 1

    return "\n".join(out) + "\n"


# ══════════════════════════════════════════════════════════════════════════════
# §5  SOLVATED PDB
# ══════════════════════════════════════════════════════════════════════════════

_H36_DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

def _h36(value: int, width: int) -> str:
    """Hybrid-36 encoding: integers beyond 10^width get letter prefixes."""
    limit = 10 ** width
    if value < limit:
        return str(value).rjust(width)
    # Standard hybrid-36 algorithm
    value -= limit
    base = 26 * (limit // 10)
    if value < base:
        prefix = "A"
    else:
        value -= base
        prefix = "a"
    digits = []
    v = value
    for _ in range(width - 1):
        digits.append(_H36_DIGITS[v % 36])
        v //= 36
    digits.append(prefix)
    return "".join(reversed(digits))


def _hetatm_record(
    serial: int,
    name: str,
    resname: str,
    chain: str,
    resseq: int,
    x: float,   # Angstrom
    y: float,
    z: float,
    segname: str = "",
) -> str:
    """Format a PDB HETATM record.

    segname (optional): written at cols 73-76 so NAMD can match PSF segid to
    PDB atoms.  Omitting it produces a standard 66-column record.  resseq must
    be ≤9999 (plain integer); values above 9999 produce hybrid-36 strings that
    NAMD cannot parse as residue numbers.
    """
    # PDB HETATM format:
    # cols 1-6:   record name "HETATM"
    # cols 7-11:  serial (5-char, hybrid-36)
    # col  12:    space
    # cols 13-16: atom name (left-pad 1 space for 1-letter element, else no pad)
    # col  17:    alternate location indicator (space)
    # cols 18-20: residue name (3-char right-justified; here 3-4 char)
    # col  21:    space (or chain in some variants)
    # col  22:    chain ID
    # cols 23-26: residue seq num (plain decimal, must be ≤9999)
    # col  27:    insertion code (space)
    # cols 28-30: spaces
    # cols 31-38: x (8.3f)
    # cols 39-46: y (8.3f)
    # cols 47-54: z (8.3f)
    # cols 55-60: occupancy  "  1.00"
    # cols 61-66: temp factor "  0.00"
    # cols 67-76: (optional) 6 spaces + 4-char segname
    # NAMD matches PDB atoms by (segid,resid,atomname) — not serial.
    # Cap at 9999 so the serial field always has a leading space (HETATM + space +
    # 4-digit serial = unambiguous record-type detection by NAMD's PDB parser).
    # 5-digit serials (10000+) abut "HETATM" with no space, causing NAMD to
    # misread the record type and silently skip the atom → count mismatch.
    pdb_serial = (serial - 1) % 9999 + 1
    name_field = f" {name:<3s}" if len(name) < 4 else f"{name:<4s}"
    base = (
        f"HETATM{pdb_serial:5d} {name_field} {resname:<4s}{chain}{resseq:4d}    "
        f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00"
    )
    if segname:
        base += f"      {segname:<4s}"
    return base


def _build_solvated_pdb(
    dna_pdb: str,
    waters: list[_Water],
    na_pos: list[tuple[float, float, float]],
    cl_pos: list[tuple[float, float, float]],
    box_nm: tuple[float, float, float],
    base_serial: int,
    mg_pos: list[tuple[float, float, float]] | None = None,
    mgh_clusters: list[_MgHexahydrate] | None = None,
    progress: Optional[ProgressCb] = None,
) -> str:
    """Build a PDB with DNA ATOM records + water/ion HETATM records.

    DNA atoms are taken verbatim from dna_pdb (ATOM/TER/LINK/REMARK lines).
    Water and ions are appended as HETATM records.
    CRYST1 is rewritten with solvated box dimensions.
    """
    NM_TO_A = 10.0
    bx, by, bz = box_nm

    # Replace or prepend CRYST1 with solvated box
    cryst1 = (
        f"CRYST1{bx * NM_TO_A:9.3f}{by * NM_TO_A:9.3f}{bz * NM_TO_A:9.3f}"
        f"  90.00  90.00  90.00 P 1           1"
    )

    # Strip old CRYST1 and END from dna_pdb; keep everything else
    dna_lines = [
        ln for ln in dna_pdb.splitlines()
        if not ln.startswith("CRYST1") and not ln.startswith("END")
    ]

    out: list[str] = [cryst1] + dna_lines

    serial = base_serial

    n_waters = len(waters) or 1
    for wi, w in enumerate(waters):
        if progress is not None and (wi & 0x1FFFF) == 0:  # every ~131k waters
            _emit(progress, "assemble", 0.78 + 0.2 * (wi / n_waters),
                  "Writing solvated structure (PDB)…")
        s_oh2 = serial + 1
        s_h1  = serial + 2
        s_h2  = serial + 3
        serial += 3
        segid, resid = _water_seg_info(wi)
        ox_a  = w.ox  * NM_TO_A
        oy_a  = w.oy  * NM_TO_A
        oz_a  = w.oz  * NM_TO_A
        h1x_a = w.h1x * NM_TO_A
        h1y_a = w.h1y * NM_TO_A
        h1z_a = w.h1z * NM_TO_A
        h2x_a = w.h2x * NM_TO_A
        h2y_a = w.h2y * NM_TO_A
        h2z_a = w.h2z * NM_TO_A
        out.append(_hetatm_record(s_oh2, "OH2", "TIP3", "W", resid, ox_a,  oy_a,  oz_a,  segname=segid))
        out.append(_hetatm_record(s_h1,  "H1",  "TIP3", "W", resid, h1x_a, h1y_a, h1z_a, segname=segid))
        out.append(_hetatm_record(s_h2,  "H2",  "TIP3", "W", resid, h2x_a, h2y_a, h2z_a, segname=segid))

    mg_pos = mg_pos or []
    mgh_clusters = mgh_clusters or []

    ion_idx = 0
    for i, (x_nm, y_nm, z_nm) in enumerate(na_pos):
        serial += 1
        segid, resid = _ion_seg_info(ion_idx)
        ion_idx += 1
        out.append(_hetatm_record(
            serial, "SOD", "SOD", "I", resid,
            x_nm * NM_TO_A, y_nm * NM_TO_A, z_nm * NM_TO_A,
            segname=segid,
        ))

    for i, (x_nm, y_nm, z_nm) in enumerate(mg_pos):
        serial += 1
        segid, resid = _ion_seg_info(ion_idx)
        ion_idx += 1
        out.append(_hetatm_record(
            serial, "MG", "MG", "I", resid,
            x_nm * NM_TO_A, y_nm * NM_TO_A, z_nm * NM_TO_A,
            segname=segid,
        ))

    for cluster in mgh_clusters:
        segid, resid = _ion_seg_info(ion_idx)
        ion_idx += 1
        serial += 1
        out.append(_hetatm_record(
            serial, "MG", "MGH", "I", resid,
            cluster.mg[0] * NM_TO_A, cluster.mg[1] * NM_TO_A, cluster.mg[2] * NM_TO_A,
            segname=segid,
        ))
        for water, (oname, h1name, h2name) in zip(cluster.waters, _MGH_WATER_NAMES):
            serial += 1
            out.append(_hetatm_record(
                serial, oname, "MGH", "I", resid,
                water.ox * NM_TO_A, water.oy * NM_TO_A, water.oz * NM_TO_A,
                segname=segid,
            ))
            serial += 1
            out.append(_hetatm_record(
                serial, h1name, "MGH", "I", resid,
                water.h1x * NM_TO_A, water.h1y * NM_TO_A, water.h1z * NM_TO_A,
                segname=segid,
            ))
            serial += 1
            out.append(_hetatm_record(
                serial, h2name, "MGH", "I", resid,
                water.h2x * NM_TO_A, water.h2y * NM_TO_A, water.h2z * NM_TO_A,
                segname=segid,
            ))

    for i, (x_nm, y_nm, z_nm) in enumerate(cl_pos):
        serial += 1
        segid, resid = _ion_seg_info(ion_idx)
        ion_idx += 1
        out.append(_hetatm_record(
            serial, "CLA", "CLA", "I", resid,
            x_nm * NM_TO_A, y_nm * NM_TO_A, z_nm * NM_TO_A,
            segname=segid,
        ))

    out.append("END")
    return "\n".join(out) + "\n"


def _mgh_extrabonds(
    base_serial: int,
    n_waters: int,
    n_na: int,
    n_mg: int,
    n_mgh: int,
    *,
    k: float = 1.0,
    distance_ang: float = 1.94,
) -> str:
    """Return NAMD extraBonds for Mg-O links in MGH residues.

    The 1.94 Å / 1 kcal mol^-1 Å^-2 default follows the published
    DNA-origami Mg-hexahydrate setup used for counterion equilibration.
    NAMD extraBonds uses zero-based atom indices in this project.
    """
    if n_mgh <= 0:
        return ""
    first_mgh_serial = base_serial + n_waters * 3 + n_na + n_mg + 1
    lines: list[str] = []
    for cluster_idx in range(n_mgh):
        s_mg = first_mgh_serial + cluster_idx * 19
        for water_idx in range(6):
            s_o = s_mg + 1 + water_idx * 3
            lines.append(f"bond {s_mg - 1:d} {s_o - 1:d} {k:.4f} {distance_ang:.4f}")
    return "\n".join(lines) + "\n"


# ══════════════════════════════════════════════════════════════════════════════
# §6  NAMD CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

def _render_solvated_namd_conf(
    name: str,
    box_nm: tuple[float, float, float],
    n_atoms: int,
    *,
    nacl_mM: float = 150.0,
    mgcl2_mM: float = 0.0,
    mg_hexahydrate: bool = False,
) -> str:
    bx, by, bz = box_nm
    bx_a, by_a, bz_a = bx * 10, by * 10, bz * 10
    cx, cy, cz = bx_a / 2, by_a / 2, bz_a / 2
    return f"""\
# NAMD explicit-solvent configuration generated by NADOC
# System: {name}  ({n_atoms:,} atoms, TIP3P water + {nacl_mM:g} mM NaCl + {mgcl2_mM:g} mM MgCl2)
# Mode:   Standard CUDA, PME electrostatics, minimization preflight

structure          {name}.psf
coordinates        {name}.pdb
outputName         output/{name}

paraTypeCharmm     on
parameters         forcefield/par_all36_na.prm
parameters         forcefield/toppar_water_ions_cufix.str
parameters         forcefield/par_stub_ions_nbfix.str
{("extraBonds         on\nextraBondsFile     mgh_extrabonds.txt\n") if mg_hexahydrate else ""}

# ── Periodic boundary conditions ──────────────────────────────────────────────
cellBasisVector1   {bx_a:.3f}  0.000    0.000
cellBasisVector2   0.000    {by_a:.3f}  0.000
cellBasisVector3   0.000    0.000    {bz_a:.3f}
cellOrigin         {cx:.3f}   {cy:.3f}   {cz:.3f}

wrapAll            on
wrapWater          on

# ── PME electrostatics ────────────────────────────────────────────────────────
PME                yes
PMEGridSpacing     1.0

# ── Nonbonded ─────────────────────────────────────────────────────────────────
cutoff             12.0
switching          on
switchdist         10.0
pairlistdist       14.0
exclude            scaled1-4
oneFourScaling     1.0

# ── Constraints ───────────────────────────────────────────────────────────────
# First-contact minimization must not use RATTLE/SHAKE; enable rigidBonds all
# only in downstream dynamics configs after minimization has relieved clashes.
rigidBonds         none
rigidTolerance     1.0e-8

# ── Thermostat ────────────────────────────────────────────────────────────────
temperature        0
langevin           on
langevinDamping    5
langevinTemp       0
langevinHydrogen   off

# ── Barostat ──────────────────────────────────────────────────────────────────
useGroupPressure   yes
useFlexibleCell    no
useConstantArea    no
langevinPiston     off
langevinPistonTarget  1.01325
langevinPistonPeriod  200.0
langevinPistonDecay   100.0
langevinPistonTemp    0

# ── Integrator ────────────────────────────────────────────────────────────────
timestep           1.0        ;# minimization/preflight config
nonbondedFreq      1
fullElectFrequency 1
stepspercycle      10

# ── GPU acceleration ──────────────────────────────────────────────────────────
# Standard CUDA is the default for reproducibility. GPU-resident can be tested
# separately after validating energy/temperature/structure.

# ── Output ────────────────────────────────────────────────────────────────────
outputEnergies     500
dcdFreq            5000
dcdFile            output/{name}.dcd
xstFreq            5000
xstFile            output/{name}.xst
restartfreq        50000
binaryrestart      yes

# ── Run ───────────────────────────────────────────────────────────────────────
minimize           2000       ;# use managed ladder configs for dynamics
run                0
"""


def _render_solvated_fast_namd_conf(
    name: str,
    box_nm: tuple[float, float, float],
    n_atoms: int,
    *,
    nacl_mM: float = 150.0,
    mgcl2_mM: float = 0.0,
    mg_hexahydrate: bool = False,
    n_hmr: int = 0,
    nvt_only: bool = False,
    run_steps: int = 250000,
    capture_vel_force: bool = False,
) -> str:
    from backend.core.namd_helpers import vel_force_dcd_block
    bx, by, bz = box_nm
    bx_a, by_a, bz_a = bx * 10, by * 10, bz * 10
    cx, cy, cz = bx_a / 2, by_a / 2, bz_a / 2
    vf_block = vel_force_dcd_block(f"output/{name}_fast", 9600, capture=capture_vel_force)
    # ``nvt_only`` is set exactly when the package was built with a water-shell carve,
    # and a carved cell contains vacuum.  NAMD 3 GPU-resident sizes its GPU tile /
    # exclusion buffers from the cell-average density, so it under-counts exclusions in
    # a sparse cell and dies at step 0 with "Low global CUDA exclusion count!".  Keep
    # HMR + rigidBonds all + 4 fs (all fine) but run the standard CUDA-offload path.
    gpu_resident_block = (
        "# GPUresident is OMITTED: this package was built with a water-shell carve, and\n"
        "# NAMD 3 GPU-resident cannot handle a cell containing vacuum (it needs >=~90%\n"
        "# water fill).  Nonbonded + PME still run on the GPU via the standard CUDA path."
        if nvt_only else
        "GPUresident        on"
    )
    piston = (
        "langevinPiston     off\n"
        if nvt_only else
        """useGroupPressure   yes
useFlexibleCell    no
useConstantArea    no
langevinPiston     on
langevinPistonTarget  1.01325
langevinPistonPeriod  1000.0
langevinPistonDecay   500.0
langevinPistonTemp    300
"""
    )
    return f"""\
# NAMD explicit-solvent fast-relaxation template generated by NADOC
# System: {name}  ({n_atoms:,} atoms, TIP3P water + {nacl_mM:g} mM NaCl + {mgcl2_mM:g} mM MgCl2)
# Mode:   HMR ({n_hmr:,} non-water H) + 4 fs {"(CUDA offload — carved cell)" if nvt_only else "+ GPUresident"}
#
# Use after namd.conf minimization/preflight has completed cleanly.  GPUresident
# requires a UNIFORMLY FILLED cell (>=~90% water): it sizes its GPU exclusion/tile
# buffers from the cell-average density, so a water-shell-carved cell (vacuum corners)
# dies at step 0 with "Low global CUDA exclusion count!".  It is omitted automatically
# for carved packages.

structure          {name}_hmr.psf
coordinates        {name}.pdb
outputName         output/{name}_fast

paraTypeCharmm     on
parameters         forcefield/par_all36_na.prm
parameters         forcefield/toppar_water_ions_cufix.str
parameters         forcefield/par_stub_ions_nbfix.str
{("extraBonds         on\nextraBondsFile     mgh_extrabonds.txt\n") if mg_hexahydrate else ""}

# ── Periodic boundary conditions ──────────────────────────────────────────────
cellBasisVector1   {bx_a:.3f}  0.000    0.000
cellBasisVector2   0.000    {by_a:.3f}  0.000
cellBasisVector3   0.000    0.000    {bz_a:.3f}
cellOrigin         {cx:.3f}   {cy:.3f}   {cz:.3f}

wrapAll            off
wrapWater          off

# ── PME electrostatics ────────────────────────────────────────────────────────
PME                yes
PMEGridSpacing     1.5

# ── Nonbonded ─────────────────────────────────────────────────────────────────
cutoff             10.0
switching          on
switchdist         8.0
pairlistdist       12.0
exclude            scaled1-4
oneFourScaling     1.0

# ── HMR fast integrator ───────────────────────────────────────────────────────
rigidBonds         all
rigidTolerance     1.0e-8
timestep           4.0
nonbondedFreq      1
fullElectFrequency 2
stepspercycle      20
{gpu_resident_block}

# ── Thermostat / barostat ─────────────────────────────────────────────────────
temperature        300
langevin           on
langevinDamping    5
langevinTemp       300
langevinHydrogen   off
{piston}
# ── Output ────────────────────────────────────────────────────────────────────
outputEnergies     9600
dcdFreq            9600
dcdFile            output/{name}_fast.dcd
{vf_block}xstFreq            9600
xstFile            output/{name}_fast.xst
restartfreq        9600
binaryrestart      yes

# ── Run ───────────────────────────────────────────────────────────────────────
run                {run_steps}
"""


# ══════════════════════════════════════════════════════════════════════════════
# §7  README / LAUNCH
# ══════════════════════════════════════════════════════════════════════════════

_README = """\
{name} — NAMD Explicit-Solvent Simulation Package
=======================================================
Generated by NADOC.

Contents
--------
{name}.pdb          Solvated structure (DNA + TIP3P water + NaCl/MgCl2 ions)
{name}.psf          Complete topology (bonds/angles/dihedrals)
{name}_hmr.psf      HMR topology for fast dynamics (non-water H mass x3)
namd.conf           Conservative minimization/preflight config
namd_fast.conf      Fast-relaxation template: HMR + GPUresident + 4 fs
forcefield/         CHARMM36 parameters
launch.sh           Automated launch script (installs NAMD3 if absent)

Quick start
-----------
    bash launch.sh

Alternatively, run manually:
    mkdir -p output
    namd3 +p4 +setcpuaffinity +devices 0 namd.conf > output/namd.log &
    namd3 +p4 +setcpuaffinity +devices 0 namd_fast.conf > output/namd_fast.log &

Requirements
------------
- NAMD 3.0+ (CUDA build) — automatically downloaded by launch.sh
- CUDA-capable GPU
- ~16 GB RAM for large DNA origami

Performance
-----------
namd_fast.conf mirrors NADOC's local fast-relaxation path: HMR topology,
GPUresident on, 4 fs timestep, sparse output, and 12-step cycles. Use it only
after namd.conf preflight is clean. It is for capped solvated boxes; periodic
unit-cell packages with wrap bonds must stay on standard CUDA.

Typical workflow
----------------
1. namd.conf is a conservative minimization preflight.
2. namd_fast.conf is a standalone fast dynamics template.
3. For full production, use NADOC's managed equilibrium-aware ladder configs.
4. Analyse with VMD: vmd {name}.psf output/{name}.dcd
"""

_LAUNCH_SH = """\
#!/usr/bin/env bash
# NADOC NAMD Explicit-Solvent Launch Script
# Usage: bash launch.sh
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
cd "$SCRIPT_DIR"
mkdir -p output

CONF="${{1:-namd.conf}}"

# ── Locate NAMD3 ──────────────────────────────────────────────────────────────
if [ -n "${{NAMD_CMD:-}}" ] && command -v "$NAMD_CMD" &>/dev/null; then
    NAMD="$NAMD_CMD"
elif [ -n "${{NADOC_NAMD_BIN:-}}" ] && [ -x "$NADOC_NAMD_BIN" ]; then
    NAMD="$NADOC_NAMD_BIN"
elif command -v namd3 &>/dev/null; then
    NAMD=namd3
elif [ -x "$HOME/Applications/NAMD_3.0.2/namd3" ]; then
    NAMD="$HOME/Applications/NAMD_3.0.2/namd3"
else
    echo "NAMD3 not found.  Downloading NAMD 3.0.2 (Linux/CUDA)..."
    wget -q "https://www.ks.uiuc.edu/Research/namd/3.0.2/download/NAMD_3.0.2_Linux-x86_64-multicore-CUDA.tar.gz" -O /tmp/namd3.tar.gz
    tar -xzf /tmp/namd3.tar.gz -C "$HOME/Applications/"
    NAMD="$HOME/Applications/NAMD_3.0.2_Linux-x86_64-multicore-CUDA/namd3"
fi

echo "Using NAMD: $NAMD"
N_THREADS="${{NAMD_THREADS:-$(( ($(nproc 2>/dev/null || echo 2) + 1) / 2 ))}}"
DEVICES="${{NAMD_DEVICES:-0}}"
PEMAP="${{NAMD_PEMAP:-}}"

namd_args=("+p${{N_THREADS}}" "+setcpuaffinity")
if [ -n "$PEMAP" ]; then
    namd_args+=("+pemap" "$PEMAP")
fi
if [ -n "$DEVICES" ]; then
    namd_args+=("+devices" "$DEVICES")
fi

base="$(basename "$CONF" .conf)"
echo "Config: $CONF"
echo "Threads: $N_THREADS"
if [ -n "$DEVICES" ]; then echo "CUDA devices: $DEVICES"; fi
"$NAMD" "${{namd_args[@]}}" "$CONF" 2>&1 | tee "output/${{base}}.log"
echo "Done. See output/${{base}}.log"
"""

_MONITOR_PY = """\
#!/usr/bin/env python3
\"\"\"Tail the NAMD log and print energy/step summary.\"\"\"
import sys, re, time
log = sys.argv[1] if len(sys.argv) > 1 else "output/namd.log"
pat = re.compile(r"^ENERGY:\\s+(\\d+)\\s+[\\d.+-]+\\s+[\\d.+-]+\\s+[\\d.+-]+\\s+[\\d.+-]+\\s+([\\d.+-]+)")
seen = 0
while True:
    try:
        with open(log) as f:
            lines = f.readlines()[seen:]
        for ln in lines:
            m = pat.match(ln)
            if m:
                print(f"step {m.group(1):>10s}  Etotal = {float(m.group(2)):12.1f} kcal/mol")
            seen += 1 if ln.strip() else 0
    except FileNotFoundError:
        pass
    time.sleep(2)
"""


# ══════════════════════════════════════════════════════════════════════════════
# §8  PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def _overwrite_solute_coords(pdb_text: str, coords) -> str:
    """Rewrite the x/y/z columns of the solute PDB's ATOM/HETATM records in order.

    ``coords`` is an (N, 3) array in Å, one row per ATOM/HETATM line, in the SAME
    order the topology builder emitted them (the row count must match exactly).
    Only columns 31-54 (PDB fixed-width x/y/z) are touched; every other column
    (serial, atom name, resname, chain, element, occupancy/beta) is preserved, so
    the connectivity/PSF mapping is untouched — this seeds a conformation, not a
    topology.  Coordinates outside the PDB ±9999.999 Å field would corrupt the
    fixed-width layout, so they are rejected."""
    import numpy as np  # noqa: PLC0415

    xyz = np.asarray(coords, dtype=float)
    if xyz.ndim != 2 or xyz.shape[1] != 3:
        raise ValueError(f"solute_coords must be (N, 3); got {xyz.shape}")
    if not np.isfinite(xyz).all():
        raise ValueError("solute_coords contains non-finite values")
    if (np.abs(xyz) > 9999.999).any():
        raise ValueError("solute_coords exceed the PDB ±9999.999 Å column width")
    out, i = [], 0
    for line in pdb_text.splitlines(keepends=True):
        if line.startswith(("ATOM", "HETATM")):
            if i >= len(xyz):
                raise ValueError(
                    f"solute_coords has {len(xyz)} rows but the built PDB has more atoms")
            x, y, z = xyz[i]
            nl = line.rstrip("\n").rstrip("\r")
            nl = f"{nl[:30]}{x:8.3f}{y:8.3f}{z:8.3f}{nl[54:]}"
            out.append(nl + ("\n" if line.endswith("\n") else ""))
            i += 1
        else:
            out.append(line)
    if i != len(xyz):
        raise ValueError(
            f"solute_coords has {len(xyz)} rows but the built PDB has {i} atoms")
    return "".join(out)


def build_namd_solvated_package(
    design: Design,
    *,
    padding_nm: float = 1.2,
    ion_conc_mM: float = 150.0,
    mg_conc_mM: float = 0.0,
    mg_hexahydrate: bool = False,
    require_full_topology: bool = False,
    #: Unrestrained nanoseconds this package will run — drives the cell-sizing rule.
    #: See :data:`ROTATION_FREE_NS_THRESHOLD`.  None = size for an arbitrarily long
    #: free run.
    free_ns: "float | None" = None,
    seed: int = 42,
    atomistic_model: "AtomisticModel | None" = None,
    solute_coords: "np.ndarray | None" = None,
    water_shell_nm: Optional[float] = None,
    # Compute target, used ONLY to size the box against the right memory ceiling
    # (see _box_mode_atom_cap).  "cpu"/"none" sizes to host RAM instead of VRAM.
    devices: str = "0",
    progress: Optional[ProgressCb] = None,
) -> bytes:
    """Return raw ZIP bytes of a complete NAMD explicit-solvent package.

    Parameters
    ----------
    design:
        Active NADOC design.
    atomistic_model:
        Optional pre-built heavy-atom model supplying the DNA starting
        coordinates.  Pass an oxDNA-relaxed model (Phase-2 NAMD seed) so the
        solvated PDB starts from relaxed backbone positions instead of ideal
        B-DNA; the PSF (topology/connectivity) is unaffected.  Default: build
        ideal B-DNA internally.
    solute_coords:
        Optional (N_solute, 3) array of ALL-ATOM solute coordinates (Å) that
        overwrite the built DNA PDB's x/y/z, in the SAME atom order the topology
        builder emits (psfgen order when ``require_full_topology``).  Unlike
        ``atomistic_model`` (heavy atoms only, hydrogens re-guessed), this seeds
        the exact all-atom conformation — the hook for a BLADE-relaxed NAMD seed.
        Water is then placed fresh around the seeded conformation.  Row count must
        equal the built solute atom count or a ValueError is raised.
    padding_nm:
        Water padding around the DNA bounding box (nm). Default 1.2 nm.
    ion_conc_mM:
        Target NaCl bulk concentration (mM). Default 150 mM.
    mg_conc_mM:
        Target MgCl2 bulk concentration (mM). Default 0 mM.  Use nonzero values
        for DNA-origami protocols that rely on magnesium-stabilized packing.
    mg_hexahydrate:
        If true, place Mg as idealized MGH Mg(H2O)6 residues and write Mg-O
        extraBonds. If false, place bare MG ions.
    water_shell_nm:
        If set, keep only water within this distance (nm) of any DNA atom and drop
        the rest (see :func:`_carve_water_shell`).  Box dimensions are unchanged;
        atom count drops ~2× for large non-globular designs so GPU-resident NAMD
        fits a memory-limited card.  The carved cell has vacuum corners, so the
        downstream stages must run NVT (barostat off).  Need 2·shell ≥ cutoff for
        a valid minimum image (cutoff is 12 Å, so ≥0.6 nm; 1.5 nm recommended).
    seed:
        Random seed for reproducible ion placement.

    Returns
    -------
    bytes
        ZIP file contents ready to write to disk or serve as a download.
    """
    _check_ff_files()

    name = (design.metadata.name or "design").replace(" ", "_")
    prefix = f"{name}_namd_solvated/"

    # 1. Build DNA-only PDB and complete PSF.  Legacy mode keeps the old
    # heavy-atom Python PSF for compatibility; strict mode uses psfgen so the
    # topology has hydrogens and CHARMM terminal/deoxy patches.
    topology_metadata: dict = {"topology_builder": "nadoc_legacy_heavy_atom_psf"}
    _emit(progress, "topology", None, "Building DNA topology (PSF/PDB)…")
    if require_full_topology:
        topology_build = build_charmm_psfgen_topology(design, atomistic_model=atomistic_model)
        dna_pdb = topology_build.pdb_text
        dna_psf = topology_build.psf_text
        topology_metadata = topology_build.metadata
    else:
        dna_pdb = export_pdb(design, box_margin_nm=padding_nm, model=atomistic_model)
        dna_psf = complete_psf(design)
    if solute_coords is not None:
        dna_pdb = _overwrite_solute_coords(dna_pdb, solute_coords)
    dry_audit = audit_psf(
        dna_psf,
        require_dna_hydrogens=require_full_topology,
        require_dna_residue_charge=require_full_topology,
    )
    if require_full_topology and not dry_audit.passed:
        raise RuntimeError(
            "Dry DNA topology audit failed; cannot start equilibrium-aware NAMD. "
            + "; ".join(dry_audit.errors)
        )

    with tempfile.TemporaryDirectory(prefix="nadoc_solvate_") as _tmpdir:
        tmpdir = Path(_tmpdir)

        # 2. GROMACS solvation → water positions + solvated box dimensions.
        #    _gmx_solvate returns the DNA re-centred into the SAME [0,L] frame as the
        #    water; use THAT text below so DNA + water co-register and every atom
        #    lands inside the periodic cell (else NAMD's GPU kernel crashes).
        # Cell-sizing rule: prefer rotation (orientation-proof), but fall back to the
        # historical bbox rule when that would not fit the hardware — a cell too big to
        # run is not safer than one too small.  The downgrade is recorded, not silent.
        _atom_cap = _box_mode_atom_cap(devices)
        # Prefer the tutorial's bbox ± 20 Å, but only where it does not force a carve
        # (which would cost the barostat, and with it the settle stage + box trace).
        padding_nm, padding_note = resolve_padding_nm(
            dna_pdb, padding_nm, max_atoms=_atom_cap)
        if padding_note:
            logger.info("box sizing: %s", padding_note)
        box_mode, box_mode_note = resolve_box_mode(
            dna_pdb, padding_nm, max_atoms=_atom_cap, free_ns=free_ns)
        if box_mode_note:
            logger.warning("box sizing: %s", box_mode_note)
            _emit(progress, "assemble", 0.4, f"Box sizing: {box_mode_note}")
        waters, box_nm, dna_pdb = _gmx_solvate(
            dna_pdb, padding_nm, tmpdir, progress=progress,
            water_shell_nm=water_shell_nm, box_mode=box_mode,
        )

    # 3. Count DNA net charge (1 phosphate = -1 charge) and calculate ion counts.
    #    Under the Aksimentiev recipe the counterion is Mg(H₂O)₆²⁺, not Na⁺ — see
    #    :func:`ion_counts`.  The bulk terms are charged over the SOLVENT volume, so a
    #    carved (or rotation-sized, mostly-empty) cell is not over-salted.
    _emit(progress, "assemble", 0.5, "Placing neutralising ions…")
    dna_charge = _count_dna_charge(dna_pdb)
    ions = ion_counts(
        len(waters), dna_charge, nacl_mM=ion_conc_mM, mgcl2_mM=mg_conc_mM,
        box_nm=box_nm, mg_hexahydrate=mg_hexahydrate,
    )
    n_na, n_mg, n_cl = ions.as_tuple()
    ion_volume_nm3 = ions.volume_nm3

    # A cell too tight to hold the hydration waters each Mg(H₂O)₆ needs cannot be
    # built.  Report the shortfall in the units the caller can act on (padding /
    # shell), not as a bare arithmetic failure deep inside placement.
    needed = waters_needed_for_ions(ions, mg_hexahydrate=mg_hexahydrate)
    if needed > len(waters):
        raise RuntimeError(
            f"Cell holds {len(waters):,} waters but the ion recipe needs {needed:,} "
            f"({n_mg:,} Mg(H₂O)₆ × {MGH_WATERS_CONSUMED} + {n_na:,} Na⁺ + {n_cl:,} Cl⁻). "
            f"Neutralising {ions.dna_neg_charge:,} backbone charges with magnesium "
            f"costs ~3 waters per phosphate. Increase padding_nm or the water shell."
        )

    # 4. Place ions (replace water molecules)
    waters, na_pos, mg_pos, cl_pos, mgh_clusters = _place_ions_mixed(
        waters, n_na, n_mg, n_cl, seed=seed, mg_hexahydrate=mg_hexahydrate,
        progress=progress, dna_pdb_text=dna_pdb,
    )

    # 5. Find last DNA atom serial for sequential numbering
    dna_n_atoms = _find_last_atom_serial(dna_psf)
    n_total = (
        dna_n_atoms
        + len(waters) * 3
        + n_na
        + len(mg_pos)
        + len(mgh_clusters) * 19
        + n_cl
    )

    # 6. Build solvated PSF
    solvated_psf = _extend_psf(
        dna_psf, waters, na_pos, cl_pos, mg_pos=mg_pos, mgh_clusters=mgh_clusters,
        progress=progress,
    )
    final_audit = audit_psf(
        solvated_psf,
        require_neutral=require_full_topology,
        require_dna_hydrogens=require_full_topology,
        require_dna_residue_charge=require_full_topology,
    )
    if require_full_topology and not final_audit.passed:
        raise RuntimeError(
            "Solvated topology audit failed; cannot start equilibrium-aware NAMD. "
            + "; ".join(final_audit.errors)
        )

    # 7. Build solvated PDB
    solvated_pdb = _build_solvated_pdb(
        dna_pdb,
        waters,
        na_pos,
        cl_pos,
        box_nm,
        dna_n_atoms,
        mg_pos=mg_pos,
        mgh_clusters=mgh_clusters,
        progress=progress,
    )
    mgh_extrabonds = _mgh_extrabonds(
        dna_n_atoms,
        len(waters),
        len(na_pos),
        len(mg_pos),
        len(mgh_clusters),
    )

    # 8. Render NAMD conf + package ZIP (cheap tail of the assemble phase; the
    # 'finalize' phase is reserved for the caller's config/manifest writes that
    # come after the elastic-network step).
    _emit(progress, "assemble", 0.99, "Packaging solvated system…")
    namd_conf = _render_solvated_namd_conf(
        name,
        box_nm,
        n_total,
        nacl_mM=ion_conc_mM,
        mgcl2_mM=mg_conc_mM,
        mg_hexahydrate=mg_hexahydrate and bool(mgh_clusters),
    )
    with tempfile.TemporaryDirectory(prefix="nadoc_hmr_") as _hmr_tmp:
        hmr_tmp = Path(_hmr_tmp)
        psf_path = hmr_tmp / f"{name}.psf"
        hmr_path = hmr_tmp / f"{name}_hmr.psf"
        psf_path.write_text(solvated_psf)
        n_hmr = write_hmr_psf(psf_path, hmr_path)
        hmr_psf = hmr_path.read_text()
    fast_conf = _render_solvated_fast_namd_conf(
        name,
        box_nm,
        n_total,
        nacl_mM=ion_conc_mM,
        mgcl2_mM=mg_conc_mM,
        mg_hexahydrate=mg_hexahydrate and bool(mgh_clusters),
        n_hmr=n_hmr,
        nvt_only=bool(water_shell_nm and water_shell_nm > 0),
    )

    readme  = _README.format(name=name)
    prompt  = _AI_PROMPT.replace("{name}", name)
    launch  = _LAUNCH_SH.format(name=name)
    audit_json = {
        "topology_builder": topology_metadata.get("topology_builder", "unknown"),
        "topology_metadata": topology_metadata,
        "production_ready": final_audit.passed
        and final_audit.dna_hydrogens > 0
        and abs(final_audit.total_charge) <= 1.0e-3,
        "requirements": {
            "full_dna_topology_required": require_full_topology,
            "neutral_final_psf_required": require_full_topology,
        },
        "dry_dna": dry_audit.to_dict(),
        "final_solvated": final_audit.to_dict(),
        "ionization": {
            "dna_charge_method": "phosphate_count_legacy",
            "dna_charge_used_e": dna_charge,
            # Cross-check the phosphate count against the force field's own charges.
            # They agree today (psfgen's 5TER/3TER patches carry -0.47/-0.53 e, which
            # sum to exactly -1.00 per strand, so an N-nt strand carries -(N-1) = its
            # phosphate count).  Recording the delta means a future terminal-patch
            # change cannot silently de-neutralise the box.
            "dna_charge_from_psf_e": dry_audit.total_charge,
            "dna_charge_agrees": abs(dry_audit.total_charge - dna_charge) <= 0.01,
            "counterion": ions.counterion,
            "n_na": n_na,
            "n_mg": n_mg,
            "n_cl": n_cl,
            "n_mg_neutralising": ions.n_mg_neutralising,
            "n_mg_bulk": ions.n_mg_bulk,
            "net_ion_charge_e": 2 * n_mg + n_na - n_cl,
            "neutral": (2 * n_mg + n_na - n_cl) == ions.dna_neg_charge,
            "mg_hexahydrate": mg_hexahydrate and bool(mgh_clusters),
            "n_waters": len(waters),
            "box_nm": list(box_nm),
            "water_shell_nm": water_shell_nm,
            "ion_volume_nm3": ion_volume_nm3,
        },
        # Which sizing rules produced this cell.  Both were previously logger-only, so a
        # finished job had no record of whether its box came from rotation or bbox, or
        # whether the tutorial's padding had been refused for it.
        "box_sizing": {
            "padding_nm": padding_nm,
            "box_mode": box_mode,
            "padding_note": padding_note,
            "box_mode_note": box_mode_note,
            # What the cell was sized FOR.  A package sized for a short ladder cannot
            # safely host a long production run; append_md_production reads this back.
            "sized_for_free_ns": free_ns,
        },
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(prefix + f"{name}.pdb",             solvated_pdb)
        zf.writestr(prefix + f"{name}.psf",             solvated_psf)
        zf.writestr(prefix + f"{name}_hmr.psf",         hmr_psf)
        zf.writestr(prefix + "charge_audit.json",       json.dumps(audit_json, indent=2))
        zf.writestr(prefix + "namd.conf",               namd_conf)
        zf.writestr(prefix + "namd_fast.conf",          fast_conf)
        if mgh_extrabonds:
            zf.writestr(prefix + "mgh_extrabonds.txt",  mgh_extrabonds)
        zf.writestr(prefix + "README.txt",              readme)
        zf.writestr(prefix + "AI_ASSISTANT_PROMPT.txt", prompt)
        zf.writestr(prefix + "scripts/monitor.py",      _MONITOR_PY)

        for ff_file in _FF_FILES:
            ff_path = _FF_DIR / ff_file
            if ff_path.exists():
                zf.writestr(prefix + f"forcefield/{ff_file}", ff_path.read_bytes())

        info = zipfile.ZipInfo(prefix + "launch.sh")
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = (
            stat.S_IFREG
            | stat.S_IRWXU
            | stat.S_IRGRP | stat.S_IXGRP
            | stat.S_IROTH | stat.S_IXOTH
        ) << 16
        zf.writestr(info, launch)

    buf.seek(0)
    return buf.getvalue()


def get_solvation_stats(
    design: Design,
    *,
    padding_nm: float = 1.2,
    ion_conc_mM: float = 150.0,
    mg_conc_mM: float = 0.0,
    mg_hexahydrate: bool = False,
    water_shell_nm: Optional[float] = None,
) -> dict:
    """Return a dict with estimated system size without building the package.

    Runs gmx editconf + solvate to count water molecules, then returns
    atom counts and box dimensions.  Fast (~10 s) compared to the full
    PSF/PDB build (~60-120 s for large designs).

    ``water_shell_nm`` mirrors :func:`build_namd_solvated_package`: when set, the
    reported counts reflect the carved hydration shell.
    """
    dna_pdb = export_pdb(design, box_margin_nm=padding_nm)
    dna_psf = complete_psf(design)
    dna_n_atoms = _find_last_atom_serial(dna_psf)
    dna_charge  = _count_dna_charge(dna_pdb)

    with tempfile.TemporaryDirectory(prefix="nadoc_solvate_stats_") as _tmp:
        tmpdir = Path(_tmp)
        waters, box_nm, _ = _gmx_solvate(dna_pdb, padding_nm, tmpdir, water_shell_nm=water_shell_nm)

    # Same recipe as the real build — ion_counts is the single implementation, so a
    # pre-flight estimate cannot drift from what the package actually gets.
    ions = ion_counts(
        len(waters), dna_charge, nacl_mM=ion_conc_mM, mgcl2_mM=mg_conc_mM,
        box_nm=box_nm, mg_hexahydrate=mg_hexahydrate,
    )
    n_na, n_mg, n_cl = ions.as_tuple()
    n_replaced_by_mg = (MGH_WATERS_CONSUMED * n_mg) if mg_hexahydrate else n_mg
    n_remaining_waters = len(waters) - n_na - n_replaced_by_mg - n_cl
    n_water_atoms = n_remaining_waters * 3
    n_mg_atoms = n_mg * MGH_ATOMS if mg_hexahydrate else n_mg
    n_total = dna_n_atoms + n_water_atoms + n_na + n_mg_atoms + n_cl

    bx, by, bz = box_nm
    return {
        "dna_atoms":    dna_n_atoms,
        "n_waters":     n_remaining_waters,
        "water_atoms":  n_water_atoms,
        "n_na":         n_na,
        "n_mg":         n_mg,
        "mg_hexahydrate": mg_hexahydrate,
        "mgh_atoms":    n_mg * MGH_ATOMS if mg_hexahydrate else 0,
        "counterion":   ions.counterion,
        "n_cl":         n_cl,
        "total_atoms":  n_total,
        "box_nm":       box_nm,
        "box_volume_nm3": bx * by * bz,
        "water_shell_nm": water_shell_nm,
        "dna_charge":   dna_charge,
    }


# ── Helpers ────────────────────────────────────────────────────────────────────

def _check_ff_files() -> None:
    missing = [f for f in _FF_FILES if not (_FF_DIR / f).exists()]
    if missing:
        raise RuntimeError(
            "Force field files not found in backend/data/forcefield/: "
            + ", ".join(missing)
        )


_AI_PROMPT = """\
You are assisting with a NAMD explicit-solvent molecular dynamics simulation of
a DNA origami nanostructure called {name}.

The system was set up by NADOC using:
  - CHARMM36 force field for DNA
  - TIP3P explicit water model
  - 150 mM NaCl
  - CUDASOAintegrate (GPU-resident integration)
  - PME electrostatics
  - NPT ensemble (310 K, 1 atm)

Key files:
  {name}.pdb    — solvated structure
  {name}.psf    — complete topology
  namd.conf     — simulation parameters
  output/       — trajectory output

To extend the simulation, increase `run` in namd.conf and restart from the
latest .restart.coor / .restart.vel / .restart.xsc files in output/.

For analysis, use VMD:
  vmd {name}.psf output/{name}.dcd
"""
