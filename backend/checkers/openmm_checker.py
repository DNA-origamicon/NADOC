"""
OpenMM geometric verification checker — Phase 9.

Runs a short AMBER14+OL15+GBNeck2 implicit-solvent MD simulation on a NADOC
design and computes per-helix C1' drift metrics against NADOC's B-DNA geometric
prediction.

Force field note
----------------
NADOC's PDB export (pdb_export.py) uses CHARMM36 atom names (OP1/OP2 for
non-bridging phosphate oxygens). The PDB compatibility path removes the
5'-terminal P/OP1/OP2 atoms absent from AMBER14 DA5/DT5/DC5/DG5 templates.
OpenMM's PDB reader normalizes phosphate names; explicit XX5/XX3 template maps
select OL15 terminal variants while residue names remain canonical for hydrogen
definitions.

The force field used here (AMBER14+OL15+GBNeck2) intentionally differs from
NADOC's NAMD export workflow (CHARMM36 + explicit solvent). This is by design:
GBNeck2 (igb=8) in OpenMM is parameterized for AMBER OBC radii; there is no
CHARMM36-compatible GBNeck2 variant in OpenMM's standard library.
AMBER14+OL15 is paired here with the nucleic-acid GBn2 refinement of Nguyen et al.
(J. Chem. Theory Comput. 2015, 11, 3714–3728; DOI: 10.1021/acs.jctc.5b00271).

Architecture note (NADOC three-layer axiom)
-------------------------------------------
Simulation positions are computed here for drift metric computation only.
They are NEVER written back to the Design object or to any topology/geometric
layer. This module is a read-only consumer of the NADOC design.

Mg²⁺ limitation
----------------
Implicit solvent omits explicit Mg²⁺ ions, which in reality bridge inter-helix
contacts. This can systematically overestimate inter-helix distances by ~0.2–0.3 nm.
Explicit ion support is deferred to a follow-up investigation.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from backend.core.models import Design


# ── Result type ──────────────────────────────────────────────────────────────────


@dataclass
class VerificationResult:
    """Per-helix C1' drift metrics from a short AMBER14+OL15+GBNeck2 MD run."""

    # Metadata
    n_atoms: int  # total atoms in system (after addHydrogens)
    platform_used: str  # "CUDA" | "CPU"
    ff_description: str  # human-readable force field description

    # Drift — C1' atoms, time-averaged over last 50% of trajectory, vs AtomisticModel
    global_rmsd_nm: float  # RMS deviation over all matched C1' atoms
    per_helix_rmsd_nm: dict[str, float]  # helix_id → per-helix RMSD (nm)
    max_deviation_nm: float  # worst-case single C1' deviation (nm)
    n_missing: int  # C1' keys absent from simulation result

    # Inter-helix COM drift: |dist_sim - dist_ref| for each helix pair
    inter_helix_com_drift_nm: dict[str, float]  # "hA_hB" → drift (nm), sorted IDs

    # Pass/fail: max_deviation_nm < 0.5 AND global_rmsd_nm < 0.3
    passed: bool
    warnings: list[str]

    # Post-minimization potential energy (kJ/mol) — sanity check
    potential_energy_kj_per_mol: float


# Thresholds: 5 Å max single-atom drift, 3 Å global RMS.
# Rationale: 5 Å allows for genuine thermal motion at 300 K in a 10 ps window;
# 3 Å global RMS is stricter because ensemble averaging suppresses noise.
# Both are intentionally generous for this first baseline — adjust after exp21.
_MAX_DEVIATION_THRESHOLD_NM: float = 0.5  # 5 Å
_GLOBAL_RMSD_THRESHOLD_NM: float = 0.3  # 3 Å

_FF_DESCRIPTION: str = (
    "AMBER14+OL15+GBNeck2 (igb=8); 150 mM NaCl implicit solvent; "
    "PDB atom names normalized by OpenMM, OL15 XX5/XX3 template maps, "
    "5'-terminal P/OP1/OP2 removed per AMBER14 terminal convention"
)


# ── CHARMM36 → AMBER14 PDB preprocessing ────────────────────────────────────────

# Atom name fields (4-char, cols 12–15) absent from AMBER14 5'-terminal templates.
# The AMBER14 DA5/DT5/DC5/DG5 templates start at O5'; P and its oxygens are absent.
_5PRIME_EXCLUDE: frozenset[str] = frozenset({" P  ", " OP1", " OP2"})

_INNER_DNA: frozenset[str] = frozenset({"DA", "DT", "DC", "DG"})


def _rename_charmm_to_amber_pdb(pdb_text: str) -> str:
    """
    Preprocess a NADOC CHARMM36 PDB for AMBER14+OL15+OpenMM compatibility.

    Applied in a single pass over ATOM/HETATM lines:
    1. Strip CONECT and LINK records (OpenMM derives bonds from FF templates).
    2. Remove P, OP1, OP2 from 5'-terminal residues (first residue per chain):
       AMBER14 DA5/DT5/DC5/DG5 templates start at O5', with no prior phosphate.
    3. Rename phosphate oxygens: OP1 → O1P, OP2 → O2P (inner residues only,
       since 5'-terminal ones are dropped in step 2).
    4. Rename terminal residues in the 3-char residue name field:
       first-in-chain → DA5/DT5/DC5/DG5   (5'-OH terminus)
       last-in-chain  → DA3/DT3/DC3/DG3   (3'-OH terminus)

    Single-residue chains (simultaneously 5'- and 3'-terminal) are left with their
    inner residue name; AMBER14 will raise a clear error for these degenerate designs.
    """
    # Step 1 — identify first and last seq_num per PDB chain.
    # Use dict (insertion-ordered) to record seq_nums in file order.
    chain_seqs: dict[str, dict[int, None]] = {}
    for line in pdb_text.splitlines():
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        chain = line[21]
        try:
            seq_num = int(line[22:26])
        except ValueError:
            continue
        chain_seqs.setdefault(chain, {})[seq_num] = None

    chain_first: dict[str, int] = {c: next(iter(d)) for c, d in chain_seqs.items()}
    chain_last: dict[str, int] = {
        c: next(reversed(list(d))) for c, d in chain_seqs.items()
    }

    # Step 2 — rewrite PDB.
    out: list[str] = []
    for line in pdb_text.splitlines():
        if line.startswith(("CONECT", "LINK")):
            continue  # strip connectivity — OpenMM uses FF templates
        if not line.startswith(("ATOM  ", "HETATM")):
            out.append(line)
            continue

        chain = line[21]
        try:
            seq_num = int(line[22:26])
        except ValueError:
            out.append(line)
            continue

        atom_field = line[12:16]  # 4-char atom name field
        resname = line[17:20].strip()  # residue name, e.g. "DA"
        is_5prime = seq_num == chain_first.get(chain)
        is_3prime = seq_num == chain_last.get(chain)

        # Drop 5'-terminal backbone atoms absent from AMBER14 XX5 templates
        if is_5prime and resname in _INNER_DNA and atom_field in _5PRIME_EXCLUDE:
            continue

        # Rename non-bridging phosphate oxygens (inner residues; 5'-terminal ones removed above)
        if atom_field == " OP1":
            line = line[:12] + " O1P" + line[16:]
        elif atom_field == " OP2":
            line = line[:12] + " O2P" + line[16:]

        # Rename terminal residue names
        if resname in _INNER_DNA:
            if is_5prime and not is_3prime:
                line = line[:17] + f"{resname + '5':>3s}" + line[20:]
            elif is_3prime and not is_5prime:
                line = line[:17] + f"{resname + '3':>3s}" + line[20:]

        out.append(line)

    return "\n".join(out) + "\n"


# ── Nucleotide key mapping ───────────────────────────────────────────────────────


def _build_seq_to_nuc(design: "Design") -> dict[tuple[str, int], tuple[str, int, str]]:
    """
    Build (pdb_chain_char, seq_num) → (helix_id, bp_index, direction) from P atoms.

    Uses the AtomisticModel (same source as export_pdb) to correlate PDB chain
    letter and residue seq_num to NADOC nucleotide keys. Works for all residues
    including 5'-terminal ones whose P atom is removed from the OpenMM PDB.
    """
    from backend.core.atomistic import build_atomistic_model
    from backend.core.pdb_export import _chain_char

    model = build_atomistic_model(design)
    seq_to_nuc: dict[tuple[str, int], tuple[str, int, str]] = {}
    for atom in model.atoms:
        if atom.name == "P":
            pdb_chain = _chain_char(atom.chain_id)
            seq_to_nuc[(pdb_chain, atom.seq_num)] = (
                atom.helix_id,
                atom.bp_index,
                atom.direction,
            )
    return seq_to_nuc


def _build_c1prime_reference(
    design: "Design",
) -> dict[tuple[str, int, str], np.ndarray]:
    """
    Return reference C1' positions in nm from NADOC's AtomisticModel.

    These are the ideal B-DNA C1' positions against which post-simulation drift
    is measured. Keyed by (helix_id, bp_index, direction).
    """
    from backend.core.atomistic import build_atomistic_model

    model = build_atomistic_model(design)
    ref: dict[tuple[str, int, str], np.ndarray] = {}
    for atom in model.atoms:
        if atom.name == "C1'":
            ref[(atom.helix_id, atom.bp_index, atom.direction)] = np.array(
                [atom.x, atom.y, atom.z]  # already nm
            )
    return ref


# ── Platform selection ───────────────────────────────────────────────────────────


def _select_platform(prefer_gpu: bool) -> str:
    """Return 'CUDA' if available and preferred, else 'CPU'."""
    if not prefer_gpu:
        return "CPU"
    try:
        from openmm import Platform

        Platform.getPlatformByName("CUDA")
        return "CUDA"
    except Exception:
        return "CPU"


# ── Drift metric computation ─────────────────────────────────────────────────────


def _compute_drift_metrics(
    avg_c1prime_nm: dict[tuple[str, int, str], np.ndarray],
    ref_c1prime_nm: dict[tuple[str, int, str], np.ndarray],
    design: "Design",
) -> tuple[float, dict[str, float], float, int, dict[str, float]]:
    """
    Compute per-helix C1' RMSD and inter-helix COM drift after centroid alignment.

    Centroid correction removes any constant global translation introduced by the
    OpenMM coordinate frame (no PBC, but modeller may centre the structure).
    Follows the same approach as atomistic_to_nadoc._compute_comparison.

    Returns
    -------
    (global_rmsd_nm, per_helix_rmsd_nm, max_deviation_nm, n_missing, com_drift_nm)
    """
    # Centroid alignment
    sim_pts: list[np.ndarray] = []
    ref_pts: list[np.ndarray] = []
    for key, sim_pos in avg_c1prime_nm.items():
        ref_pos = ref_c1prime_nm.get(key)
        if ref_pos is not None:
            sim_pts.append(sim_pos)
            ref_pts.append(ref_pos)

    translation = np.zeros(3)
    if sim_pts:
        translation = np.mean(ref_pts, axis=0) - np.mean(sim_pts, axis=0)

    # Per-atom deviations
    per_helix_devs: dict[str, list[float]] = {}
    all_devs: list[float] = []
    n_missing = 0

    for key, sim_pos in avg_c1prime_nm.items():
        ref_pos = ref_c1prime_nm.get(key)
        if ref_pos is None:
            n_missing += 1
            continue
        dev = float(np.linalg.norm(sim_pos + translation - ref_pos))
        all_devs.append(dev)
        per_helix_devs.setdefault(key[0], []).append(dev)

    per_helix_rmsd = {
        hid: float(np.sqrt(np.mean(np.array(devs) ** 2)))
        for hid, devs in per_helix_devs.items()
    }
    global_rmsd = float(np.sqrt(np.mean(np.array(all_devs) ** 2))) if all_devs else 0.0
    max_dev = float(max(all_devs)) if all_devs else 0.0

    # Inter-helix COM drift: compare pairwise COM distances sim vs ref
    helix_ids = [h.id for h in design.helices]

    def _com(
        positions: dict[tuple[str, int, str], np.ndarray],
        hid: str,
        offset: np.ndarray,
    ) -> np.ndarray | None:
        pts = [pos + offset for k, pos in positions.items() if k[0] == hid]
        return np.mean(pts, axis=0) if pts else None

    com_drift: dict[str, float] = {}
    for i, ha in enumerate(helix_ids):
        for hb in helix_ids[i + 1 :]:
            sim_a = _com(avg_c1prime_nm, ha, translation)
            sim_b = _com(avg_c1prime_nm, hb, translation)
            ref_a = _com(ref_c1prime_nm, ha, np.zeros(3))
            ref_b = _com(ref_c1prime_nm, hb, np.zeros(3))
            if any(x is None for x in (sim_a, sim_b, ref_a, ref_b)):
                continue
            sim_dist = float(np.linalg.norm(sim_b - sim_a))
            ref_dist = float(np.linalg.norm(ref_b - ref_a))
            com_drift["_".join(sorted([ha, hb]))] = abs(sim_dist - ref_dist)

    return global_rmsd, per_helix_rmsd, max_dev, n_missing, com_drift


# ── Public API ───────────────────────────────────────────────────────────────────


def verify_design_with_openmm(
    design: "Design",
    *,
    n_steps_minimize: int = 500,
    n_steps_nvt: int = 5_000,
    temperature_k: float = 300.0,
    friction_coeff_per_ps: float = 1.0,
    timestep_fs: float = 2.0,
    reporting_interval: int = 500,
    prefer_gpu: bool = True,
) -> VerificationResult:
    """
    Run a short AMBER14+OL15+GBNeck2 implicit-solvent MD simulation on *design*
    and return per-helix C1' drift metrics vs NADOC's geometric prediction.

    At the default settings (n_steps_nvt=5000, timestep_fs=2.0), the NVT run
    covers 10 ps. Drift is time-averaged over the last 50% of frames.

    Force field note: NADOC's PDB export uses CHARMM36 atom names (OP1/OP2).
    This function converts them to AMBER14 convention and renames terminal
    residues before loading. See module docstring for the full rationale.

    Architecture note: simulation positions are computed for drift metric
    computation only and are NEVER written back to the Design.

    Parameters
    ----------
    design
        NADOC Design object (topological layer ground truth).
    n_steps_minimize
        Maximum steepest-descent minimisation steps before NVT.
    n_steps_nvt
        NVT production steps. Drift is averaged over the last 50% of frames.
    temperature_k
        Simulation temperature in Kelvin.
    friction_coeff_per_ps
        Langevin thermostat friction coefficient (1/ps).
    timestep_fs
        Integration timestep in femtoseconds.
    reporting_interval
        Frequency (in steps) at which trajectory frames are collected.
    prefer_gpu
        If True, try CUDA platform first; fall back to CPU automatically.

    Returns
    -------
    VerificationResult
        Per-helix RMSD metrics, inter-helix COM drift, and pass/fail summary.

    Raises
    ------
    ImportError
        If openmm is not installed (install with ``uv sync`` in this repository).
    RuntimeError
        If PDB export fails or AMBER14 template matching fails (e.g. unknown residue).
    """
    try:
        from openmm import app, LangevinMiddleIntegrator, Platform
        from openmm import unit
    except ImportError as exc:
        raise ImportError(
            "openmm is required for verify_design_with_openmm(). "
            "Install the locked project environment with: uv sync"
        ) from exc

    # ── 1. Export and preprocess PDB ─────────────────────────────────────────
    from backend.core.pdb_export import export_pdb

    pdb_charmm = export_pdb(design)
    pdb_amber = _rename_charmm_to_amber_pdb(pdb_charmm)

    # ── 2. Build reference C1' positions and sequence→nucleotide map ──────────
    c1prime_ref = _build_c1prime_reference(design)
    seq_to_nuc = _build_seq_to_nuc(design)

    # ── 3. Load preprocessed PDB into OpenMM ─────────────────────────────────
    pdb = app.PDBFile(io.StringIO(pdb_amber))

    # ── 4. Force field ────────────────────────────────────────────────────────
    # AMBER14+OL15+GBNeck2 — best-validated implicit DNA GB model in OpenMM.
    # ``amber14-all.xml`` already includes ``amber14/DNA.OL15.xml``.  There is
    # no top-level ``DNA.OL15.xml`` in stock OpenMM.  GBn2 reference for nucleic
    # acids: Nguyen et al. JCTC 2015, DOI 10.1021/acs.jctc.5b00271.
    from backend.core.openmm_implicit import (
        FORCEFIELD_FILES,
        OpenMMImplicitProtocol,
        amber_terminal_templates,
        debye_kappa_per_nm,
    )

    ff = app.ForceField(*FORCEFIELD_FILES)

    # ── 5. Add hydrogens (AMBER14 is an all-atom FF; NADOC exports heavy only) ─
    modeller = app.Modeller(pdb.topology, pdb.positions)
    # PDB residue suffixes select OL15 terminal templates, but OpenMM's
    # hydrogen definitions are keyed by canonical DA/DT/DC/DG.
    terminal_templates = {}
    for residue in modeller.topology.residues():
        if len(residue.name) == 3 and residue.name[-1] in {"3", "5"}:
            terminal_templates[residue] = residue.name
            residue.name = residue.name[:2]
    try:
        modeller.addHydrogens(
            ff,
            pH=7.0,
            residueTemplates=terminal_templates,
        )
    except Exception as exc:
        raise RuntimeError(
            "OpenMM addHydrogens failed. Likely a terminal residue name mismatch "
            "(AMBER14 expects DA5/DA3 etc.). Check _rename_charmm_to_amber_pdb output. "
            f"Original error: {exc}"
        ) from exc

    # ── 6. Build C1' index map from post-H topology ───────────────────────────
    # Must be done AFTER addHydrogens because atom ordering changes.
    c1prime_index_map: dict[tuple[str, int, str], int] = {}
    for atom in modeller.topology.atoms():
        if atom.name == "C1'":
            try:
                res_seq = int(atom.residue.id)
            except ValueError:
                continue
            nuc_key = seq_to_nuc.get((atom.residue.chain.id, res_seq))
            if nuc_key is not None:
                c1prime_index_map[nuc_key] = atom.index

    # ── 7. Create system with GBNeck2 implicit solvent ────────────────────────
    system = ff.createSystem(
        modeller.topology,
        residueTemplates=amber_terminal_templates(modeller.topology),
        nonbondedMethod=app.NoCutoff,  # no PBC in implicit solvent
        constraints=app.HBonds,  # constrain X-H bonds → 2 fs timestep
        soluteDielectric=1.0,
        solventDielectric=78.5,
        implicitSolventKappa=debye_kappa_per_nm(
            OpenMMImplicitProtocol(
                temperature_k=temperature_k,
                salt_molar=0.15,
                timestep_fs=timestep_fs,
            )
        ),
    )

    # ── 8. Integrator and simulation ──────────────────────────────────────────
    integrator = LangevinMiddleIntegrator(
        temperature_k * unit.kelvin,
        friction_coeff_per_ps / unit.picosecond,
        timestep_fs * unit.femtoseconds,
    )
    platform_name = _select_platform(prefer_gpu)
    platform = Platform.getPlatformByName(platform_name)

    simulation = app.Simulation(modeller.topology, system, integrator, platform)
    simulation.context.setPositions(modeller.positions)

    # ── 9. Energy minimisation ────────────────────────────────────────────────
    simulation.minimizeEnergy(maxIterations=n_steps_minimize)
    state_min = simulation.context.getState(getEnergy=True)
    potential_energy = state_min.getPotentialEnergy().value_in_unit(
        unit.kilojoule_per_mole
    )

    # ── 10. Set velocities and run NVT production ─────────────────────────────
    simulation.context.setVelocitiesToTemperature(temperature_k * unit.kelvin)

    frames_nm: list[np.ndarray] = []
    n_frames = max(1, n_steps_nvt // reporting_interval)
    actual_nvt_steps = 0

    for _ in range(n_frames):
        simulation.step(reporting_interval)
        actual_nvt_steps += reporting_interval
        state = simulation.context.getState(getPositions=True)
        frames_nm.append(
            state.getPositions(asNumpy=True).value_in_unit(unit.nanometer).copy()
        )

    n_total_atoms = system.getNumParticles()

    # ── 11. Time-average C1' positions from last 50% of trajectory ────────────
    n_last = max(1, len(frames_nm) // 2)
    last_frames = frames_nm[-n_last:]

    avg_c1prime: dict[tuple[str, int, str], np.ndarray] = {}
    for nuc_key, atom_idx in c1prime_index_map.items():
        stack = np.stack([f[atom_idx] for f in last_frames])  # (n_frames, 3)
        avg_c1prime[nuc_key] = stack.mean(axis=0)

    # ── 12. Compute drift metrics ─────────────────────────────────────────────
    global_rmsd, per_helix_rmsd, max_dev, n_missing, com_drift = _compute_drift_metrics(
        avg_c1prime, c1prime_ref, design
    )

    # ── 13. Assemble result ───────────────────────────────────────────────────
    warnings: list[str] = []
    if n_missing > 0:
        warnings.append(f"{n_missing} C1' atom(s) had no NADOC reference match")
    missing_helices = {h.id for h in design.helices} - set(per_helix_rmsd)
    if missing_helices:
        warnings.append(f"No C1' data for helices: {sorted(missing_helices)}")

    passed = (max_dev < _MAX_DEVIATION_THRESHOLD_NM) and (
        global_rmsd < _GLOBAL_RMSD_THRESHOLD_NM
    )

    return VerificationResult(
        n_atoms=n_total_atoms,
        platform_used=platform_name,
        ff_description=_FF_DESCRIPTION,
        global_rmsd_nm=global_rmsd,
        per_helix_rmsd_nm=per_helix_rmsd,
        max_deviation_nm=max_dev,
        n_missing=n_missing,
        inter_helix_com_drift_nm=com_drift,
        passed=passed,
        warnings=warnings,
        potential_energy_kj_per_mol=potential_energy,
    )
