"""Charge and topology audits for NAMD PSF/PDB packages."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


DNA_RESNAMES = {"DA", "DC", "DG", "DT", "ADE", "CYT", "GUA", "THY"}
WATER_RESNAMES = {"TIP3", "HOH", "WAT"}
ION_RESNAMES = {"SOD", "CLA", "MG", "MGH", "POT"}


@dataclass(frozen=True)
class PsfAtom:
    serial: int
    segid: str
    resid: str
    resname: str
    atomname: str
    atomtype: str
    charge: float
    mass: float


@dataclass
class ChargeAudit:
    n_atoms: int = 0
    total_charge: float = 0.0
    nearest_integer_charge: int = 0
    integer_charge_error: float = 0.0
    dna_atoms: int = 0
    dna_residues: int = 0
    dna_hydrogens: int = 0
    dna_total_charge: float = 0.0
    dna_residue_charge_min: float | None = None
    dna_residue_charge_max: float | None = None
    water_atoms: int = 0
    ion_atoms: int = 0
    ion_total_charge: float = 0.0
    residue_counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        data = asdict(self)
        data["passed"] = self.passed
        return data


def parse_psf_atoms(psf_text: str) -> list[PsfAtom]:
    """Parse the NATOM section of an extended or standard CHARMM PSF."""
    atoms: list[PsfAtom] = []
    in_natom = False
    expected: int | None = None
    for line in psf_text.splitlines():
        if "!NATOM" in line:
            in_natom = True
            try:
                expected = int(line.split()[0])
            except (IndexError, ValueError):
                expected = None
            continue
        if not in_natom:
            continue
        stripped = line.strip()
        if not stripped:
            if expected is None or len(atoms) >= expected:
                break
            continue
        if stripped.startswith("!") or "!N" in line:
            break
        parts = stripped.split()
        if len(parts) < 8:
            continue
        try:
            atoms.append(
                PsfAtom(
                    serial=int(parts[0]),
                    segid=parts[1],
                    resid=parts[2],
                    resname=parts[3],
                    atomname=parts[4],
                    atomtype=parts[5],
                    charge=float(parts[6]),
                    mass=float(parts[7]),
                )
            )
        except ValueError:
            continue
        if expected is not None and len(atoms) >= expected:
            break
    return atoms


def audit_psf(
    psf_text: str,
    *,
    require_neutral: bool = False,
    require_dna_hydrogens: bool = False,
    require_dna_residue_charge: bool = False,
    integer_tolerance: float = 1.0e-3,
    dna_residue_charge_bounds: tuple[float, float] = (-1.25, -0.25),
) -> ChargeAudit:
    """Return production-readiness diagnostics for a PSF topology."""
    atoms = parse_psf_atoms(psf_text)
    audit = ChargeAudit(n_atoms=len(atoms))
    residue_charge: dict[tuple[str, str, str], float] = {}

    for atom in atoms:
        resname = atom.resname.upper()
        audit.total_charge += atom.charge
        audit.residue_counts[resname] = audit.residue_counts.get(resname, 0) + 1
        if resname in DNA_RESNAMES:
            audit.dna_atoms += 1
            audit.dna_total_charge += atom.charge
            if atom.atomname.upper().startswith(
                "H"
            ) or atom.atomtype.upper().startswith("H"):
                audit.dna_hydrogens += 1
            key = (atom.segid, atom.resid, resname)
            residue_charge[key] = residue_charge.get(key, 0.0) + atom.charge
        elif resname in WATER_RESNAMES:
            audit.water_atoms += 1
        elif resname in ION_RESNAMES:
            audit.ion_atoms += 1
            audit.ion_total_charge += atom.charge

    audit.dna_residues = len(residue_charge)
    audit.nearest_integer_charge = int(round(audit.total_charge))
    audit.integer_charge_error = audit.total_charge - audit.nearest_integer_charge
    if residue_charge:
        charges = list(residue_charge.values())
        audit.dna_residue_charge_min = min(charges)
        audit.dna_residue_charge_max = max(charges)

    if not atoms:
        audit.errors.append("PSF has no parseable NATOM records.")
    if abs(audit.integer_charge_error) > integer_tolerance:
        audit.errors.append(
            f"Total PSF charge {audit.total_charge:.6f} is not close to an integer."
        )
    if require_neutral and abs(audit.total_charge) > integer_tolerance:
        audit.errors.append(
            f"Final PSF is not neutral: total charge {audit.total_charge:.6f} e."
        )
    if require_dna_hydrogens and audit.dna_atoms and audit.dna_hydrogens == 0:
        audit.errors.append(
            "DNA topology has zero hydrogens; production NAMD requires a full all-atom DNA topology."
        )
    if require_dna_residue_charge and residue_charge:
        low, high = dna_residue_charge_bounds
        bad = [
            charge
            for charge in residue_charge.values()
            if not (low <= charge <= high)
        ]
        if bad:
            audit.errors.append(
                "DNA residue charges are outside expected nucleotide/terminal ranges "
                f"(min={min(residue_charge.values()):.3f}, max={max(residue_charge.values()):.3f})."
            )
    if audit.dna_atoms and audit.dna_hydrogens == 0:
        audit.warnings.append(
            "DNA contains no hydrogens; this is a setup/audit-only topology."
        )
    if audit.dna_atoms and audit.dna_total_charge / max(audit.dna_residues, 1) < -1.5:
        audit.warnings.append(
            "DNA is substantially overcharged per residue, usually indicating heavy-atom-only partial charges."
        )
    return audit


def audit_psf_file(path: str | Path, **kwargs) -> ChargeAudit:
    return audit_psf(Path(path).read_text(errors="replace"), **kwargs)
