"""Execute a native command on a generated part's explicitly named input subset.

The scope contains references and an identity namespace, never authored objects,
geometry, diffs, or Python. New identities are namespaced after native execution;
existing objects outside the scope survive untouched. This is also used while
compiling a plan, so recording and verification share the same composition rule.
"""

from uuid import UUID

from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.part_scope_references import (
    COLLECTIONS, check_injective, namespace_mapping, referenced_resources,
    remap_design, scope_identity_index as identity_index,
)


def _require_legacy_organization(*designs):
    if any(design.group_organization is not None for design in designs):
        raise NotImplementedError("Generated scope does not support separate group organization")


def map_values(value, mapping):
    """Historical string mapping, used only to check old receipt equivalence."""
    if isinstance(value, str):
        return mapping.get(value, value)
    if isinstance(value, list):
        return [map_values(v, mapping) for v in value]
    if isinstance(value, dict):
        return {k: map_values(v, mapping) for k, v in value.items()}
    return value


def _legacy_identifiers(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "id" and isinstance(child, str):
                yield child
            else:
                yield from _legacy_identifiers(child)
    elif isinstance(value, list):
        for child in value:
            yield from _legacy_identifiers(child)


def namespaced(identifier, group_id):
    prefix = next((p for p in ("__np__", "__strep_dna__", "join_") if identifier.startswith(p)), "")
    return f"{prefix}gen_{group_id}_{identifier}"


def merge_changes(destination, before, after, *, require_legacy_order=False):
    """Compose native selected subsequences without reordering independent work.

    Fill the old selection's slots with the native after-order. Removed slots
    disappear and surplus native records append after the existing list. Thus
    selected order is exact while independent records keep their relative order.
    """
    _require_legacy_organization(destination, before, after)
    changes = {}
    for field in AUTHORING_FIELDS:
        prior, values = getattr(before, field), getattr(after, field)
        if prior == values:
            continue
        if not isinstance(prior, list) or not isinstance(values, list):
            raise ValueError(
                f"Generated native command cannot change global field {field}"
            )
        if not all(hasattr(v, "id") for v in [*prior, *values]):
            raise ValueError(f"Generated native command cannot compose {field}")
        old, new = {v.id: v for v in prior}, {v.id: v for v in values}
        current = getattr(destination, field)
        current_ids = {v.id for v in current}
        collisions = (new.keys() - old.keys()) & current_ids
        if collisions:
            raise ValueError(f"Generated identity already exists in {field}")
        if old.keys() - current_ids:
            raise ValueError(f"Generated composition source is missing in {field}")
        ordered = iter(values)
        composed = []
        for model in current:
            if model.id not in old:
                composed.append(model)
            else:
                replacement = next(ordered, None)
                if replacement is not None:
                    composed.append(replacement)
        composed.extend(ordered)
        if require_legacy_order:
            removed = old.keys() - new.keys()
            historical_ids = [model.id for model in current if model.id not in removed]
            historical_ids += [identity for identity in new if identity not in current_ids]
            if [model.id for model in composed] != historical_ids:
                raise NotImplementedError("Legacy generated scope requires an explicit version-2 ordering upgrade")
        changes[field] = composed
    merged = destination.copy_with(**changes)
    identity_index(merged)  # Also reject collisions in nested owned identities.
    old_records, _ = identity_index(before)
    new_records, _ = identity_index(after)
    removed_resources = old_records.keys() - new_records.keys()
    if removed_resources:
        # A scope may not leave an outside dependent dangling when it deletes a
        # retained source. This scan is needed only for identity removals, never
        # for ordinary append-only construction or unscoped commands.
        for field in COLLECTIONS:
            for model in getattr(merged, field):
                dangling = referenced_resources(model) & removed_resources
                if dangling:
                    resource, identity = sorted(dangling)[0]
                    raise _missing("Generated command would leave an existing dependent without its source", resource, identity)
    return merged


def _missing(detail, kind, identity):
    return ReferenceResolutionError(detail, references=[{
        "kind": kind, "identity": identity,
        "parameter_path": ["_generated_scope", "input_ids"],
    }])


def _selection(design, group, input_ids):
    _require_legacy_organization(design)
    records, owners = identity_index(design)
    if not isinstance(input_ids, list) or any(not isinstance(i, str) for i in input_ids):
        raise ValueError("Generated scope requires object references")
    if len(input_ids) != len(set(input_ids)):
        raise ValueError("Generated scope repeats an input reference")
    requested = set(input_ids)
    missing = requested - {identity for _, identity in records}
    if missing:
        raise _missing("Generated command source object is missing", "object", sorted(missing)[0])
    retained = {key for key in records if key[1] in requested}
    # Retaining a top-level owner retains its nested identities too. Naming a
    # nested object alone does not silently select the rest of its owner.
    retained |= {key for key, owner in owners.items() if owner in retained}
    inverse = {}
    prefix = f"gen_{group}_"
    markers = (prefix, f"__np__{prefix}", f"__strep_dna__{prefix}", f"join_{prefix}")
    for key in records.keys() - retained:
        for marker in markers:
            if key[1].startswith(marker):
                inverse[key] = key[1][len(marker):]
                break
    # Functional synthetic IDs follow their owner instead of receiving an
    # independent namespace. No substring rewriting of arbitrary IDs or text.
    for (kind, identity), local in list(inverse.items()):
        if kind == "overhang_connection":
            for child_kind, suffix in (("helix", ""), ("strand", "__a"), ("strand", "__b"), ("strand", "__s")):
                key = child_kind, f"__lnk__{identity}{suffix}"
                if key in records and key not in retained:
                    inverse[key] = f"__lnk__{local}{suffix}"
    selected = retained | inverse.keys()
    for key in selected:
        if owners[key] not in selected:
            raise _missing("Generated nested reference requires its top-level owner", *owners[key])
    selected |= {key for key, owner in owners.items() if owner in selected}
    local_ids = {key: inverse.get(key, key[1]) for key in selected}
    # Typed injectivity preserves independent families sharing textual IDs,
    # while retaining the wrong-object alias guard within each resource family.
    check_injective(local_ids)
    # This view never reaches a builder. remap_design creates an independent
    # authoring-only Design immediately; avoid copying history/physical payloads.
    local = design.model_copy(update={
        field: [model for model in getattr(design, field) if (kind, model.id) in selected]
        for field, kind in COLLECTIONS.items()
    })
    return local, local_ids, retained


def _legacy_equivalent(source, mapped, mapping):
    """Old receipts are usable only if the corrected semantics are identical."""
    data = source.model_dump(mode="json", include=AUTHORING_FIELDS)
    records, _ = identity_index(source)
    flat = {}
    for (kind, identity), target in mapping.items():
        if identity in flat and flat[identity] != target:
            raise NotImplementedError("Legacy generated scope requires an explicit version-2 identity/reference upgrade")
        flat[identity] = target
    if (set(_legacy_identifiers(data)) - {identity for _, identity in records}
            or map_values(data, flat) != mapped.model_dump(mode="json", include=AUTHORING_FIELDS)):
        raise NotImplementedError("Legacy generated scope requires an explicit version-2 identity/reference upgrade")


def execute(kind, design, params, executor):
    _require_legacy_organization(design)
    scope = params["_generated_scope"]
    if not isinstance(scope, dict) or set(scope) not in (
        {"group_id", "input_ids"}, {"version", "group_id", "input_ids"}
    ):
        raise ValueError("Invalid generated command scope")
    version = scope.get("version", 1)
    if type(version) is not int or version not in {1, 2}:
        raise NotImplementedError("Unsupported generated scope version")
    group = str(UUID(scope["group_id"]))
    local, inverse, retained = _selection(design, group, scope["input_ids"])
    before = remap_design(local, inverse)
    if version == 1:
        _legacy_equivalent(local, before, inverse)
    arguments = {
        k: v for k, v in params.items() if k not in {"_generated_scope", "_generator"}
    }
    after = executor(kind, before, arguments)
    mapping = {**namespace_mapping(before, group, retained),
               **namespace_mapping(after, group, retained)}
    mapping.update({(resource, raw): original for (resource, original), raw in inverse.items()})
    check_injective(mapping)

    def mapped(model):
        result = remap_design(model, mapping)
        if version == 1:
            _legacy_equivalent(model, result, mapping)
        return result

    return merge_changes(design, mapped(before), mapped(after), require_legacy_order=version == 1)
