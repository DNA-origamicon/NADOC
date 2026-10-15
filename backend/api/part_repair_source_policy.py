"""Named command-source admission for the explicit repair upload host.

Reuse command-owned limits and fixed identities without running importers,
solvers or content parsing. Source content remains the native builder's input;
success here is neither construction authority nor a regeneration certificate.
"""

from backend.core.part_repair_sources import RepairSourceError


def admit_descriptor(kind, params, parameter, source):
    if kind == "protein-import" and parameter == "source":
        from backend.api.part_protein_commands import MAX_PROTEIN_SOURCE_BYTES
        limit, expected_format, media = MAX_PROTEIN_SOURCE_BYTES, "pdb", "chemical/x-pdb"
    elif kind == "aptamer-import" and parameter == "source":
        from backend.api.part_aptamer_commands import MAX_APTAMER_SOURCE_BYTES
        limit, expected_format, media = MAX_APTAMER_SOURCE_BYTES, "pdb", "chemical/x-pdb"
    elif kind == "cadnano-import" and parameter == "source":
        from backend.core.part_cadnano_source import MAX_SOURCE_BYTES
        limit, expected_format, media = MAX_SOURCE_BYTES, "cadnano-v2", "application/json"
    elif kind == "nanoparticle-create" and "quantum_dot_version" in params and parameter == "source":
        from backend.api.part_quantum_dot_commands import MAX_CATALOG_BYTES
        limit, expected_format, media = MAX_CATALOG_BYTES, "quantum-dot-catalog", "application/json"
    elif kind == "nanoparticle-patch" and "coating_version" in params and params.get("action") == "set":
        if parameter == "pdb_source":
            from backend.api.part_streptavidin_commands import _pdb_descriptor
            _pdb_descriptor(source)
            return
        if parameter != "coverage_source":
            raise RepairSourceError("Unsupported named coating input", code="unsupported_source")
        from backend.api.part_streptavidin_commands import MAX_COVERAGE_BYTES
        limit, expected_format, media = MAX_COVERAGE_BYTES, "json", "application/json"
    else:
        raise RepairSourceError("This named command input has no repair-upload contract", code="unsupported_source")
    if source.size_bytes > limit:
        raise RepairSourceError("Source exceeds the selected command's byte allowance", code="source_limit")
    if source.format != expected_format or source.media_type != media:
        raise RepairSourceError("Source format does not satisfy the selected named command input", code="unsupported_source")
