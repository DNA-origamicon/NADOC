from __future__ import annotations

import hashlib

from backend.core.atomistic import Atom, AtomisticModel
from backend.core.models import Design, PhotoproductJunction
from backend.core.namd_topology import _psfgen_script, photoproduct_patch_plan


def _atom(serial, name, *, chain, seq, helix, bp, direction, crossover=None, k=None):
    return Atom(
        serial=serial,
        name=name,
        element="C",
        residue="DT",
        chain_id=chain,
        seq_num=seq,
        x=float(serial),
        y=0.0,
        z=0.0,
        strand_id=chain,
        helix_id=helix,
        bp_index=bp,
        direction=direction,
        crossover_id=crossover,
        extra_base_k=k,
    )


def test_patch_plan_derives_psf_identity_from_ordinary_and_extra_provenance(tmp_path):
    topology = tmp_path / "tt_cpd.str"
    topology.write_text("* test topology\n")
    topology_hash = hashlib.sha256(topology.read_bytes()).hexdigest()
    registry = {
        "products": [
            {
                "id": "tt-cpd-cis-syn",
                "product": "TT-CPD",
                "stereochemistry": "cis-syn",
                "assets": {
                    "topology": {
                        "path": topology.name,
                        "sha256": topology_hash,
                        "patch_name": "TCPD",
                    }
                },
            }
        ]
    }
    ordinary_key = "helix:with:colons:4:FORWARD"
    extra_key = "__xb__:crossover:with:colons:1"
    design = Design(
        photoproduct_junctions=[
            PhotoproductJunction(
                id="lesion-1",
                base_key_1=ordinary_key,
                base_key_2=extra_key,
            )
        ]
    )
    model = AtomisticModel(
        atoms=[
            _atom(
                0,
                "C5",
                chain="A",
                seq=7,
                helix="helix:with:colons",
                bp=4,
                direction="FORWARD",
            ),
            _atom(
                1,
                "C5",
                chain="B",
                seq=12,
                helix="source",
                bp=9,
                direction="REVERSE",
                crossover="crossover:with:colons",
                k=1,
            ),
        ],
        bonds=[],
    )
    segments = [
        {"chain_id": "A", "segid": "D000"},
        {"chain_id": "B", "segid": "D001"},
    ]
    plan = photoproduct_patch_plan(
        design,
        model,
        segments,
        registry=registry,
        registry_root=tmp_path,
    )
    assert plan["topology_paths"] == [topology]
    assert plan["patches"][0]["endpoints"] == [
        {
            "endpoint": 1,
            "base_key": ordinary_key,
            "segid": "D000",
            "resid": 7,
        },
        {
            "endpoint": 2,
            "base_key": extra_key,
            "segid": "D001",
            "resid": 12,
        },
    ]
    assert {item["base_key"] for item in plan["reverse_identity"]} == {
        ordinary_key,
        extra_key,
    }

    script = _psfgen_script(
        [],
        tmp_path / "output",
        extra_topologies=plan["topology_paths"],
        photoproduct_patches=plan["patches"],
    )
    assert f"topology {topology}" in script
    assert "patch TCPD D000:7 D001:12" in script
    assert script.index("patch TCPD") < script.index("regenerate angles dihedrals")
