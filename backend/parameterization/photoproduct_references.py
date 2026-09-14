"""Fetch immutable structural references used by photoproduct workflows.

References are downloaded only by an explicit CLI action.  Every byte stream must
match the digest in the reviewed chemical definition before it enters the cache.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any, Callable
from urllib.request import urlopen

from backend.core.photoproduct_chemistry import load_chemical_definition


class ReferenceAssetError(RuntimeError):
    """A reference could not be obtained without weakening provenance."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch_verified_asset(
    *,
    url: str,
    expected_sha256: str,
    destination: Path,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    """Download *url* atomically and reject any digest mismatch.

    Existing matching cache entries are reused. Existing mismatches are never
    overwritten, preserving evidence for diagnosis and avoiding a silent source
    update.
    """

    if destination.exists():
        actual = sha256_file(destination)
        if actual != expected_sha256:
            raise ReferenceAssetError(
                f"cached reference digest mismatch for {destination}: "
                f"expected {expected_sha256}, found {actual}"
            )
        return {
            "path": str(destination.resolve()),
            "sha256": actual,
            "source": url,
            "cache": "reused",
        }

    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with opener(url, timeout=60) as response:
            payload = response.read()
    except Exception as exc:  # urllib exposes several transport exception types
        raise ReferenceAssetError(f"failed to download {url}: {exc}") from exc
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected_sha256:
        raise ReferenceAssetError(
            f"downloaded reference digest mismatch for {url}: "
            f"expected {expected_sha256}, found {actual}"
        )
    with tempfile.NamedTemporaryFile(
        dir=destination.parent, prefix=f".{destination.name}.", delete=False
    ) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    temporary.replace(destination)
    return {
        "path": str(destination.resolve()),
        "sha256": actual,
        "source": url,
        "cache": "downloaded",
    }


def fetch_reference_bundle(
    product: str,
    stereochemistry: str,
    cache_dir: Path,
) -> dict[str, Any]:
    definition = load_chemical_definition(product, stereochemistry)
    assets = definition.get("source_assets")
    if not isinstance(assets, list) or not assets:
        raise ReferenceAssetError(
            f"{product} {stereochemistry} has no reviewed source_assets"
        )
    records: list[dict[str, Any]] = []
    for asset in assets:
        required = ("id", "url", "filename", "sha256", "license")
        missing = [field for field in required if not asset.get(field)]
        if missing:
            raise ReferenceAssetError(
                f"reference asset is missing required fields: {', '.join(missing)}"
            )
        record = fetch_verified_asset(
            url=asset["url"],
            expected_sha256=asset["sha256"],
            destination=cache_dir / definition["id"] / asset["filename"],
        )
        records.append(
            {
                "id": asset["id"],
                "license": asset["license"],
                "license_url": asset.get("license_url"),
                **record,
            }
        )
    manifest = {
        "schema": "nadoc.photoproduct-reference-cache.v1",
        "product_id": definition["id"],
        "product": product,
        "stereochemistry": stereochemistry,
        "gate_effect": "none",
        "assets": records,
    }
    manifest_path = cache_dir / definition["id"] / "reference_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
