"""Explicit identity/reference schema for independently composed part commands.

Only declared model fields participate. Text and arbitrary metadata never become
references because their value happens to equal an ID. New model fields or
unclassified selected families fail closed until their semantics are reviewed.
"""

from dataclasses import dataclass
from functools import cached_property

from backend.core import models
from backend.core.base_keys import parse_base_key
from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.part_saved_topology import remap_snapshot, snapshot_for, validate_owner


@dataclass(frozen=True)
class Schema:
    identity: str | None
    refs: dict
    children: frozenset
    plain: frozenset
    special: frozenset
    blocked: frozenset

    @cached_property
    def fields(self):
        return (self.refs.keys() | self.children | self.plain | self.special
                | self.blocked | ({"id"} if self.identity else set()))


SCHEMAS = {}


def _schema(name, identity=None, *, refs=None, children="", plain="", special="", blocked=""):
    SCHEMAS[getattr(models, name)] = Schema(
        identity, refs or {}, frozenset(children.split()), frozenset(plain.split()),
        frozenset(special.split()), frozenset(blocked.split()),
    )


_schema("Dimension", "dimension", plain="name a b visible")
_schema("LatticeFrame", "lattice_frame", refs={"placement_cluster_id": "cluster"}, plain="plane")
_schema("Helix", "helix", refs={"lattice_frame_id": "lattice_frame"},
        plain="axis_start axis_end native_residues native_source phase_offset twist_per_bp_rad length_bp bp_start loop_skips label grid_pos direction")
_schema("Strand", "strand", children="domains routing_seed",
        plain="strand_type sequence custom_scaffold_length color name notes is_reference")
_schema("Domain", refs={"helix_id": "helix", "overhang_id": "overhang", "binds_overhang_id": "overhang"},
        plain="start_bp end_bp direction")
_schema("SubDomain", "sub_domain", plain="name color start_bp_offset length_bp sequence_override rotation_theta_deg rotation_phi_deg notes tm_celsius gc_percent hairpin_warning dimer_warning")
_schema("OverhangSpec", "overhang", children="sub_domains",
        refs={"helix_id": "helix", "strand_id": "strand", "parent_overhang_id": "overhang"},
        plain="sequence label rotation pivot translation auxiliary_endpoint", blocked="strand_anim_setup")
_schema("OverhangConnection", "overhang_connection",
        refs={"overhang_a_id": "overhang", "overhang_b_id": "overhang", "target_joint_id": "joint"},
        plain="name overhang_a_attach overhang_b_attach linker_type length_value length_unit bridge_relaxed bridge_bin_index bridge_r_ee_min_nm bridge_r_ee_max_nm bridge_sequence unbound_angle_deg bound_angle_deg")
_schema("OverhangBinding", "overhang_binding",
        refs={"sub_domain_a_id": "sub_domain", "sub_domain_b_id": "sub_domain", "overhang_a_id": "overhang", "overhang_b_id": "overhang", "target_joint_id": "joint", "driver_oh_id": "overhang", "driven_oh_id": "overhang"},
        plain="name created_at bound binding_mode locked_angle_deg prior_min_angle_deg prior_max_angle_deg allow_n_wildcard unbound_angle_deg bound_angle_deg connection_type",
        special="prior_driven_topology")
_schema("ConnectionVersion", "connection_version", refs={"overhang_a_id": "overhang", "overhang_b_id": "overhang"},
        plain="name created_at connection_type overhang_a_seq overhang_b_seq bridge_length bridge_seq applied")
_schema("Duplex", "duplex", refs={"target_joint_id": "joint"}, children="left right",
        plain="name created_at driver bound binding_mode allow_n_wildcard locked_angle_deg connection_type", special="prior_driven_topology")
_schema("DuplexEnd", refs={"overhang_id": "overhang"}, plain="start_bp end_bp")
_schema("ClusterRigidTransform", "cluster", children="domain_ids",
        refs={"helix_ids": "helix", "parent_cluster_id": "cluster", "overhang_duplex_driver_id": "overhang"},
        plain="name is_default translation rotation pivot color opacity auto_created")
_schema("DomainRef", refs={"strand_id": "strand"}, plain="domain_index")
_schema("ClusterJoint", "joint", refs={"cluster_id": "cluster"},
        plain="name joint_type local_axis_origin local_axis_direction surface_detail min_angle_deg max_angle_deg")
_schema("ClusterJoinConstraint", "join_constraint", children="first second", plain="reach_nm")
_schema("JoinAttachment", refs={"cluster_id": "cluster"}, children="source target")
_schema("JoinEndpoint", refs={"helix_id": "helix"}, plain="bp_index direction")
_schema("Crossover", "crossover", children="half_a half_b", plain="extra_bases process_id")
_schema("HalfCrossover", refs={"helix_id": "helix"}, plain="index strand")
_schema("CrossoverConstraint", "crossover_constraint", refs={"helix_ids_a": "helix", "helix_ids_b": "helix"}, plain="allowed_bp_intervals")
_schema("ForcedLigation", "forced_ligation", refs={"three_prime_helix_id": "helix", "five_prime_helix_id": "helix"},
        plain="three_prime_bp three_prime_direction five_prime_bp five_prime_direction extra_bases is_periodic_seam")
_schema("StrandExtension", "extension", refs={"strand_id": "strand"}, plain="end sequence modification label")
_schema("StapleGroup", "staple_group", refs={"strand_ids": "strand"}, plain="name color")
_schema("FlexibleSegmentMark", "flexible_mark", refs={"strand_id": "strand"}, plain="domain_index bp_index direction")
_schema("FlexibleConnection", "flexible_connection", refs={"cluster_a_id": "cluster", "cluster_b_id": "cluster"},
        children="anchor_a anchor_b segment_bead_keys", plain="n_ss_bases contour_length_nm")
_schema("FlexibleAnchor", refs={"strand_id": "strand"}, plain="domain_index bp_index direction")
_schema("NucleotideTransform", "nucleotide_transform", refs={"helix_id": "helix", "crossover_id": "crossover"},
        plain="kind bp_index direction copy_k extra_base_k pivot translation rotation")
_schema("DeformationOp", "deformation", refs={"affected_helix_ids": "helix", "cluster_ids": "cluster"},
        children="target_ranges params", special="targets", plain="type plane_a_bp plane_b_bp")
_schema("DeformationRange", refs={"helix_id": "helix", "strand_id": "strand"}, plain="start_bp end_bp direction domain_index")
_schema("TwistParams", plain="kind total_degrees degrees_per_nm")
_schema("BendParams", plain="kind curvature_deg_per_bp direction_deg endpoints midpoint polymer_circle_count")
_schema("SweepParams", refs={"preceding_op_ids": "deformation"},
        plain="kind points_nm origin_nm initial_rotation initial_tangent point_frames warning_bps auto_loop_skips loop_skip_warnings direction start_step steps path_length_nm bp_positions_nm bp_frames")
_schema("PhotoproductJunction", "photoproduct", special="base_key_1 base_key_2 design_coordinates context_coordinates",
        plain="product stereochemistry formation patch_order orientation_method photoproduct_id",
        blocked="t1_stable_id t2_stable_id bond_relaxation")
_schema("ProteinAsset", "protein_asset",
        plain="name source_filename atoms bonds default_conjugation_atom_serial center_of_mass metadata")
_schema("ProteinAttachment", "protein_attachment", refs={"asset_id": "protein_asset", "binder_strand_id": "strand"},
        children="target", plain="conjugation_atom_serial conjugation_chemistry conjugation_accessible_fraction azide_end pose handle_complement_bp handle_spacer_nt handle_sequence visible")
_schema("ProteinTargetDesign", refs={"overhang_id": "overhang"}, plain="kind attach_end")
_schema("ProteinTargetFree", plain="kind")
_schema("Nanoparticle", "nanoparticle", children="biotin_dna",
        plain="kind diameter_nm pose visible quantum_dot coating oxdna_fixed_core")
_schema("BiotinDNA", refs={"strand_id": "strand", "helix_id": "helix"},
        plain="tetramer_index placement_version chain linker_nm linker_chemistry")
_schema("NanoparticleConjugation", "nanoparticle_conjugation", refs={"nanoparticle_id": "nanoparticle"},
        children="surface_strands", plain="scheme sequence attach_end spacer_nm requested_count estimated_capacity density_per_nm2 distribution_seed model_version literature_key")
_schema("NanoparticleSurfaceStrand", refs={"strand_id": "strand", "helix_id": "helix", "overhang_id": "overhang", "bound_overhang_id": "overhang"},
        plain="site_local sulfur_local_nm backbone_attachment_local_nm")
_schema("NanoparticleConnectionVersion", "nanoparticle_connection_version",
        refs={"nanoparticle_id": "nanoparticle", "strand_id": "strand", "overhang_id": "overhang", "duplex_id": "duplex"},
        plain="name created_at connection_type direct_variant nanoparticle_attach target_attach applied relaxed residual_nm constraint_root_nm constraint_radius_nm")

# Model field declarations are fixed at import. Check source/schema evolution
# once, not once per domain at every composition step; still fail on first use
# of an unclassified class rather than weakening the selected-record contract.
_UNCLASSIFIED_MODELS = frozenset(
    model for model, schema in SCHEMAS.items() if set(model.model_fields) != schema.fields
)


# Asset references are mapped for retained inputs. This is not a native asset
# creation/reproducibility contract; that separate P4 admission remains explicit.
COLLECTIONS = {
    "dimensions": "dimension", "lattice_frames": "lattice_frame", "helices": "helix",
    "strands": "strand", "deformations": "deformation", "cluster_transforms": "cluster",
    "nucleotide_transforms": "nucleotide_transform", "cluster_joints": "joint",
    "cluster_join_constraints": "join_constraint", "overhangs": "overhang",
    "overhang_connections": "overhang_connection", "overhang_bindings": "overhang_binding",
    "connection_versions": "connection_version", "duplexes": "duplex",
    "flexible_segment_marks": "flexible_mark", "flexible_connections": "flexible_connection",
    "protein_assets": "protein_asset", "protein_attachments": "protein_attachment",
    "nanoparticles": "nanoparticle", "nanoparticle_conjugations": "nanoparticle_conjugation",
    "nanoparticle_connection_versions": "nanoparticle_connection_version",
    "extensions": "extension", "staple_groups": "staple_group",
    "photoproduct_junctions": "photoproduct", "crossovers": "crossover",
    "crossover_constraints": "crossover_constraint", "forced_ligations": "forced_ligation",
}
GLOBALS = frozenset({"lattice_type", "metadata", "tm_settings"})


def _issue(detail, kind, identity, *, code="missing_reference"):
    return ReferenceResolutionError(detail, code=code, references=[{
        "kind": kind, "identity": identity,
        "parameter_path": ["_generated_scope", "input_ids"],
    }])


def _schema_for(model):
    model_type = type(model)
    schema = SCHEMAS.get(model_type)
    if schema is None:
        raise NotImplementedError(f"Generated scope has no reference contract for {type(model).__name__}")
    if model_type in _UNCLASSIFIED_MODELS:
        raise NotImplementedError(f"Generated scope has unclassified fields on {type(model).__name__}")
    for field in schema.blocked:
        if getattr(model, field):
            raise NotImplementedError(f"Generated scope has no reference contract for {type(model).__name__}.{field}")
    return schema


def identity_index(design):
    """Index typed record identities and their top-level owners, never metadata."""
    if set(COLLECTIONS) | GLOBALS != AUTHORING_FIELDS:
        raise NotImplementedError("Generated scope has unclassified authoring fields")
    records, owners = {}, {}
    for field, kind in COLLECTIONS.items():
        for model in getattr(design, field):
            key = (kind, model.id)
            entries = [(key, model)]
            if isinstance(model, models.OverhangSpec):
                entries += [(('sub_domain', sub.id), sub) for sub in model.sub_domains]
            for identity, record in entries:
                if identity in records:
                    raise _issue("Generated scope has duplicate typed identities", *identity, code="invalid_selection")
                records[identity], owners[identity] = record, key
    return records, owners


def scope_identity_index(design):
    """Reserve restorable identities without presenting them as live geometry."""
    records, owners = identity_index(design)
    live = set(records)
    for owner in [*design.overhang_bindings, *design.duplexes]:
        owner_key = ("duplex" if isinstance(owner, models.Duplex) else "overhang_binding", owner.id)
        try:
            snapshot = snapshot_for(owner)
        except NotImplementedError:
            # Unsupported restoration state outside a selection stays legacy.
            # A selected owner is parsed strictly by remap_design below.
            continue
        if snapshot is None:
            continue
        for key, definition in snapshot.definitions():
            if key in live:
                continue
            if key in records and owners[key] != owner_key:
                raise NotImplementedError("Saved topology has ambiguous historical identity ownership")
            records[key], owners[key] = definition, owner_key
    return records, owners


def linker_owners(records):
    """Canonical linker identities are derived from the connection owner."""
    possible = {}
    for kind, identity in records:
        if kind == "overhang_connection":
            possible[("helix", f"__lnk__{identity}")] = (identity, "")
            for suffix in ("__a", "__b", "__s"):
                possible[("strand", f"__lnk__{identity}{suffix}")] = (identity, suffix)
    result = {}
    for key in records:
        if key[0] in {"helix", "strand"} and key[1].startswith("__lnk__"):
            if key not in possible:
                raise _issue("Generated linker is missing its connection owner", *key)
            result[key] = possible[key]
    return result


def check_injective(mapping):
    destinations = [(kind, target) for (kind, _), target in mapping.items()]
    if len(destinations) != len(set(destinations)):
        raise ValueError("Generated scope identity aliases are ambiguous")


def _base_key(key, reference):
    parsed = parse_base_key(key)
    if parsed is None or parsed.family == "extension":
        raise NotImplementedError("Generated scope requires a supported canonical nucleotide key")
    if parsed.crossover_id is not None:
        owner = reference("crossover", parsed.crossover_id)
        return f"__xb__:{owner}:{key.rpartition(':')[2]}"
    owner = reference("helix", parsed.helix_id)
    return owner + key[len(parsed.helix_id):]


def _targets(targets, reference):
    if targets is None:
        return None
    result = []
    for target in targets:
        kind = target.get("kind")
        value = dict(target)
        if kind in {"cluster", "strand"} and set(target) == {"kind", "id"}:
            value["id"] = reference(kind, target["id"])
        elif kind == "domain" and set(target) in (
            {"kind", "strandId", "domainIndex"}, {"kind", "strand_id", "domain_index"}
        ):
            field = "strandId" if "strandId" in target else "strand_id"
            value[field] = reference("strand", target[field])
        else:
            raise NotImplementedError("Generated scope has an unsupported deformation selection")
        result.append(value)
    return result


def referenced_resources(model):
    """Return typed outgoing references using the same fail-closed schema."""
    references = set()

    def reference(kind, identity):
        if identity is not None:
            references.add((kind, identity))
        return identity

    def visit(value):
        schema = _schema_for(value)
        # These identities encode a real ownership reference even though no
        # explicit owner field exists on the Helix/Strand model.
        if isinstance(value, (models.Helix, models.Strand)) and value.id.startswith("__lnk__"):
            owner = value.id[len("__lnk__"):]
            if isinstance(value, models.Strand):
                suffix = next((suffix for suffix in ("__a", "__b", "__s") if owner.endswith(suffix)), None)
                if suffix is None:
                    raise NotImplementedError("Generated scope has an unsupported linker strand identity")
                owner = owner[:-len(suffix)]
            reference("overhang_connection", owner)
        for field, kind in schema.refs.items():
            child = getattr(value, field)
            for identity in child if isinstance(child, list) else [child]:
                reference(kind, identity)
        for field in schema.children:
            child = getattr(value, field)
            for item in child if isinstance(child, list) else [child]:
                if item is not None:
                    visit(item)
        if isinstance(value, models.DeformationOp):
            _targets(value.targets, reference)
        if isinstance(value, models.PhotoproductJunction):
            for key in [value.base_key_1, value.base_key_2, *value.design_coordinates, *value.context_coordinates]:
                _base_key(key, reference)
        snapshot = snapshot_for(value)
        if snapshot is not None:
            for field in ("driver_oh_id", "driven_oh_id"):
                reference("overhang", snapshot.value[field])
            reference("strand", snapshot.value["strand_id"])
            saved = {key for key, _ in snapshot.definitions()}
            for _, definition in snapshot.definitions():
                # Saved definitions own their historical references. External
                # dependencies still participate in incoming-removal checks.
                references.update(referenced_resources(definition) - saved)

    visit(model)
    return frozenset(references)


def remap_design(design, mapping):
    """Map declared references and require complete ownership/dependency closure."""
    records, _ = identity_index(design)
    scoped_records, _ = scope_identity_index(design)
    check_injective({key: mapping.get(key, key[1]) for key in scoped_records})

    def reference(kind, identity):
        if identity is None:
            return None
        key = kind, identity
        if key not in records:
            raise _issue("Generated scope omits a required referenced object", kind, identity)
        return mapping.get(key, identity)

    def mapped(model, resolve=reference):
        schema = _schema_for(model)
        result = model.model_dump(mode="json")
        if schema.identity:
            result["id"] = resolve(schema.identity, model.id)
        for field, kind in schema.refs.items():
            value = getattr(model, field)
            result[field] = ([resolve(kind, item) for item in value]
                             if isinstance(value, list) else resolve(kind, value))
        for field in schema.children:
            value = getattr(model, field)
            result[field] = ([mapped(item, resolve) for item in value] if isinstance(value, list)
                             else mapped(value, resolve) if value is not None else None)
        if isinstance(model, models.DeformationOp):
            result["targets"] = _targets(model.targets, resolve)
        if isinstance(model, models.PhotoproductJunction):
            for field in ("base_key_1", "base_key_2"):
                result[field] = _base_key(getattr(model, field), resolve)
            result["context_coordinates"] = {
                _base_key(key, resolve): atoms for key, atoms in model.context_coordinates.items()
            }
            result["design_coordinates"] = {
                _base_key(key, resolve): atoms for key, atoms in model.design_coordinates.items()
            }
        snapshot = snapshot_for(model)
        if snapshot is not None:
            validate_owner(snapshot, records)
            saved = {key for key, _ in snapshot.definitions()}

            def historical(kind, identity):
                if (kind, identity) in saved:
                    return mapping.get((kind, identity), identity)
                return reference(kind, identity)

            result["prior_driven_topology"] = remap_snapshot(snapshot, reference, historical, mapped)
        return result

    # A dangling canonical linker must not become an apparently ordinary helix.
    for key, (owner, suffix) in linker_owners(scoped_records).items():
        expected = f"__lnk__{reference('overhang_connection', owner)}{suffix}"
        if mapping.get(key, key[1]) != expected:
            raise _issue("Generated linker identity disagrees with its connection owner", *key, code="invalid_selection")
    data = design.model_dump(mode="json", include=GLOBALS)
    data.update({field: [mapped(model) for model in getattr(design, field)] for field in COLLECTIONS})
    # External input hashes are immutable source identities, not generated
    # geometry IDs. Each local replay needs the captured table; copy its mutable
    # mapping while retaining the frozen byte records without serialization.
    data["input_sources"] = dict(design.input_sources)
    return models.Design.model_validate(data)


def namespace_mapping(design, group, retained=()):
    """Allocate typed IDs, deriving linker children from their allocated owner."""
    records, owners = scope_identity_index(design)
    retained = set(retained)
    retained |= {key for key, owner in owners.items() if owner in retained}
    mapping = {}
    for key in records:
        identifier = key[1]
        prefix = next((p for p in ("__np__", "__strep_dna__", "join_") if identifier.startswith(p)), "")
        mapping[key] = identifier if key in retained else f"{prefix}gen_{group}_{identifier}"
    for key, (owner, suffix) in linker_owners(records).items():
        expected = f"__lnk__{mapping['overhang_connection', owner]}{suffix}"
        if key in retained and mapping[key] != expected:
            raise _issue("Retained linker requires its retained connection owner", *key)
        mapping[key] = expected
    check_injective(mapping)
    return mapping


def namespace_design(design, group, retained_ids=()):
    records, _ = scope_identity_index(design)
    retained_ids = set(retained_ids)
    retained = {key for key in records if key[1] in retained_ids}
    return remap_design(design, namespace_mapping(design, group, retained))
