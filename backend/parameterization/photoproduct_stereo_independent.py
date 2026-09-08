"""Independent, gate-neutral Open Babel cross-checks for TT-CPD candidates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from backend.core.photoproduct_registry import photoproduct_registry


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _openbabel_value(executable: Path, sdf_path: Path, output_format: str) -> str:
    completed = subprocess.run(
        [str(executable), str(sdf_path), f"-o{output_format}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise ValueError(
            f"Open Babel {output_format} conversion failed for {sdf_path}: "
            f"{completed.stderr[-1000:].strip()}"
        )
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ValueError(
            f"Open Babel {output_format} conversion returned {len(lines)} records"
        )
    return lines[0].split()[0]


def audit_tt_cpd_stereo_with_openbabel(
    *,
    series_manifest_path: Path,
    candidate_audit_path: Path,
    openbabel_executable: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Cross-check all candidate stereographs with a separately installed toolkit.

    The result proves that Open Babel independently perceives stereochemistry and the
    expected two constitutional graphs. It deliberately cannot establish that a Roman
    numeral or ordered endpoint label was assigned correctly by the literature source.
    """

    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite Open Babel audit: {output_path}")
    executable = openbabel_executable.resolve()
    if not executable.is_file():
        raise ValueError(f"Open Babel executable not found: {executable}")
    version_run = subprocess.run(
        [str(executable), "-V"],
        check=False,
        capture_output=True,
        text=True,
    )
    version = (version_run.stdout or version_run.stderr).strip()
    if version_run.returncode != 0 or "Open Babel" not in version:
        raise ValueError(f"executable is not a working Open Babel CLI: {executable}")

    series = json.loads(series_manifest_path.read_text())
    candidate_audit = json.loads(candidate_audit_path.read_text())
    if (
        series.get("schema") != "nadoc.tt-cpd-stereo-candidate-series.v1"
        or candidate_audit.get("schema")
        != "nadoc.tt-cpd-stereo-candidate-audit.v1"
        or candidate_audit.get("status") != "passed_candidate"
        or (candidate_audit.get("series_manifest") or {}).get("sha256")
        != _sha256(series_manifest_path)
    ):
        raise ValueError("Open Babel audit requires the passed hash-linked candidate audit")
    passed_candidates = {
        item.get("product_id"): item
        for item in candidate_audit.get("candidates") or []
        if item.get("passed") is True
    }

    registry = photoproduct_registry()
    entries = {
        item["id"]: item
        for item in registry["products"]
        if item["product"] == "TT-CPD"
    }
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    for source_record in series.get("records") or []:
        product_id = source_record.get("product_id")
        manifest_path = Path(str(source_record.get("manifest") or ""))
        if (
            product_id not in entries
            or not manifest_path.is_file()
            or _sha256(manifest_path) != source_record.get("sha256")
            or (passed_candidates.get(product_id) or {}).get("manifest_sha256")
            != source_record.get("sha256")
        ):
            errors.append(
                f"{product_id}: candidate manifest is unavailable, changed, or not passed"
            )
            continue
        manifest = json.loads(manifest_path.read_text())
        sdf_record = (manifest.get("outputs") or {}).get("sdf") or {}
        sdf_path = Path(str(sdf_record.get("path") or ""))
        if not sdf_path.is_file() or _sha256(sdf_path) != sdf_record.get("sha256"):
            errors.append(f"{product_id}: candidate SDF is unavailable or changed")
            continue
        canonical_smiles = _openbabel_value(executable, sdf_path, "can")
        inchikey = _openbabel_value(executable, sdf_path, "inchikey")
        if "@" not in canonical_smiles or len(inchikey.split("-", 1)[0]) != 14:
            errors.append(f"{product_id}: Open Babel did not preserve stereochemistry")
        records.append(
            {
                "product_id": product_id,
                "orientation": entries[product_id]["structural_class"][
                    "double_bond_orientation"
                ],
                "sdf_sha256": _sha256(sdf_path),
                "canonical_isomeric_smiles": canonical_smiles,
                "inchikey": inchikey,
                "constitutional_inchikey_block": inchikey.split("-", 1)[0],
            }
        )

    by_id = {item["product_id"]: item for item in records}
    if set(by_id) != set(entries):
        errors.append("Open Babel results do not cover all eight registered TT-CPDs")
    orientation_blocks: dict[str, set[str]] = {"syn": set(), "anti": set()}
    for record in records:
        orientation_blocks[record["orientation"]].add(
            record["constitutional_inchikey_block"]
        )
    if any(len(blocks) != 1 for blocks in orientation_blocks.values()):
        errors.append("candidates do not form one constitutional graph per syn/anti class")
    if orientation_blocks["syn"] & orientation_blocks["anti"]:
        errors.append("Open Babel does not distinguish syn and anti constitutional graphs")
    if set(by_id) == set(entries):
        if by_id["tt-cpd-cis-syn"]["inchikey"] != by_id[
            "tt-cpd-cis-syn-ii"
        ]["inchikey"]:
            errors.append(
                "identically capped cis-syn I/II candidates do not collapse by symmetry"
            )
        if by_id["tt-cpd-trans-anti-i"]["inchikey"] == by_id[
            "tt-cpd-trans-anti-ii"
        ]["inchikey"]:
            errors.append(
                "trans-anti I/II candidates unexpectedly collapse to one stereochemical identifier"
            )

    passed = not errors
    report = {
        "schema": "nadoc.tt-cpd-openbabel-stereo-audit.v1",
        "status": "software_crosscheck_passed_human_review_required" if passed else "failed",
        "passed": passed,
        "gate_effect": "none",
        "series_manifest": {
            "path": str(series_manifest_path.resolve()),
            "sha256": _sha256(series_manifest_path),
        },
        "candidate_audit": {
            "path": str(candidate_audit_path.resolve()),
            "sha256": _sha256(candidate_audit_path),
        },
        "engine": {
            "path": str(executable),
            "sha256": _sha256(executable),
            "version_output": version,
        },
        "orientation_constitutional_blocks": {
            key: sorted(value) for key, value in orientation_blocks.items()
        },
        "records": sorted(records, key=lambda item: item["product_id"]),
        "errors": errors,
        "limitations": [
            "canonical identifiers do not validate the literature Roman-numeral mapping",
            "ordered DNA endpoints collapse when their model caps are constitutionally identical",
            "human atom-mapped review of all four stereocenters remains required",
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report
