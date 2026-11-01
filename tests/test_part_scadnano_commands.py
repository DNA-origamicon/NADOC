"""Reproducible source import preserves existing scientific interpretation."""

import json
import os
import subprocess
import sys

import pytest
from pydantic import ValidationError

from backend.api import part_scadnano_commands as commands
from backend.core import part_scadnano_source as limits
from backend.core.cluster_autodetect import _autodetect_clusters, with_default_cluster
from backend.core.conversion_integrity import require_import_integrity
from backend.core.lattice import autodetect_all_overhangs
from backend.core.lattice_import_normalization import _backfill_overhang_sequences, _recenter_design
from backend.core.part_history_contract import create_empty_part
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.part_input_sources import EmbeddedResolver, SourceContractError, describe, embed
from backend.core.part_scope_references import identity_index, remap_design
from backend.core.scadnano import import_scadnano
from tests.test_scadnano import _sq_design


SEED = "f3e589d6-d1b3-47a6-9f4c-201c91664582"


def source(case="square"):
    data = _sq_design(name="Pinned source")
    if case == "honeycomb":
        data["grid"] = "honeycomb"
        data["helices"][1]["grid_position"] = [0, 1]
    elif case == "loopout":
        data["strands"][0]["domains"].insert(1, {"loopout": 3})
        data["strands"][0]["sequence"] = "ACGTACGT" + "TTA" + "GCGCGCGC"
    elif case == "extensions":
        data["strands"][1]["domains"].insert(0, {"extension_num_bases": 4})
        data["strands"][1]["domains"].append({"extension_num_bases": 3})
        data["strands"][1]["sequence"] = "ACGT" + "A" * 16 + "TCG"
    elif case == "modifications":
        for strand in data["strands"]:
            strand["domains"][0]["insertions"] = [[3, 2]]
            strand["domains"][0]["deletions"] = [5]
    elif case == "circular":
        data["strands"][0]["circular"] = True
    elif case == "empty_helix":
        data["helices"].append({"grid_position": [2, 0], "max_offset": 16})
    elif case == "inline":
        data["strands"][1]["domains"][0]["end"] = 12
        data["strands"][1]["sequence"] = "ACGT" * 5
    elif case == "same_helix_jump":
        data["strands"] = [{"is_scaffold": True, "domains": [
            {"helix": 0, "forward": True, "start": 0, "end": 4},
            {"loopout": 2},
            {"helix": 0, "forward": True, "start": 8, "end": 12},
        ]}]
    return data


def inputs(data=None, *, raw=None, **changes):
    raw = json.dumps(source() if data is None else data, separators=(",", ":")).encode() if raw is None else raw
    descriptor = describe(raw, format="scadnano", media_type="application/json")
    params = {"_proof_version": 1, "lattice_import_version": 1, "importer_version": 1,
        "source": descriptor.model_dump(mode="json"), "history_seed": SEED,
        "identity_policy": "source-content-v1", "name_override": None,
        "loss_policy": "existing-importer-v1", **changes}
    initial = create_empty_part("Import root", "HONEYCOMB").copy_with(
        input_sources={descriptor.sha256: embed(descriptor, raw)})
    return initial, params, EmbeddedResolver(initial.input_sources)


def legacy_pipeline(data):
    imported, warnings = import_scadnano(data)
    imported = autodetect_all_overhangs(imported)
    imported = _backfill_overhang_sequences(imported)
    imported = _recenter_design(imported)
    imported = _autodetect_clusters(imported)
    require_import_integrity(imported)
    return with_default_cluster(imported), warnings


@pytest.mark.parametrize("case", ["square", "honeycomb", "loopout", "extensions", "modifications",
                                  "circular", "empty_helix", "inline", "same_helix_jump"])
def test_complete_existing_pipeline_is_preserved(case):
    data = source(case)
    initial, params, resolver = inputs(data)
    before = initial.model_dump_json()
    expected, expected_warnings = legacy_pipeline(data)
    command = commands.parse_command("scadnano-import", params)
    expected = remap_design(expected, commands.identity_mapping(expected, command))
    actual, warnings = commands.evaluate("scadnano-import", initial, params, resolver=resolver)
    assert actual.model_dump(include=AUTHORING_FIELDS) == expected.model_dump(include=AUTHORING_FIELDS)
    assert warnings == expected_warnings
    assert initial.model_dump_json() == before
    assert actual.recipe_root == initial.recipe_root and actual.input_sources == initial.input_sources
    if case in {"circular", "empty_helix", "same_helix_jump"}:
        assert warnings  # Every existing declared loss remains visible.
    if case == "extensions":
        assert [item.sequence for item in actual.extensions] == ["ACGT", "TCG"]
    if case == "inline":
        assert actual.overhangs and all(item.sequence for item in actual.overhangs)


def test_identity_mapping_preserves_derived_positions_and_orientations():
    from backend.core.design_geometry import _geometry_for_design

    initial, params, resolver = inputs(source("modifications"))
    original, _ = legacy_pipeline(source("modifications"))
    mapping = commands.identity_mapping(original, commands.parse_command("scadnano-import", params))
    actual = commands.build("scadnano-import", initial, params, resolver=resolver)
    expected = []
    for row in _geometry_for_design(original):
        expected.append({**row, "strand_id": mapping["strand", row["strand_id"]],
                         "helix_id": mapping["helix", row["helix_id"]]})
    assert _geometry_for_design(actual) == expected


def test_ordinary_nadoc_export_is_admitted_without_experimental_chemistry():
    from backend.core.scadnano import export_scadnano

    original, _ = legacy_pipeline(source())
    data = export_scadnano(original)
    assert data["photoproduct_junctions"] == []
    initial, params, resolver = inputs(data)
    actual = commands.build("scadnano-import", initial, params, resolver=resolver)
    expected, _ = legacy_pipeline(data)
    expected = remap_design(expected, commands.identity_mapping(expected, commands.parse_command("scadnano-import", params)))
    assert actual.model_dump(include=AUTHORING_FIELDS) == expected.model_dump(include=AUTHORING_FIELDS)


def test_repeated_imports_names_and_changed_source_have_explicit_identity():
    initial, params, resolver = inputs(source("extensions"))
    one = commands.build("scadnano-import", initial, params, resolver=resolver)
    two = commands.build("scadnano-import", initial.copy_with(id="new-document"),
                         {**params, "name_override": "Renamed"}, resolver=resolver)
    assert two.metadata.name == "Renamed"
    assert one.model_dump(include=AUTHORING_FIELDS - {"metadata"}) == two.model_dump(include=AUTHORING_FIELDS - {"metadata"})
    changed, changed_params, changed_resolver = inputs(raw=json.dumps(source("extensions"), indent=1).encode())
    changed = commands.build("scadnano-import", changed, changed_params, resolver=changed_resolver)
    assert set(identity_index(one)[0]).isdisjoint(identity_index(changed)[0])


@pytest.mark.parametrize("patch", [
    {"_proof_version": True}, {"importer_version": 2}, {"history_seed": "random"},
    {"identity_policy": "nearest"}, {"loss_policy": "silent"}, {"helices": []}, {"geometry": {}},
])
def test_only_complete_versioned_inputs_are_accepted(patch):
    _, params, _ = inputs()
    with pytest.raises(ValidationError):
        commands.parse_command("scadnano-import", {**params, **patch})


@pytest.mark.parametrize("case", ["rootless", "nonempty", "cursor"])
def test_nonempty_or_unproven_input_refuses_before_resolving(case):
    initial, params, resolver = inputs()
    if case == "rootless":
        initial.recipe_root = None
    elif case == "cursor":
        initial.feature_log_cursor = 0
    else:
        initial = commands.build("scadnano-import", initial, params, resolver=resolver)
    before = initial.model_dump_json()
    with pytest.raises(ValueError, match="scadnano import"):
        commands.build("scadnano-import", initial, params, resolver=lambda _: pytest.fail("Resolved source"))
    assert initial.model_dump_json() == before


@pytest.mark.parametrize("case", ["huge_extension", "huge_insertion", "huge_span", "sparse_span",
    "many_strands", "many_helices", "bool_index", "duplicate_grid", "duplicate_index", "extra_field",
    "cpd_payload", "transformed", "bad_grid", "nonboolean", "mixed_domain", "sequence", "opaque_name"])
def test_opaque_or_excessive_sources_refuse_before_importer(monkeypatch, case):
    from backend.core import scadnano

    data = source()
    if case == "huge_extension":
        data["strands"][0]["domains"].append({"extension_num_bases": 1_000_000})
    elif case == "huge_insertion":
        data["strands"][0]["domains"][0]["insertions"] = [[2, 1_000_000]]
    elif case == "huge_span":
        data["helices"][0]["max_offset"] = 1_000_000
    elif case == "sparse_span":
        data["strands"][0]["domains"].append({"helix": 0, "forward": True, "start": 9999, "end": 10000})
    elif case == "many_strands":
        data["strands"] *= 100
    elif case == "many_helices":
        data["helices"] *= 100
    elif case == "bool_index":
        data["helices"][0]["idx"] = False
    elif case == "duplicate_grid":
        data["helices"][1]["grid_position"] = [0, 0]
    elif case == "duplicate_index":
        data["helices"][1]["idx"] = 0
    elif case == "extra_field":
        data["geometry"] = []
    elif case == "cpd_payload":
        data["photoproduct_junctions"] = [{}]
    elif case == "transformed":
        data["helices"][0]["roll"] = 0.1
    elif case == "bad_grid":
        data["grid"] = {}
    elif case == "nonboolean":
        data["strands"][0]["is_scaffold"] = "false"
    elif case == "mixed_domain":
        data["strands"][0]["domains"][0]["loopout"] = 2
    elif case == "sequence":
        data["strands"][0]["sequence"] = 123
    else:
        data["strands"][0]["name"] = "Would be silently lost"
    initial, params, resolver = inputs(data)
    monkeypatch.setattr(scadnano, "import_scadnano", lambda _: pytest.fail("Unbounded source reached importer"))
    with pytest.raises((ValueError, SourceContractError)):
        commands.build("scadnano-import", initial, params, resolver=resolver)


@pytest.mark.parametrize("raw", [b'{"helices":[],"helices":[]}', b'{"name":NaN}',
    b'{"name":1e999}', b'{"name":99999999999999999999}', b'[' * 17 + b']' * 17,
    b'\xff', b'{bad json}', b' ' * (limits.MAX_SOURCE_BYTES + 1)])
def test_transport_and_json_limits(raw):
    descriptor = describe(raw, format="scadnano", media_type="application/json")
    with pytest.raises(SourceContractError):
        limits.parse_source(raw, descriptor)


def test_source_resolution_never_uses_recovery_or_wrong_format():
    initial, params, _ = inputs()
    with pytest.raises(SourceContractError, match="unavailable"):
        commands.build("scadnano-import", initial, params)
    with pytest.raises(SourceContractError, match="match"):
        commands.build("scadnano-import", initial, params, resolver=lambda _: b"{}")
    params["source"]["format"] = "cadnano-v2"
    with pytest.raises(SourceContractError, match="requires"):
        commands.build("scadnano-import", initial, params, resolver=lambda _: pytest.fail("Resolved wrong format"))


def test_process_hash_seeds_do_not_change_complete_authored_output():
    program = """
import hashlib, json
from tests.test_part_scadnano_commands import inputs, source, commands, AUTHORING_FIELDS
initial, params, resolver = inputs(source('extensions'))
result = commands.build('scadnano-import', initial, params, resolver=resolver)
print(hashlib.sha256(json.dumps(result.model_dump(mode='json', include=AUTHORING_FIELDS), sort_keys=True).encode()).hexdigest())
"""
    outputs = [subprocess.check_output([sys.executable, "-c", program], env={**os.environ, "PYTHONHASHSEED": str(seed)},
                text=True, timeout=15).strip() for seed in (11, 97)]
    assert outputs[0] == outputs[1]
