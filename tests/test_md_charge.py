from __future__ import annotations

from backend.core.md_charge import audit_psf


def _psf(atom_lines: list[str]) -> str:
    return "\n".join([
        "PSF EXT",
        "",
        f"{len(atom_lines):8d} !NATOM",
        *atom_lines,
        "",
        "       0 !NBOND: bonds",
        "",
    ])


def test_audit_rejects_heavy_atom_dna_when_full_topology_required() -> None:
    psf = _psf([
        "         1 DNAA     1        DA       P        P        1.165900     30.974000        0",
        "         2 DNAA     1        DA       O1P      ON      -0.776100     15.999000        0",
        "         3 DNAA     1        DA       O2P      ON      -0.776100     15.999000        0",
    ])

    audit = audit_psf(
        psf,
        require_dna_hydrogens=True,
        require_dna_residue_charge=True,
    )

    assert not audit.passed
    assert audit.dna_hydrogens == 0
    assert any("zero hydrogens" in err for err in audit.errors)


def test_audit_accepts_neutral_hydrogenated_dna_package() -> None:
    psf = _psf([
        "         1 DNAA     1        ADE      P        P        0.100000     30.974000        0",
        "         2 DNAA     1        ADE      H8       H        0.100000      1.008000        0",
        "         3 DNAA     1        ADE      O1P      ON      -1.200000     15.999000        0",
        "         4 I000     1        SOD      SOD      SOD      1.000000     22.990000        0",
    ])

    audit = audit_psf(
        psf,
        require_neutral=True,
        require_dna_hydrogens=True,
        require_dna_residue_charge=True,
    )

    assert audit.passed
    assert audit.total_charge == 0.0
    assert audit.dna_hydrogens == 1
    assert audit.ion_total_charge == 1.0
