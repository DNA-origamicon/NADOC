from __future__ import annotations

from copy import deepcopy

from backend.core.photoproduct_psf_audit import (
    _graph_terms,
    audit_photoproduct_psf,
)


ATOMS = [
    (1, "D000", 7, "C5", "TC5", -0.1),
    (2, "D000", 7, "C6", "TC6", 0.1),
    (3, "D000", 7, "N1", "TN1", 0.0),
    (4, "D000", 7, "C4", "TC4", 0.0),
    (5, "D001", 12, "C5", "TC5", -0.1),
    (6, "D001", 12, "C6", "TC6", 0.1),
    (7, "D001", 12, "N1", "TN1", 0.0),
    (8, "D001", 12, "C4", "TC4", 0.0),
]
BASELINE_BONDS = {(1, 2), (1, 4), (2, 3), (5, 6), (5, 8), (6, 7)}
CROSSLINKS = {(1, 5), (2, 6)}
ANTI_CROSSLINKS = {(1, 6), (2, 5)}
IMPROPERS = [(1, 4, 2, 5), (2, 3, 1, 6), (5, 8, 6, 1), (6, 7, 5, 2)]


def _section(marker, paths):
    flat = [value for path in paths for value in path]
    lines = [f"{len(paths):8d} {marker}"]
    lines.extend(
        "".join(f"{value:8d}" for value in flat[index : index + 8])
        for index in range(0, len(flat), 8)
    )
    return "\n".join(lines)


def _psf(bonds, impropers, *, wrong_type=False):
    graph = _graph_terms(bonds)
    lines = ["PSF", "", f"{len(ATOMS):8d} !NATOM"]
    for index, segid, resid, name, atom_type, charge in ATOMS:
        if wrong_type and index == 1:
            atom_type = "WRONG"
        lines.append(
            f"{index:8d} {segid} {resid} THY {name} {atom_type} {charge:.6f} 12.0110 0"
        )
    lines.extend(
        [
            "",
            _section("!NBOND: bonds", sorted(graph["bonds"])),
            "",
            _section("!NTHETA: angles", sorted(graph["angles"])),
            "",
            _section("!NPHI: dihedrals", sorted(graph["dihedrals"])),
            "",
            _section("!NIMPHI: impropers", impropers),
            "",
        ]
    )
    return "\n".join(lines)


PATCH_PLAN = {
    "patches": [
        {
            "lesion_id": "lesion-1",
            "product_id": "tt-cpd-cis-syn",
            "patch_name": "TCPD",
            "endpoints": [
                {"endpoint": 1, "base_key": "a", "segid": "D000", "resid": 7},
                {"endpoint": 2, "base_key": "b", "segid": "D001", "resid": 12},
            ],
        }
    ],
    "reverse_identity": [
        {
            "lesion_id": "lesion-1",
            "product_id": "tt-cpd-cis-syn",
            "endpoint": 1,
            "base_key": "a",
            "segid": "D000",
            "resid": 7,
        },
        {
            "lesion_id": "lesion-1",
            "product_id": "tt-cpd-cis-syn",
            "endpoint": 2,
            "base_key": "b",
            "segid": "D001",
            "resid": 12,
        },
    ],
}

SPEC = {
    "schema": "nadoc.photoproduct-topology-audit-spec.v1",
    "product_id": "tt-cpd-cis-syn",
    "expected_product_atoms": [
        {"atom": f"{endpoint}:{name}", "type": atom_type, "charge": charge}
        for endpoint, offset in ((1, 0), (2, 4))
        for _index, _segid, _resid, name, atom_type, charge in ATOMS[offset : offset + 4]
    ],
    "crosslinks": [["1:C5", "2:C5"], ["1:C6", "2:C6"]],
    "retained_bonds": [["1:C5", "1:C6"], ["2:C5", "2:C6"]],
    "impropers_added": [
        ["1:C5", "1:C4", "1:C6", "2:C5"],
        ["1:C6", "1:N1", "1:C5", "2:C6"],
        ["2:C5", "2:C4", "2:C6", "1:C5"],
        ["2:C6", "2:N1", "2:C5", "1:C6"],
    ],
    "impropers_removed": [],
}


def test_static_psf_audit_proves_full_graph_charge_types_and_reverse_identity():
    report = audit_photoproduct_psf(
        product_psf_text=_psf(BASELINE_BONDS | CROSSLINKS, IMPROPERS),
        reactant_psf_text=_psf(BASELINE_BONDS, []),
        patch_plan=PATCH_PLAN,
        topology_specs={"tt-cpd-cis-syn": SPEC},
    )
    assert report["passed"] is True
    assert report["atom_count_conserved"] is True
    assert report["product_total_charge"] == report["reactant_total_charge"]
    assert len(report["actual_added_bonds"]) == 2
    assert report["lesions"][0]["product_pair_charge"] == 0.0


def test_static_psf_audit_rejects_bonds_only_or_wrong_product_types():
    report = audit_photoproduct_psf(
        product_psf_text=_psf(BASELINE_BONDS | CROSSLINKS, [], wrong_type=True),
        reactant_psf_text=_psf(BASELINE_BONDS, []),
        patch_plan=PATCH_PLAN,
        topology_specs={"tt-cpd-cis-syn": SPEC},
    )
    assert report["passed"] is False
    assert any("type WRONG" in error for error in report["errors"])
    assert any("added impropers" in error for error in report["errors"])


def test_static_psf_audit_does_not_accept_syn_bonds_for_an_anti_product():
    patch_plan = deepcopy(PATCH_PLAN)
    patch_plan["patches"][0]["product_id"] = "tt-cpd-trans-anti-i"
    for record in patch_plan["reverse_identity"]:
        record["product_id"] = "tt-cpd-trans-anti-i"
    spec = deepcopy(SPEC)
    spec["product_id"] = "tt-cpd-trans-anti-i"
    report = audit_photoproduct_psf(
        product_psf_text=_psf(BASELINE_BONDS | CROSSLINKS, IMPROPERS),
        reactant_psf_text=_psf(BASELINE_BONDS, []),
        patch_plan=patch_plan,
        topology_specs={"tt-cpd-trans-anti-i": spec},
    )
    assert report["passed"] is False
    assert any("ordered registry graph" in error for error in report["errors"])


def test_static_psf_audit_accepts_the_registered_head_to_tail_anti_graph():
    patch_plan = deepcopy(PATCH_PLAN)
    patch_plan["patches"][0]["product_id"] = "tt-cpd-trans-anti-i"
    for record in patch_plan["reverse_identity"]:
        record["product_id"] = "tt-cpd-trans-anti-i"
    spec = deepcopy(SPEC)
    spec["product_id"] = "tt-cpd-trans-anti-i"
    spec["crosslinks"] = [["1:C5", "2:C6"], ["1:C6", "2:C5"]]
    report = audit_photoproduct_psf(
        product_psf_text=_psf(BASELINE_BONDS | ANTI_CROSSLINKS, IMPROPERS),
        reactant_psf_text=_psf(BASELINE_BONDS, []),
        patch_plan=patch_plan,
        topology_specs={"tt-cpd-trans-anti-i": spec},
    )
    assert report["passed"] is True
    assert {tuple(item) for item in report["actual_added_bonds"]} == ANTI_CROSSLINKS
