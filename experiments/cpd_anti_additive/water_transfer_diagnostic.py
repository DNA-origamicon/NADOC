"""Evaluate unchanged additive transfer against audited anti water curves."""

import json
from pathlib import Path
import sys
import warnings
import numpy as np
from openmm import app

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_anti_additive.core_baseline import checked, source, write
from experiments.cpd_published_comparator.reconstruct import BASE, FF
from backend.parameterization.photoproduct_qm import parse_xyz
from backend.parameterization.photoproduct_nonbonded_fit import (
    _interaction_row,
    _quadratic_grid_minimum,
)

ART = Path(".development-artifacts").resolve()


def load_cases():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        params = app.CharmmParameterSet(
            str(BASE / "top_all36_na.rtf"),
            str(BASE / "par_all36_na.prm"),
            str(FF / "top_all36_cgenff.rtf"),
            str(FF / "par_all36_cgenff.prm"),
            str(ART / "cpd-published-comparator-v1/comparator_last.prm"),
        )
    nb = {
        k: dict(epsilon_kcal_mol=v.epsilon, rmin_half_angstrom=v.rmin)
        for k, v in params.atom_types_str.items()
    }
    curves = json.loads((ART / "cpd-anti-water-curves-v2/assessment.json").read_text())[
        "records"
    ]
    cases = []
    for e in (1, 2):
        ep = ART / f"cpd-anti-boundary-esp-v2/endpoint-{e}"
        esp = json.loads((ep / "esp_audit.json").read_text())
        job = json.loads(checked(esp["job_manifest"]).read_text())
        atoms, _ = parse_xyz(checked(job["source_xyz"]).read_text())
        x = np.array([a[1:] for a in atoms])
        names = job["atom_map"]
        base = (
            ART
            / (
                "cpd-anti-additive-boundary-baseline-v1"
                if e == 1
                else "cpd-anti-additive-boundary-endpoint2-v1"
            )
            / f"endpoint-{e}"
        )
        psf = app.CharmmPsfFile(str(base / "fragment.psf"))
        assert [a.name for a in psf.atom_list] == [f"A{i:03d}" for i in range(len(x))]
        charges = np.array([a.charge for a in psf.atom_list])
        lj = [nb[a.attype] for a in psf.atom_list]
        for a in psf.atom_list:
            for w in ["OGTIP3", "HGTIP3"]:
                assert (a.attype, w) not in params.nbfix_types and (
                    w,
                    a.attype,
                ) not in params.nbfix_types, (
                    "Pair-specific LJ needs explicit evaluation"
                )
        rows = []
        for curve in curves:
            if curve["identity"]["model_id"] != job["model_id"]:
                continue
            assert curve["passed"]
            points = []
            for point in curve["points"]:
                folder = Path(point["job_dir"])
                jp = folder / "job_manifest.json"
                assert source(jp)["sha256"] == point["job_manifest_sha256"]
                j = json.loads(jp.read_text())
                assert j["source_xyz"]["sha256"] == job["source_xyz"]["sha256"]
                water, _ = parse_xyz(checked(j["water_xyz"]).read_text())
                row, le = _interaction_row(x, lj, np.array([a[1:] for a in water]), nb)
                wxyz = np.array([a[1:] for a in water])
                probe_index = {"O": 0, "H1": 1, "H2": 2}[j["probe_atom"]]
                axis = wxyz[probe_index] - x[names.index(j["target_atom"])]
                shifted = wxyz - 0.2 * axis / np.linalg.norm(axis)
                offset_row, offset_lj = _interaction_row(x, lj, shifted, nb)
                points.append(
                    dict(
                        distance=point["distance_angstrom"],
                        offset_row=offset_row,
                        offset_lj=offset_lj,
                        row=row,
                        lj=le,
                        target=point["scaled_target_kcal_mol"],
                    )
                )
            rows.append(dict(site=curve["identity"]["probe_id"], points=points))
        cases.append(
            dict(
                endpoint=e,
                names=names,
                xyz=x,
                charges=charges,
                curves=rows,
                esp=esp,
                psf_source=source(base / "fragment.psf"),
            )
        )
    return cases


def metrics(c, charges):
    results = []
    for curve in c["curves"]:
        points = curve["points"]
        ds = np.array([p["distance"] for p in points])
        qm = np.array([p["target"] for p in points])
        mm = np.array([p["row"] @ charges + p["lj"] for p in points])
        qd, qe = _quadratic_grid_minimum(ds, qm)
        md, me = _quadratic_grid_minimum(ds, mm)
        results.append(
            dict(
                endpoint=c["endpoint"],
                site=curve["site"],
                qm_scaled_minimum_kcal_mol=qe,
                mm_minimum_kcal_mol=me,
                energy_error_kcal_mol=me - qe,
                qm_offset_distance_A=qd - 0.2,
                mm_minimum_distance_A=md,
                distance_error_A=md - (qd - 0.2),
                mm_minimum_bracketed=bool(0 < int(np.argmin(mm)) < len(mm) - 1),
                distances_A=ds.tolist(),
                qm_scaled_curve_kcal_mol=qm.tolist(),
                mm_curve_kcal_mol=mm.tolist(),
            )
        )
    return results


if __name__ == "__main__":
    root = ART / "cpd-anti-water-transfer-diagnostic-v1"
    root.mkdir(exist_ok=False)
    (root / "executed_source.py").write_text(Path(__file__).read_text())
    cases = load_cases()
    records = [r for c in cases for r in metrics(c, c["charges"])]
    write(
        root / "assessment.json",
        dict(
            records=records,
            simulation_ready=False,
            scope="Unchanged additive baseline; CHARMM TIP3P including H LJ; QM energies scaled1.16 and minima offset -0.2 A, local three-point parabolic interpolation; no charge fit or acceptance claim",
            sources=[source(ART / "cpd-anti-water-curves-v2/assessment.json")]
            + [c["psf_source"] for c in cases],
        ),
    )
    print(
        [
            (
                r["endpoint"],
                r["site"],
                round(r["energy_error_kcal_mol"], 3),
                round(r["distance_error_A"], 3),
                r["mm_minimum_bracketed"],
            )
            for r in records
        ]
    )
