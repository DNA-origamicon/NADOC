"""Assess unchanged published-transfer charges at audited anti QM geometries."""

import json
from pathlib import Path
import sys
import numpy as np
from openmm import app

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_anti_additive.core_baseline import checked, source, write

ART = Path(".development-artifacts").resolve()
root = ART / "cpd-anti-charge-transfer-diagnostic-v1"
root.mkdir(exist_ok=False)
(root / "executed_source.py").write_text(Path(__file__).read_text())
records = []
for endpoint in (1, 2):
    folder = ART / f"cpd-anti-boundary-esp-v2/endpoint-{endpoint}"
    audit = json.loads((folder / "esp_audit.json").read_text())
    job = json.loads(checked(audit["job_manifest"]).read_text())
    assert audit["passed"] and audit["dipole"]["required"]
    xyz = checked(job["source_xyz"])
    x = np.array(
        [
            list(map(float, l.split()[1:]))
            for l in xyz.read_text().splitlines()[2:]
            if l.strip()
        ]
    )
    grid = np.loadtxt(checked(audit["grid"]))
    target = np.loadtxt(checked(audit["potentials"]))
    if target.ndim > 1:
        target = target[:, -1]
    base = (
        ART
        / (
            "cpd-anti-additive-boundary-baseline-v1"
            if endpoint == 1
            else "cpd-anti-additive-boundary-endpoint2-v1"
        )
        / f"endpoint-{endpoint}"
    )
    psf = app.CharmmPsfFile(str(base / "fragment.psf"))
    # Native psfgen atom names encode source manifest order.
    assert [a.name for a in psf.atom_list] == [f"A{i:03d}" for i in range(len(x))]
    charges = np.array([a.charge for a in psf.atom_list])
    assert abs(charges.sum()) < 1e-7
    distance = np.linalg.norm(grid[:, None, :] - x[None, :, :], axis=2)
    prediction = (0.529177210903 / distance) @ charges
    dipole = (charges[:, None] * x).sum(axis=0) / 0.529177210903
    qm = np.asarray(audit["dipole"]["vector"])
    error = prediction - target
    records.append(
        dict(
            endpoint=endpoint,
            net_charge=float(charges.sum()),
            esp_rmse_au=float(np.sqrt(np.mean(error**2))),
            esp_target_rms_au=float(np.sqrt(np.mean(target**2))),
            esp_relative_rmse=float(np.linalg.norm(error) / np.linalg.norm(target)),
            qm_dipole_au=qm.tolist(),
            mm_dipole_au=dipole.tolist(),
            dipole_vector_error_debye=float(np.linalg.norm(dipole - qm) * 2.541746473),
            dipole_angle_deg=float(
                np.degrees(
                    np.arccos(
                        np.clip(
                            np.dot(dipole, qm)
                            / np.linalg.norm(dipole)
                            / np.linalg.norm(qm),
                            -1,
                            1,
                        )
                    )
                )
            ),
            sources=[
                source(folder / "esp_audit.json"),
                source(base / "fragment.psf"),
                source(xyz),
            ],
        )
    )
write(
    root / "assessment.json",
    dict(
        records=records,
        simulation_ready=False,
        scope="Unfitted transfer diagnostic on two training geometries; no pass threshold or charge fitting; gas-phase HF dipole comparison without empirical scaling.",
    ),
)
print(json.dumps(records, indent=2))
