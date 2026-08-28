"""Deferred tests for the OL15/GBn2 production scaffold.

These were intentionally written but not executed while a NAMD production run
owns the GPU.  Only tests marked ``slow`` may create an OpenMM Context.
"""

from __future__ import annotations

import pytest

from backend.core.openmm_implicit import (
    FORCEFIELD_FILES,
    OpenMMImplicitProtocol,
    debye_kappa_per_nm,
    platform_properties,
)


def test_protocol_records_generic_150mm_salt_and_mixed_cuda():
    protocol = OpenMMImplicitProtocol()
    assert protocol.salt_molar == pytest.approx(0.150)
    assert protocol.platform == "CUDA"
    assert platform_properties(protocol) == {"Precision": "mixed", "DeviceIndex": "0"}
    assert debye_kappa_per_nm(protocol) == pytest.approx(0.9267, rel=1e-3)


def test_protocol_refuses_unvalidated_hmr_timestep_and_cpu_fallback():
    with pytest.raises(ValueError, match="HMR/4 fs"):
        OpenMMImplicitProtocol(timestep_fs=4.0)
    with pytest.raises(ValueError, match="CUDA-only"):
        OpenMMImplicitProtocol(platform="CPU")


def test_forcefield_does_not_request_nonexistent_top_level_ol15_file():
    assert FORCEFIELD_FILES == ("amber14-all.xml", "implicit/gbn2.xml")


def test_direct_topology_keeps_more_than_62_strands(monkeypatch):
    pytest.importorskip("openmm")
    from backend.core.atomistic import Atom, AtomisticModel
    from backend.core.openmm_implicit import build_openmm_topology

    atoms = []
    bonds = []
    for chain_index in range(63):
        chain_id = f"strand_{chain_index}"
        for seq_num in (1, 2):
            serial = len(atoms)
            atoms.append(
                Atom(
                    serial=serial,
                    name="C1'",
                    element="C",
                    residue="DA",
                    chain_id=chain_id,
                    seq_num=seq_num,
                    x=float(chain_index),
                    y=0.0,
                    z=float(seq_num),
                    strand_id=chain_id,
                    helix_id="h",
                    bp_index=seq_num,
                    direction="FORWARD",
                )
            )
        bonds.append((len(atoms) - 2, len(atoms) - 1))
    model = AtomisticModel(atoms=atoms, bonds=bonds)
    monkeypatch.setattr(
        "backend.core.atomistic.build_atomistic_model", lambda design: model
    )

    topology, positions, keys = build_openmm_topology(object())
    assert sum(1 for _ in topology.chains()) == 63
    assert sum(1 for _ in topology.bonds()) == 63
    assert len(positions) == len(keys) == 126


def test_direct_topology_groups_interleaved_crossover_chain_atoms(monkeypatch):
    pytest.importorskip("openmm")
    from backend.core.atomistic import Atom, AtomisticModel
    from backend.core.openmm_implicit import build_openmm_topology

    atoms = []
    # Geometric atom order revisits strand_a after strand_b, as crossover
    # designs do.  OpenMM must still receive one contiguous block per chain.
    for serial, (chain_id, seq_num) in enumerate(
        (("strand_a", 2), ("strand_b", 1), ("strand_a", 1), ("strand_b", 2))
    ):
        atoms.append(
            Atom(
                serial=serial,
                name="C1'",
                element="C",
                residue="DA",
                chain_id=chain_id,
                seq_num=seq_num,
                x=float(serial),
                y=0.0,
                z=0.0,
                strand_id=chain_id,
                helix_id="h",
                bp_index=seq_num,
                direction="FORWARD",
            )
        )
    monkeypatch.setattr(
        "backend.core.atomistic.build_atomistic_model",
        lambda design: AtomisticModel(atoms=atoms, bonds=[]),
    )

    topology, _, _ = build_openmm_topology(object())
    assert [[r.id for r in c.residues()] for c in topology.chains()] == [
        ["1", "2"],
        ["1", "2"],
    ]


@pytest.mark.slow
@pytest.mark.atomistic
def test_6hb_parameterizes_with_ol15_gbn2():
    """Future integration gate; parameterizes only and creates no Context."""
    pytest.importorskip("openmm")
    from backend.core.openmm_implicit import prepare_implicit_system
    from tests.conftest import make_6hb_design

    design = make_6hb_design(length_bp=21)
    prepared = prepare_implicit_system(design, OpenMMImplicitProtocol())
    assert prepared.n_strands == len(design.strands)
    assert prepared.n_atoms > prepared.n_heavy_atoms > 0
    assert prepared.net_charge_e < 0
