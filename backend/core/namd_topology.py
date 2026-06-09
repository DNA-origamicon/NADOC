"""CHARMM/psfgen topology builders for NADOC NAMD packages."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from backend.core.atomistic import Atom, build_atomistic_model
from backend.core.md_charge import audit_psf
from backend.core.models import Design
from backend.core.pdb_export import _chain_char, _cryst1_record, _h36, _psf_segid


_FF_DIR = Path(__file__).parent.parent / "data" / "forcefield"
_TOP_ALL36_NA = _FF_DIR / "top_all36_na.rtf"

_RESNAME_TO_CHARMM = {
    "DA": "ADE",
    "DC": "CYT",
    "DG": "GUA",
    "DT": "THY",
}

_ATOM_TO_CHARMM = {
    "OP1": "O1P",
    "OP2": "O2P",
    "C7": "C5M",
}


@dataclass(frozen=True)
class CharmmTopologyBuild:
    pdb_text: str
    psf_text: str
    metadata: dict


def find_psfgen() -> str:
    """Return a local psfgen executable path."""
    candidates = [
        shutil.which("psfgen"),
        str(Path.home() / "Applications" / "NAMD_3.0.2" / "psfgen"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise RuntimeError("psfgen not found; install NAMD or add psfgen to PATH.")


def _pdb_atom_name(name: str, element: str) -> str:
    if len(name) >= 4:
        return f"{name[:4]:<4s}"
    if len(element) == 1:
        return f" {name:<3s}"
    return f"{name:<4s}"


def _psfgen_resname(atom: Atom) -> str:
    return _RESNAME_TO_CHARMM.get(atom.residue, atom.residue)


def _psfgen_atom_name(atom: Atom) -> str:
    return _ATOM_TO_CHARMM.get(atom.name, atom.name)


def _psfgen_pdb_record(atom: Atom, serial: int) -> str:
    atom_name = _psfgen_atom_name(atom)
    resname = _psfgen_resname(atom)
    chain = _chain_char(atom.chain_id)
    segid = _psf_segid(atom.chain_id)[:4]
    x_ang = atom.x * 10.0
    y_ang = atom.y * 10.0
    z_ang = atom.z * 10.0
    return (
        f"ATOM  {serial:5d} {_pdb_atom_name(atom_name, atom.element)} {resname:>3s} {chain}"
        f"{_h36(atom.seq_num, 4)}    "
        f"{x_ang:8.3f}{y_ang:8.3f}{z_ang:8.3f}"
        f"  1.00  0.00      {segid:<4s}{atom.element:>2s}  "
    )


def _write_segment_pdbs(design: Design, tmpdir: Path) -> tuple[list[dict], str]:
    model = build_atomistic_model(design)
    atoms_by_chain: dict[str, list[Atom]] = {}
    for atom in model.atoms:
        atoms_by_chain.setdefault(atom.chain_id, []).append(atom)

    full_lines = [
        "REMARK  NADOC psfgen input model (heavy atoms; CHARMM residue/atom names)",
        _cryst1_record(model.atoms, margin_nm=1.2),
    ]
    segments: list[dict] = []
    serial = 1
    for chain_id, atoms in sorted(atoms_by_chain.items(), key=lambda item: item[0]):
        atoms = sorted(atoms, key=lambda a: (a.seq_num, a.serial))
        segid = _psf_segid(chain_id)[:4]
        residues = sorted({a.seq_num for a in atoms})
        if not residues:
            continue
        seg_lines = [
            "REMARK  NADOC psfgen segment input",
            _cryst1_record(atoms, margin_nm=1.2),
        ]
        for atom in atoms:
            line = _psfgen_pdb_record(atom, serial)
            seg_lines.append(line)
            full_lines.append(line)
            serial += 1
        last = atoms[-1]
        seg_lines.append(
            f"TER   {serial:5d}      {_psfgen_resname(last):>3s} "
            f"{_chain_char(last.chain_id)}{_h36(last.seq_num, 4)}"
        )
        full_lines.append(seg_lines[-1])
        serial += 1
        seg_lines.append("END")
        seg_path = tmpdir / f"{segid}.pdb"
        seg_path.write_text("\n".join(seg_lines) + "\n")
        segments.append({
            "segid": segid,
            "chain_id": chain_id,
            "path": seg_path,
            "first_resid": residues[0],
            "last_resid": residues[-1],
            "n_residues": len(residues),
            "n_atoms_input": len(atoms),
        })

    full_lines.append("END")
    return segments, "\n".join(full_lines) + "\n"


def _psfgen_script(segments: list[dict], output_prefix: Path) -> str:
    lines = [
        "package require psfgen",
        "resetpsf",
        f"topology {_TOP_ALL36_NA}",
    ]
    for seg in segments:
        segid = seg["segid"]
        path = seg["path"]
        first = seg["first_resid"]
        last = seg["last_resid"]
        lines.extend([
            f"segment {segid} {{",
            "  first 5TER",
            "  last 3TER",
            "  auto angles dihedrals",
            f"  pdb {path}",
            "}",
            f"patch DEO5 {segid}:{first}",
        ])
        for resid in range(first + 1, last + 1):
            lines.append(f"patch DEOX {segid}:{resid}")
        lines.extend([
            f"coordpdb {path} {segid}",
        ])
    lines.extend([
        "regenerate angles dihedrals",
        "guesscoord",
        f"writepsf {output_prefix}.psf",
        f"writepdb {output_prefix}.pdb",
        "exit",
    ])
    return "\n".join(lines) + "\n"


def build_charmm_psfgen_topology(design: Design, *, psfgen_path: str | None = None) -> CharmmTopologyBuild:
    """Build a full all-hydrogen CHARMM DNA PSF/PDB with psfgen.

    This follows the working AutoNAMD NAMD-side topology convention:
    CHARMM residue names (ADE/CYT/GUA/THY), 5TER/3TER strand termini,
    DEO5 on the 5-prime residue, DEOX on internal/3-prime residues, and
    psfgen guesscoord for hydrogens.
    """
    if not _TOP_ALL36_NA.exists():
        raise RuntimeError(f"Missing CHARMM NA topology file: {_TOP_ALL36_NA}")
    psfgen = psfgen_path or find_psfgen()
    with tempfile.TemporaryDirectory(prefix="nadoc_psfgen_") as raw_tmp:
        tmpdir = Path(raw_tmp)
        segments, input_pdb = _write_segment_pdbs(design, tmpdir)
        if not segments:
            raise RuntimeError("No DNA segments found for psfgen topology build.")
        out_prefix = tmpdir / "nadoc_charmm"
        script = _psfgen_script(segments, out_prefix)
        script_path = tmpdir / "build_psfgen.tcl"
        script_path.write_text(script)
        proc = subprocess.run(
            [psfgen, str(script_path)],
            cwd=tmpdir,
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                "psfgen failed while building full DNA topology.\n"
                f"stdout:\n{proc.stdout[-4000:]}\n"
                f"stderr:\n{proc.stderr[-4000:]}"
            )
        psf_path = out_prefix.with_suffix(".psf")
        pdb_path = out_prefix.with_suffix(".pdb")
        if not psf_path.exists() or not pdb_path.exists():
            raise RuntimeError(
                "psfgen completed but did not write PSF/PDB outputs.\n"
                f"stdout:\n{proc.stdout[-4000:]}\n"
                f"stderr:\n{proc.stderr[-4000:]}"
            )
        psf_text = psf_path.read_text(errors="replace")
        pdb_text = pdb_path.read_text(errors="replace")
        audit = audit_psf(
            psf_text,
            require_dna_hydrogens=True,
            require_dna_residue_charge=True,
        )
        if not audit.passed:
            raise RuntimeError(
                "psfgen topology failed audit: " + "; ".join(audit.errors)
            )
        metadata = {
            "topology_builder": "charmm_psfgen",
            "psfgen_path": psfgen,
            "forcefield_topology": str(_TOP_ALL36_NA),
            "segments": [
                {k: str(v) if isinstance(v, Path) else v for k, v in seg.items() if k != "path"}
                for seg in segments
            ],
            "audit": audit.to_dict(),
            "psfgen_stdout_tail": proc.stdout[-4000:],
            "psfgen_stderr_tail": proc.stderr[-4000:],
        }
        metadata["json"] = json.dumps(metadata, indent=2)
        return CharmmTopologyBuild(pdb_text=pdb_text, psf_text=psf_text, metadata=metadata)
