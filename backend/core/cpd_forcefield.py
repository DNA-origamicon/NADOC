"""Single capability gate for formed TT-CPD simulation chemistry."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

_MANIFEST_PATH = (
    Path(__file__).parents[1] / "data" / "forcefield" / "cpd_forcefield_manifest.json"
)


class CpdCapabilityError(RuntimeError):
    """Raised before any exporter can silently emit reactant chemistry."""


def cpd_forcefield_manifest() -> dict[str, Any]:
    return json.loads(_MANIFEST_PATH.read_text())


def cpd_capability() -> dict[str, Any]:
    manifest = cpd_forcefield_manifest()
    from backend.core.photoproduct_registry import photoproduct_capabilities

    products = photoproduct_capabilities()["products"]
    released = [item["id"] for item in products if item["simulation_ready"]]
    return {
        "available": bool(released),
        "released_product_ids": released,
        "availability_authority": "per-product registry gates and asset hashes",
        "legacy_manifest_available_ignored": bool(manifest.get("available")),
        "manifest_schema": manifest.get("schema"),
        "manifest_path": str(_MANIFEST_PATH),
        "manifest_sha256": hashlib.sha256(_MANIFEST_PATH.read_bytes()).hexdigest(),
        "missing_requirements": list(manifest.get("missing_requirements") or []),
        "policy": manifest.get("policy"),
    }


def design_has_photoproducts(design: object) -> bool:
    return bool(getattr(design, "photoproduct_junctions", None))


def reject_photoproduct_design(design: object, *, path: str, supported_path: str) -> None:
    """Permanently reject a product in an exporter that lacks lesion support.

    This is deliberately different from :func:`assert_cpd_simulation_supported`.
    That capability gate will open as individual products acquire released assets;
    an old exporter must not become product-aware merely because that happened.
    """

    if not design_has_photoproducts(design):
        return
    raise CpdCapabilityError(
        f"{path} does not implement formed-photoproduct topology and parameter handling. "
        f"Use {supported_path}. The design annotation is preserved; no reactant-topology "
        "or two-bond/restraint fallback was generated."
    )


def assert_cpd_simulation_supported(design: object, *, path: str) -> None:
    """Reject product designs unless the complete validated asset set is enabled."""
    if not design_has_photoproducts(design):
        return
    from backend.core.photoproduct_registry import photoproduct_capability

    registry_blockers: list[str] = []
    for lesion in getattr(design, "photoproduct_junctions", []):
        try:
            capability = photoproduct_capability(
                lesion.product, lesion.stereochemistry
            )
        except KeyError:
            registry_blockers.append(
                f"unregistered chemistry {lesion.product}/{lesion.stereochemistry}"
            )
            continue
        if not capability["simulation_ready"]:
            # Do not hide the missing parameter/template/audit tail behind an
            # abbreviated message.  A formed-product rejection must say exactly
            # which gates and assets are still absent.
            summary = ", ".join(capability["blockers"])
            registry_blockers.append(f"{capability['id']}: {summary}")
    if registry_blockers:
        raise CpdCapabilityError(
            f"{path} cannot prepare a formed TT-CPD: the complete validated "
            f"photoproduct capability is unavailable. Missing: {'; '.join(registry_blockers)}. "
            "The design annotation is preserved; no reactant-topology or "
            "two-bond/restraint fallback was generated."
        )

    # The registry already proved every product asset. The umbrella manifest is
    # provenance for the shared base force field, not a second release switch.
    manifest = cpd_forcefield_manifest()
    for label in ("local_topology", "local_parameters"):
        record = (manifest.get("base_forcefield") or {}).get(label) or {}
        source = _MANIFEST_PATH.parent / str(record.get("path") or "")
        if (
            not source.is_file()
            or hashlib.sha256(source.read_bytes()).hexdigest() != record.get("sha256")
        ):
            raise CpdCapabilityError(
                f"{path} cannot prepare a formed TT-CPD: shared CHARMM36 asset "
                f"{label!r} is missing or hash-mismatched. The design annotation is "
                "preserved; no reactant-topology or two-bond/restraint fallback was generated."
            )


def photoproduct_package_assets(design: object) -> list[dict[str, Any]]:
    """Return hash-verified released assets needed by a product simulation package."""

    if not design_has_photoproducts(design):
        return []
    assert_cpd_simulation_supported(design, path="photoproduct force-field asset resolver")
    from backend.core.photoproduct_registry import REGISTRY_PATH, photoproduct_registry

    registry = photoproduct_registry()
    records: dict[str, dict[str, Any]] = {}
    excluded = {"help_trajectory"}
    for lesion in getattr(design, "photoproduct_junctions"):
        entry = next(
            item
            for item in registry["products"]
            if item["product"] == lesion.product
            and item["stereochemistry"] == lesion.stereochemistry
        )
        for kind, record in entry["assets"].items():
            if kind in excluded:
                continue
            relative = str(record["path"])
            source = (REGISTRY_PATH.parent / relative).resolve()
            try:
                source.relative_to(REGISTRY_PATH.parent.resolve())
            except ValueError:
                raise CpdCapabilityError(
                    f"{entry['id']}: packaged asset {kind} escapes the force-field root"
                ) from None
            if not source.is_file():
                raise CpdCapabilityError(
                    f"{entry['id']}: packaged asset {kind} is missing: {relative}"
                )
            actual = hashlib.sha256(source.read_bytes()).hexdigest()
            if actual != record["sha256"]:
                raise CpdCapabilityError(
                    f"{entry['id']}: packaged asset {kind} is missing or hash-mismatched"
                )
            existing = records.get(relative)
            if existing is not None and existing["sha256"] != actual:
                raise CpdCapabilityError(
                    f"conflicting photoproduct assets share package path {relative!r}"
                )
            records[relative] = {
                "kind": kind,
                "product_id": entry["id"],
                "relative_path": relative,
                "source_path": source,
                "sha256": actual,
            }
    return [records[key] for key in sorted(records)]


def photoproduct_parameter_directives(design: object) -> list[str]:
    """NAMD parameter directives for every distinct released product parameter file."""

    return [
        f"parameters         forcefield/{record['relative_path']}"
        for record in photoproduct_package_assets(design)
        if record["kind"] == "parameters"
    ]


def inject_photoproduct_parameters(config: str, design: object) -> str:
    """Insert released lesion parameters into a generated NAMD configuration."""

    directives = photoproduct_parameter_directives(design)
    if not directives:
        return config
    lines = config.splitlines()
    parameter_indices = [
        index for index, line in enumerate(lines) if line.lstrip().startswith("parameters")
    ]
    if not parameter_indices:
        raise CpdCapabilityError(
            "NAMD configuration has no CHARMM parameter block for photoproduct insertion"
        )
    insertion = parameter_indices[-1] + 1
    lines[insertion:insertion] = directives
    return "\n".join(lines) + ("\n" if config.endswith("\n") else "")


_PACKAGED_MANIFEST = "photoproduct_forcefield_manifest.json"


def packaged_photoproduct_manifest(package_dir: Path) -> dict[str, Any] | None:
    """Load and hash-audit the frozen lesion assets in an existing NAMD package."""

    manifest_path = Path(package_dir) / _PACKAGED_MANIFEST
    if not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, ValueError) as exc:
        raise CpdCapabilityError(
            f"packaged photoproduct manifest is unreadable: {manifest_path}: {exc}"
        ) from exc
    if manifest.get("schema") != "nadoc.packaged-photoproduct-forcefield.v1":
        raise CpdCapabilityError(
            f"unsupported packaged photoproduct manifest schema in {manifest_path}"
        )
    if not manifest.get("lesions"):
        raise CpdCapabilityError(
            f"packaged photoproduct manifest contains no lesions: {manifest_path}"
        )
    for record in manifest.get("assets") or []:
        relative = record.get("relative_path")
        expected = record.get("sha256")
        if not relative or not expected:
            raise CpdCapabilityError(
                f"packaged photoproduct asset record is incomplete: {record!r}"
            )
        source = (Path(package_dir) / "forcefield" / str(relative)).resolve()
        try:
            source.relative_to((Path(package_dir) / "forcefield").resolve())
        except ValueError:
            raise CpdCapabilityError(
                f"packaged photoproduct asset escapes forcefield directory: {relative!r}"
            ) from None
        if not source.is_file():
            raise CpdCapabilityError(f"packaged photoproduct asset is missing: {relative}")
        actual = hashlib.sha256(source.read_bytes()).hexdigest()
        if actual != expected:
            raise CpdCapabilityError(
                f"packaged photoproduct asset hash mismatch: {relative}"
            )
    return manifest


def package_has_photoproducts(package_dir: Path) -> bool:
    """Whether a frozen simulation package contains an audited product lesion."""

    return packaged_photoproduct_manifest(Path(package_dir)) is not None


def packaged_photoproduct_parameter_directives(package_dir: Path) -> list[str]:
    """Resolve parameter directives from a package's immutable asset manifest."""

    manifest = packaged_photoproduct_manifest(Path(package_dir))
    if manifest is None:
        return []
    directives: list[str] = []
    seen: set[str] = set()
    for record in manifest.get("assets") or []:
        if record.get("kind") != "parameters":
            continue
        relative = str(record["relative_path"])
        if relative not in seen:
            directives.append(f"parameters         forcefield/{relative}")
            seen.add(relative)
    if not directives:
        raise CpdCapabilityError(
            "packaged photoproduct manifest contains no lesion parameter file"
        )
    return directives


def inject_packaged_photoproduct_parameters(config: str, package_dir: Path) -> str:
    """Insert frozen lesion parameters into any continuation-stage NAMD config."""

    directives = packaged_photoproduct_parameter_directives(Path(package_dir))
    if not directives:
        return config
    lines = config.splitlines()
    existing = {line.strip() for line in lines}
    missing = [line for line in directives if line.strip() not in existing]
    if not missing:
        return config
    parameter_indices = [
        index for index, line in enumerate(lines) if line.lstrip().startswith("parameters")
    ]
    if not parameter_indices:
        raise CpdCapabilityError(
            "NAMD continuation configuration has no CHARMM parameter block for "
            "photoproduct insertion"
        )
    insertion = parameter_indices[-1] + 1
    lines[insertion:insertion] = missing
    return "\n".join(lines) + ("\n" if config.endswith("\n") else "")


def assert_packaged_photoproduct_integrator(
    package_dir: Path,
    *,
    timestep_fs: float,
    hmr: bool,
    path: str,
) -> None:
    """Fail closed unless a product package uses the validated interim integrator."""

    if not package_has_photoproducts(Path(package_dir)):
        return
    if float(timestep_fs) > 2.0 or bool(hmr):
        raise CpdCapabilityError(
            f"{path} cannot run a formed photoproduct at {float(timestep_fs):g} fs "
            f"with HMR={'on' if hmr else 'off'}. Product-specific HMR/4 fs behavior "
            "has not been validated; use at most 2 fs with the ordinary-mass PSF."
        )
