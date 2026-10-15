"""Private, bounded display projections; never a recipe or publication input.

Version one covers complete uncoated particles and free protein placements.
Unsupported molecular families fail closed instead of disappearing from a
comparison. Existing native protein transforms own all placement mathematics.
"""

from math import isfinite

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import FIELD_ROLES
from backend.core.part_history_proof import AUTHORING_FIELDS, digest
from backend.core.part_operation_input import validate_operation_input
from backend.core.part_repair_inputs import RepairIdentity


SCOPE = "uncoated-particles-free-proteins-v1"
MAX_PLACEMENTS = 128
MAX_PROJECTED_ATOMS = 4096
RECIPE_FIELDS = frozenset({"recipe_root", "feature_log", "input_sources",
                          "feature_log_cursor", "feature_log_sub_cursor"})
_ALLOWED_AUTHORING = frozenset({"dimensions", "lattice_type", "metadata", "tm_settings",
                              "nanoparticles", "protein_assets", "protein_attachments"})


class ComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    projection_version: StrictInt = Field(ge=1, le=1)
    expected_design_id: RepairIdentity
    expected_revision: StrictInt = Field(ge=0)
    expected_draft_id: RepairIdentity
    expected_generation: StrictInt = Field(ge=0)


def parse_request(value):
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    validate_operation_input(value)
    return ComparisonRequest.model_validate(value)


def _reject(detail, code="unsupported_comparison_scope"):
    raise CommandContractError(detail, code=code)


def candidate_digests(data):
    """The same exact authoring/recipe projections checked by job commit."""
    return {"authoring": digest({name: data[name] for name in AUTHORING_FIELDS}),
            "recipe": digest({name: data[name] for name in RECIPE_FIELDS})}


def decode_candidate(data):
    from backend.core.models import Design

    expected = candidate_digests(data)
    candidate = Design.model_validate(data)
    if digest(candidate.model_dump(mode="json", include=AUTHORING_FIELDS)) != expected["authoring"]:
        _reject("The evaluated authoring changed during decoding", "candidate_decode_changed_authoring")
    if digest(candidate.model_dump(mode="json", include=RECIPE_FIELDS)) != expected["recipe"]:
        _reject("The evaluated recipe changed during decoding", "candidate_decode_changed_recipe")
    return candidate, expected


def _identity(value):
    # Check length before hashing even an internally mutated source identity.
    if type(value) is not str or not 1 <= len(value) <= 256:
        _reject("Comparison requires bounded nonempty resource identities", "invalid_comparison_reference")
    return value


def _unique(items, label, checkpoint):
    found = {}
    for item in items:
        checkpoint()
        identity = _identity(item.id)
        if identity in found:
            _reject(f"Comparison requires unique {label} identities", "invalid_comparison_reference")
        found[identity] = item
    return found


def check_scope(design, *, checkpoint=lambda: None):
    """Cheap closure check on owned data, also used before live source capture."""
    from backend.core.models import Design

    if type(design) is not Design or set(type(design).model_fields) != set(FIELD_ROLES):
        _reject("Comparison requires the reviewed mutable standard-part schema")
    for name, role in FIELD_ROLES.items():
        checkpoint()
        if role == "authoring" and name not in _ALLOWED_AUTHORING and getattr(design, name):
            _reject(f"Comparison does not yet cover {name}")
    if len(design.nanoparticles) + len(design.protein_attachments) > MAX_PLACEMENTS:
        _reject("Comparison placement count exceeds its display allowance", "comparison_limit")
    if len(design.protein_assets) > MAX_PLACEMENTS:
        _reject("Comparison asset count exceeds its display allowance", "comparison_limit")
    _unique(design.nanoparticles, "particle", checkpoint)
    _unique(design.protein_attachments, "protein attachment", checkpoint)
    assets = _unique(design.protein_assets, "protein asset", checkpoint)
    atoms = 0
    for particle in design.nanoparticles:
        checkpoint()
        if particle.coating is not None or particle.biotin_dna:
            _reject("Coated or DNA-bearing particles need a separate complete projection")
        if type(particle.kind) is not str or len(particle.kind) > 32 or particle.kind not in {"gold_nanosphere", "quantum_dot"}:
            _reject("Unsupported particle display kind")
        if particle.kind == "quantum_dot" and particle.quantum_dot is None:
            _reject("Quantum-dot display metadata is missing", "invalid_comparison_reference")
    for attachment in design.protein_attachments:
        checkpoint()
        if attachment.target.kind != "free" or attachment.binder_strand_id is not None:
            _reject("Anchored proteins need a separate complete projection")
        asset = assets.get(_identity(attachment.asset_id))
        if asset is None or not asset.atoms:
            _reject("A placed protein has no unique nonempty asset", "invalid_comparison_reference")
        atoms += len(asset.atoms)
        if atoms > MAX_PROJECTED_ATOMS:
            _reject("Comparison atom count exceeds its display allowance", "comparison_limit")


def _finite(values):
    if any(type(value) not in {int, float} or not isfinite(value) for value in values):
        _reject("Comparison placement contains nonfinite coordinates", "invalid_comparison_geometry")


def project(design):
    """Return coarse authored display inputs using unchanged native helpers.

    All placements are retained, including authored hidden placements. Consumers
    receive visibility metadata but may not silently call this a normal viewport
    or physical-state projection. Unplaced library assets have no geometry.
    """
    import numpy as np
    from backend.core.protein import compose_protein_world_transform, protein_asset_to_atomistic

    check_scope(design)
    particles, proteins = [], []
    lower, upper = [float("inf")] * 3, [float("-inf")] * 3

    def include(point, radius=0):
        _finite(point)
        for index in range(3):
            lower[index] = min(lower[index], point[index] - radius)
            upper[index] = max(upper[index], point[index] + radius)

    for particle in design.nanoparticles:
        pose = particle.pose.to_array()
        _finite(pose.reshape(-1).tolist())
        # The ordinary particle renderer decomposes its pose into rigid TRS.
        # Do not invent shear/perspective interpretation for comparison.
        if (not np.allclose(pose[3], [0, 0, 0, 1], rtol=0, atol=1e-9)
                or not np.allclose(pose[:3, :3].T @ pose[:3, :3], np.eye(3), rtol=0, atol=1e-7)
                or not np.isclose(np.linalg.det(pose[:3, :3]), 1, rtol=0, atol=1e-7)):
            _reject("Particle comparison requires a rigid authored pose")
        _finite([particle.diameter_nm])
        if not 0 < particle.diameter_nm <= 1000:
            _reject("Particle diameter is outside its native range", "invalid_comparison_geometry")
        include(pose[:3, 3].tolist(), particle.diameter_nm / 2)
        particles.append({"id": particle.id, "kind": particle.kind, "diameter_nm": particle.diameter_nm,
            "pose": particle.pose.values[:], "authored_visible": particle.visible,
            "display_color": particle.quantum_dot.display_color if particle.kind == "quantum_dot" else "#eac13b"})
    assets = {asset.id: asset for asset in design.protein_assets}
    for attachment in design.protein_attachments:
        asset = assets[attachment.asset_id]
        for atom in asset.atoms:
            _finite([atom.x, atom.y, atom.z])
        world = compose_protein_world_transform(asset, attachment)
        _finite(world.reshape(-1).tolist())
        model = protein_asset_to_atomistic(asset, pose_matrix=world, sentinel_id=attachment.id)
        atoms = []
        for atom in model.atoms:
            point = [atom.x, atom.y, atom.z]
            include(point)
            atoms.append({"serial": atom.serial, "helix_id": atom.helix_id, "name": atom.name,
                          "chain_id": atom.chain_id, "x": atom.x, "y": atom.y, "z": atom.z})
        proteins.append({"id": attachment.id, "asset_id": attachment.asset_id,
            "authored_visible": attachment.visible,
            "representation": "trace" if any(atom["name"] == "CA" for atom in atoms) else "ovoid",
            "atoms": atoms})
    return {"units": "nm", "particles": particles, "proteins": proteins,
            "bounds_nm": None if lower[0] == float("inf") else {"minimum": lower, "maximum": upper},
            "unplaced_asset_ids": [asset.id for asset in design.protein_assets if not any(
                attachment.asset_id == asset.id for attachment in design.protein_attachments)]}


def compare(source, candidate_data):
    """Called only with independently owned inputs in the disposable worker."""
    candidate, expected = decode_candidate(candidate_data)
    if candidate.id != source.id:
        _reject("Candidate belongs to another part", "comparison_conflict")
    return {"status": "projected", "issues": [], "projection_version": 1,
        "scope": SCOPE, "comparison_basis": "published_materialized_authoring_vs_evaluated_recipe",
        "coverage": {"complete": True, "scientific_qualification": False,
                     "visibility": "all_authored_placements", "excluded_layers": ["physical", "presentation"]},
        "published": project(source), "proposed": project(candidate), "candidate_digests": expected}
