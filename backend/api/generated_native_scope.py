"""Execute a native command on a generated part's explicitly named input subset.

The scope contains references and an identity namespace, never authored objects,
geometry, diffs, or Python. New identities are namespaced after native execution;
existing objects outside the scope survive untouched. This is also used while
compiling a plan, so recording and verification share the same composition rule.
"""

from uuid import UUID

from backend.core.models import Design
from backend.core.part_history_proof import AUTHORING_FIELDS


def map_values(value, mapping):
    if isinstance(value, str):
        return mapping.get(value, value)
    if isinstance(value, list):
        return [map_values(v, mapping) for v in value]
    if isinstance(value, dict):
        return {k: map_values(v, mapping) for k, v in value.items()}
    return value


def identifiers(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "id" and isinstance(child, str):
                yield child
            else:
                yield from identifiers(child)
    elif isinstance(value, list):
        for child in value:
            yield from identifiers(child)


def namespaced(identifier, group_id):
    prefix = next((p for p in ("__np__", "join_") if identifier.startswith(p)), "")
    return f"{prefix}gen_{group_id}_{identifier}"


def merge_changes(destination, before, after):
    """Compose only native changes to identified lists, preserving other work."""
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
        removed = old.keys() - new.keys()
        changed = {i: v for i, v in new.items() if old.get(i) != v}
        current = getattr(destination, field)
        current_ids = {v.id for v in current}
        collisions = (changed.keys() - old.keys()) & current_ids
        if collisions:
            raise ValueError(f"Generated identity already exists in {field}")
        changes[field] = [changed.get(v.id, v) for v in current if v.id not in removed]
        changes[field] += [v for i, v in changed.items() if i not in current_ids]
    return destination.copy_with(**changes)


def execute(kind, design, params, executor):
    scope = params["_generated_scope"]
    if set(scope) != {"group_id", "input_ids"}:
        raise ValueError("Invalid generated command scope")
    group = str(UUID(scope["group_id"]))
    retained = set(scope["input_ids"])
    if any(not isinstance(i, str) for i in retained):
        raise ValueError("Generated scope requires object references")
    data = design.model_dump(mode="json", include=AUTHORING_FIELDS)
    prefix = f"gen_{group}_"
    inverse = {}
    for identifier in identifiers(data):
        if identifier in retained:
            continue
        for marker in (prefix, f"__np__{prefix}", f"join_{prefix}"):
            if identifier.startswith(marker):
                inverse[identifier] = identifier[len(marker) :]
                break
    # A retained source and a generated object must never become the same
    # local identity. Native lookups and merge dictionaries would otherwise
    # apply an edit to the wrong object or silently discard one of its effects.
    # Different namespace markers must also have distinct inverse identities.
    aliases = list(inverse.values())
    if retained.intersection(aliases) or len(set(aliases)) != len(aliases):
        raise ValueError("Generated scope identity aliases are ambiguous")
    selected = retained | inverse.keys()
    local = {}
    for field, values in data.items():
        if isinstance(values, list):
            local[field] = [
                v for v in values if isinstance(v, dict) and v.get("id") in selected
            ]
        else:
            local[field] = values
    # References may name nested subdomains; require their containing objects
    # through the top-level IDs and verify all references actually exist.
    existing = set(identifiers(data))
    if retained - existing:
        raise ValueError("Generated command source object is missing")
    before = Design.model_validate(map_values(local, inverse))
    arguments = {
        k: v for k, v in params.items() if k not in {"_generated_scope", "_generator"}
    }
    after = executor(kind, before, arguments)
    mapping = {
        i: namespaced(i, group)
        for i in identifiers(after.model_dump(mode="json", include=AUTHORING_FIELDS))
        if i not in retained
    }
    mapping.update({raw: original for original, raw in inverse.items()})

    def mapped(model):
        return Design.model_validate(
            map_values(model.model_dump(mode="json", include=AUTHORING_FIELDS), mapping)
        )

    return merge_changes(design, mapped(before), mapped(after))
