"""Generated native imports retain pinned inputs across local identity scopes."""

import pytest

from backend.api.generated_native_scope import namespaced
from backend.api.part_proof_commands import dependencies, execute
from backend.core.models import Design, SnapshotLogEntry
from backend.core.part_history_contract import assess_part_history, create_empty_part
from backend.core.part_input_sources import EmbeddedInput, SourceContractError
from backend.core.part_scope_references import remap_design
from tests.test_native_protein_input_proof import imported_part


GROUPS = (
    "00000000-0000-0000-0000-000000000071",
    "00000000-0000-0000-0000-000000000072",
)


def source_and_params():
    imported, descriptor = imported_part()
    source = create_empty_part("Scoped imports", "HONEYCOMB").copy_with(
        input_sources=imported.input_sources)
    return source, imported.feature_log[0].params, descriptor


def scoped_params(params, group):
    return {**params, "_generated_scope": {
        "version": 2, "group_id": group, "input_ids": [],
    }}


def test_independent_scoped_imports_share_pinned_bytes_and_cold_replay():
    design, params, descriptor = source_and_params()
    original_table = dict(design.input_sources)
    for group in GROUPS:
        scoped = scoped_params(params, group)
        design = execute("protein-import", design, scoped)
        entry = SnapshotLogEntry(
            op_kind="protein-import", label="Scoped source import", params=scoped,
            design_snapshot_gz_b64="poisoned recovery", post_state_gz_b64="poisoned output",
        )
        design = design.copy_with(feature_log=[*design.feature_log, entry])

    assert [asset.id for asset in design.protein_assets] == [
        namespaced(params["asset_id"], group) for group in GROUPS]
    assert [asset.name for asset in design.protein_assets] == [params["name"]] * 2
    assert design.protein_assets[0].atoms == design.protein_assets[1].atoms
    assert design.input_sources == original_table
    result = assess_part_history(Design.from_json(design.to_json()),
                                 execute=execute, dependencies=dependencies)
    assert result["status"] == "reproduced_import", result
    assert result["checked_commands"] == 2
    assert result["imported_sources"] == [{"kind": "input_source", "identity": descriptor.sha256}]


def test_local_scope_has_an_independent_source_table():
    design, _, _ = source_and_params()
    local = remap_design(design, {})
    assert local.input_sources == design.input_sources
    local.input_sources.clear()
    assert design.input_sources


@pytest.mark.parametrize("corrupt", [False, True])
def test_missing_or_corrupt_scoped_source_fails_before_parsing(corrupt, monkeypatch):
    design, params, descriptor = source_and_params()
    design = design.copy_with(input_sources=(
        {descriptor.sha256: EmbeddedInput(data_b64="AAAA")} if corrupt else {}))
    before = design.to_json()

    def forbidden(*_args, **_kwargs):
        pytest.fail("Unavailable source reached the protein parser")

    monkeypatch.setattr("backend.core.protein.parse_protein_pdb", forbidden)
    with pytest.raises(SourceContractError) as caught:
        execute("protein-import", design, scoped_params(params, GROUPS[0]))
    assert caught.value.code == ("source_integrity_mismatch" if corrupt else "source_unavailable")
    assert caught.value.as_issue()["references"][0]["identity"] == descriptor.sha256
    assert design.to_json() == before
