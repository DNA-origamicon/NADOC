"""Small pinned caDNAno Import features, without fabricated construction history.

The complete existing importer/postprocessing pipeline owns topology and
geometry. This adapter bounds input work and normalizes output identity only.
Live route admission is deliberately a separate, measurement-gated increment.
"""

import json
from typing import Annotated, Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from backend.core.feature_identity import identity_factory
from backend.core.part_cadnano_source import MAX_SOURCE_BYTES, parse_source
from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_history_contract import create_empty_part
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.part_input_sources import EmbeddedResolver, InputSource, SourceContractError, verify


KINDS = frozenset({"cadnano-import"})
_Id = Annotated[str, Field(strict=True, min_length=1, max_length=256)]
_OUTPUT_FIELDS = frozenset({"helices", "strands", "lattice_type", "metadata", "overhangs",
                            "cluster_transforms", "crossovers", "forced_ligations"})


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    proof_version: Annotated[StrictInt, Field(ge=1, le=1)] = Field(alias="_proof_version")
    lattice_import_version: StrictInt = Field(ge=1, le=1)
    importer_version: StrictInt = Field(ge=1, le=1)
    source: InputSource
    history_seed: _Id
    identity_policy: Literal["source-content-v1"]
    name_override: str | None = Field(max_length=1_024)

    @model_validator(mode="after")
    def identity_namespace(self):
        UUID(self.history_seed)
        return self


def parse_command(kind, params):
    if kind not in KINDS:
        raise ValueError("Unsupported pinned caDNAno command")
    return ImportRequest.model_validate(params)


def resources(kind, params):
    command = parse_command(kind, params)
    return {"sources": (command.source,), "imports": True}


def _empty_input(design):
    root = design.recipe_root
    if (root is None or root.kind != "empty" or root.version != 1
            or root.source_json is not None or root.source_sha256 is not None
            or design.feature_log or design.feature_log_cursor != -1 or design.feature_log_sub_cursor is not None):
        raise ReferenceResolutionError("caDNAno import requires an explicit empty recipe input",
            code="invalid_selection", references=[{"kind": "recipe_root", "identity": "empty",
                                                     "parameter_path": []}])
    empty = create_empty_part(root.initial_name, root.lattice_type)
    nonempty = sorted(field for field in AUTHORING_FIELDS if getattr(design, field) != getattr(empty, field))
    if nonempty:
        raise ReferenceResolutionError(f"caDNAno import cannot replace existing authored fields: {', '.join(nonempty)}",
            code="invalid_selection", references=[{"kind": "recipe_root", "identity": "empty",
                                                     "parameter_path": []}])


def _source(command, resolver):
    source = command.source
    if source.format != "cadnano-v2" or source.media_type != "application/json":
        raise SourceContractError("caDNAno v1 requires a cadnano-v2 application/json source",
                                  source=source, code="unsupported_source")
    if source.size_bytes > MAX_SOURCE_BYTES:
        raise SourceContractError("caDNAno source exceeds the initial 100 KB contract",
                                  source=source, code="source_limit")
    raw = verify(source, (resolver if resolver is not None else EmbeddedResolver({}))(source))
    return parse_source(raw, source)


def _pipeline(data, command):
    from backend.core.cadnano import import_cadnano
    from backend.core.cluster_autodetect import _autodetect_clusters, with_default_cluster
    from backend.core.conversion_integrity import require_import_integrity
    from backend.core.lattice import autodetect_all_overhangs
    from backend.core.lattice_import_normalization import _recenter_design

    imported, warnings = import_cadnano(data)
    # The established clustering threshold is three distinct helices. With at
    # most one such scaffold there is no bridge ownership/tie-selection branch
    # or multi-scaffold geometry assignment. Do not change those algorithms to
    # obtain a deterministic result for a broader, unqualified source class.
    module_scaffolds = sum(strand.is_scaffold and len({d.helix_id for d in strand.domains}) >= 3
                           for strand in imported.strands)
    if module_scaffolds > 1:
        raise SourceContractError("caDNAno v1 supports at most one module scaffold; multiple-module clustering is unqualified",
                                  source=command.source, code="unsupported_source")
    imported = _recenter_design(imported)
    imported = autodetect_all_overhangs(imported)
    imported = _autodetect_clusters(imported)
    require_import_integrity(imported)
    # Match the route's response bootstrap before identity normalization, so
    # response formatting can never add an unrecorded placement umbrella.
    imported = with_default_cluster(imported)
    if command.name_override is not None:
        imported = imported.copy_with(metadata=imported.metadata.model_copy(update={"name": command.name_override}))
    return imported, warnings


def identity_mapping(imported, command):
    """Map typed output identities after all legacy choices have been made.

    A new source digest deliberately invalidates every output identity. It does
    not guess correspondence from array position, a nearby cell or geometry.
    """
    from backend.core.models import Design, NADOC_SUBDOMAIN_NS
    from backend.core.part_scope_references import identity_index

    empty = Design()
    unexpected = sorted(field for field in AUTHORING_FIELDS - _OUTPUT_FIELDS
                        if getattr(imported, field) != getattr(empty, field))
    if unexpected or any(helix.native_residues for helix in imported.helices):
        raise SourceContractError("caDNAno importer produced fields outside its topology-only contract",
                                  source=command.source, code="unsupported_source")
    records, _ = identity_index(imported)
    namespace = uuid5(UUID(command.history_seed), f"nadoc:cadnano:v1:{command.source.sha256}")
    allocate = identity_factory(namespace)
    mapping, used_keys = {}, set()

    def assign(kind, old, key):
        encoded = json.dumps(key, sort_keys=True, separators=(",", ":"))
        if (kind, encoded) in used_keys:
            raise SourceContractError("caDNAno output has ambiguous identity ownership",
                                      source=command.source, code="unsupported_source")
        used_keys.add((kind, encoded))
        mapping[kind, old] = allocate(kind, [encoded])

    for helix in imported.helices:
        assign("helix", helix.id, helix.id)
    for strand in imported.strands:
        assign("strand", strand.id, strand.id)
    for crossover in imported.crossovers:
        assign("crossover", crossover.id, sorted((half.helix_id, half.index, half.strand.value)
                                                 for half in (crossover.half_a, crossover.half_b)))
    for ligation in imported.forced_ligations:
        assign("forced_ligation", ligation.id, [ligation.three_prime_helix_id, ligation.three_prime_bp,
            ligation.three_prime_direction.value, ligation.five_prime_helix_id, ligation.five_prime_bp,
            ligation.five_prime_direction.value])
    for overhang in imported.overhangs:
        # Inline-overhang prefix is used by later reconciliation. Preserve that
        # functional convention while mapping each explicit typed owner/ref.
        end = next((end for end in ("5p", "3p")
                    if overhang.id == f"ovhg_inline_{overhang.strand_id}_{end}"), None)
        if end is None:
            raise SourceContractError("caDNAno import has an unsupported overhang identity convention",
                                      source=command.source, code="unsupported_source")
        mapped = f"ovhg_inline_{mapping['strand', overhang.strand_id]}_{end}"
        mapping["overhang", overhang.id] = mapped
        if len(overhang.sub_domains) != 1:
            raise SourceContractError("caDNAno import has an unexpected subdomain partition",
                                      source=command.source, code="unsupported_source")
        mapping["sub_domain", overhang.sub_domains[0].id] = str(uuid5(NADOC_SUBDOMAIN_NS, f"{mapped}:whole"))
    for cluster in imported.cluster_transforms:
        family = ("default" if cluster.is_default else "scaffold" if cluster.name.startswith("Scaffold Cluster ")
                  else "geometry" if cluster.name.startswith("Geometry Cluster ") else None)
        if family is None:
            raise SourceContractError("caDNAno import has an unexpected placement cluster family",
                                      source=command.source, code="unsupported_source")
        assign("cluster", cluster.id, [family, sorted(cluster.helix_ids),
            sorted((ref.strand_id, ref.domain_index) for ref in cluster.domain_ids)])
    if mapping.keys() != records.keys():
        raise SourceContractError("caDNAno output contains unclassified identities",
                                  source=command.source, code="unsupported_source")
    return mapping


def evaluate(kind, design, params, *, resolver=None):
    """Return candidate/warnings without publishing a document or reading recovery."""
    from backend.core.part_scope_references import remap_design

    command = parse_command(kind, params)
    _empty_input(design)
    data, _counts = _source(command, resolver)
    imported, warnings = _pipeline(data, command)
    imported = remap_design(imported, identity_mapping(imported, command))
    return design.copy_with(**{field: getattr(imported, field) for field in _OUTPUT_FIELDS}), warnings


def build(kind, design, params, *, resolver=None):
    return evaluate(kind, design, params, resolver=resolver)[0]
