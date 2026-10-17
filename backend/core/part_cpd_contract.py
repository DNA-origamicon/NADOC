"""Explicit native CPD inputs and a pinned, bounded execution contract.

The manifest inventories executed placement code, not transitive imports or the
entire application. Installed source/assets must remain immutable during a job;
the command checks their identity before and after placement. Qualification is a
separate current policy: an old digest never overrides a withdrawn capability.
No atomistic model or optimization is built by admission or manifest capture.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_history_contract import FIELD_ROLES


KINDS = frozenset({"photoproduct-create", "photoproduct-relax"})
ENGINE_ID = "nadoc.cpd-native-engine.v1"
MAX_SOURCE_ATOMS = 50_000
_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_PATH = "photoproducts/tt-cpd-cis-syn/preliminary-v6/template.json"
TEMPLATE_SHA256 = "cfb5cd66b05f210b8e6f5e95478373ad169d9de3dfbfcff91a2b0c9fe908c0d6"

# Empty-family guards are part of the closure too (aptamer, linker and biotin
# helpers). Imports of unrelated simulation/export functions are not execution.
SOURCE_PATHS = tuple(f"backend/core/{name}.py" for name in (
    "part_cpd_contract", "part_numerical_runtime", "cpd_design", "cpd_product", "atomistic",
    "atomistic_helpers", "atomistic_minimisers", "atomistic_validation",
    "base_keys", "constants", "geometry", "design_geometry", "deformation",
    "deformation_scope", "sweep_path", "native_full_placement",
    "native_slab_placement", "measured_atomistic", "measured_positioning",
    "nucleotide_landmarks", "junction_topology", "flexible_segments", "aptamer",
    "lattice", "sequences", "chain_ids", "models", "sweep_model",
    "lattice_frame_model", "dimensions", "biotin_extensions", "part_history_contract",
)) + ("backend/api/part_cpd_commands.py",)
DATA_PATHS = ("backend/core/data/measured_atomistic_template.json",)
_AUTHORING = frozenset(k for k, role in FIELD_ROLES.items() if role == "authoring")
_BLOCKED_FIELDS = frozenset("""
protein_assets protein_attachments nanoparticles nanoparticle_conjugations
nanoparticle_connection_versions extensions overhangs overhang_connections
overhang_bindings connection_versions duplexes cluster_joints cluster_join_constraints
flexible_segment_marks flexible_connections
""".split())
_ALLOWED_FIELDS = frozenset("""
dimensions lattice_frames helices strands lattice_type metadata deformations
cluster_transforms nucleotide_transforms tm_settings staple_groups
photoproduct_junctions crossovers crossover_constraints forced_ligations
""".split())


class CPDContractError(CommandContractError):
    def __init__(self, detail, *, code, fields=()):
        super().__init__(detail, code=code)
        self.fields = tuple(fields)

    def as_issue(self):
        issue = super().as_issue()
        if self.fields:
            issue["fields"] = list(self.fields)
        return issue


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


Hash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Identity = Annotated[str, StringConstraints(min_length=1, max_length=512)]


class NativeSource(_Strict):
    kind: Literal["native"]


class TemplatePin(_Strict):
    product_id: Literal["tt-cpd-cis-syn"]
    schema_version: Literal["nadoc.photoproduct-coordinate-template.v1"] = Field(alias="schema")
    sha256: Hash


class EnginePin(_Strict):
    id: Literal["nadoc.cpd-native-engine.v1"]
    implementation_sha256: Hash
    runtime_sha256: Hash


class _Inputs(_Strict):
    source: NativeSource
    product: Literal["TT-CPD"] = "TT-CPD"
    stereochemistry: Literal["cis-syn"] = "cis-syn"


class CreateInputs(_Inputs):
    method: Literal["convert"] = "convert"
    base_keys: list[Identity] = Field(min_length=2, max_length=2)
    history_seed: str

    @field_validator("history_seed")
    @classmethod
    def _canonical_seed(cls, value):
        if str(uuid.UUID(value)) != value:
            raise ValueError("history_seed must be a canonical UUID")
        return value


class RelaxInputs(_Inputs):
    method: Literal["relax"] = "relax"
    photoproduct_id: Identity


class _Pins(_Strict):
    proof_version: Literal[1] = Field(alias="_proof_version")
    conversion_version: Literal[1]
    template: TemplatePin
    engine: EnginePin

    @model_validator(mode="before")
    @classmethod
    def _exact_versions(cls, value):
        if isinstance(value, dict) and any(type(value.get(k)) is not int for k in
                                          ("_proof_version", "conversion_version")):
            raise ValueError("CPD contract versions must be explicit integers")
        return value


class CreateCommand(CreateInputs, _Pins):
    pass


class RelaxCommand(RelaxInputs, _Pins):
    pass


def parse_command(kind, params):
    """Cheap complete-schema admission; never fills or refreshes engine pins."""
    if kind == "photoproduct-create":
        return CreateCommand.model_validate(params)
    if kind == "photoproduct-relax":
        return RelaxCommand.model_validate(params)
    raise ValueError("Unsupported native CPD command")


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _file_digest(path):
    from backend.core.part_numerical_runtime import file_digest
    return file_digest(path, error_type=CPDContractError, label="CPD")


def implementation_manifest():
    """Only fixed server-owned paths are read; input never names executable files."""
    return {
        "id": ENGINE_ID,
        "solver": "canonical-torsion-search-v2",
        "placement": "native-full-o5-v1",
        "source_policy": "ordinary-native-dna-v1",
        "files": {name: _file_digest(_ROOT / name) for name in SOURCE_PATHS},
        "data": {name: _file_digest(_ROOT / name) for name in DATA_PATHS},
    }


def _numerical_libraries():
    from backend.core.part_numerical_runtime import numerical_libraries
    return numerical_libraries(file_digest_fn=_file_digest, error_type=CPDContractError, label="CPD")


def runtime_fingerprint():
    from backend.core.part_numerical_runtime import runtime_fingerprint as fingerprint
    return fingerprint(libraries=_numerical_libraries(), error_type=CPDContractError)


def _qualified_template():
    from backend.core.photoproduct_registry import REGISTRY_PATH, photoproduct_capability, photoproduct_registry

    capability = photoproduct_capability("TT-CPD", "cis-syn")
    if not capability.get("simulation_supported"):
        raise CPDContractError("The CPD template no longer passes current qualification gates",
                               code="template_unavailable")
    entries = [p for p in photoproduct_registry()["products"] if p["id"] == capability["id"]]
    if len(entries) != 1 or entries[0]["id"] != "tt-cpd-cis-syn":
        raise CPDContractError("The registered CPD product is not covered by this engine", code="template_mismatch")
    asset = entries[0]["assets"]["coordinate_template"]
    if asset.get("path") != TEMPLATE_PATH or asset.get("sha256") != TEMPLATE_SHA256:
        raise CPDContractError("The registered CPD template requires an explicit engine upgrade", code="template_mismatch")
    try:
        data = (REGISTRY_PATH.parent / TEMPLATE_PATH).read_bytes()
    except OSError as error:
        raise CPDContractError("The pinned CPD template is unavailable", code="template_unavailable") from error
    if hashlib.sha256(data).hexdigest() != TEMPLATE_SHA256:
        raise CPDContractError("The pinned CPD template bytes do not match", code="template_mismatch")
    # Preserve all of the current template schema/provenance gates, without
    # placing atoms. The scientific capability check above is independent.
    from backend.core.cpd_product import _template_coordinates
    _template_coordinates(json.loads(data), allowed_release_statuses=frozenset({"released", "preliminary"}))
    return TemplatePin.model_validate({"product_id": "tt-cpd-cis-syn",
        "schema": "nadoc.photoproduct-coordinate-template.v1", "sha256": TEMPLATE_SHA256})


def contract_defaults():
    """Capture pins only in the dedicated worker under its numerical policy."""
    return {
        "_proof_version": 1, "conversion_version": 1,
        "template": _qualified_template().model_dump(mode="json", by_alias=True),
        "engine": {"id": ENGINE_ID,
                   "implementation_sha256": _digest(implementation_manifest()),
                   "runtime_sha256": _digest(runtime_fingerprint())},
    }


def prepare_command(kind, inputs):
    """Create complete recipe inputs; never accepts caller-supplied pins or outputs."""
    model = CreateInputs if kind == "photoproduct-create" else RelaxInputs if kind == "photoproduct-relax" else None
    if model is None:
        raise ValueError("Unsupported native CPD command")
    authored = model.model_validate(inputs).model_dump(mode="json")
    return parse_command(kind, {**authored, **contract_defaults()}).model_dump(mode="json", by_alias=True)


def validate_environment(command):
    if command.template != _qualified_template():
        raise CPDContractError("CPD template identity differs from the authored recipe", code="template_mismatch")
    if command.engine.implementation_sha256 != _digest(implementation_manifest()):
        raise CPDContractError("CPD placement code/data differs from the authored engine", code="engine_mismatch")
    if command.engine.runtime_sha256 != _digest(runtime_fingerprint()):
        raise CPDContractError("CPD numerical runtime differs from the authored engine", code="runtime_mismatch")


def _reference(detail, kind, identity, path, *, invalid=False):
    raise ReferenceResolutionError(detail, code="invalid_selection" if invalid else "missing_reference",
        references=[{"kind": kind, "identity": identity, "parameter_path": path}])


def _endpoints(design, keys, paths):
    from backend.core.base_keys import parse_base_key, resolve_base_keys

    parsed = []
    for key, path in zip(keys, paths):
        base = parse_base_key(key)
        if (base is None or base.family != "xover"
                or key != f"__xb__:{base.crossover_id}:{base.k}"):
            _reference("Select canonical crossover-extra base keys", "base_key", key, path, invalid=True)
        owners = [v for v in (*design.crossovers, *design.forced_ligations) if v.id == base.crossover_id]
        if not owners:
            _reference("The selected extra-base producer is missing", "base_key", key, path)
        if len(owners) != 1:
            _reference("The selected extra-base producer is ambiguous", "base_key", key, path, invalid=True)
        owner = owners[0]
        helix_ids = ([owner.half_a.helix_id, owner.half_b.helix_id] if hasattr(owner, "half_a")
                     else [owner.three_prime_helix_id, owner.five_prime_helix_id])
        if any(design.find_helix(identity) is None for identity in helix_ids):
            _reference("The selected extra-base producer has a missing helix", "base_key", key, path)
        resolved, errors = resolve_base_keys(design, [key], require_atoms=False)
        if errors or not resolved:
            _reference("The selected extra base no longer exists", "base_key", key, path)
        if resolved[0].base != "T":
            _reference("The selected extra base must be thymine", "base_key", key, path, invalid=True)
        parsed.append(base)
    if len(set(keys)) != 2:
        _reference("Select two distinct extra thymines", "base_key", keys[-1], paths[-1], invalid=True)
    return parsed


def validate_source(design):
    """Admit exactly the source families audited by this engine; never drop any."""
    if (_ALLOWED_FIELDS | _BLOCKED_FIELDS != _AUTHORING
            or set(type(design).model_fields) != set(FIELD_ROLES)):
        raise CPDContractError("The design schema requires a new CPD source contract", code="unsupported_source")
    blocked = sorted(field for field in _BLOCKED_FIELDS if getattr(design, field))
    if any(h.native_residues or h.native_source is not None for h in design.helices):
        blocked.append("helices.native_residues/native_source")
    if any(h.id.startswith(("__np__", "__strep_dna__", "__lnk__")) for h in design.helices):
        blocked.append("helices.synthetic_carrier")
    if any(s.is_reference or s.strand_type.value not in {"scaffold", "staple"} for s in design.strands):
        blocked.append("strands.reference_or_asset_type")
    if any(d.overhang_id or d.binds_overhang_id for s in design.strands for d in s.domains):
        blocked.append("strands.domains.overhang_reference")
    if any(c.overhang_duplex_driver_id for c in design.cluster_transforms):
        blocked.append("cluster_transforms.overhang_duplex_driver_id")
    if any(p.t1_stable_id or p.t2_stable_id or not p.base_key_1 or not p.base_key_2
           or p.product != "TT-CPD" or p.stereochemistry != "cis-syn" for p in design.photoproduct_junctions):
        blocked.append("photoproduct_junctions.legacy_or_unsupported_product")
    if blocked:
        raise CPDContractError("This CPD engine supports ordinary native DNA only", code="unsupported_source", fields=blocked)

    helices = {h.id: h for h in design.helices}
    if len(helices) != len(design.helices):
        raise CPDContractError("The native source has duplicate helix identities", code="unsupported_source")
    spans = {h.id: [h.bp_start, h.bp_start + h.length_bp - 1] for h in design.helices}
    positive_loops = {}
    for helix in design.helices:
        marks = sorted((mark.bp_index, max(0, mark.delta)) for mark in helix.loop_skips)
        positions, prefix = [], [0]
        for bp, delta in marks:
            positions.append(bp)
            prefix.append(prefix[-1] + delta)
        positive_loops[helix.id] = (positions, prefix)
    domain_residues = 0
    for strand in design.strands:
        for domain in strand.domains:
            if domain.helix_id not in spans:
                _reference("Native CPD source strand refers to a missing helix", "helix", domain.helix_id, ["source"])
            span = spans[domain.helix_id]
            lo, hi = sorted((domain.start_bp, domain.end_bp))
            span[0] = min(span[0], lo)
            span[1] = max(span[1], hi)
            positions, prefix = positive_loops[domain.helix_id]
            domain_residues += hi - lo + 1 + prefix[bisect_right(positions, hi)] - prefix[bisect_left(positions, lo)]
    residues = sum(2 * (max(0, hi - lo + 1) + sum(max(0, mark.delta) for mark in helices[hid].loop_skips))
                   for hid, (lo, hi) in spans.items())
    # Atomistic construction iterates every strand/domain, including malformed
    # overlapping domains. They cannot evade admission by sharing helix slots.
    residues = max(residues, domain_residues)
    residues += sum(len(item.extra_bases or "") for item in (*design.crossovers, *design.forced_ligations))
    estimate = residues * 32  # Conservative heavy-atom admission, not a heap guarantee.
    if estimate > MAX_SOURCE_ATOMS:
        raise CPDContractError(f"Native CPD source exceeds {MAX_SOURCE_ATOMS} estimated atoms", code="source_limit")
    return estimate


def validate_inputs(kind, design, params):
    """Resolve targets without atomistic construction, then admit the source."""
    command = parse_command(kind, params)
    lesion = None
    if isinstance(command, CreateCommand):
        keys = command.base_keys
        paths = [["base_keys", i] for i in range(2)]
    else:
        matches = [p for p in design.photoproduct_junctions if p.id == command.photoproduct_id]
        if len(matches) != 1:
            _reference("The CPD to relax is missing or ambiguous", "photoproduct", command.photoproduct_id,
                       ["photoproduct_id"], invalid=bool(matches))
        lesion = matches[0]
        keys = [lesion.base_key_1, lesion.base_key_2]
        paths = [["photoproduct_id"], ["photoproduct_id"]]
        if not lesion.design_coordinates or set(lesion.design_coordinates) != set(keys):
            _reference("Relaxation requires a converted CPD with both native endpoint poses", "photoproduct",
                       lesion.id, ["photoproduct_id"], invalid=True)
    parsed = _endpoints(design, keys, paths)
    if lesion is None:
        consumed = {key for p in design.photoproduct_junctions for key in (p.base_key_1, p.base_key_2)}
        for key, path in zip(keys, paths):
            if key in consumed:
                _reference("The selected extra base already belongs to a CPD", "base_key", key, path, invalid=True)
        if any(p.id == command.history_seed for p in design.photoproduct_junctions):
            _reference("The CPD identity already exists", "photoproduct", command.history_seed, ["history_seed"], invalid=True)
    for key, base, path in zip(keys, parsed, paths):
        target = ("extra_base", base.crossover_id, base.k)
        poses = [p for p in design.nucleotide_transforms if p.target_key() == target]
        if len(poses) > 1 or (lesion is not None and len(poses) != 1):
            _reference("The CPD endpoint requires one unambiguous native pose", "base_key", key, path, invalid=True)
        if lesion is None and not poses:
            pose_id = str(uuid.uuid5(uuid.UUID(command.history_seed), key))
            if any(p.id == pose_id for p in design.nucleotide_transforms):
                _reference("The generated endpoint pose identity collides with an existing pose", "nucleotide_transform",
                           pose_id, ["history_seed"], invalid=True)
    validate_source(design)
    return command


def native_source(design):
    """Independent authoring-only copy; preserve values without model migrations.

    Only an already admitted Design is accepted by the command adapter. No
    physical/reference coordinates, history or presentation enter placement.
    """
    from backend.core.models import Design
    return Design.model_construct(id=design.id, **deepcopy({name: getattr(design, name) for name in _AUTHORING}))
