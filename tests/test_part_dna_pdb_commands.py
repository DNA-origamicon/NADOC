"""Original PDB bytes reproduce the existing duplex projection, without snapshots."""

from dataclasses import asdict
from uuid import UUID

import pytest
from pydantic import ValidationError

from backend.api import part_dna_pdb_commands as commands
from backend.api.part_proof_commands import dependencies, execute
from backend.api.part_recipe_edit import prepare_change
from backend.api.part_verification_worker import VerificationWorker
from backend.core.models import Design, SnapshotLogEntry
from backend.core.part_dna_pdb_source import parse_source
from backend.core.part_history_contract import assess_part_history, create_empty_part
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.part_input_sources import EmbeddedResolver, SourceContractError, describe, embed, portable_sources
from backend.core.part_scope_references import remap_design
from backend.core.part_verification_capture import capture
from tests.test_pdb_to_design import _write_synthetic_duplex_pdb


KIND = "dna-pdb-import"


def packet(raw, **changes):
    source = describe(raw, format="dna-pdb", media_type="chemical/x-pdb")
    design = create_empty_part("PDB source", "HONEYCOMB").copy_with(input_sources={source.sha256: embed(source, raw)})
    params = {"_proof_version": 1, "pdb_import_version": 1, "importer_version": 1,
        "source": source.model_dump(mode="json"), "history_seed": str(UUID(int=3501)),
        "identity_policy": "source-content-v1", "loss_policy": "existing-duplex-projection-v1",
        "name_override": None, **changes}
    return design, params


@pytest.fixture(scope="module")
def pdb_bytes(tmp_path_factory):
    path = tmp_path_factory.mktemp("dna-pdb") / "duplex.pdb"
    _write_synthetic_duplex_pdb(str(path))
    return path.read_bytes()


def imported(raw, **changes):
    design, params = packet(raw, **changes)
    output = execute(KIND, design, params)
    return output.copy_with(feature_log=[SnapshotLogEntry(id="pdb-import", op_kind=KIND,
        label="Import DNA PDB", timestamp="2026-11-01T00:00:00Z", params=params,
        design_snapshot_gz_b64="poisoned recovery", post_state_gz_b64="poisoned recovery")])


def test_complete_converter_authoring_atoms_bonds_and_warnings_match(pdb_bytes):
    from backend.core.pdb_to_design import import_pdb
    source, params = packet(pdb_bytes)
    before = source.model_dump_json()
    candidate, warnings, atoms = commands.evaluate(KIND, source, params, resolver=EmbeddedResolver(source.input_sources))
    legacy, legacy_atoms, legacy_warnings = import_pdb(pdb_bytes.decode())
    mapping = commands.identity_mapping(legacy, commands.parse_command(KIND, params))
    legacy = remap_design(legacy, mapping)
    assert candidate.model_dump(include=AUTHORING_FIELDS) == legacy.model_dump(include=AUTHORING_FIELDS)
    assert warnings == legacy_warnings
    assert asdict(atoms) == asdict(commands.remap_atomistic(legacy_atoms, mapping))
    assert source.model_dump_json() == before
    # Every emitted position is one of the unchanged parser's actual atoms.
    assert sorted((atom.name, atom.x, atom.y, atom.z) for atom in atoms.atoms) == sorted(
        (atom.name, atom.x, atom.y, atom.z) for atom in legacy_atoms.atoms)


def test_portable_original_bytes_and_spawned_cold_reproduction(pdb_bytes):
    design = Design.from_json(imported(pdb_bytes).to_json())
    sources = portable_sources(design)
    assert len(sources) == 1
    assert EmbeddedResolver(design.input_sources)(next(iter(sources.values()))) == pdb_bytes
    assert dependencies(KIND, design.feature_log[0].params).imported_sources
    worker = VerificationWorker(capture(design))
    try:
        worker.start()
        assert worker.wait(5)
        result = worker.result()
        assert result["status"] == "reproduced_import", result
        assert result["native_editable"] is False
    finally:
        worker.close()
        assert not worker.is_alive()


def test_name_edit_preserves_identities_and_regenerates_downstream_nick(pdb_bytes):
    from tests.test_part_transform_preview import snapshot
    design = imported(pdb_bytes)
    design = snapshot(design, "nick", {"helix_id": design.helices[0].id, "bp_index": 2,
        "direction": "FORWARD"}, "downstream-nick")
    updated, _ = prepare_change(design, capture(design, preserve_entry_types=True), 0,
                                lambda: None, params={"name_override": "Renamed DNA"})
    assert updated.metadata.name == "Renamed DNA"
    assert updated.helices == design.helices and updated.strands == design.strands
    assert [row.id for row in updated.feature_log] == [row.id for row in design.feature_log]
    assert assess_part_history(updated, execute=execute, dependencies=dependencies)["status"] == "reproduced_import"


def test_source_replacement_does_not_guess_identity_correspondence(pdb_bytes):
    first, second = imported(pdb_bytes), imported(pdb_bytes + b"REMARK changed bytes\n")
    assert not {helix.id for helix in first.helices} & {helix.id for helix in second.helices}
    assert not {strand.id for strand in first.strands} & {strand.id for strand in second.strands}
    assert first.helices[0].axis_start == second.helices[0].axis_start


@pytest.mark.parametrize("changes", [{"pdb_import_version": 2}, {"pdb_import_version": True},
    {"importer_version": 2}, {"loss_policy": "lossless"}, {"identity_policy": "guess-nearest"},
    {"saved_atoms": []}, {"name_override": "x" * 1025}])
def test_unknown_contracts_and_output_inputs_are_refused(pdb_bytes, changes):
    _, params = packet(pdb_bytes, **changes)
    with pytest.raises(ValidationError):
        commands.parse_command(KIND, params)
    assert not dependencies(KIND, params).known


@pytest.mark.parametrize("damage", ["model", "alternate", "insertion", "duplicate", "nan", "truncated", "utf8", "width", "bytes"])
def test_ambiguous_or_unbounded_sources_refuse_before_converter(pdb_bytes, monkeypatch, damage):
    lines = pdb_bytes.decode().splitlines(keepends=True)
    if damage == "model":
        raw = b"MODEL        1\n" + pdb_bytes + b"ENDMDL\n"
    elif damage in {"alternate", "insertion"}:
        index = 16 if damage == "alternate" else 26
        lines[0] = lines[0][:index] + "A" + lines[0][index + 1:]
        raw = "".join(lines).encode()
    elif damage == "duplicate":
        raw = pdb_bytes + lines[0].encode()
    elif damage == "nan":
        raw = (lines[0][:30] + "     nan" + lines[0][38:] + "".join(lines[1:])).encode()
    else:
        raw = {"truncated": b"ATOM      1\n", "utf8": b"\xff", "width": b"REMARK " + b"x" * 257,
               "bytes": b" " * 200_001}[damage]
    source, params = packet(raw)
    from backend.core import pdb_to_design
    monkeypatch.setattr(pdb_to_design, "import_pdb", lambda *_args, **_kwargs: pytest.fail("Invalid source reached geometry"))
    with pytest.raises(SourceContractError):
        commands.build(KIND, source, params, resolver=EmbeddedResolver(source.input_sources))


def test_original_non_dna_records_remain_source_evidence(pdb_bytes):
    water = "HETATM 9999  O   HOH Z   1       0.000   0.000   0.000  1.00  0.00           O\n"
    raw = pdb_bytes + water.encode()
    source, params = packet(raw)
    descriptor = commands.parse_command(KIND, params).source
    assert parse_source(raw, descriptor)[1]["atoms"] == parse_source(pdb_bytes, descriptor)[1]["atoms"] + 1
    candidate = commands.build(KIND, source, params, resolver=EmbeddedResolver(source.input_sources))
    assert candidate.input_sources == source.input_sources
    assert candidate.helices[0].length_bp == 4


@pytest.mark.parametrize("damage", ["missing", "corrupt", "coordinates"])
def test_proof_never_certifies_missing_sources_or_changed_geometry(pdb_bytes, damage):
    from backend.core.part_input_sources import EmbeddedInput
    design = imported(pdb_bytes)
    if damage == "coordinates":
        design.helices[0].axis_start.x += .01
    else:
        design.input_sources = {} if damage == "missing" else {
            next(iter(design.input_sources)): EmbeddedInput(data_b64="AAAA")}
    result = assess_part_history(design, execute=execute, dependencies=dependencies)
    assert result["status"] == ("mismatch" if damage == "coordinates" else "unverified"), result
