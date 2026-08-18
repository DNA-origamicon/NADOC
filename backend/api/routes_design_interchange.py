"""PDB import and file interchange routes for active designs."""

import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from backend.api import state as design_state
from backend.api.crud import (
    _design_for_export,
    _design_response,
    _export_filename_stem,
)

router = APIRouter()


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


@router.post("/design/import/pdb-auto", status_code=200)
def import_pdb_auto(body: PdbAutoImportRequest) -> dict:
    """Unified PDB import: download by RCSB id or accept file content, then
    route by residue content.

    * Protein present → imported as a free-standing, movable protein object
      (embedded in the design, logged in the feature log).  If DNA is ALSO
      present and ``remove_dna_from_protein`` is undecided, returns
      ``needs_dna_decision`` (with the resolved ``content``) instead of
      importing, so the UI can ask whether to strip the DNA.
    * DNA only → imported as a design (the classic PDB-as-design path).
    """
    from backend.core.pdb_to_design import import_pdb, merge_pdb_into_design
    from backend.core.protein import classify_pdb_content, parse_protein_pdb
    from backend.core.validator import validate_design

    if body.pdb_id:
        content = _download_rcsb_pdb(body.pdb_id)
        name = body.name or body.pdb_id.strip().upper()
        source = f"rcsb:{body.pdb_id.strip().upper()}"
    elif body.content:
        content = body.content
        name = body.name or "structure"
        source = "file"
    else:
        raise HTTPException(400, detail="Provide either pdb_id or content.")

    has_dna, has_protein = classify_pdb_content(content)
    if not has_dna and not has_protein:
        raise HTTPException(400, detail="No DNA or protein residues found in the PDB.")

    resp: dict = {
        "imported": {"dna": False, "protein": False},
        "source": source,
        "name": name,
    }

    if has_protein:
        # Ask before stripping DNA from a protein-DNA complex.
        if has_dna and body.remove_dna_from_protein is None:
            return {
                **resp,
                "needs_dna_decision": True,
                "has_dna": True,
                "has_protein": True,
                "content": content,
            }
        exclude_dna = bool(body.remove_dna_from_protein)
        try:
            asset = parse_protein_pdb(
                content, name=name, source_filename=name, exclude_dna=exclude_dna
            )
        except Exception as exc:
            raise HTTPException(
                400, detail=f"Protein PDB import failed: {exc}"
            ) from exc
        if not asset.atoms:
            raise HTTPException(400, detail="No protein atoms found after parsing.")
        updated, report, meta = _import_protein_free(asset)
        resp.update(_design_response(updated, report))
        resp["protein"] = meta
        resp["imported"]["protein"] = True
        return resp

    # DNA only → design import.
    existing = design_state.get_design()
    try:
        if existing and existing.helices:
            design, pdb_atomistic, w = merge_pdb_into_design(existing, content)
        else:
            design, pdb_atomistic, w = import_pdb(content)
    except Exception as exc:
        raise HTTPException(400, detail=f"DNA PDB import failed: {exc}") from exc
    design_state.clear_history()
    design_state.set_design(design)
    design_state.set_pdb_atomistic(pdb_atomistic)
    report = validate_design(design)
    # New lineage — nothing in the client's cache matches this design's history.
    resp.update(_design_response(design, report, full_feature_log=True))
    resp["imported"]["dna"] = True
    if w:
        resp["import_warnings"] = w
    return resp


def _import_protein_free(asset):
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
        if not any(a.id == asset.id for a in d.protein_assets):
            d.protein_assets = [*d.protein_assets, asset]
        d.protein_attachments = [*d.protein_attachments, attachment]

    updated, report, _entry = design_state.mutate_with_feature_log(
        "protein-import",
        f"Import protein {asset.name}",
        {"asset_id": asset.id, "name": asset.name},
        _fn,
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
