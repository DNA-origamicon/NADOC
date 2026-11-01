"""Reproduce the existing bounded DNA-PDB duplex projection from original bytes.

The converter owns all pairing, axis fitting and atom/bond calculations. This
adapter changes identities only. Original atoms are a display result, not native
authored DNA geometry; original source bytes remain portable recipe evidence.
"""

from dataclasses import replace
from typing import Annotated, Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from backend.api.part_cadnano_commands import _empty_input
from backend.core.feature_identity import identity_factory
from backend.core.part_dna_pdb_source import MAX_SOURCE_BYTES, parse_source
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.part_input_sources import EmbeddedResolver, InputSource, SourceContractError, verify


KINDS = frozenset({"dna-pdb-import"})
OUTPUT_FIELDS = frozenset({"helices", "strands", "lattice_type", "metadata", "cluster_transforms"})


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    proof_version: Annotated[StrictInt, Field(ge=1, le=1)] = Field(alias="_proof_version")
    pdb_import_version: StrictInt = Field(ge=1, le=1)
    importer_version: StrictInt = Field(ge=1, le=1)
    source: InputSource
    history_seed: str = Field(min_length=1, max_length=256)
    identity_policy: Literal["source-content-v1"]
    loss_policy: Literal["existing-duplex-projection-v1"]
    name_override: str | None = Field(max_length=1_024)

    @field_validator("history_seed")
    @classmethod
    def canonical_seed(cls, value):
        if str(UUID(value)) != value:
            raise ValueError("history_seed must be a canonical UUID")
        return value


def parse_command(kind, params):
    if kind not in KINDS:
        raise ValueError("Unsupported DNA PDB command")
    return ImportRequest.model_validate(params)


def resources(kind, params):
    return {"sources": (parse_command(kind, params).source,), "imports": True}


def identity_mapping(imported, command):
    from backend.core.models import Design
    from backend.core.part_scope_references import identity_index
    empty = Design()
    if any(getattr(imported, field) != getattr(empty, field) for field in AUTHORING_FIELDS - OUTPUT_FIELDS):
        raise SourceContractError("DNA PDB converter produced unclassified authored fields",
                                  source=command.source, code="unsupported_source")
    allocate = identity_factory(uuid5(UUID(command.history_seed), f"nadoc:dna-pdb:v1:{command.source.sha256}"))
    # The unchanged converter emits duplexes in sorted source-chain/residue
    # order, then forward/reverse strands. Never use its random IDs as inputs.
    mapping = {("helix", helix.id): allocate("helix", [index]) for index, helix in enumerate(imported.helices)}
    mapping.update({("strand", strand.id): allocate("strand", [index])
                    for index, strand in enumerate(imported.strands)})
    mapping.update({("cluster", cluster.id): allocate("cluster", [index])
                    for index, cluster in enumerate(imported.cluster_transforms)})
    if mapping.keys() != identity_index(imported)[0].keys():
        raise SourceContractError("DNA PDB converter produced unclassified identities",
                                  source=command.source, code="unsupported_source")
    return mapping


def remap_atomistic(model, mapping):
    """Normalize reference/serial ordering only; preserve every coordinate/bond."""
    from backend.core.atomistic import AtomisticModel
    atoms = [replace(atom, helix_id=mapping["helix", atom.helix_id],
                     strand_id=mapping["strand", atom.strand_id]) for atom in model.atoms]
    atoms.sort(key=lambda atom: (atom.strand_id, atom.bp_index if atom.direction == "FORWARD" else -atom.bp_index,
                                atom.name))
    serials = {atom.serial: index for index, atom in enumerate(atoms)}
    return AtomisticModel(atoms=[replace(atom, serial=index) for index, atom in enumerate(atoms)],
        bonds=sorted(tuple(sorted((serials[a], serials[b]))) for a, b in model.bonds), warnings=list(model.warnings))


def evaluate(kind, design, params, *, resolver=None):
    from backend.core.pdb_to_design import import_pdb
    from backend.core.part_scope_references import remap_design
    command = parse_command(kind, params)
    _empty_input(design, format_name="DNA PDB")
    source = command.source
    if source.format != "dna-pdb" or source.media_type != "chemical/x-pdb":
        raise SourceContractError("DNA PDB requires a dna-pdb chemical/x-pdb source",
                                  source=source, code="unsupported_source")
    if source.size_bytes > MAX_SOURCE_BYTES:
        raise SourceContractError("DNA PDB source exceeds 200,000 bytes", source=source, code="source_limit")
    raw = verify(source, (resolver if resolver is not None else EmbeddedResolver({}))(source))
    content, _counts = parse_source(raw, source)
    name = command.name_override if command.name_override is not None else "PDB Import"
    imported, atoms, warnings = import_pdb(content, cluster_name=name)
    mapping = identity_mapping(imported, command)
    imported = remap_design(imported, mapping)
    return design.copy_with(**{field: getattr(imported, field) for field in OUTPUT_FIELDS}), warnings, remap_atomistic(atoms, mapping)


def build(kind, design, params, *, resolver=None):
    return evaluate(kind, design, params, resolver=resolver)[0]
