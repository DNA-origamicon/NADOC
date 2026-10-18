"""Small source-based imports preserve the established PDB parser exactly."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.api import part_protein_commands as commands
from backend.core.models import Design, ProteinAttachment, ProteinTargetFree
from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_input_sources import (
    EmbeddedResolver, SourceContractError, describe, embed,
)
from backend.core.protein import parse_protein_pdb
from tests.test_protein import _SYNTH_PROT_DNA


def _inputs(data=None, **changes):
    data = _SYNTH_PROT_DNA.encode() if data is None else data
    source = describe(data, format="pdb", media_type="chemical/x-pdb")
    params = {
        "_proof_version": 1, "protein_version": 1, "importer_version": 1,
        "source": source.model_dump(mode="json"), "asset_id": "authored-protein",
        "name": "selected name", "source_filename": "selected.pdb", "exclude_dna": False,
        **changes,
    }
    return params, source, EmbeddedResolver({source.sha256: embed(source, data)})


@pytest.mark.parametrize("exclude_dna", [False, True])
def test_pinned_import_preserves_complete_native_parser_output(exclude_dna):
    params, source, resolver = _inputs(exclude_dna=exclude_dna)
    initial = Design(metadata={"label": "authored-protein"})
    before = initial.model_dump_json()
    expected = parse_protein_pdb(_SYNTH_PROT_DNA, name=params["name"],
        source_filename=params["source_filename"], exclude_dna=exclude_dna)
    expected.id = params["asset_id"]
    result = commands.build("protein-import", initial, params, resolver=resolver)
    assert result.protein_assets == [expected]
    assert len(result.protein_assets[0].atoms) == (9 if exclude_dna else 12)
    assert result.protein_assets[0].bonds
    assert result.protein_assets[0].metadata == expected.metadata
    assert not result.protein_attachments
    assert initial.model_dump_json() == before
    assert result.model_dump(exclude={"protein_assets"}) == initial.model_dump(exclude={"protein_assets"})
    assert commands.resources("protein-import", params) == {"sources": (source,), "imports": True}


def test_same_bytes_can_author_two_independent_assets_with_stable_identity():
    first, _, resolver = _inputs()
    original = commands.build("protein-import", Design(), first, resolver=resolver)
    second = {**first, "asset_id": "second-protein", "name": "second name"}
    twice = commands.build("protein-import", original, second, resolver=resolver)
    replayed = commands.build("protein-import", Design(), first, resolver=resolver)
    replayed = commands.build("protein-import", replayed, second, resolver=resolver)
    assert twice.protein_assets == replayed.protein_assets
    assert [asset.id for asset in twice.protein_assets] == ["authored-protein", "second-protein"]
    assert [asset.name for asset in twice.protein_assets] == ["selected name", "second name"]
    assert len(original.protein_assets) == 1


@pytest.mark.parametrize("dangling", [False, True])
def test_output_identity_cannot_replace_an_asset_or_capture_dangling_attachment(dangling):
    params, _, resolver = _inputs()
    if dangling:
        initial = Design(protein_attachments=[ProteinAttachment(
            asset_id=params["asset_id"], target=ProteinTargetFree())])
    else:
        initial = commands.build("protein-import", Design(), params, resolver=resolver)
    with pytest.raises(ReferenceResolutionError) as error:
        commands.build("protein-import", initial, params,
                       resolver=lambda _s: pytest.fail("Identity collision resolved source bytes"))
    assert error.value.as_issue()["references"] == [{
        "kind": "protein_asset", "identity": params["asset_id"], "parameter_path": ["asset_id"],
    }]


@pytest.mark.parametrize("change", [
    lambda p: p.pop("protein_version"),
    lambda p: p.update(importer_version=2),
    lambda p: p.update(importer_version=True),
    lambda p: p.update(_proof_version=True),
    lambda p: p.update(exclude_dna="false"),
    lambda p: p.update(atoms=[]),
    lambda p: p.update(parsed_asset={}),
    lambda p: p["source"].update(path="/local/source.pdb"),
    lambda p: p["source"].update(url="https://example.invalid/source.pdb"),
    lambda p: p.update(module_path="/local/parser.py"),
])
def test_import_rejects_legacy_inputs_output_substitution_and_dynamic_code(change):
    params, _, _ = _inputs()
    change(params)
    with pytest.raises(ValidationError):
        commands.parse_command("protein-import", params)


def test_missing_resolver_is_unverified_and_never_uses_library_or_filename(monkeypatch):
    from backend.api import routes_protein

    monkeypatch.setattr(routes_protein, "_resolve_protein_asset",
                        lambda *_a: pytest.fail("Import consulted the mutable library"))
    params, source, _ = _inputs(source_filename="/a/file/that/must/not/be/opened.pdb")
    with pytest.raises(SourceContractError) as error:
        commands.build("protein-import", Design(), params)
    assert error.value.status == "unverified"
    assert error.value.code == "source_unavailable"
    assert error.value.as_issue()["references"] == [{
        "kind": "input_source", "identity": source.sha256, "parameter_path": ["source"],
    }]


@pytest.mark.parametrize("returned", [b"short", _SYNTH_PROT_DNA.replace("ALA", "GLY").encode()])
def test_executor_reverifies_even_a_bad_resolver_before_parsing(returned, monkeypatch):
    from backend.core import protein

    params, _, _ = _inputs()
    monkeypatch.setattr(protein, "parse_protein_pdb",
                        lambda *_a, **_kw: pytest.fail("Unverified bytes reached parser"))
    with pytest.raises(SourceContractError) as error:
        commands.build("protein-import", Design(), params, resolver=lambda _s: returned)
    assert error.value.code == "source_integrity_mismatch"
    assert error.value.status == "unverified"


@pytest.mark.parametrize("patch", [{"format": "mmcif"}, {"media_type": "text/plain"}])
def test_other_formats_are_explicitly_outside_import_contract(patch):
    params, _, _ = _inputs()
    params["source"].update(patch)
    with pytest.raises(SourceContractError) as error:
        commands.build("protein-import", Design(), params,
                       resolver=lambda _s: pytest.fail("Unsupported source was resolved"))
    assert error.value.code == "unsupported_source"


def test_byte_limit_precedes_resolver_and_parser():
    params, _, _ = _inputs(b"x" * (commands.MAX_PROTEIN_SOURCE_BYTES + 1))
    with pytest.raises(SourceContractError) as error:
        commands.build("protein-import", Design(), params,
                       resolver=lambda _s: pytest.fail("Oversized source was resolved"))
    assert error.value.code == "source_limit"


def test_record_limit_precedes_native_parser(monkeypatch):
    from backend.core import protein

    line = next(line for line in _SYNTH_PROT_DNA.splitlines() if line.startswith("ATOM"))
    params, _, resolver = _inputs(((line + "\n") * (commands.MAX_PROTEIN_ATOM_RECORDS + 1)).encode())
    monkeypatch.setattr(protein, "parse_protein_pdb",
                        lambda *_a, **_kw: pytest.fail("Oversized atom selection reached parser"))
    with pytest.raises(SourceContractError) as error:
        commands.build("protein-import", Design(), params, resolver=resolver)
    assert error.value.code == "source_limit"


def test_excessive_bond_output_is_rejected_without_pruning(monkeypatch):
    from backend.core import protein

    params, _, resolver = _inputs()
    parsed = parse_protein_pdb(_SYNTH_PROT_DNA)
    parsed.bonds = [(0, 1)] * (commands.MAX_PROTEIN_BONDS + 1)
    original = deepcopy(parsed)
    monkeypatch.setattr(protein, "parse_protein_pdb", lambda *_a, **_kw: parsed)
    with pytest.raises(SourceContractError) as error:
        commands.build("protein-import", Design(), params, resolver=resolver)
    assert error.value.code == "source_limit"
    assert parsed == original


def test_invalid_encoding_remains_a_repairable_source_contract_failure():
    params, _, resolver = _inputs(b"\xff\xfe")
    with pytest.raises(SourceContractError) as error:
        commands.build("protein-import", Design(), params, resolver=resolver)
    assert error.value.code == "unsupported_source"
    assert error.value.as_issue()["references"][0]["parameter_path"] == ["source"]


def test_pinned_empty_structure_is_a_failed_input_not_successful_noop():
    params, _, resolver = _inputs(b"REMARK no atom records\nEND\n")
    with pytest.raises(ValueError, match="no supported atoms"):
        commands.build("protein-import", Design(), params, resolver=resolver)
