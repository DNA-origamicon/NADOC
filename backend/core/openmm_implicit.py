"""GPU-resident OpenMM/GBn2 scaffolding for atomistic DNA origami.

This is the production-oriented successor to the small OpenMM geometry checker.
It deliberately builds an OpenMM ``Topology`` directly from NADOC's atomistic
model instead of round-tripping through PDB.  PDB has only 62 usable one-character
chain identifiers; a realistic origami can have hundreds of strands.

The solvent model is AMBER OL15 DNA with GBn2 (igb=8) and 0.15 M *generic
monovalent ionic strength*.  It does not contain discrete sodium or chloride
particles and therefore cannot reproduce site-specific ion binding.

OpenMM imports are lazy.  Importing this module is safe on machines without
OpenMM and does not create a Context or touch a GPU.  Callers must pass through
``assert_simulation_slot_available`` immediately before creating a Context.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from backend.core.models import Design


FORCEFIELD_FILES: tuple[str, ...] = (
    # amber14-all.xml already includes amber14/DNA.OL15.xml.  Adding a second,
    # top-level "DNA.OL15.xml" is both redundant and invalid in stock OpenMM.
    "amber14-all.xml",
    "implicit/gbn2.xml",
)
FORCEFIELD_DESCRIPTION = "AMBER14/OL15 + GBn2 (igb=8)"
DEFAULT_SALT_MOLAR = 0.150

NonbondedMode = Literal["no_cutoff", "cutoff_nonperiodic"]


@dataclass(frozen=True, slots=True)
class OpenMMImplicitProtocol:
    """Reproducible protocol values; no OpenMM objects or hidden defaults."""

    temperature_k: float = 300.0
    salt_molar: float = DEFAULT_SALT_MOLAR
    solute_dielectric: float = 1.0
    solvent_dielectric: float = 78.5
    timestep_fs: float = 2.0
    friction_per_ps: float = 1.0
    constraint_tolerance: float = 1.0e-6
    random_seed: int = 20260827
    platform: str = "CUDA"
    precision: Literal["single", "mixed", "double"] = "mixed"
    device_index: str = "0"
    nonbonded_mode: NonbondedMode = "no_cutoff"
    cutoff_nm: float = 3.0
    minimize_max_iterations: int = 10_000
    equilibration_steps: int = 250_000
    production_steps: int = 5_000_000
    trajectory_interval_steps: int = 25_000
    state_interval_steps: int = 5_000
    checkpoint_interval_steps: int = 250_000

    def __post_init__(self) -> None:
        if self.temperature_k <= 0:
            raise ValueError("temperature_k must be positive")
        if self.salt_molar < 0:
            raise ValueError("salt_molar cannot be negative")
        if not 0 < self.timestep_fs <= 2.0:
            raise ValueError(
                "timestep_fs must be in (0, 2]; this first OL15/GBn2 protocol "
                "does not validate HMR/4 fs"
            )
        if self.friction_per_ps <= 0:
            raise ValueError("friction_per_ps must be positive")
        if not 0 < self.constraint_tolerance < 1:
            raise ValueError("constraint_tolerance must be between 0 and 1")
        if self.random_seed <= 0:
            raise ValueError("random_seed must be a positive, recorded integer")
        if self.platform != "CUDA":
            raise ValueError(
                "Production implicit-solvent runs are CUDA-only; CPU fallback is "
                "intentionally not silent"
            )
        if self.nonbonded_mode == "cutoff_nonperiodic" and self.cutoff_nm <= 0:
            raise ValueError("cutoff_nm must be positive for cutoff_nonperiodic")
        for field_name in (
            "minimize_max_iterations",
            "equilibration_steps",
            "production_steps",
            "trajectory_interval_steps",
            "state_interval_steps",
            "checkpoint_interval_steps",
        ):
            if getattr(self, field_name) <= 0:
                raise ValueError(f"{field_name} must be positive")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class PreparedImplicitSystem:
    """Objects prepared on the CPU before an OpenMM Context is created."""

    topology: object
    positions: object
    system: object
    atom_keys: tuple[tuple[str, int, str, str], ...]
    n_heavy_atoms: int
    n_atoms: int
    n_strands: int
    net_charge_e: float


def platform_properties(protocol: OpenMMImplicitProtocol) -> dict[str, str]:
    """CUDA properties chosen explicitly for reproducibility and stability."""
    return {"Precision": protocol.precision, "DeviceIndex": protocol.device_index}


def debye_kappa_per_nm(protocol: OpenMMImplicitProtocol) -> float:
    """Convert molar monovalent salt to Amber/OpenMM Debye kappa in 1/nm.

    This is OpenMM's Amber topology conversion, including Amber's 0.73 ion-
    exclusion factor and the Å→nm conversion.  The standalone GBn2 XML accepts
    ``implicitSolventKappa`` rather than ``implicitSolventSaltConc``.
    """
    if protocol.salt_molar == 0:
        return 0.0
    return 50.33355 * math.sqrt(
        protocol.salt_molar
        / protocol.solvent_dielectric
        / protocol.temperature_k
    ) * 7.3


def assert_simulation_slot_available() -> None:
    """Refuse to contend with a running NAMD/oxDNA/mrDNA/GROMACS simulation."""
    from backend.core.hardware import heavy_sim_running

    running, reason = heavy_sim_running()
    if running:
        raise RuntimeError(
            "OpenMM launch blocked by NADOC's heavy-simulation guard: " + reason
        )


def _terminal_residue_names(model) -> dict[tuple[str, int], str]:
    residues: dict[str, dict[int, str]] = {}
    for atom in model.atoms:
        residues.setdefault(atom.chain_id, {}).setdefault(atom.seq_num, atom.residue)

    names: dict[tuple[str, int], str] = {}
    for chain_id, chain_residues in residues.items():
        if len(chain_residues) < 2:
            raise ValueError(
                f"OpenMM/OL15 does not support one-nucleotide strand {chain_id!r}"
            )
        first_seq = min(chain_residues)
        last_seq = max(chain_residues)
        first_name = chain_residues[first_seq]
        last_name = chain_residues[last_seq]
        names[(chain_id, first_seq)] = first_name + "5"
        names[(chain_id, last_seq)] = last_name + "3"
    return names


def amber_terminal_templates(topology) -> dict[object, str]:
    """Map canonical DNA terminal residues to their OL15 5'/3' templates.

    OpenMM's hydrogen-definition table uses canonical residue names (``DA``),
    while OL15's force-field templates use terminal names (``DA5``/``DA3``).
    Keeping the Topology canonical and supplying this explicit map lets
    ``Modeller.addHydrogens`` add terminal HO5'/HO3' atoms correctly.
    """
    templates: dict[object, str] = {}
    for chain in topology.chains():
        residues = list(chain.residues())
        # Solvated topologies also contain water and ion chains.  Only DNA uses
        # the OL15 terminal-template convention.
        if not residues or residues[0].name not in {"DA", "DT", "DC", "DG"}:
            continue
        if len(residues) < 2:
            raise ValueError(
                f"OpenMM/OL15 does not support one-nucleotide strand {chain.id!r}"
            )
        templates[residues[0]] = residues[0].name + "5"
        templates[residues[-1]] = residues[-1].name + "3"
    return templates


def build_openmm_topology(design: "Design"):
    """Build a lossless heavy-atom OpenMM topology directly from a NADOC design.

    Returns ``(topology, positions, atom_keys)``.  ``atom_keys`` follows topology
    atom order and records ``(strand_id, seq_num, atom_name, element)``.
    Routine and crossover phosphodiester bonds come from ``AtomisticModel.bonds``;
    no connectivity is inferred from geometric proximity or PDB records.
    """
    from openmm import Vec3, unit
    from openmm.app import Element, Topology

    from backend.core.atomistic import build_atomistic_model

    model = build_atomistic_model(design)
    terminal_names = _terminal_residue_names(model)

    topology = Topology()
    chain_by_id: dict[str, object] = {}
    residue_by_key: dict[tuple[str, int], object] = {}
    atom_by_serial: dict[int, object] = {}
    positions: list[object] = []
    atom_keys: list[tuple[str, int, str, str]] = []

    # AtomisticModel is laid out geometrically and can revisit a crossover
    # strand after atoms from another strand.  OpenMM Topology requires every
    # chain's residues to form one contiguous block, so group by lossless
    # multi-character chain id before adding atoms.  Bond creation below still
    # uses source serials and is independent of this topology ordering.
    atoms_by_chain: dict[str, list[object]] = {}
    for source in model.atoms:
        atoms_by_chain.setdefault(source.chain_id, []).append(source)

    for chain_id, chain_atoms in atoms_by_chain.items():
        # Physical atom generation is helix-oriented.  seq_num is explicitly
        # renumbered by the atomistic builder to follow the strand backbone,
        # including crossover insertions, and therefore defines residue order.
        chain_atoms.sort(key=lambda source: source.seq_num)
        # Multi-character IDs are legal in OpenMM Topology and mmCIF.
        chain = topology.addChain(id=chain_id)
        chain_by_id[chain_id] = chain
        for source in chain_atoms:
            residue_key = (source.chain_id, source.seq_num)
            is_five_prime = terminal_names.get(residue_key, "").endswith("5")
            if is_five_prime and source.name in {"P", "OP1", "OP2"}:
                continue

            residue = residue_by_key.get(residue_key)
            if residue is None:
                residue = topology.addResidue(
                    # Hydrogen definitions are keyed by canonical DA/DT/DC/DG.
                    # Terminal OL15 variants are selected through residueTemplates.
                    source.residue,
                    chain,
                    id=str(source.seq_num),
                )
                residue_by_key[residue_key] = residue

            # Direct Topology construction bypasses PDBFile's O1P/O2P → OP1/OP2
            # normalization, so use the atom names that OL15.xml itself declares.
            name = source.name
            element = Element.getBySymbol(source.element)
            target = topology.addAtom(name, element, residue, id=str(source.serial + 1))
            atom_by_serial[source.serial] = target
            positions.append(Vec3(source.x, source.y, source.z))
            atom_keys.append((source.strand_id, source.seq_num, name, source.element))

    for serial_a, serial_b in model.bonds:
        atom_a = atom_by_serial.get(serial_a)
        atom_b = atom_by_serial.get(serial_b)
        if atom_a is not None and atom_b is not None:
            topology.addBond(atom_a, atom_b)

    return topology, positions * unit.nanometer, tuple(atom_keys)


def prepare_implicit_system(
    design: "Design", protocol: OpenMMImplicitProtocol
) -> PreparedImplicitSystem:
    """Parameterize on the CPU without creating a GPU Context."""
    from openmm import unit
    from openmm import app

    topology, positions, heavy_keys = build_openmm_topology(design)
    forcefield = app.ForceField(*FORCEFIELD_FILES)
    modeller = app.Modeller(topology, positions)
    modeller.addHydrogens(
        forcefield,
        pH=7.0,
        residueTemplates=amber_terminal_templates(modeller.topology),
    )
    residue_templates = amber_terminal_templates(modeller.topology)

    method = (
        app.NoCutoff
        if protocol.nonbonded_mode == "no_cutoff"
        else app.CutoffNonPeriodic
    )
    kwargs = {
        "nonbondedMethod": method,
        "constraints": app.HBonds,
        "soluteDielectric": protocol.solute_dielectric,
        "solventDielectric": protocol.solvent_dielectric,
        "implicitSolventKappa": debye_kappa_per_nm(protocol),
    }
    if protocol.nonbonded_mode == "cutoff_nonperiodic":
        kwargs["nonbondedCutoff"] = protocol.cutoff_nm * unit.nanometer
    system = forcefield.createSystem(
        modeller.topology,
        residueTemplates=residue_templates,
        **kwargs,
    )

    # Record the force-field charge, including added hydrogens.  A net-negative
    # origami is expected: 150 mM here screens it but does not add counterions.
    net_charge_e = 0.0
    for force in system.getForces():
        if force.__class__.__name__ == "NonbondedForce":
            for index in range(force.getNumParticles()):
                charge, _, _ = force.getParticleParameters(index)
                net_charge_e += charge.value_in_unit(unit.elementary_charge)
            break

    return PreparedImplicitSystem(
        topology=modeller.topology,
        positions=modeller.positions,
        system=system,
        atom_keys=heavy_keys,
        n_heavy_atoms=len(heavy_keys),
        n_atoms=system.getNumParticles(),
        n_strands=sum(1 for _ in modeller.topology.chains()),
        net_charge_e=float(net_charge_e),
    )


def create_cuda_simulation(prepared: PreparedImplicitSystem, protocol: OpenMMImplicitProtocol):
    """Create a CUDA Context after enforcing the no-contention guard.

    There is intentionally no CPU fallback: a requested GPU-resident production
    run must fail visibly if CUDA is unavailable.
    """
    assert_simulation_slot_available()

    from openmm import LangevinMiddleIntegrator, Platform, unit
    from openmm.app import Simulation

    integrator = LangevinMiddleIntegrator(
        protocol.temperature_k * unit.kelvin,
        protocol.friction_per_ps / unit.picosecond,
        protocol.timestep_fs * unit.femtoseconds,
    )
    integrator.setConstraintTolerance(protocol.constraint_tolerance)
    integrator.setRandomNumberSeed(protocol.random_seed)
    platform = Platform.getPlatformByName("CUDA")
    simulation = Simulation(
        prepared.topology,
        prepared.system,
        integrator,
        platform,
        platform_properties(protocol),
    )
    simulation.context.setPositions(prepared.positions)
    return simulation


def attach_production_reporters(
    simulation,
    output_dir: Path,
    protocol: OpenMMImplicitProtocol,
    *,
    append: bool = False,
) -> None:
    """Attach sparse, restartable reporters to limit host/device transfers."""
    from openmm import app

    output_dir.mkdir(parents=True, exist_ok=True)
    simulation.reporters.extend(
        [
            app.DCDReporter(
                str(output_dir / "trajectory.dcd"),
                protocol.trajectory_interval_steps,
                append=append,
                enforcePeriodicBox=False,
            ),
            app.StateDataReporter(
                str(output_dir / "state.csv"),
                protocol.state_interval_steps,
                step=True,
                time=True,
                potentialEnergy=True,
                kineticEnergy=True,
                temperature=True,
                speed=True,
                remainingTime=True,
                totalSteps=protocol.production_steps,
                separator=",",
                append=append,
            ),
            app.CheckpointReporter(
                str(output_dir / "checkpoint.chk"),
                protocol.checkpoint_interval_steps,
            ),
            # Checkpoints preserve exact continuation but are hardware/version
            # specific.  The serialized State is a portable, approximate fallback.
            app.CheckpointReporter(
                str(output_dir / "state.xml"),
                protocol.checkpoint_interval_steps,
                writeState=True,
            ),
        ]
    )


def write_run_manifest(
    output_dir: Path,
    protocol: OpenMMImplicitProtocol,
    prepared: PreparedImplicitSystem,
) -> Path:
    """Write run provenance without creating or stepping a Context."""
    import openmm
    from openmm import app

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "engine": "OpenMM",
        "openmm_version": openmm.version.version,
        "forcefield": FORCEFIELD_DESCRIPTION,
        "forcefield_files": list(FORCEFIELD_FILES),
        "salt_interpretation": (
            "generic monovalent Debye screening; no discrete Na/Cl particles"
        ),
        "protocol": protocol.to_dict(),
        "system": {
            "n_heavy_atoms": prepared.n_heavy_atoms,
            "n_atoms": prepared.n_atoms,
            "n_strands": prepared.n_strands,
            "net_charge_e": prepared.net_charge_e,
        },
    }
    path = output_dir / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    with (output_dir / "input.cif").open("w") as handle:
        app.PDBxFile.writeFile(prepared.topology, prepared.positions, handle)
    return path
