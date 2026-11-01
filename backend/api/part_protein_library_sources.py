"""Original library inputs, carried in the asset's existing metadata envelope.

The session library remains a cache. Placement transfers the existing import
command and EmbeddedInput into the document; replay never reads this cache or
reconstructs a PDB from atoms. Document assets remain ordinary parser outputs.
"""

from backend.api.part_protein_commands import ImportRequest
from backend.core.part_input_sources import EmbeddedInput, decode, describe, embed


SOURCE_KEY = "native_import_input"


def retain_source(asset, raw, *, name, source_filename, exclude_dna):
    source = describe(raw, format="pdb", media_type="chemical/x-pdb")
    command = ImportRequest.model_validate({
        "_proof_version": 1, "protein_version": 1, "importer_version": 1,
        "asset_id": asset.id, "source": source.model_dump(mode="json"),
        "name": name, "source_filename": source_filename, "exclude_dna": exclude_dna,
    })
    return asset.model_copy(update={"metadata": {**asset.metadata, SOURCE_KEY: {
        "command": command.model_dump(mode="json", by_alias=True),
        "input": embed(source, raw).model_dump(mode="json"),
    }}})


def original_input(asset):
    record = asset.metadata.get(SOURCE_KEY)
    if record is None:
        return None
    if type(record) is not dict or set(record) != {"command", "input"}:
        raise ValueError("Protein library import input is malformed")
    command = ImportRequest.model_validate(record["command"])
    if command.asset_id != asset.id:
        raise ValueError("Protein library import identity does not match its asset")
    raw = decode(command.source, EmbeddedInput.model_validate(record["input"]))
    return command, raw


def same_original_input(left, right):
    """Deduplicate exact uploaded input/filter choices, never merely its atoms."""
    try:
        a, b = original_input(left), original_input(right)
    except ValueError:
        # A damaged old cache entry cannot deduplicate a new upload. Placement
        # still diagnoses that entry; no old bytes or metadata are repaired.
        return False
    return bool(a and b and a[0].source == b[0].source
                and a[0].exclude_dna == b[0].exclude_dna)


def document_asset(asset):
    """Strip the library envelope; a document stores bytes in input_sources."""
    return asset.model_copy(update={"metadata": {
        key: value for key, value in asset.metadata.items() if key != SOURCE_KEY}})
