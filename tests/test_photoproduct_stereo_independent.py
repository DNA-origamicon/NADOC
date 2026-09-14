import hashlib
import json
from pathlib import Path

from backend.core.photoproduct_registry import photoproduct_registry
from backend.parameterization.photoproduct_stereo_independent import (
    audit_tt_cpd_stereo_with_openbabel,
)


def test_openbabel_stereo_audit_is_gate_neutral_and_hash_linked(tmp_path, monkeypatch):
    registry = photoproduct_registry()
    records = []
    candidate_results = []
    for index, entry in enumerate(registry["products"]):
        item_dir = tmp_path / entry["id"]
        item_dir.mkdir()
        sdf = item_dir / "candidate.sdf"
        sdf.write_text(f"candidate {index}\n")
        manifest = {
            "outputs": {
                "sdf": {
                    "path": str(sdf),
                    "sha256": hashlib.sha256(sdf.read_bytes()).hexdigest(),
                }
            }
        }
        manifest_path = item_dir / "candidate_manifest.json"
        manifest_path.write_text(json.dumps(manifest))
        digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        records.append(
            {"product_id": entry["id"], "manifest": str(manifest_path), "sha256": digest}
        )
        candidate_results.append(
            {"product_id": entry["id"], "manifest_sha256": digest, "passed": True}
        )
    series = {
        "schema": "nadoc.tt-cpd-stereo-candidate-series.v1",
        "records": records,
    }
    series_path = tmp_path / "series.json"
    series_path.write_text(json.dumps(series))
    candidate_audit = {
        "schema": "nadoc.tt-cpd-stereo-candidate-audit.v1",
        "status": "passed_candidate",
        "series_manifest": {
            "sha256": hashlib.sha256(series_path.read_bytes()).hexdigest()
        },
        "candidates": candidate_results,
    }
    candidate_audit_path = tmp_path / "candidate_audit.json"
    candidate_audit_path.write_text(json.dumps(candidate_audit))
    executable = tmp_path / "obabel"
    executable.write_text("fake")

    class Completed:
        returncode = 0
        stderr = ""

        def __init__(self, stdout):
            self.stdout = stdout

    def fake_run(command, **_kwargs):
        if command[-1] == "-V":
            return Completed("Open Babel 3.1.0\n")
        product_id = Path(command[1]).parent.name
        entry = next(item for item in registry["products"] if item["id"] == product_id)
        orientation = entry["structural_class"]["double_bond_orientation"]
        if command[-1] == "-ocan":
            return Completed(f"C[C@H]({orientation})N\t{product_id}\n")
        if orientation == "syn":
            stereo = {
                "tt-cpd-cis-syn": "AAAA",
                "tt-cpd-cis-syn-ii": "AAAA",
                "tt-cpd-trans-syn-i": "BBBB",
                "tt-cpd-trans-syn-ii": "CCCC",
            }[product_id]
            return Completed(f"SYNBLOCKABCDEF-{stereo}-N\n")
        stereo = {
            "tt-cpd-cis-anti-i": "DDDD",
            "tt-cpd-cis-anti-ii": "EEEE",
            "tt-cpd-trans-anti-i": "FFFF",
            "tt-cpd-trans-anti-ii": "GGGG",
        }[product_id]
        return Completed(f"ANTIBLOCKABCDE-{stereo}-N\n")

    monkeypatch.setattr("subprocess.run", fake_run)
    report = audit_tt_cpd_stereo_with_openbabel(
        series_manifest_path=series_path,
        candidate_audit_path=candidate_audit_path,
        openbabel_executable=executable,
        output_path=tmp_path / "report.json",
    )
    assert report["passed"] is True
    assert report["status"] == "software_crosscheck_passed_human_review_required"
    assert report["gate_effect"] == "none"
    assert len(report["records"]) == 8
