import json
from pathlib import Path

from scripts.run_photoproduct_response_queue import _passed


def test_queue_accepts_only_matching_passed_batch(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    payload = {
        "schema": "nadoc.photoproduct-local-fixed-hessian-batch.v1",
        "status": "passed",
        "product_id": "tt-cpd-trans-syn-i",
        "conformer_id": "conformer-001",
    }
    report.write_text(json.dumps(payload) + "\n")

    assert _passed(report, "tt-cpd-trans-syn-i", "001")
    assert not _passed(report, "tt-cpd-trans-syn-ii", "001")
    assert not _passed(report, "tt-cpd-trans-syn-i", "002")

    payload["status"] = "failed"
    report.write_text(json.dumps(payload) + "\n")
    assert not _passed(report, "tt-cpd-trans-syn-i", "001")
