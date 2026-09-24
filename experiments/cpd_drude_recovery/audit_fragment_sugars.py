"""Check archived optimized sugar fragments against native source handedness."""

import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.audit_boundary_seeds import read_outputs, volume
from experiments.cpd_drude_recovery.campaign import source, checked, write
from backend.parameterization.photoproduct_qm import parse_xyz

root = Path(".development-artifacts/cpd-primary-fragment-sugar-reaudit-v1").resolve()
root.mkdir(exist_ok=False)
(root / "source_snapshot.py").write_text(Path(__file__).read_text())
campaign = Path(
    "/media/jojo/Archive/NADOC_archive/photoproduct_evidence/tt-cpd-local-fragment-campaign-v1/cases"
)
records = []
for family in ("syn", "anti"):
    for endpoint in (1, 2):
        folder = campaign / f"{family}-primary-endpoint-{endpoint}"
        case_path = folder / "case_manifest.json"
        case = json.loads(case_path.read_text())
        model_path = checked(case["model_manifest"])
        model = json.loads(model_path.read_text())
        names = model["atom_map"]
        audit_path = folder / "job/optimized_model_audit.json"
        audit = json.loads(audit_path.read_text())
        xyz_path = checked(audit["optimized_xyz"])
        xyz = np.array([a[1:] for a in parse_xyz(xyz_path.read_text())[0]])
        boundary_path = checked(case["source_boundary_manifest"])
        boundary = json.loads(boundary_path.read_text())
        ref_record = boundary.get("source_selection", {}).get("reference_manifest")
        ref_path = checked(ref_record) if ref_record else boundary_path
        ref = json.loads(ref_path.read_text())
        paths, refnames, refxyz, _, _ = read_outputs(ref_path, ref)
        centers = []
        for center, local in [
            ("C1'", ["O4'", "C2'", "N1", "H1'"]),
            ("C3'", ["C2'", "C4'", "O3'", "H3'"]),
            ("C4'", ["O4'", "C3'", "C5'", "H4'"]),
        ]:
            ordered = [f"{endpoint}:{n}" for n in local]
            before = volume(refxyz, refnames, ordered)
            after = volume(xyz, names, ordered)
            centers.append(
                {
                    "center": f"{endpoint}:{center}",
                    "reference_volume": before,
                    "optimized_volume": after,
                    "preserved": bool(np.sign(before) == np.sign(after)),
                }
            )
        records.append(
            {
                "case_id": case["id"],
                "product_id": case["product_id"],
                "all_sugar_centers_preserved": all(c["preserved"] for c in centers),
                "centers": centers,
                "sources": [
                    source(p)
                    for p in (
                        case_path,
                        model_path,
                        audit_path,
                        xyz_path,
                        boundary_path,
                        ref_path,
                        *paths.values(),
                    )
                ],
            }
        )
write(
    root / "assessment.json",
    {
        "simulation_ready": False,
        "gate_effect": "none",
        "scope": "Native-source sugar handedness check, not inherited candidate-continuity check. A frequency minimum cannot validate the wrong stereoisomer.",
        "records": records,
        "script": source(root / "source_snapshot.py"),
    },
)
for r in records:
    print(
        r["case_id"],
        "preserved",
        r["all_sugar_centers_preserved"],
        "inverted",
        [c["center"] for c in r["centers"] if not c["preserved"]],
    )
