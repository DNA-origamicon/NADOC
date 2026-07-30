"""In-vacuo ENRG-MD shape relaxation — tutorial §3.2.  RETIRED 2026-07-30, DORMANT.

**This does not run.**  ``fast_shape`` is marked unavailable and
``routes_md._wants_vacuum_prestage`` returns False unconditionally.  The module is kept
intact rather than deleted so the decision is reversible in one line, following the
precedent set by the BLADE retirement.

WHY IT EXISTS IN THE TUTORIAL, AND WHY NOT HERE.  Their §3.2 turns caDNAno's output into
a structure: the ENRG-MD server hands back helices that are exactly parallel with
abnormally stretched Holliday junctions (their Figs. 3a / 4a) — an abstract lattice, not
a conformation.  Something has to fold that into the chickenwire arrangement before it is
worth solvating, and vacuum is the cheap place to do it.

NADOC never starts from an abstract lattice.  Geometry here is DERIVED — helix axes and
nucleotide positions come from the topology, the B-DNA constants and the design's own
deformations (the Three-Layer Law) — so every design, including one imported from
caDNAno, already carries physical positions.  Measured (exp50): the ideal build of
``6hbx100_90deg`` already holds ~98.5 degrees of per-helix centreline bend.  There is no
parallel-helix lattice here for this step to unfold.  **NADOC's own builder is the
large-geometry relaxation solution; this step is the answer to a problem NADOC does not
have.**

AND IT WAS NOT NEUTRAL.  The interhelical repulsion that truncated Coulomb cannot supply
comes from mrdna's push-bond rule, which requires a crossover-free span > 22 nt.
Honeycomb crossovers to a given neighbour recur every **21** nt, so a dense NADOC bundle
scores **zero** push bonds and the run proceeds with ``PME no``, Coulomb truncated at
10 Å, no Mg screening and no interhelical force term whatsoever.  Measured consequence
(exp50): bundles swelled +5.6 % to +10.0 %, corroborated by exp48's independent P-P
measurement (20.6 -> 22.6 Å).  Mg screening REDUCES interhelical repulsion relative to
unscreened vacuum, so a bundle that opens here is moving away from the equilibrium the
solvated ladder converges on — i.e. the step was seeding the ladder from a worse
structure, not a better one.  The one design that behaved differently, ``24hb_1xT``,
had 495 push bonds and contracted instead: the outcome was decided by whether mrdna's
rule happened to fire, which is an artefact of crossover spacing, not physics.

NOT ADDRESSED HERE: a design carrying genuinely overstretched bonds (a scaffold
connection spanning distant clusters, say), where the derived geometry IS unphysical.
That strain is topological rather than a missing relaxation, and needs its own treatment.

WHAT WOULD MAKE IT DEFENSIBLE, if ever revived: replace mrdna's transplanted >22 nt rule
with a NADOC-native one.  The lattice is known — 2.25 nm honeycomb centre-to-centre, and
the square-lattice equivalent — and so is the neighbour list, straight from the topology.
Restraints at the design spacing would be better founded than a universal 31 Å, which
exp48 already measured as +51 % over the built 20.6 Å.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from backend.core.md_charge import audit_psf
from backend.core.md_protocols import (
    AKSIMENTIEV_STEPS_PER_CYCLE,
    SegmentSpec,
    _min_conf,
    _round_up_to_cycle,
    _segment_conf,
    design_has_extra_bases,
    design_has_extensions,
    identify_unpaired_residues,
    minimize_steps_for_atoms,
    write_aksimentiev_enm_files,
    write_restraints_pdb,
)
from backend.core.models import Design
from backend.core.namd_push_bonds import PUSH_R0_ANG, interhelical_push_bonds
from backend.core.namd_topology import build_charmm_psfgen_topology

logger = logging.getLogger(__name__)

VACUUM_PROTOCOL = "vacuum_enrgmd_namd"

#: Simulated time for the relaxation.  See the convergence table above.
VACUUM_NS = 0.5
#: 2 fs with rigidBonds all, as the tutorial's own step-2 script uses — and as exp48
#: validated at 3k / 21k / 224k atoms with zero base pairs broken.  Do NOT soften this
#: to 1 fs as RATTLE insurance: what actually makes 2 fs safe on an idealised build is
#: minimising ENOUGH (:func:`md_protocols.minimize_steps_for_atoms`), and halving the
#: timestep would double the cost of the step whose whole point is being cheap.
VACUUM_TIMESTEP_FS = 2.0
#: Below this the step is measurably counter-productive (a 2hb's box GREW 6.8 %).
#: The UI asks before running it; the API accepts the answer as ``skip_vacuum_prestage``.
VACUUM_MIN_HELICES = 4
#: The tutorial's step-2 script sets langevinDamping 0.1 — deliberately low friction so
#: the structure relaxes fast, rather than the 5 ps⁻¹ used for thermostatting in water.
VACUUM_DAMPING = 0.1
#: mrdna's default bath temperature for this step (initial velocities are drawn at 300).
VACUUM_TEMP_K = 295.0

_FF_DIR = Path(__file__).parent.parent / "data" / "forcefield"
_FF_FILES = [
    "top_all36_na.rtf",
    "par_all36_na.prm",
    "toppar_water_ions_cufix.str",
    "par_stub_ions_nbfix.str",
]


def vacuum_steps(ns: float = VACUUM_NS, timestep_fs: float = VACUUM_TIMESTEP_FS) -> int:
    """MD steps for ``ns`` nanoseconds, rounded to NAMD's stepspercycle."""
    return _round_up_to_cycle(int(round(ns * 1e6 / timestep_fs)),
                              AKSIMENTIEV_STEPS_PER_CYCLE)


def design_helix_count(design: Design) -> int:
    """Helices in the design — the input to the :data:`VACUUM_MIN_HELICES` decision."""
    return len(getattr(design, "helices", ()) or ())


def build_namd_vacuum_package(
    design: Design,
    job_dir: Path,
    *,
    ns: float = VACUUM_NS,
    minimize_steps: Optional[int] = None,
    min_scale: float = 0.5,
    push_r0_ang: "float | None" = PUSH_R0_ANG,
    atomistic_model=None,
    progress=None,
    force_soft: bool = False,
) -> tuple[str, str, list[SegmentSpec]]:
    """Build a DRY (no water, no ions, no periodic cell) ENRG-MD relaxation package.

    Returns ``(package_subdir, name_stem, segments)`` — the same contract as the
    explicit and GBIS builders, so ``namd_runner.run_job`` drives it unmodified.
    """
    name = (design.metadata.name or "design").replace(" ", "_")
    name_stem = name

    # 1. Dry, hydrogen-complete DNA topology — the same builder the explicit path uses
    #    in strict mode, so the atom ORDER matches and the relaxed coordinates can seed
    #    solvation directly (see build_namd_seed_from_vacuum).
    if progress is not None:
        progress("topology", None, "Building DNA topology (PSF/PDB)…")
    topology_build = build_charmm_psfgen_topology(design, atomistic_model=atomistic_model)
    dna_pdb = topology_build.pdb_text
    dna_psf = topology_build.psf_text

    dry_audit = audit_psf(
        dna_psf, require_dna_hydrogens=True, require_dna_residue_charge=True
    )
    if not dry_audit.passed:
        raise RuntimeError(
            "Dry DNA topology audit failed; cannot start vacuum relaxation. "
            + "; ".join(dry_audit.errors)
        )

    # 2. Package layout.
    package_dir = job_dir / "package" / f"{name}_namd_vacuum"
    (package_dir / "forcefield").mkdir(parents=True, exist_ok=True)
    (package_dir / "output").mkdir(exist_ok=True)
    (package_dir / f"{name_stem}.psf").write_text(dna_psf)
    (package_dir / f"{name_stem}.pdb").write_text(dna_pdb)
    for ff_file in _FF_FILES:
        ff_path = _FF_DIR / ff_file
        if ff_path.exists():
            (package_dir / "forcefield" / ff_file).write_bytes(ff_path.read_bytes())

    pdb_path = package_dir / f"{name_stem}.pdb"

    # 3. Base-ring ENM — holds base pairing/stacking while the global shape relaxes.
    #    Single-stranded inserts and tails stay OUT of the network so they can relax
    #    rather than being pinned into a stretched backbone bond.
    if progress is not None:
        progress("enm", None, "Building elastic-network restraints…")
    write_restraints_pdb(pdb_path, package_dir / "restraints_dna_heavy.pdb")
    exclude = None
    if design_has_extra_bases(design) or design_has_extensions(design):
        exclude = identify_unpaired_residues(package_dir / f"{name_stem}.psf", pdb_path)
    enm_report = write_aksimentiev_enm_files(
        pdb_path, package_dir, name_stem, scales=(min_scale,),
        exclude_residues=exclude or None, progress=progress)

    # 4. Push bonds — the interhelical repulsion surrogate.  Zero of them is a normal,
    #    expected outcome for a 2-helix or densely crossed-over design (see the module
    #    docstring), NOT a failure, so this never raises.
    if progress is not None:
        progress("enm", None, "Building interhelical push bonds…")
    push = interhelical_push_bonds(design, dna_pdb, r0_ang=push_r0_ang)
    push_file: Optional[str] = None
    if push.n_bonds:
        push_file = f"{name_stem}_push.exb"
        (package_dir / push_file).write_text(push.text)
    logger.info("vacuum push bonds for %s: %d (%s)", name_stem, push.n_bonds, push.reason)

    # 5. One relaxation segment.  No barostat (nothing to pressurise), no NPT, and the
    #    tutorial's low-friction thermostat.
    n_atoms = sum(1 for ln in dna_pdb.splitlines() if ln.startswith("ATOM"))
    steps = vacuum_steps(ns, 1.0 if force_soft else VACUUM_TIMESTEP_FS)
    if minimize_steps is None:
        minimize_steps = minimize_steps_for_atoms(n_atoms)
    min_name = f"{name_stem}_00_min_vacuum"
    seg = SegmentSpec(
        name=f"{name_stem}_01_vacuum_enrgmd",
        stage="Vacuum ENRG-MD shape relaxation",
        percent=100.0,
        steps=steps,
        temp=VACUUM_TEMP_K,
        damping=VACUUM_DAMPING,
        scale=min_scale,
        npt=False,
        previous=min_name,
        reinit=False,
        dcd_freq=max(AKSIMENTIEV_STEPS_PER_CYCLE, steps // 50),
        extra_bonds_file=f"{name_stem}_k{min_scale:g}.enm.extra",
        # rigidBonds all at 2 fs — exp48 ran exactly this at 3k / 21k / 224k atoms with
        # 0 base pairs broken.  ``force_soft`` remains available for a structure that
        # still trips RATTLE, but scaled minimisation is the real remedy.
        soft=bool(force_soft),
        timestep_fs=1.0 if force_soft else VACUUM_TIMESTEP_FS,
    )

    if progress is not None:
        progress("finalize", None, "Writing simulation configs…")
    box = (0.0, 0.0, 0.0)          # unused: no periodic cell in vacuum
    (package_dir / f"{min_name}.conf").write_text(
        _min_conf(min_name, name_stem, box, False, minimize_steps, min_scale,
                  vacuum=True, push_bonds_file=push_file)
    )
    (package_dir / f"{seg.name}.conf").write_text(
        _segment_conf(seg, name_stem, box, False, vacuum=True, push_bonds_file=push_file)
    )

    segments = [seg]
    manifest = {
        "nadoc_md_run_manifest_version": 1,
        "protocol": VACUUM_PROTOCOL,
        "package_dir": str(package_dir.resolve()),
        "name_stem": name_stem,
        "files": {
            "topology": f"{name_stem}.psf",
            "coordinates": f"{name_stem}.pdb",
            "forcefield_dir": "forcefield",
            "output_dir": "output",
            "restraints": "restraints_dna_heavy.pdb",
            **({"push_bonds": push_file} if push_file else {}),
        },
        "box_ang": None,
        "mgh_extrabonds": False,
        "solvent": {
            "model": "vacuum",
            "note": (
                "In-vacuo ENRG-MD shape relaxation (Aksimentiev tutorial §3.2). No "
                "solvent model and no PME; interhelical repulsion comes from push bonds. "
                "This is a SHAPE step — it produces a structure, not thermodynamics."
            ),
        },
        "push_bonds": {
            "n_bonds": push.n_bonds,
            "r0_ang": push_r0_ang,
            "reason": push.reason,
            "n_positions": len(push.positions),
        },
        "helices": design_helix_count(design),
        "minimization": {
            "name": min_name,
            "steps": minimize_steps,
            "scale": min_scale,
            "restraint": "aksimentiev_base_ring_enm",
            "extra_bonds_file": f"{name_stem}_k{min_scale:g}.enm.extra",
        },
        "aksimentiev_enm": enm_report,
        "relax_protocol_settings": {
            "ns": ns,
            "steps": steps,
            "timestep_fs": seg.timestep_fs,
            "langevin_damping_ps_inv": VACUUM_DAMPING,
            "temperature_k": VACUUM_TEMP_K,
        },
        "segments": [_segment_dict(seg)],
        "health_checks": "After the relaxation segment.",
    }
    manifest_text = json.dumps(manifest, indent=2)
    (package_dir / "manifest.json").write_text(manifest_text)
    (package_dir / "nadoc_md_run.json").write_text(manifest_text)

    return str(package_dir.relative_to(job_dir)), name_stem, segments


# ── Vacuum → solvation handoff ────────────────────────────────────────────────
# The tutorial's §3.3 starts from ``hextube_min.pdb`` — the LAST FRAME of the vacuum run,
# not the idealised build.  Same shape as the BLADE seed path
# (blade_runner.build_namd_seed_from_blade): read an exact all-atom conformation in
# psfgen atom order and hand it to ``build_namd_solvated_package(solute_coords=...)``,
# which overwrites the freshly built PDB's coordinates before placing any water.

class VacuumNamdSeed:
    """A vacuum-relaxed structure ready to seed the solvated ladder.

    ``solute_coords`` is (N_atoms, 3) in Å, in the order
    ``build_charmm_psfgen_topology(design)`` emits.  The solvation step rebuilds the
    topology from the SAME design with the SAME builder, so the order matches by
    construction — but the row count is checked against the package's own PDB anyway,
    because a silent mis-order would scramble every atom rather than fail loudly.
    """

    __slots__ = ("solute_coords", "n_atoms", "source_job_id", "source")

    def __init__(self, solute_coords, source_job_id, source):
        self.solute_coords = solute_coords
        self.n_atoms = len(solute_coords)
        self.source_job_id = source_job_id
        self.source = source          # which file the coordinates came from


def _pdb_atom_count(pdb_path: Path) -> int:
    n = 0
    with pdb_path.open("r", errors="ignore") as fh:
        for ln in fh:
            if ln.startswith(("ATOM", "HETATM")):
                n += 1
    return n


def build_namd_seed_from_vacuum(job_id: str, workspace_dir: Path) -> VacuumNamdSeed:
    """Read the final coordinates of a completed vacuum relaxation.

    Prefers NAMD's end-of-run binary ``.coor`` (full double precision, and with
    ``wrapAll off`` never wrapped); falls back to the last DCD frame, which is single
    precision but adequate as a seed.
    """
    import numpy as np  # noqa: PLC0415
    import MDAnalysis as mda  # noqa: PLC0415

    from backend.core.md_job import MdJob  # noqa: PLC0415

    job = MdJob.load(job_id, workspace_dir)          # FileNotFoundError if unknown
    package_dir = job.package_dir(workspace_dir)
    psf = package_dir / f"{job.name_stem}.psf"
    pdb = package_dir / f"{job.name_stem}.pdb"
    if not psf.exists() or not pdb.exists():
        raise FileNotFoundError(
            f"Vacuum job {job_id} has no topology in {package_dir}; cannot seed.")

    manifest = json.loads((package_dir / "manifest.json").read_text())
    seg_names = [s["name"] for s in manifest.get("segments", [])]
    if not seg_names:
        raise FileNotFoundError(f"Vacuum job {job_id} manifest lists no segments.")
    last = seg_names[-1]
    out = package_dir / "output"

    coords, source = None, ""
    for candidate in (out / f"{last}.coor", out / f"{last}.restart.coor"):
        if candidate.exists():
            u = mda.Universe(str(psf), str(candidate), format="NAMDBIN")
            coords, source = u.atoms.positions.copy(), candidate.name
            break
    if coords is None:
        dcd = out / f"{last}.dcd"
        if not dcd.exists():
            raise FileNotFoundError(
                f"Vacuum job {job_id} produced no coordinates yet "
                f"(looked for {last}.coor / .restart.coor / .dcd in {out}).")
        u = mda.Universe(str(psf), str(dcd))
        u.trajectory[-1]
        coords, source = u.atoms.positions.copy(), dcd.name

    expected = _pdb_atom_count(pdb)
    if len(coords) != expected:
        raise RuntimeError(
            f"Vacuum seed atom-count mismatch for job {job_id}: {source} has "
            f"{len(coords):,} atoms but {pdb.name} has {expected:,}. Refusing to seed "
            f"— the coordinates would be assigned to the wrong atoms.")
    if not np.all(np.isfinite(coords)):
        raise RuntimeError(
            f"Vacuum seed from job {job_id} contains non-finite coordinates ({source}); "
            f"the relaxation likely blew up.")
    return VacuumNamdSeed(coords, job_id, source)


def _segment_dict(s: SegmentSpec) -> dict:
    return {
        "name": s.name, "stage": s.stage, "percent": s.percent, "steps": s.steps,
        "temp": s.temp, "damping": s.damping, "scale": s.scale, "npt": s.npt,
        "previous": s.previous, "reinit": s.reinit, "dcd_freq": s.dcd_freq,
        "min_c1_paired": s.min_c1_paired, "min_wc_ref_relative": s.min_wc_ref_relative,
        "extra_bonds_file": s.extra_bonds_file, "soft": s.soft, "gentle": s.gentle,
        "timestep_fs": s.timestep_fs,
    }


def prepare_vacuum_enrgmd_namd(
    design: Design,
    job_dir: Path,
    *,
    minimize_steps: Optional[int] = None,
    atomistic_model=None,
    progress=None,
    force_soft: bool = False,
    require_full_topology: bool = True,
    allow_catenated_seed: bool = False,
    # Accept-and-ignore the explicit-solvent kwargs so the shared prep call site
    # (routes_md) can pass ONE uniform kwarg set regardless of protocol.  See
    # tests/test_prepare_signatures.py, which pins this against the real call site.
    ion_conc_mM: float = 0.0,      # noqa: ARG001 — no solvent
    mg_conc_mM: float = 0.0,       # noqa: ARG001
    salt_mode: str = "custom",     # noqa: ARG001
    padding_nm: float = 1.2,       # noqa: ARG001 — no box
    water_shell_nm: float = 0.0,   # noqa: ARG001
    fast: bool = False,            # noqa: ARG001 — standard CUDA, no GPUresident
    seed: int = 42,                # noqa: ARG001 — nothing random to place
    declash: bool = False,         # noqa: ARG001 — the ladder is soft throughout
    gpu_resident_mode: str = "auto",       # noqa: ARG001
    production_timestep_fs: float = 4.0,   # noqa: ARG001
    devices: str = "0",            # noqa: ARG001
    anchors: Optional[list] = None,        # noqa: ARG001
    field: Optional[dict] = None,          # noqa: ARG001
    solute_coords=None,            # noqa: ARG001 — this stage PRODUCES the seed
) -> tuple[str, str, list[SegmentSpec]]:
    """Protocol entry point: prepare an in-vacuo ENRG-MD shape relaxation.

    The same two gates the solvated builder applies run here, deliberately: this stage's
    output SEEDS the solvated run, so a poly-T or topologically catenated structure
    relaxed in vacuum would poison everything downstream rather than just wasting one
    experiment.
    """
    if require_full_topology:
        from backend.core.md_sequence_guard import require_sequenced_scaffold  # noqa: PLC0415
        require_sequenced_scaffold(design)

    from backend.core.junction_topology import gate_seed_topology  # noqa: PLC0415
    gate_seed_topology(design, model=atomistic_model, allow=allow_catenated_seed)

    return build_namd_vacuum_package(
        design, job_dir,
        minimize_steps=minimize_steps,
        atomistic_model=atomistic_model,
        progress=progress,
        force_soft=force_soft,
    )
