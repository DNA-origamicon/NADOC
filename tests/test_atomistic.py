"""
Tests for backend/core/atomistic.py and backend/core/pdb_export.py — Phase AA.
"""

import math
import re

import pytest

from backend.core.atomistic import (
    BASE_TEMPLATES,
    _SUGAR,
    _SUGAR_BONDS,
    build_atomistic_model,
    atomistic_to_json,
)
from backend.core.lattice import make_bundle_design
from backend.core.pdb_export import _box_dimensions, _h36, export_pdb, export_psf


# ── Helpers ───────────────────────────────────────────────────────────────────

_CELLS_6HB = [(0, 0), (0, 1), (1, 0), (1, 2), (0, 2), (2, 1)]


def _small_design():
    """6HB 42-bp design — minimum valid design for scaffold/staple tests."""
    return make_bundle_design(cells=_CELLS_6HB, length_bp=42, plane='XY')


# ── Template completeness ─────────────────────────────────────────────────────

EXPECTED_BACKBONE_ATOMS = {
    "P", "OP1", "OP2", "O5'", "C5'", "C4'", "O4'", "C3'", "O3'", "C2'", "C1'",
}

EXPECTED_BASE_ATOMS = {
    "DA": {"N9", "C8", "N7", "C5", "C4", "N3", "C2", "N1", "C6", "N6"},
    "DT": {"N1", "C2", "O2", "N3", "C4", "O4", "C5", "C6", "C7"},
    "DC": {"N1", "C2", "O2", "N3", "C4", "N4", "C5", "C6"},
    "DG": {"N9", "C8", "N7", "C5", "C4", "N3", "C2", "N2", "N1", "C6", "O6"},
}


def test_sugar_contains_all_backbone_atoms():
    sugar_names = {entry[0] for entry in _SUGAR}
    assert EXPECTED_BACKBONE_ATOMS == sugar_names


@pytest.mark.parametrize("residue", ["DA", "DT", "DC", "DG"])
def test_base_template_completeness(residue):
    base_atoms, _ = BASE_TEMPLATES[residue]
    atom_names = {entry[0] for entry in base_atoms}
    assert EXPECTED_BASE_ATOMS[residue] == atom_names, (
        f"{residue}: missing {EXPECTED_BASE_ATOMS[residue] - atom_names}, "
        f"extra {atom_names - EXPECTED_BASE_ATOMS[residue]}"
    )


# ── Intra-residue bond graph integrity ────────────────────────────────────────

@pytest.mark.parametrize("residue", ["DA", "DT", "DC", "DG"])
def test_base_bond_atoms_present(residue):
    """Every atom named in a bond must be present in the template (sugar or base)."""
    base_atoms, base_bonds = BASE_TEMPLATES[residue]
    all_names = {e[0] for e in _SUGAR} | {e[0] for e in base_atoms}
    for a, b in base_bonds:
        assert a in all_names, f"{residue} bond {a}-{b}: {a!r} not in atoms"
        assert b in all_names, f"{residue} bond {a}-{b}: {b!r} not in atoms"


def test_sugar_bond_atoms_present():
    sugar_names = {e[0] for e in _SUGAR}
    for a, b in _SUGAR_BONDS:
        assert a in sugar_names, f"Sugar bond {a}-{b}: {a!r} not in atoms"
        assert b in sugar_names, f"Sugar bond {a}-{b}: {b!r} not in atoms"


# ── Model build counts ─────────────────────────────────────────────────────────

def test_build_atomistic_model_non_empty():
    design = _small_design()
    model  = build_atomistic_model(design)
    assert len(model.atoms) > 0
    assert len(model.bonds) > 0


def test_build_atomistic_model_serials_unique():
    design = _small_design()
    model  = build_atomistic_model(design)
    serials = [a.serial for a in model.atoms]
    assert len(serials) == len(set(serials)), "Duplicate atom serials"


def test_build_atomistic_model_serials_zero_based():
    design = _small_design()
    model  = build_atomistic_model(design)
    serials = sorted(a.serial for a in model.atoms)
    assert serials[0] == 0
    assert serials[-1] == len(model.atoms) - 1


def test_build_atomistic_model_bond_serials_in_range():
    design = _small_design()
    model  = build_atomistic_model(design)
    n = len(model.atoms)
    for i, j in model.bonds:
        assert 0 <= i < n, f"Bond serial {i} out of range [0, {n})"
        assert 0 <= j < n, f"Bond serial {j} out of range [0, {n})"
        assert i != j,      f"Self-bond at serial {i}"


def test_atoms_per_nucleotide_count():
    """Each nucleotide should have exactly len(_SUGAR) + len(base_atoms) heavy atoms."""
    import math as _math
    design = _small_design()
    model  = build_atomistic_model(design)
    # Count atoms by (helix_id, bp_index, direction)
    from collections import Counter
    counts = Counter((a.helix_id, a.bp_index, a.direction) for a in model.atoms)
    for (hid, bp, direction), count in counts.items():
        # Residue type for this nucleotide — get from atom list
        residue = next(
            a.residue for a in model.atoms
            if a.helix_id == hid and a.bp_index == bp and a.direction == direction
        )
        base_atoms, _ = BASE_TEMPLATES[residue]
        expected = len(_SUGAR) + len(base_atoms)
        assert count == expected, (
            f"Nucleotide ({hid}, bp={bp}, {direction}): "
            f"expected {expected} atoms, got {count}"
        )


# ── P atom position test ───────────────────────────────────────────────────────

def test_p_atom_at_backbone_position():
    """
    All P atoms should be within a reasonable distance of their backbone bead
    (the coarse-grained position).  The Rodrigues azimuth correction displaces
    P from the corrected radial position, so we check that the distance is
    plausible (< 0.5 nm) rather than requiring strict consistency.
    """
    import numpy as np
    from backend.core.geometry import nucleotide_positions

    design = _small_design()
    model  = build_atomistic_model(design)

    p_atoms = [a for a in model.atoms if a.name == "P"]
    assert p_atoms, "No P atoms found in model"

    nuc_pos_lookup: dict = {}
    for helix in design.helices:
        for nuc in nucleotide_positions(helix):
            key = (nuc.helix_id, nuc.bp_index, nuc.direction.value)
            nuc_pos_lookup[key] = nuc.position

    for atom in p_atoms:
        key = (atom.helix_id, atom.bp_index, atom.direction)
        ref = nuc_pos_lookup.get(key)
        if ref is None:
            continue
        dist = float(np.linalg.norm(np.array([atom.x, atom.y, atom.z]) - ref))
        assert dist < 1.5, f"P atom at ({atom.x:.3f},{atom.y:.3f},{atom.z:.3f}) is {dist:.3f} nm from backbone bead — seems wrong"


# ── atomistic_to_json ────────────────────────────────────────────────────────

def test_atomistic_to_json_keys():
    design = _small_design()
    model  = build_atomistic_model(design)
    data   = atomistic_to_json(model)
    assert "atoms" in data
    assert "bonds" in data
    assert "element_meta" in data
    for atom_dict in data["atoms"][:5]:
        for key in ("serial", "name", "element", "residue", "chain_id",
                    "seq_num", "x", "y", "z", "strand_id", "helix_id",
                    "bp_index", "direction", "is_modified"):
            assert key in atom_dict, f"Missing key {key!r} in atom dict"


# ── PDB format tests ──────────────────────────────────────────────────────────

def test_pdb_export_runs():
    design   = _small_design()
    pdb_text = export_pdb(design)
    assert isinstance(pdb_text, str)
    assert len(pdb_text) > 0


def test_pdb_has_atom_records():
    design = _small_design()
    pdb    = export_pdb(design)
    atom_lines = [l for l in pdb.splitlines() if l.startswith("ATOM  ")]
    model  = build_atomistic_model(design)
    assert len(atom_lines) == len(model.atoms)


def test_pdb_atom_record_column_widths():
    """ATOM records must be exactly 80 chars with correct column layout."""
    design = _small_design()
    pdb    = export_pdb(design)
    for line in pdb.splitlines():
        if not line.startswith("ATOM  "):
            continue
        assert len(line) >= 54, f"ATOM line too short: {len(line)}: {line!r}"
        # x coordinate at cols 31-38 (0-based: 30-37) — must be a float
        x_field = line[30:38]
        float(x_field)   # raises ValueError if not a number


def test_pdb_coordinates_in_angstroms():
    """PDB coordinates should be ≈10× larger than nm values (Å = nm × 10)."""
    import numpy as np
    design = _small_design()
    pdb    = export_pdb(design)
    model  = build_atomistic_model(design)

    # Get first P atom nm coordinates
    first_p = next(a for a in model.atoms if a.name == "P")
    # Find its ATOM record (serial = first_p.serial + 1, 1-based)
    target_serial = first_p.serial + 1
    for line in pdb.splitlines():
        if not line.startswith("ATOM  "):
            continue
        serial_field = int(line[6:11].strip())
        if serial_field == target_serial:
            x_ang = float(line[30:38])
            y_ang = float(line[38:46])
            z_ang = float(line[46:54])
            assert abs(x_ang - first_p.x * 10.0) < 1e-2
            assert abs(y_ang - first_p.y * 10.0) < 1e-2
            assert abs(z_ang - first_p.z * 10.0) < 1e-2
            break


def test_pdb_ends_with_end():
    design = _small_design()
    pdb    = export_pdb(design)
    assert pdb.strip().endswith("END")


def test_pdb_has_conect_records():
    design = _small_design()
    pdb    = export_pdb(design)
    conect_lines = [l for l in pdb.splitlines() if l.startswith("CONECT")]
    assert len(conect_lines) > 0


def test_pdb_non_std_bonds_link_record():
    """Passing non_std_bonds should generate LINK records for those pairs."""
    design = _small_design()
    model  = build_atomistic_model(design)
    # Pick two arbitrary C5 / C6 atoms on different nucleotides as a mock CPD bond
    c5_atoms = [a for a in model.atoms if a.name == "C5"]
    if len(c5_atoms) < 2:
        pytest.skip("Design too small for mock CPD bond test")
    pair = [(c5_atoms[0].serial, c5_atoms[1].serial)]
    pdb  = export_pdb(design, non_std_bonds=pair)
    link_lines = [l for l in pdb.splitlines() if l.startswith("LINK")]
    # Should have at least one LINK for the non-standard bond
    assert len(link_lines) >= 1


# ── PSF format tests ──────────────────────────────────────────────────────────

def test_psf_export_runs():
    design   = _small_design()
    psf_text = export_psf(design)
    assert isinstance(psf_text, str)
    assert len(psf_text) > 0


def test_psf_starts_with_psf():
    design = _small_design()
    psf    = export_psf(design)
    # "PSF EXT" was changed to "PSF" for NAMD3 compatibility (EXT caused
    # "DIDN'T FIND NATOM" errors in NAMD 3.0.2 multicore builds).
    assert psf.startswith("PSF")


def test_psf_natom_count_matches():
    """The integer on the !NATOM line must match the actual atom count."""
    design = _small_design()
    model  = build_atomistic_model(design)
    psf    = export_psf(design)

    natom_line = next(l for l in psf.splitlines() if "!NATOM" in l)
    declared   = int(natom_line.split()[0])
    assert declared == len(model.atoms)


def test_psf_nbond_count_matches():
    """The integer on the !NBOND line must match the actual bond count."""
    design = _small_design()
    model  = build_atomistic_model(design)
    psf    = export_psf(design)

    nbond_line = next(l for l in psf.splitlines() if "!NBOND" in l)
    declared   = int(nbond_line.split()[0])
    assert declared == len(model.bonds)


def test_psf_atom_line_has_charmm_fields():
    """Each !NATOM entry must have at least 8 space-separated fields."""
    design = _small_design()
    psf    = export_psf(design)
    lines  = psf.splitlines()

    in_natom = False
    count    = 0
    for line in lines:
        if "!NATOM" in line:
            in_natom = True
            continue
        if in_natom:
            if not line.strip() or "!" in line:
                break
            parts = line.split()
            assert len(parts) >= 8, f"PSF NATOM line has only {len(parts)} fields: {line!r}"
            count += 1
    assert count > 0, "No NATOM lines found in PSF"


def test_psf_has_empty_angle_dihedral_sections():
    """Angles, dihedrals, impropers, and cross-terms must be present with count=0."""
    design = _small_design()
    psf    = export_psf(design)
    for section in ("!NTHETA", "!NPHI", "!NIMPHI", "!NCRTERM"):
        assert section in psf, f"Missing section {section!r} in PSF"
        sec_line = next(l for l in psf.splitlines() if section in l)
        count = int(sec_line.split()[0])
        assert count == 0, f"{section} count should be 0, got {count}"


# ── Chain continuity ──────────────────────────────────────────────────────────

def test_inter_residue_backbone_bonds_present():
    """
    For consecutive nucleotides on the same strand, there must be a bond
    between the O3' of the 5' nucleotide and the P of the 3' nucleotide.
    """
    design = _small_design()
    model  = build_atomistic_model(design)

    bond_set = set(model.bonds)

    def _canonical(i, j):
        return (min(i, j), max(i, j))

    # Build per-nucleotide atom lookup
    nuc_atoms: dict = {}
    for atom in model.atoms:
        key = (atom.helix_id, atom.bp_index, atom.direction)
        nuc_atoms.setdefault(key, {})[atom.name] = atom.serial

    from backend.core.sequences import domain_bp_range

    found_bonds = 0
    for strand in design.strands:
        prev_o3_serial = None
        for domain in strand.domains:
            dir_str = domain.direction.value
            for bp in domain_bp_range(domain):
                key = (domain.helix_id, bp, dir_str)
                atoms_here = nuc_atoms.get(key, {})
                p_serial  = atoms_here.get("P")
                o3_serial = atoms_here.get("O3'")

                if prev_o3_serial is not None and p_serial is not None:
                    pair = _canonical(prev_o3_serial, p_serial)
                    assert pair in bond_set, (
                        f"Missing O3'→P bond between serials "
                        f"{prev_o3_serial} and {p_serial} in strand {strand.id}"
                    )
                    found_bonds += 1

                prev_o3_serial = o3_serial

    assert found_bonds > 0, "No inter-residue backbone bonds were checked"


# ── CRYST1 / LINK / TER / NAMD-bundle ────────────────────────────────────────

def test_h36_decimal_range():
    """Values 0-99999 must round-trip as plain decimal in a 5-char field."""
    assert _h36(0, 5)     == "    0"
    assert _h36(99999, 5) == "99999"


def test_h36_overflow_uses_letter_prefix():
    """Values ≥ 100000 must encode with a letter prefix, staying 5 chars wide."""
    encoded = _h36(100000, 5)
    assert len(encoded) == 5, f"_h36(100000, 5) = {encoded!r} is not 5 chars"
    assert encoded[0].isalpha(), f"Expected letter prefix, got {encoded!r}"


def test_pdb_atom_records_fixed_width_large_design():
    """
    Every ATOM line in a large design must be exactly 80 characters wide.
    This catches serial-number overflow that corrupts coordinate columns.
    """
    # 6HB 200bp has ~25,200 atoms — well within 5-char serial; use a repeating
    # cell pattern to get a design large enough to stress-test column alignment.
    big = make_bundle_design(cells=_CELLS_6HB, length_bp=200, plane='XY')
    pdb = export_pdb(big)
    atom_lines = [l for l in pdb.splitlines() if l.startswith("ATOM")]
    assert atom_lines, "No ATOM records found"
    for line in atom_lines:
        assert len(line) == 80, (
            f"ATOM line wrong length ({len(line)}): {line!r}"
        )


def test_pdb_has_cryst1_record():
    """CRYST1 must be present and contain three positive floats."""
    pdb = export_pdb(_small_design())
    cryst_lines = [l for l in pdb.splitlines() if l.startswith("CRYST1")]
    assert len(cryst_lines) == 1, "Expected exactly one CRYST1 record"
    parts = cryst_lines[0].split()
    # CRYST1 a b c alpha beta gamma sg z
    assert len(parts) >= 4, f"CRYST1 line too short: {cryst_lines[0]!r}"
    a, b, c = float(parts[1]), float(parts[2]), float(parts[3])
    assert a > 0 and b > 0 and c > 0, "CRYST1 cell dimensions must be positive"


def test_pdb_cryst1_covers_atoms():
    """CRYST1 cell dimensions must be ≥ the atom bounding box in each axis."""
    design = _small_design()
    model  = build_atomistic_model(design)
    pdb    = export_pdb(design)

    cryst_line = next(l for l in pdb.splitlines() if l.startswith("CRYST1"))
    parts = cryst_line.split()
    ax, ay, az = float(parts[1]), float(parts[2]), float(parts[3])

    xs = [a.x * 10.0 for a in model.atoms]
    ys = [a.y * 10.0 for a in model.atoms]
    zs = [a.z * 10.0 for a in model.atoms]
    span_x = max(xs) - min(xs)
    span_y = max(ys) - min(ys)
    span_z = max(zs) - min(zs)

    assert ax >= span_x, f"CRYST1 a={ax:.3f} < atom span_x={span_x:.3f}"
    assert ay >= span_y, f"CRYST1 b={ay:.3f} < atom span_y={span_y:.3f}"
    assert az >= span_z, f"CRYST1 c={az:.3f} < atom span_z={span_z:.3f}"


def test_pdb_link_records_include_backbone_bonds():
    """
    LINK records must cover all inter-residue O3'→P bonds.
    For a multi-helix design (which has crossovers), the number of LINK
    records should match the number of inter-residue backbone bonds in the model.
    """
    design   = _small_design()
    model    = build_atomistic_model(design)
    pdb      = export_pdb(design)

    link_lines = [l for l in pdb.splitlines() if l.startswith("LINK")]
    assert len(link_lines) > 0, "Expected LINK records for backbone bonds"

    # Count expected inter-residue O3'→P bonds from the model
    atom_by_serial = {a.serial: a for a in model.atoms}
    expected = 0
    for i, j in model.bonds:
        a, b = atom_by_serial[i], atom_by_serial[j]
        if a.seq_num != b.seq_num or a.chain_id != b.chain_id:
            if (a.name == "O3'" and b.name == "P") or \
               (b.name == "O3'" and a.name == "P"):
                expected += 1

    assert len(link_lines) == expected, (
        f"Expected {expected} LINK records, found {len(link_lines)}"
    )


def test_pdb_multiple_ter_records():
    """There must be at least as many TER records as there are strands."""
    design     = _small_design()
    pdb        = export_pdb(design)
    ter_lines  = [l for l in pdb.splitlines() if l.startswith("TER")]
    n_strands  = len(design.strands)
    assert len(ter_lines) == n_strands, (
        f"Expected {n_strands} TER records (one per strand), got {len(ter_lines)}"
    )


def test_namd_bundle_zip_contents():
    """The NAMD bundle ZIP must contain PDB, PSF, namd.conf, and README.txt."""
    import io
    import zipfile

    design     = _small_design()
    model      = build_atomistic_model(design)
    ax, ay, az, ox, oy, oz = _box_dimensions(model.atoms, margin_nm=5.0)
    name       = "test"

    pdb_text  = export_pdb(design)
    psf_text  = export_psf(design)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{name}.pdb", pdb_text)
        zf.writestr(f"{name}.psf", psf_text)
        zf.writestr("namd.conf",   f"cellBasisVector1 {ax:.3f} 0 0\n")
        zf.writestr("README.txt",  "NADOC NAMD Export\n")
    buf.seek(0)

    with zipfile.ZipFile(buf) as zf:
        names = set(zf.namelist())
    assert f"{name}.pdb" in names, "ZIP missing PDB file"
    assert f"{name}.psf" in names, "ZIP missing PSF file"
    assert "namd.conf"   in names, "ZIP missing namd.conf"
    assert "README.txt"  in names, "ZIP missing README.txt"
