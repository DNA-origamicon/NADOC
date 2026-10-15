"""Replay discrete flexible-connection choices without supplying geometry.

Native derivation owns the connection, contour length and bead path. A preview
only records which rigid anchor came first and the connection list order. Replay
resolves those nucleotide references and preserves that same displayed choice,
independently of Python set ordering or the newly derived connection hash.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from backend.core.part_command_errors import ReferenceResolutionError


class _AnchorChoice(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    helix_id: str = Field(min_length=1)
    bp_index: int
    direction: Literal["FORWARD", "REVERSE"]


class _ConnectionChoice(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    anchor_a: _AnchorChoice
    anchor_b: _AnchorChoice
    component_helix_ids: list[str] | None = Field(default=None, min_length=1)


_CHOICES = TypeAdapter(list[_ConnectionChoice])


def _reference(kind, identity, path):
    return {"kind": kind, "identity": identity, "parameter_path": path}


def _anchor_key(anchor):
    return anchor.helix_id, anchor.bp_index, anchor.direction


def _native_anchor(anchor, strands, helices, path):
    strand = strands.get(anchor.strand_id)
    if strand is None:
        raise ReferenceResolutionError(
            "Flexible anchor strand is missing",
            references=[_reference("strand", anchor.strand_id, path)],
        )
    if not 0 <= anchor.domain_index < len(strand.domains):
        raise ReferenceResolutionError(
            "Flexible anchor domain is missing",
            references=[_reference(
                "domain", f"{strand.id}:{anchor.domain_index}", path
            )],
        )
    domain = strand.domains[anchor.domain_index]
    reference = _reference("helix", domain.helix_id, path + ["helix_id"])
    if domain.helix_id not in helices:
        raise ReferenceResolutionError(
            "Flexible anchor helix is missing", references=[reference]
        )
    if (
        anchor.direction != domain.direction
        or not min(domain.start_bp, domain.end_bp)
        <= anchor.bp_index <= max(domain.start_bp, domain.end_bp)
    ):
        raise ReferenceResolutionError(
            "Flexible anchor no longer identifies a nucleotide in its domain",
            code="invalid_selection", references=[reference],
        )
    return _AnchorChoice(
        helix_id=domain.helix_id, bp_index=anchor.bp_index,
        direction=anchor.direction.value,
    )


def _native_choices(design):
    strands = {strand.id: strand for strand in design.strands}
    helices = {helix.id for helix in design.helices}
    if len(strands) != len(design.strands) or len(helices) != len(design.helices):
        raise ReferenceResolutionError(
            "Flexible anchor identities are ambiguous", code="invalid_selection",
            references=[],
        )
    result = []
    for index, connection in enumerate(design.flexible_connections):
        path = ["flexible_choices", index]
        a = _native_anchor(connection.anchor_a, strands, helices, path + ["anchor_a"])
        b = _native_anchor(connection.anchor_b, strands, helices, path + ["anchor_b"])
        component = {
            _native_anchor(anchor, strands, helices, path + ["component_helix_ids"]).helix_id
            for anchor in connection.segment_bead_keys
        }
        if _anchor_key(a) == _anchor_key(b) or not component:
            raise ReferenceResolutionError(
                "Flexible component has no distinct endpoint pair or bead path",
                code="invalid_selection", references=[],
            )
        result.append(_ConnectionChoice(
            anchor_a=a, anchor_b=b, component_helix_ids=sorted(component)
        ))
    return result


def capture_flexible_choices(design):
    """Capture the actual preview's reference-only endpoint and list choices."""
    choices = [choice.model_dump(mode="json") for choice in _native_choices(design)]
    # Reject previews whose references could not distinguish their components
    # during replay; never mint an apparently valid ambiguous receipt.
    apply_flexible_choices(design, choices)
    return choices


def apply_flexible_choices(design, choices):
    """Orient fresh native components and order them by uniquely resolved choices.

    Swapping endpoints also reverses the native bead path. Nothing about its
    membership, contour, identity, coordinates, topology or cluster pose is
    supplied by the choice or changed here. Missing choices never select a
    default or cause a native component to be silently omitted.
    """
    try:
        parsed = _CHOICES.validate_python(choices, strict=True)
    except ValidationError as exc:
        raise ReferenceResolutionError(
            "Malformed flexible orientation choices", code="invalid_selection",
            references=[_reference(
                "selection", "flexible_choices", ["flexible_choices", *error["loc"]]
            ) for error in exc.errors()],
        ) from exc

    native = _native_choices(design)
    endpoint_index, component_index = {}, {}
    for index, candidate in enumerate(native):
        endpoints = frozenset((_anchor_key(candidate.anchor_a), _anchor_key(candidate.anchor_b)))
        endpoint_index.setdefault(endpoints, []).append(index)
        component_index.setdefault(
            (endpoints, frozenset(candidate.component_helix_ids)), []
        ).append(index)
    used, ordered = set(), []
    for index, choice in enumerate(parsed):
        path = ["flexible_choices", index]
        references = [
            _reference("helix", anchor.helix_id, path + [key, "helix_id"])
            for key, anchor in (("anchor_a", choice.anchor_a), ("anchor_b", choice.anchor_b))
        ]
        a, b = _anchor_key(choice.anchor_a), _anchor_key(choice.anchor_b)
        component = choice.component_helix_ids
        if a == b or (component is not None and (
            any(not identity for identity in component)
            or len(set(component)) != len(component)
        )):
            raise ReferenceResolutionError(
                "Flexible choice requires distinct endpoints and component identities",
                code="invalid_selection", references=references,
            )
        endpoints = frozenset((a, b))
        matches = (
            endpoint_index.get(endpoints, []) if component is None
            else component_index.get((endpoints, frozenset(component)), [])
        )
        if not matches:
            raise ReferenceResolutionError(
                "Flexible endpoint/component choice no longer resolves",
                references=references + [
                    _reference("helix", identity, path + ["component_helix_ids", i])
                    for i, identity in enumerate(component or [])
                ],
            )
        if len(matches) != 1 or matches[0] in used:
            raise ReferenceResolutionError(
                "Flexible endpoint/component choice is ambiguous or repeated",
                code="invalid_selection", references=references,
            )
        match = matches[0]
        used.add(match)
        connection = design.flexible_connections[match]
        if a != _anchor_key(native[match].anchor_a):
            connection = connection.model_copy(update={
                "cluster_a_id": connection.cluster_b_id,
                "cluster_b_id": connection.cluster_a_id,
                "anchor_a": connection.anchor_b,
                "anchor_b": connection.anchor_a,
                "segment_bead_keys": list(reversed(connection.segment_bead_keys)),
            })
        ordered.append(connection)
    if len(used) != len(native):
        raise ReferenceResolutionError(
            "Flexible orientation choices do not cover every native component",
            references=[_reference(
                "flexible_connection", connection.id, ["flexible_choices"]
            ) for i, connection in enumerate(design.flexible_connections) if i not in used],
        )
    return design.copy_with(flexible_connections=ordered)
