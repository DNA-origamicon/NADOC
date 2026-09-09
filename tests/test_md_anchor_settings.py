import json

import pytest

from backend.core.md_anchor_settings import harmonic_anchor_k, production_anchor_file
from backend.core.md_protocols import SegmentSpec, package_npt_allowed


def test_appended_production_preserves_harmonic_dna_and_graphene(tmp_path):
    from backend.api.routes_md import _conservative_production_conf

    def atom(index, residue, segid, weight):
        line = f"ATOM  {index:5d}  P   {residue:3s} A   1       1.000   2.000   3.000  1.00{weight:6.2f}"
        return line.ljust(72) + segid.ljust(4) + "\n"

    original = (
        atom(1, "DA", "DNA", 1) + atom(2, "GRP", "GR00", 1) + atom(3, "DT", "DNA", 0)
    )
    (tmp_path / "anchors.pdb").write_text(original)
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "anchors": {
                    "mechanism": "harmonic_positional",
                    "force_constant_kcal_mol_A2": 0.1,
                },
                "graphene_nanopore": {"restraint_k_kcal_mol_A2": 50},
            }
        )
    )
    spec = SegmentSpec(
        name="prod",
        stage="production",
        percent=100,
        steps=1000,
        temp=300,
        damping=5,
        scale=None,
        npt=True,
        previous="relax",
    )
    conf = _conservative_production_conf(
        spec,
        "demo",
        (100, 100, 100),
        False,
        timestep_fs=4,
        anchors_file="anchors.pdb",
        package_dir=tmp_path,
        force_resident=True,
    )
    assert "GPUresident        on" in conf
    assert "fixedAtoms " not in conf
    assert "constraints        on" in conf
    assert "constraints        off" not in conf
    assert "timestep           4" in conf
    assert "langevinPistonPeriod  10000.0" in conf
    assert "langevinPistonDecay   5000.0" in conf
    assert "consref            restraints_production_anchors.pdb" in conf
    rows = (tmp_path / "restraints_production_anchors.pdb").read_text().splitlines()
    assert [float(row[60:66]) for row in rows] == [0.1, 50, 0]
    assert (tmp_path / "anchors.pdb").read_text() == original
    assert [row[30:54] for row in rows] == [row[30:54] for row in original.splitlines()]


def test_hard_anchor_default_and_replica_schema(tmp_path):
    (tmp_path / "manifest.json").write_text("{}")
    assert production_anchor_file(tmp_path, "anchors.pdb") == ("anchors.pdb", None)
    assert (
        harmonic_anchor_k(
            {
                "anchors": {
                    "mechanism": "harmonic restraints (constraints/consref/conskfile, conskcol B)",
                    "k_kcal_mol_a2": 0.1,
                }
            }
        )
        == 0.1
    )


@pytest.mark.parametrize(
    "metadata",
    [
        {"graphene_only": True},
        {"graphene_nanopore": {"control": "graphene_only"}},
        {"charge_audit": {"graphene_only": True}},
    ],
)
def test_graphene_only_production_keeps_nvt_even_for_legacy_manifest(
    tmp_path, metadata
):
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                **metadata,
                "solvation": {"npt_allowed": True},
            }
        )
    )
    assert package_npt_allowed(tmp_path) is False
