"""Pinned scadnano imports preserve the established full topology pipeline."""

from typing import Literal

from backend.api import part_cadnano_commands as lattice_commands
from backend.core.part_input_sources import EmbeddedResolver, SourceContractError, verify
from backend.core.part_scadnano_source import MAX_SOURCE_BYTES, parse_source


KINDS = frozenset({"scadnano-import"})
_OUTPUT_FIELDS = lattice_commands._OUTPUT_FIELDS | {"extensions"}


class ImportRequest(lattice_commands.ImportRequest):
    # Preserve, and explicitly disclose, the existing importer's losses. This
    # is not permission to invent conversion choices during replay.
    loss_policy: Literal["existing-importer-v1"]


def parse_command(kind, params):
    if kind not in KINDS:
        raise ValueError("Unsupported pinned scadnano command")
    return ImportRequest.model_validate(params)


def resources(kind, params):
    command = parse_command(kind, params)
    return {"sources": (command.source,), "imports": True}


def identity_mapping(imported, command):
    return lattice_commands.identity_mapping(imported, command,
        source_format="scadnano", output_fields=_OUTPUT_FIELDS)


def _pipeline(data, command):
    from backend.core.cluster_autodetect import _autodetect_clusters, with_default_cluster
    from backend.core.conversion_integrity import require_import_integrity
    from backend.core.lattice import autodetect_all_overhangs
    from backend.core.lattice_import_normalization import _backfill_overhang_sequences, _recenter_design
    from backend.core.scadnano import import_scadnano

    imported, warnings = import_scadnano(data)
    module_scaffolds = sum(strand.is_scaffold and len({d.helix_id for d in strand.domains}) >= 3
                           for strand in imported.strands)
    if module_scaffolds > 1:
        raise SourceContractError("scadnano v1 supports at most one module scaffold; multiple-module clustering is unqualified",
                                  source=command.source, code="unsupported_source")
    if command.name_override is not None:
        imported = imported.copy_with(metadata=imported.metadata.model_copy(update={"name": command.name_override}))
    imported = autodetect_all_overhangs(imported)
    imported = _backfill_overhang_sequences(imported)
    before = [(h.id, round(h.axis_start.x, 4), round(h.axis_start.y, 4)) for h in imported.helices[:5]]
    imported = _recenter_design(imported)
    after = [(h.id, round(h.axis_start.x, 4), round(h.axis_start.y, 4)) for h in imported.helices[:5]]
    imported = _autodetect_clusters(imported)
    require_import_integrity(imported)
    return with_default_cluster(imported), warnings, (before, after)


def evaluate(kind, design, params, *, resolver=None, include_debug=False):
    from backend.core.part_scope_references import remap_design

    command = parse_command(kind, params)
    lattice_commands._empty_input(design, format_name="scadnano")
    source = command.source
    if source.format != "scadnano" or source.media_type != "application/json":
        raise SourceContractError("scadnano v1 requires a scadnano application/json source",
                                  source=source, code="unsupported_source")
    if source.size_bytes > MAX_SOURCE_BYTES:
        raise SourceContractError("scadnano source exceeds the 100 KB contract",
                                  source=source, code="source_limit")
    raw = verify(source, (resolver if resolver is not None else EmbeddedResolver({}))(source))
    data, _counts = parse_source(raw, source)
    imported, warnings, (before, after) = _pipeline(data, command)
    mapping = identity_mapping(imported, command)
    imported = remap_design(imported, mapping)
    candidate = design.copy_with(**{field: getattr(imported, field) for field in _OUTPUT_FIELDS})
    if include_debug:
        debug = {"recentered": True, "helix_count": len(imported.helices),
            "center_shift": {"x": round(after[0][1] - before[0][1], 4) if before else 0.0,
                             "y": round(after[0][2] - before[0][2], 4) if before else 0.0},
            "sample_axes_before": [{"id": mapping["helix", hid], "x": x, "y": y} for hid, x, y in before],
            "sample_axes_after": [{"id": mapping["helix", hid], "x": x, "y": y} for hid, x, y in after]}
        return candidate, warnings, debug
    return candidate, warnings


def build(kind, design, params, *, resolver=None):
    return evaluate(kind, design, params, resolver=resolver)[0]
