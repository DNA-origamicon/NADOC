"""Freeze new perturbation positions without inspecting their QM target values."""

import argparse
import importlib.util
import json
from pathlib import Path
import re
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import EVIDENCE, source, write


def main(root):
    root.mkdir(parents=True, exist_ok=False)
    old = EVIDENCE / "alpine-qm-cpd-drude-perturbed-esp-v2"
    recovery = Path(".development-artifacts/cpd-drude-anti-graph-recovery-v1").resolve()
    spec = importlib.util.spec_from_file_location(
        "old_surface_geometry", old / "prepare_campaign.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    xyz = (
        EVIDENCE
        / "tt-cpd-work-v1-completions/qm/stereo-frequencies/tt-cpd-cis-anti-i/provenance/source_geometry.xyz"
    )
    assert source(xyz)["sha256"] == module.EXPECTED_XYZ_SHA256
    atoms = module.parse_xyz(xyz)
    historical = json.loads((old / "bundle/shared/design.json").read_text())
    template = (old / "bundle/cases/case-001/input.dat").read_text()
    cases = []
    for scale, count in [(2.2, 16), (4.0, 8)]:
        candidates = module.accessible_surface(atoms, scale, 384)
        anchors = np.array(
            [
                c["position_angstrom"]
                for c in historical["cases"]
                if c.get("surface_scale") == scale
            ]
        )
        distances = np.linalg.norm(
            candidates[:, None, :] - anchors[None, :, :], axis=2
        ).min(axis=1)
        for _ in range(count):
            i = int(np.argmax(distances))
            point = candidates[i]
            if distances[i] < 0.5:
                raise ValueError("Insufficiently separated novel perturbations")
            cases.append(
                {
                    "case_id": len(cases) + 1,
                    "partition": "fresh_external_validation",
                    "surface_scale": scale,
                    "position_angstrom": point.tolist(),
                    "minimum_distance_to_historical_angstrom": float(
                        np.linalg.norm(anchors - point, axis=1).min()
                    ),
                }
            )
            distances = np.minimum(
                distances, np.linalg.norm(candidates - point, axis=1)
            )
            distances[i] = -1
    for case in [{"case_id": 0, "partition": "local_portability_reference"}, *cases]:
        folder = root / f"case-{case['case_id']:03d}"
        folder.mkdir()
        (folder / "scratch").mkdir()
        text = (
            (old / "bundle/cases/case-000/input.dat").read_text()
            if case["case_id"] == 0
            else template
        )
        text = text.replace("memory 32 GB", "memory 10 GB").replace(
            "set_num_threads(16)", "set_num_threads(8)"
        )
        if case["case_id"]:
            x, y, z = case["position_angstrom"]
            text = re.sub(
                r"external_potentials = np.array\(.*",
                f"external_potentials = np.array([[0.5, {x:.12f}, {y:.12f}, {z:.12f}]], dtype=float)",
                text,
            )
            text = re.sub(
                r"print_out\('NADOC_PERTURBATION.*",
                f"print_out('NADOC_FRESH_CASE {case['case_id']}\\\\n')",
                text,
            )
        (folder / "input.dat").write_text(text)
        (folder / "grid.dat").write_bytes(
            (old / "bundle/cases/case-000/grid.dat").read_bytes()
        )
        case["input"] = source(folder / "input.dat")
    policy = json.loads((recovery / "policy.json").read_text())
    write(
        root / "plan.json",
        {
            "schema": "nadoc.cpd-fresh-esp.v1",
            "simulation_ready": False,
            "gate_effect": "none",
            "role": "Fresh perturbation positions on the same capped anti-CPD geometry; not conformational or nucleotide validation",
            "selection": "384 directions per atom; same exposed scaled-Bondi algorithm, maximin against all prior positions and newly selected points; 16 near and 8 far",
            "cases": cases,
            "frozen_parameters": source(
                recovery / "corrected_parameters.training_frozen.json"
            ),
            "acceptance": policy["acceptance"],
            "bounds": policy["bounds"],
            "geometry": source(xyz),
            "surface_generator": source(old / "prepare_campaign.py"),
            "template": source(old / "bundle/cases/case-001/input.dat"),
            "historical_design": source(old / "bundle/shared/design.json"),
            "baseline_reference_esp": source(
                old / "bundle/cases/case-000/grid_esp.dat"
            ),
            "baseline_reference_audit": source(
                old / "bundle/cases/case-000/case_audit.json"
            ),
            "portability_esp_rms_limit_au": 1e-7,
            "portability_dipole_vector_limit_au": 1e-6,
            "no_parameter_changes_after_target_inspection": True,
        },
    )
    print(
        "Prepared",
        len(cases),
        "fresh perturbations; minimum historical separation",
        min(c["minimum_distance_to_historical_angstrom"] for c in cases),
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True, type=Path)
    main(p.parse_args().root.resolve())
