import hashlib
import json

import numpy as np
import pytest

from backend.core.dcd_fast import write_trajectory
from backend.parameterization.photoproduct_help_trajectory import (
    build_photoproduct_help_trajectory,
)


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evidence(
    tmp_path, *, product_id="tt-cpd-cis-syn", omit_crosslink=False
):
    psf = tmp_path / "product.psf"
    anti = "-anti-" in product_id
    pairs = [(1, 2), (3, 4), (1, 4) if anti else (1, 3)]
    if not omit_crosslink:
        pairs.append((2, 3) if anti else (2, 4))
    indices = " ".join(str(value) for pair in pairs for value in pair)
    psf.write_text(
        "PSF\n\n       4 !NATOM\n"
        "       1 D000 1 THY C5 CPT1 0.000000 12.011\n"
        "       2 D000 1 THY C6 CPT2 0.000000 12.011\n"
        "       3 D001 2 THY C5 CPT1 0.000000 12.011\n"
        "       4 D001 2 THY C6 CPT2 0.000000 12.011\n\n"
        f"       {len(pairs)} !NBOND: bonds\n{indices}\n"
    )
    dcd = tmp_path / "smoke.dcd"
    frames = [
        np.asarray(
            [[0, 0, 0], [1, 0, 0], [0, 1 + index * 0.01, 0], [1, 1, 0]],
            dtype=float,
        )
        for index in range(5)
    ]
    write_trajectory(
        dcd,
        4,
        frames,
        5,
        nsavc=10,
        delta=0.002 / 0.04888821,
    )
    parameter = tmp_path / "product.prm"
    parameter.write_text("BONDS\n")
    static = tmp_path / "static.json"
    static.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-static-topology-audit.v1",
                "status": "passed",
                "passed": True,
                "lesions": [
                    {
                        "product_id": product_id,
                        "endpoints": [
                            {"endpoint": 1, "segid": "D000", "resid": 1},
                            {"endpoint": 2, "segid": "D001", "resid": 2},
                        ],
                    }
                ],
            }
        )
    )
    smoke = tmp_path / "smoke.json"
    smoke.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-namd-smoke.v1",
                "status": "passed",
                "passed": True,
                "product_ids": [product_id],
                "psf_sha256": _sha(psf),
                "dcd_sha256": _sha(dcd),
                "parameters_sha256": _sha(parameter),
                "static_topology_audit_sha256": _sha(static),
                "timestep_fs": 2.0,
                "hmr": False,
                "engine": {"name": "NAMD", "version": "3.0.2"},
            }
        )
    )
    return dcd, psf, parameter, static, smoke


def test_help_trajectory_uses_only_real_dcd_frames_and_audited_psf(tmp_path):
    dcd, psf, parameter, static, smoke = _evidence(tmp_path)
    payload = build_photoproduct_help_trajectory(
        product_id="tt-cpd-cis-syn",
        dcd_path=dcd,
        psf_path=psf,
        parameter_path=parameter,
        static_topology_audit_path=static,
        namd_smoke_report_path=smoke,
        output_path=tmp_path / "help.json",
        max_frames=3,
    )
    assert payload["source_frame_indices"] == [0, 2, 4]
    assert payload["stride_steps"] == 20
    assert payload["atom_keys"] == ["1:C5", "1:C6", "2:C5", "2:C6"]
    assert len(payload["frames"]) == 3
    assert payload["provenance"]["source_dcd_sha256"] == _sha(dcd)


def test_help_trajectory_rejects_bonds_only_or_wrong_isomer_psf(tmp_path):
    dcd, psf, parameter, static, smoke = _evidence(
        tmp_path, omit_crosslink=True
    )
    with pytest.raises(ValueError, match="lacks.*crosslinks"):
        build_photoproduct_help_trajectory(
            product_id="tt-cpd-cis-syn",
            dcd_path=dcd,
            psf_path=psf,
            parameter_path=parameter,
            static_topology_audit_path=static,
            namd_smoke_report_path=smoke,
            output_path=tmp_path / "help.json",
        )


def test_help_trajectory_accepts_audited_head_to_tail_anti_crosslinks(tmp_path):
    product_id = "tt-cpd-trans-anti-i"
    dcd, psf, parameter, static, smoke = _evidence(
        tmp_path, product_id=product_id
    )
    payload = build_photoproduct_help_trajectory(
        product_id=product_id,
        dcd_path=dcd,
        psf_path=psf,
        parameter_path=parameter,
        static_topology_audit_path=static,
        namd_smoke_report_path=smoke,
        output_path=tmp_path / "anti-help.json",
    )
    keyed_bonds = {
        frozenset((payload["atom_keys"][first], payload["atom_keys"][second]))
        for first, second in payload["bonds"]
    }
    assert frozenset(("1:C5", "2:C6")) in keyed_bonds
    assert frozenset(("1:C6", "2:C5")) in keyed_bonds
