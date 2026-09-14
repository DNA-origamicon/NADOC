"""Offline vendor catalog and import policy for display-layer quantum dots."""

import json
from functools import lru_cache
from pathlib import Path

from backend.core.models import Nanoparticle, QuantumDotSpec

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "quantum_dots"


@lru_cache(maxsize=1)
def _catalog() -> dict:
    return json.loads((DATA_DIR / "catalog.json").read_text())


def quantum_dot_catalog() -> dict:
    # Callers must not be able to mutate the process-wide catalog.
    return json.loads(json.dumps(_catalog()))


def catalog_entry(catalog_id: str) -> dict:
    for entry in _catalog()["entries"]:
        if entry["catalog_id"] == catalog_id:
            return entry
    raise KeyError(catalog_id)


def validate_quantum_dot_diameter(spec: QuantumDotSpec, diameter_nm: float) -> None:
    low, high = spec.diameter_range_nm
    if not low <= diameter_nm <= high:
        raise ValueError(f"Choose a scene diameter within the vendor range ({low:g}–{high:g} nm).")


def create_quantum_dot(catalog_id: str, diameter_nm: float | None = None) -> Nanoparticle:
    entry = catalog_entry(catalog_id)
    if not entry["import_enabled"]:
        raise ValueError("Functionalized quantum dots are catalog previews only; import is not enabled yet.")
    spec = QuantumDotSpec.model_validate(entry)
    if diameter_nm is None:
        diameter_nm = sum(spec.diameter_range_nm) / 2
    validate_quantum_dot_diameter(spec, diameter_nm)
    return Nanoparticle(kind="quantum_dot", diameter_nm=diameter_nm, quantum_dot=spec)
