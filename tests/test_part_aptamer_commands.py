"""Pinned aptamer parsing changes identity only, never deposited geometry."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.api import part_aptamer_commands as commands
from backend.core.aptamer import import_aptamer, template_content
from backend.core.feature_identity import identity_factory
from backend.core.models import Design, Domain, Helix, Strand, StrandExtension
from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_history_contract import create_empty_part
from backend.core.part_input_sources import EmbeddedResolver, SourceContractError, describe, embed


SEED = "6bfae4e1-806b-4b4c-8b64-c3ef0cd322e4"


def unrelated_helix():
    return Helix(id="unrelated", axis_start={"x": 0, "y": 0, "z": 0},
                 axis_end={"x": 0, "y": 0, "z": 1}, length_bp=1)


def tiny_pdb():
    # One complete deposited DNA residue: cheap transport/contract fixture, not
    # a new geometry baseline. Full templates exercise the exact-output oracle.
    return "\n".join(line for line in template_content("148D").splitlines()
                     if line.startswith("ATOM") and line[22:26].strip() == "1") + "\nEND\n"


def inputs(text=None, **changes):
    raw = (tiny_pdb() if text is None else text).encode("utf-8")
    source = describe(raw, format="pdb", media_type="chemical/x-pdb")
    params = {"_proof_version": 1, "aptamer_version": 1, "importer_version": 1,
              "source": source.model_dump(mode="json"), "name": "Selected aptamer",
              "source_label": "exact source annotation", "_helix_id": "apt_selected",
              "_strand_id": "aptamer-strand", "history_seed": SEED,
              "initialize_metadata": False, **changes}
    return params, source, EmbeddedResolver({source.sha256: embed(source, raw)})


def normalized_import(text, params):
    expected = import_aptamer(text, params["name"], params["source_label"])
    expected.helices[0].id = params["_helix_id"]
    expected.strands[0].id = params["_strand_id"]
    expected.strands[0].domains[0].helix_id = params["_helix_id"]
    expected.cluster_transforms[0].id = identity_factory(params["history_seed"])(
        "aptamer-cluster", [params["_helix_id"]])
    expected.cluster_transforms[0].helix_ids = [params["_helix_id"]]
    return expected


@pytest.mark.parametrize("template", ["148D", "1C35", "2HY9"])
def test_complete_native_output_matches_unchanged_importer(template):
    text = template_content(template)
    params, _, resolver = inputs(text)
    initial = Design(metadata={"name": "Existing", "tags": ["authored"]},
                     helices=[unrelated_helix()], strands=[Strand(id="unrelated-strand")])
    before = initial.model_dump_json()
    expected = normalized_import(text, params)
    result = commands.build("aptamer-import", initial, params, resolver=resolver)
    assert result.helices == [*initial.helices, *expected.helices]
    assert result.strands == [*initial.strands, *expected.strands]
    assert result.cluster_transforms == expected.cluster_transforms
    assert result.model_dump(exclude={"helices", "strands", "cluster_transforms"}) == initial.model_dump(
        exclude={"helices", "strands", "cluster_transforms"})
    assert initial.model_dump_json() == before


def test_identity_depends_only_on_authored_inputs_not_document_or_random_import_ids():
    params, _, resolver = inputs()
    first = commands.build("aptamer-import", Design(id="one"), params, resolver=resolver)
    second = commands.build("aptamer-import", Design(id="two"), params, resolver=resolver)
    assert first.helices == second.helices
    assert first.strands == second.strands
    assert first.cluster_transforms == second.cluster_transforms


def test_explicit_initial_metadata_matches_legacy_first_import():
    params, _, resolver = inputs(initialize_metadata=True)
    initial = create_empty_part(params["name"], "HONEYCOMB")
    result = commands.build("aptamer-import", initial, params, resolver=resolver)
    assert result.metadata == normalized_import(tiny_pdb(), params).metadata
    assert result.recipe_root == initial.recipe_root


@pytest.mark.parametrize("initial", [Design(), Design(helices=[unrelated_helix()])])
def test_initial_metadata_cannot_replace_a_legacy_or_nonempty_part(initial):
    params, _, resolver = inputs(initialize_metadata=True)
    before = initial.model_dump_json()
    with pytest.raises(ReferenceResolutionError) as caught:
        commands.build("aptamer-import", initial, params, resolver=resolver)
    assert caught.value.as_issue()["references"][0]["parameter_path"] == ["initialize_metadata"]
    assert initial.model_dump_json() == before


@pytest.mark.parametrize("field,kind,path", [("helices", "helix", "_helix_id"),
    ("strands", "strand", "_strand_id"), ("cluster_transforms", "cluster", "history_seed")])
def test_output_identity_collision_is_structured_and_precedes_source_read(field, kind, path):
    params, _, resolver = inputs()
    result = commands.build("aptamer-import", Design(), params, resolver=resolver)
    initial = Design(**{field: getattr(result, field)})
    with pytest.raises(ReferenceResolutionError) as caught:
        commands.build("aptamer-import", initial, params,
                       resolver=lambda _: pytest.fail("Collision resolved source bytes"))
    assert caught.value.code == "invalid_selection"
    assert caught.value.as_issue()["references"][0]["kind"] == kind
    assert caught.value.as_issue()["references"][0]["parameter_path"] == [path]


@pytest.mark.parametrize("target", ["helix", "strand"])
def test_dangling_incoming_reference_cannot_adopt_an_imported_owner(target):
    params, _, _ = inputs()
    initial = (Design(strands=[Strand(id="consumer", domains=[
        Domain(helix_id=params["_helix_id"], start_bp=0, end_bp=0, direction="FORWARD")])]) if target == "helix" else
        Design(extensions=[StrandExtension(strand_id=params["_strand_id"], end="three_prime", sequence="A")]))
    before = initial.model_dump_json()
    with pytest.raises(ReferenceResolutionError, match="incoming reference") as caught:
        commands.build("aptamer-import", initial, params,
                       resolver=lambda _: pytest.fail("Dangling collision resolved source"))
    assert caught.value.as_issue()["references"][0]["kind"] == target
    assert initial.model_dump_json() == before


@pytest.mark.parametrize("change", [
    lambda p: p.pop("aptamer_version"), lambda p: p.pop("initialize_metadata"),
    lambda p: p.update(importer_version=2), lambda p: p.update(_proof_version=True),
    lambda p: p.update(aptamer_version=True), lambda p: p.update(initialize_metadata="false"),
    lambda p: p.update(history_seed="not-a-uuid"), lambda p: p.update(_helix_id=""),
    lambda p: p.update(native_residues=[]), lambda p: p.update(content="ATOM injected geometry"),
    lambda p: p.update(module_path="/mutable/parser.py"),
    lambda p: p["source"].update(path="/mutable/source.pdb"),
])
def test_strict_recipe_rejects_unknown_versions_outputs_and_implicit_sources(change):
    params, _, _ = inputs()
    change(params)
    with pytest.raises(ValidationError):
        commands.parse_command("aptamer-import", params)


def test_missing_source_never_reads_mutable_template(monkeypatch):
    from backend.core import aptamer

    params, source, _ = inputs()
    monkeypatch.setattr(aptamer, "template_content", lambda *_: pytest.fail("Replay read catalog"))
    with pytest.raises(SourceContractError) as caught:
        commands.build("aptamer-import", Design(), params)
    assert caught.value.code == "source_unavailable"
    assert caught.value.as_issue()["references"] == [{"kind": "input_source", "identity": source.sha256,
                                                       "parameter_path": ["source"]}]


def test_source_checksum_is_checked_before_parsing(monkeypatch):
    from backend.core import aptamer

    params, _, _ = inputs()
    monkeypatch.setattr(aptamer, "import_aptamer", lambda *_: pytest.fail("Unverified input reached parser"))
    with pytest.raises(SourceContractError, match="length"):
        commands.build("aptamer-import", Design(), params, resolver=lambda _: b"bad")


@pytest.mark.parametrize("patch", [{"format": "mmcif"}, {"media_type": "text/plain"},
                                  {"size_bytes": commands.MAX_APTAMER_SOURCE_BYTES + 1}])
def test_format_and_byte_admission_precede_resolution(patch):
    params, _, _ = inputs()
    params["source"].update(patch)
    with pytest.raises(SourceContractError):
        commands.build("aptamer-import", Design(), params,
                       resolver=lambda _: pytest.fail("Unsupported input was resolved"))


def test_atom_work_is_bounded_before_native_parsing(monkeypatch):
    from backend.core import aptamer

    line = next(line for line in tiny_pdb().splitlines() if line.startswith("ATOM"))
    params, _, resolver = inputs((line + "\n") * (commands.MAX_APTAMER_ATOM_RECORDS + 1))
    monkeypatch.setattr(aptamer, "import_aptamer", lambda *_: pytest.fail("Oversized input reached parser"))
    with pytest.raises(SourceContractError) as caught:
        commands.build("aptamer-import", Design(), params, resolver=resolver)
    assert caught.value.code == "source_limit"


def test_later_models_neither_count_toward_atom_work_nor_change_output():
    first = tiny_pdb()
    line = next(line for line in first.splitlines() if line.startswith("ATOM"))
    text = first + "ENDMDL\nMODEL        2\n" + (line + "\n") * 1_001
    params, _, resolver = inputs(text)
    result = commands.build("aptamer-import", Design(), params, resolver=resolver)
    assert result.helices == normalized_import(first, params).helices


def test_multiple_logical_chains_are_explicitly_outside_initial_contract():
    params, _, resolver = inputs(tiny_pdb() + "TER\n" + tiny_pdb())
    initial = Design()
    before = deepcopy(initial)
    with pytest.raises(SourceContractError, match="one complete logical DNA chain"):
        commands.build("aptamer-import", initial, params, resolver=resolver)
    assert initial == before


@pytest.mark.parametrize("case", ["missing_frame", "rna", "broken_backbone"])
def test_original_molecular_rejections_survive_adapter(case):
    text = template_content("148D")
    if case == "missing_frame":
        text = "\n".join(line for line in text.splitlines() if "C1'" not in line)
    elif case == "rna":
        line = next(line for line in text.splitlines() if line.startswith("ATOM") and "C1'" in line)
        text = line[:12] + " O2'" + line[16:] + "\n" + text
    else:
        text = "\n".join(line for line in text.splitlines()
                         if not (line.startswith("ATOM") and line[22:26].strip() == "3"))
    with pytest.raises(ValueError) as expected:
        import_aptamer(text)
    params, _, resolver = inputs(text)
    with pytest.raises(ValueError, match=str(expected.value)):
        commands.build("aptamer-import", Design(), params, resolver=resolver)


def test_altloc_selection_is_exactly_the_existing_first_atom_policy():
    first = tiny_pdb()
    atom = next(line for line in first.splitlines() if "C1'" in line)
    alternate = atom[:16] + "B" + atom[17:30] + " 999.000" + atom[38:]
    text = alternate + "\n" + first
    params, _, resolver = inputs(text)
    result = commands.build("aptamer-import", Design(), params, resolver=resolver)
    assert result.helices == normalized_import(first, params).helices


def test_live_gate_is_separate_from_pure_measured_contract(monkeypatch):
    text = tiny_pdb()
    imported = import_aptamer(text)
    monkeypatch.setattr(commands, "NATIVE_ROUTE_ENABLED", False)
    assert not commands.native_route_eligible(text, imported)
    monkeypatch.setattr(commands, "NATIVE_ROUTE_ENABLED", True)
    assert commands.native_route_eligible(text, imported)
    assert not commands.native_route_eligible(text, import_aptamer(text + "TER\n" + text))
