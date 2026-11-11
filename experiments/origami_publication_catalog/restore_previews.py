"""Restore publisher figure previews without downloading native design references.

Previews are portable repository assets; bulk source evidence remains in the
ignored assets directory. Historical manifests are never overwritten.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import io
import json
from pathlib import Path
import urllib.request
from urllib.parse import quote
import zipfile

import pymupdf

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LIMIT = 100_000_000


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def archive_member(raw, expected, suffixes):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for member in archive.infolist():
            if Path(member.filename).suffix.lower() not in suffixes or member.file_size > LIMIT:
                continue
            candidate = archive.read(member)
            if sha(candidate) == expected:
                return candidate
    raise ValueError("Archive has no image/PDF matching the recorded hash")


def acquire(row, manifest):
    path = HERE / "assets" / row["source_file"]
    expected = manifest[row["source_file"]]["sha256"]
    shared = ROOT / "workspace/Shared Designs/image-sequence-first5-20261104/inputs" / path.name
    if path.is_file():
        raw = path.read_bytes()
    elif shared.is_file() and sha(shared.read_bytes()) == expected:
        raw = shared.read_bytes()
    else:
        request = urllib.request.Request(row["image_source_url"], headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read(LIMIT + 1)
        if len(raw) > LIMIT:
            raise ValueError("Source exceeds bounded download size")
        if sha(raw) != expected and zipfile.is_zipfile(io.BytesIO(raw)) and path.suffix == ".pdf":
            raw = archive_member(raw, expected, {".pdf"})
    if sha(raw) != expected:
        raise ValueError(f"Source hash differs from catalog evidence: {path.name}")
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return raw


def restore_group(rows, manifest):
    raw = acquire(rows[0], manifest)
    outputs = []
    for row in rows:
        if row["pdf_page"]:
            with pymupdf.open(stream=raw, filetype="pdf") as doc:
                page = doc[row["pdf_page"] - 1]
                scale = 1800 / max(page.rect.width, page.rect.height)
                image = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).tobytes("png")
            method = "PyMuPDF full published page, longest dimension 1800 pixels; no redrawing"
        elif row["image_file"] == row["source_file"]:
            image = raw
            method = "Original published image bytes"
        else:
            image = archive_member(raw, manifest[row["image_file"]]["sha256"], {".png", ".jpg", ".jpeg"})
            method = "Original image bytes extracted from publisher ZIP; no native design files read"
        original_image = image
        if not row["pdf_page"]:
            pix = pymupdf.Pixmap(image)
            if max(pix.width, pix.height) > 1800:
                scale = 1800 / max(pix.width, pix.height)
                pix = pymupdf.Pixmap(pix, pix.width * scale, pix.height * scale)
                image = pix.tobytes("png")
                method += "; display preview scaled to longest dimension 1800 pixels"
        preview = HERE / "previews" / Path(row["image_file"]).name
        preview.parent.mkdir(exist_ok=True)
        preview.write_bytes(image)
        legacy = HERE / "assets" / row["image_file"]
        if not legacy.exists():
            legacy.parent.mkdir(parents=True, exist_ok=True)
            legacy.write_bytes(original_image)
        outputs.append({"id": row["id"], "preview": preview.relative_to(HERE).as_posix(),
                        "sha256": sha(image), "bytes": len(image),
                        "source_url": row["image_source_url"], "source_file": row["source_file"],
                        "source_sha256": sha(raw), "pdf_page": row["pdf_page"], "method": method})
    return outputs


def refresh_pages(rows):
    # Update only known figure links. Keep paper, sequence and author-file links.
    for filename in ("catalog.html", "structure_map.html", "CATALOG.md", "RECOVERY_QUEUE.md"):
        path = HERE / filename
        text = path.read_text()
        for row in rows:
            old = "assets/" + row["image_file"]
            new = "previews/" + Path(row["image_file"]).name
            text = text.replace(old, new).replace(quote(old, safe="/"), quote(new, safe="/"))
        path.write_text(text)


def main():
    rows = json.loads((HERE / "catalog.json").read_text())["rows"]
    manifest = {row["path"]: row for row in json.loads((HERE / "assets_manifest.json").read_text())}
    groups = {}
    for row in rows:
        groups.setdefault(row["source_file"], []).append(row)
    results, errors = [], []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(restore_group, group, manifest): group for group in groups.values()}
        for future in as_completed(futures):
            group = futures[future]
            try:
                restored = future.result()
                results.extend(restored)
                print("Restored", ", ".join(row["id"] for row in restored), flush=True)
            except Exception as exc:
                errors.append({"ids": [row["id"] for row in group], "error": str(exc)})
                print("Unavailable", errors[-1], flush=True)
    result = {"restored": sorted(results, key=lambda row: row["id"]), "errors": errors,
              "renderer": f"PyMuPDF {pymupdf.VersionBind}", "date": "2026-11-04"}
    (HERE / "preview_manifest.json").write_text(json.dumps(result, indent=2) + "\n")
    refresh_pages([row for row in rows if any(result["id"] == row["id"] for result in results)])
    if errors:
        raise SystemExit("Some source images remain unavailable; see preview_manifest.json")


if __name__ == "__main__":
    main()
