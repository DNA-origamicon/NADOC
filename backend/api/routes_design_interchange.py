"""PDB import and file interchange routes for active designs."""

import asyncio
import os
import time
import uuid
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from backend.api import state as design_state
from backend.api.crud import (
    _design_for_export,
    _design_response,
    _export_filename_stem,
)

router = APIRouter()

MAX_PDB_INPUT_BYTES = 50 * 1024 * 1024
MAX_PROTEIN_ATOMS = 250_000


class FilePathRequest(BaseModel):
    path: str


class PdbImportRequest(BaseModel):
    content: str  # raw PDB file text sent by the browser
    merge: bool = False  # if True, add to existing design instead of replacing


@router.post("/design/import/pdb", status_code=200)
def import_pdb_design(body: PdbImportRequest) -> dict:
    """Import a PDB file containing DNA, converting it to a NADOC Design.

    Non-DNA atoms (water, ions, protein) are removed.  Each duplex in the
    PDB becomes a helix with two strands.  The import is placed in its own
    cluster so it can be moved independently.

    When ``merge`` is True and a design already exists, the PDB helices and
    strands are added to the existing design as a new cluster.  Otherwise a
    fresh design is created.
    """
    from backend.core.pdb_to_design import import_pdb, merge_pdb_into_design
    from backend.core.validator import validate_design

    existing = design_state.get_design() if body.merge else None

    try:
        if existing and existing.helices:
            design, pdb_atomistic, import_warnings = merge_pdb_into_design(
                existing, body.content
            )
        else:
            design, pdb_atomistic, import_warnings = import_pdb(body.content)
    except Exception as exc:
        raise HTTPException(400, detail=f"PDB import failed: {exc}") from exc

    design_state.clear_history()
    design_state.set_design(design)
    design_state.set_pdb_atomistic(pdb_atomistic)
    report = validate_design(design)
    # New lineage — nothing in the client's cache matches this design's history.
    resp = _design_response(design, report, full_feature_log=True)
    if import_warnings:
        resp["import_warnings"] = import_warnings
    return resp


def _download_rcsb_pdb(pdb_id: str) -> str:
    """Download a structure from the RCSB Protein Data Bank by 4-char ID.

    Fetches the legacy ``.pdb`` format server-side (avoids browser CORS).  Some
    very large/modern entries are deposited only as mmCIF and 404 here.
    """
    import re
    import urllib.error
    import urllib.request

    pid = pdb_id.strip().upper()
    if not re.fullmatch(r"[0-9A-Z]{4}", pid):
        raise HTTPException(
            400, detail="PDB ID must be 4 alphanumeric characters (e.g. 1BNA)."
        )
    url = f"https://files.rcsb.org/download/{pid}.pdb"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310 (fixed host)
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise HTTPException(
                404,
                detail=f"PDB {pid} not found in RCSB as .pdb (it may be mmCIF-only).",
            ) from exc
        raise HTTPException(502, detail=f"RCSB download failed ({exc.code}).") from exc
    except Exception as exc:
        raise HTTPException(502, detail=f"RCSB download failed: {exc}") from exc


class PdbAutoImportRequest(BaseModel):
    content: Optional[str] = None  # raw PDB text (file import)
    pdb_id: Optional[str] = None  # 4-char RCSB id (download)
    name: str = ""
    # None = undecided (ask the user when the structure has both protein + DNA);
    # True/False = remove (or keep) DNA in the imported protein object.
    remove_dna_from_protein: Optional[bool] = None
    protein_placement: Literal["free", "library"] = "free"
    operation_id: Optional[str] = None
    expected_revision: Optional[int] = None


@router.post("/design/import/pdb-auto", status_code=200)
async def import_pdb_auto(body: PdbAutoImportRequest, request: Request) -> dict:
    """Unified PDB import: download by RCSB id or accept file content, then
    route by residue content.

    * Protein present → imported as a free-standing, movable protein object
      (embedded in the design, logged in the feature log).  If DNA is ALSO
      present and ``remove_dna_from_protein`` is undecided, returns
      ``needs_dna_decision`` (with the resolved ``content``) instead of
      importing, so the UI can ask whether to strip the DNA.
    * DNA only → imported as a design (the classic PDB-as-design path).
    """
    started = time.perf_counter()
    operation_id = body.operation_id or str(uuid.uuid4())
    stages_ms: dict[str, float] = {}

    from backend.core.pdb_to_design import import_pdb, merge_pdb_into_design
    from backend.core.protein import (
        classify_pdb_content,
        parse_protein_pdb,
        protein_asset_fingerprint,
    )
    from backend.core.validator import validate_design

    if body.pdb_id:
        content = await asyncio.to_thread(_download_rcsb_pdb, body.pdb_id)
        name = body.name or body.pdb_id.strip().upper()
        source = f"rcsb:{body.pdb_id.strip().upper()}"
    elif body.content:
        content = body.content
        name = body.name or "structure"
        source = "file"
    else:
        raise HTTPException(400, detail="Provide either pdb_id or content.")
    input_bytes = len(content.encode("utf-8"))
    if input_bytes > MAX_PDB_INPUT_BYTES:
        raise HTTPException(
            413,
            detail=(
                f"PDB input is {input_bytes} bytes; maximum is "
                f"{MAX_PDB_INPUT_BYTES} bytes."
            ),
        )
    stages_ms["acquire"] = (time.perf_counter() - started) * 1000.0

    stage_started = time.perf_counter()
    has_dna, has_protein = await asyncio.to_thread(classify_pdb_content, content)
    stages_ms["classify"] = (time.perf_counter() - stage_started) * 1000.0
    if not has_dna and not has_protein:
        raise HTTPException(400, detail="No DNA or protein residues found in the PDB.")

    resp: dict = {
        "imported": {"dna": False, "protein": False},
        "source": source,
        "name": name,
        "protein_placement": body.protein_placement,
    }

    if has_protein:
        # Ask before stripping DNA from a protein-DNA complex.
        if has_dna and body.remove_dna_from_protein is None:
            # A downloaded RCSB structure can be fetched again after the user
            # chooses Remove/Keep DNA. Do not echo a potentially multi-megabyte
            # PDB through the browser and ask it to upload the same text back.
            # Local-file imports still need the resolved content for step two.
            decision_source = (
                {"pdb_id": body.pdb_id.strip().upper()}
                if body.pdb_id
                else {"content": content}
            )
            return {
                **resp,
                "needs_dna_decision": True,
                "has_dna": True,
                "has_protein": True,
                # Pin the follow-up mutation to the design version inspected
                # for this decision. A tab's local watermark can lag behind a
                # background save, which made the choice fail with a 409.
                "revision": design_state.revision(),
                **decision_source,
                "process_metrics": _import_process_metrics(
                    operation_id, started, stages_ms, "needs_dna_decision"
                ),
            }
        exclude_dna = bool(body.remove_dna_from_protein)
        try:
            stage_started = time.perf_counter()
            asset = await asyncio.to_thread(
                parse_protein_pdb,
                content,
                name=name,
                source_filename=name,
                exclude_dna=exclude_dna,
            )
        except Exception as exc:
            raise HTTPException(
                400, detail=f"Protein PDB import failed: {exc}"
            ) from exc
        if not asset.atoms:
            raise HTTPException(400, detail="No protein atoms found after parsing.")
        if len(asset.atoms) > MAX_PROTEIN_ATOMS:
            raise HTTPException(
                413,
                detail=(
                    f"Protein has {len(asset.atoms)} atoms; maximum is "
                    f"{MAX_PROTEIN_ATOMS}."
                ),
            )
        stages_ms["parse_protein"] = (time.perf_counter() - stage_started) * 1000.0
        stage_started = time.perf_counter()
        fingerprint = await asyncio.to_thread(protein_asset_fingerprint, asset)
        active = design_state.get_design()
        known_assets = [*design_state.list_protein_assets()]
        if active is not None:
            known_assets.extend(active.protein_assets)
        existing_asset = next(
            (
                known
                for known in known_assets
                if (
                    known.metadata.get("structure_fingerprint")
                    or protein_asset_fingerprint(known)
                )
                == fingerprint
            ),
            None,
        )
        duplicate_detected = existing_asset is not None
        deduplicated = existing_asset is not None and body.protein_placement == "library"
        if deduplicated:
            asset = existing_asset
        stages_ms["deduplicate"] = (time.perf_counter() - stage_started) * 1000.0
        stage_started = time.perf_counter()
        await _reject_disconnected_import(request, operation_id, started, stages_ms)
        if body.protein_placement == "library":
            from backend.core.protein import protein_asset_meta

            design_state.add_protein_asset(asset)
            meta = protein_asset_meta(asset)
        else:
            updated, report, meta = _import_protein_free(
                asset,
                operation_id=operation_id,
                expected_revision=body.expected_revision,
            )
            resp.update(_design_response(updated, report))
        stages_ms["commit"] = (time.perf_counter() - stage_started) * 1000.0
        resp["protein"] = meta
        resp["protein"]["deduplicated"] = deduplicated
        resp["protein"]["duplicate_detected"] = duplicate_detected
        if meta.get("parse_warnings"):
            resp["import_warnings"] = meta["parse_warnings"]
        resp["imported"]["protein"] = True
        resp["process_metrics"] = _import_process_metrics(
            operation_id, started, stages_ms, "imported"
        )
        return resp

    # DNA only → design import.
    existing = design_state.get_design()
    try:
        stage_started = time.perf_counter()
        if existing and existing.helices:
            design, pdb_atomistic, w = await asyncio.to_thread(
                merge_pdb_into_design, existing, content
            )
        else:
            design, pdb_atomistic, w = await asyncio.to_thread(import_pdb, content)
    except Exception as exc:
        raise HTTPException(400, detail=f"DNA PDB import failed: {exc}") from exc
    stages_ms["parse_dna"] = (time.perf_counter() - stage_started) * 1000.0
    stage_started = time.perf_counter()
    await _reject_disconnected_import(request, operation_id, started, stages_ms)
    design_state.clear_history()
    design_state.set_design(design)
    design_state.set_pdb_atomistic(pdb_atomistic)
    report = validate_design(design)
    # New lineage — nothing in the client's cache matches this design's history.
    resp.update(_design_response(design, report, full_feature_log=True))
    resp["imported"]["dna"] = True
    if w:
        resp["import_warnings"] = w
    stages_ms["commit"] = (time.perf_counter() - stage_started) * 1000.0
    resp["process_metrics"] = _import_process_metrics(
        operation_id, started, stages_ms, "imported"
    )
    return resp


async def _reject_disconnected_import(
    request: Request,
    operation_id: str,
    started: float,
    stages_ms: dict[str, float],
) -> None:
    """Make browser cancellation a no-commit gate after expensive parsing.

    CPU-heavy parsing runs in worker threads so the ASGI server can observe a
    disconnected client. The check is deliberately adjacent to the first state
    mutation; cancellation during acquisition/parsing therefore leaves the
    design and protein library untouched.
    """
    if await request.is_disconnected():
        raise HTTPException(
            499,
            detail={
                "message": "Protein import cancelled before commit.",
                "operation_id": operation_id,
                "process_metrics": _import_process_metrics(
                    operation_id, started, stages_ms, "cancelled"
                ),
            },
        )


def _import_process_metrics(
    operation_id: str,
    started: float,
    stages_ms: dict[str, float],
    outcome: str,
) -> dict:
    metrics = {
        "schema_version": 1,
        "operation_id": operation_id,
        "outcome": outcome,
        "total_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "stages_ms": {name: round(value, 3) for name, value in stages_ms.items()},
    }
    from backend.core.protein_metrics import record_protein_process

    record_protein_process("import", metrics)
    return metrics


def _import_protein_free(asset, *, operation_id: str, expected_revision: int | None):
    """Embed a protein asset + add a free-standing placement, logged.

    Also registers the asset in the session library (so the attach-to-overhang
    picker can list it).  Creates an empty design if none is active, so the
    import has a feature log to record into.
    """
    from backend.core.models import Design, ProteinAttachment, ProteinTargetFree
    from backend.core.protein import protein_asset_meta

    design_state.add_protein_asset(asset)
    if design_state.get_design() is None:
        design_state.set_design(Design())

    attachment = ProteinAttachment(
        asset_id=asset.id,
        target=ProteinTargetFree(),
        conjugation_atom_serial=asset.default_conjugation_atom_serial,
    )

    def _fn(d: Design) -> None:
        if any(
            getattr(entry, "op_kind", None) == "protein-import"
            and entry.params.get("operation_id") == operation_id
            for entry in d.feature_log
        ):
            raise HTTPException(
                409, detail=f"Protein import operation {operation_id} was already committed."
            )
        if not any(a.id == asset.id for a in d.protein_assets):
            d.protein_assets = [*d.protein_assets, asset]
        d.protein_attachments = [*d.protein_attachments, attachment]

    updated, report, _entry = design_state.mutate_with_feature_log(
        "protein-import",
        f"Import protein {asset.name}",
        {"asset_id": asset.id, "name": asset.name, "operation_id": operation_id},
        _fn,
        expected_revision=expected_revision,
    )
    return updated, report, protein_asset_meta(asset)


@router.get("/design/export/cadnano")
def export_cadnano_design() -> Response:
    """Export the active design as a caDNAno v2 JSON file download.

    Returns a JSON file with Content-Disposition: attachment so the browser
    triggers a download.  Raises 400 if the design cannot be exported
    (e.g. square-lattice).
    """
    import json as _json
    from backend.core.cadnano import export_cadnano, check_cadnano_compatibility

    design = _design_for_export()
    warnings = check_cadnano_compatibility(design)
    errors = [w for w in warnings if w.startswith("ERROR")]
    if errors:
        raise HTTPException(400, detail="; ".join(errors))
    try:
        data = export_cadnano(design)
    except Exception as exc:
        raise HTTPException(400, detail=f"caDNAno export failed: {exc}") from exc
    json_bytes = _json.dumps(data, separators=(",", ":")).encode("utf-8")
    filename = f"{_export_filename_stem(design.metadata.name)}.json"
    return Response(
        content=json_bytes,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/design/export/scadnano")
def export_scadnano_design() -> Response:
    """Export the active design as a scadnano .sc JSON file."""
    import json as _json
    from backend.core.scadnano import export_scadnano

    design = _design_for_export()
    try:
        data = export_scadnano(design)
    except Exception as exc:
        raise HTTPException(400, detail=f"scadnano export failed: {exc}") from exc
    content = _json.dumps(data, separators=(",", ":")).encode("utf-8")
    filename = f"{_export_filename_stem(design.metadata.name)}.sc"
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/design/save")
def save_design(body: FilePathRequest) -> dict:
    """Save the active design to the given server-side path as .nadoc JSON."""
    design = design_state.get_or_404()
    path = os.path.abspath(body.path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(design.to_json())
    except OSError as exc:
        raise HTTPException(500, detail=f"Failed to save design: {exc}") from exc
    return {"saved_to": path}
