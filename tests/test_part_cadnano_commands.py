"""Bounded caDNAno contracts preserve the complete legacy import pipeline."""

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from pydantic import ValidationError

from backend.api import part_cadnano_commands as commands
from backend.core import part_cadnano_source as limits
from backend.core.cadnano import import_cadnano
from backend.core.cluster_autodetect import _autodetect_clusters, with_default_cluster
from backend.core.conversion_integrity import require_import_integrity
from backend.core.lattice import autodetect_all_overhangs
from backend.core.lattice_import_normalization import _recenter_design
from backend.core.models import SnapshotLogEntry
from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_history_contract import create_empty_part
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.part_input_sources import EmbeddedResolver, SourceContractError, describe, embed
from backend.core.part_scope_references import remap_design


SEED = "b1a02315-9b97-4753-a2ad-3af883af6204"
EXAMPLES = Path(__file__).resolve().parent.parent / "Examples" / "cadnano"


def path_into(data, kind, path, *, circular=False):
    by_num = {helix["num"]: helix for helix in data["vstrands"]}
    for index, (num, bp) in enumerate(path):
        previous = path[index - 1] if index or circular else (-1, -1)
        following = path[(index + 1) % len(path)] if index + 1 < len(path) or circular else (-1, -1)
        by_num[num][kind][bp] = [*previous, *following]


def source(helices=2, width=21):
    data = {"name": "Authored source.json", "vstrands": [{
        "num": index, "row": index // 2, "col": index % 2,
        "scaf": [[-1] * 4 for _ in range(width)], "stap": [[-1] * 4 for _ in range(width)],
        "loop": [0] * width, "skip": [0] * width, "stap_colors": [[0, 0xA855F7]],
    } for index in range(helices)]}
    for index in range(helices):
        path = [(index, bp) for bp in range(width)]
        path_into(data, "scaf", path if index % 2 == 0 else path[::-1])
        path_into(data, "stap", path[::-1] if index % 2 == 0 else path)
    return data


def module_source(modules=1, *, orphan=True):
    count = modules * 3 + int(orphan)
    data = source(count)
    for helix in data["vstrands"]:
        helix["scaf"] = [[-1] * 4 for _ in helix["scaf"]]
    for module in range(modules):
        path = []
        for index in range(module * 3, module * 3 + 3):
            positions = range(21) if index % 2 == 0 else range(20, -1, -1)
            path.extend((index, bp) for bp in positions)
        path_into(data, "scaf", path)
    if orphan:
        parent, tail = modules * 3 - 1, modules * 3
        first = [(parent, bp) for bp in (range(20, -1, -1) if parent % 2 == 0 else range(21))]
        last = [(tail, bp) for bp in (range(20, -1, -1) if tail % 2 == 0 else range(21))]
        path_into(data, "stap", [*first, *last])
    return data


def inputs(data=None, *, raw=None, **changes):
    raw = json.dumps(source() if data is None else data, separators=(",", ":")).encode() if raw is None else raw
    descriptor = describe(raw, format="cadnano-v2", media_type="application/json")
    params = {"_proof_version": 1, "lattice_import_version": 1, "importer_version": 1,
              "source": descriptor.model_dump(mode="json"), "history_seed": SEED,
              "identity_policy": "source-content-v1", "name_override": None, **changes}
    design = create_empty_part("Import root", "HONEYCOMB").copy_with(
        input_sources={descriptor.sha256: embed(descriptor, raw)})
    return design, params, EmbeddedResolver(design.input_sources)


def legacy_pipeline(data):
    imported, warnings = import_cadnano(data)
    imported = _recenter_design(imported)
    imported = autodetect_all_overhangs(imported)
    imported = _autodetect_clusters(imported)
    require_import_integrity(imported)
    return with_default_cluster(imported), warnings


@pytest.mark.parametrize("name", ["Honeycomb_6hb_test1.json", "6hb_cadnano_native_test1.json"])
def test_real_source_complete_pipeline_matches_after_identity_only_normalization(name):
    raw = (EXAMPLES / name).read_bytes()
    initial, params, resolver = inputs(raw=raw)
    before = initial.model_dump_json()
    expected, warnings = legacy_pipeline(json.loads(raw))
    expected = remap_design(expected, commands.identity_mapping(expected, commands.parse_command("cadnano-import", params)))
    result, actual_warnings = commands.evaluate("cadnano-import", initial, params, resolver=resolver)
    assert result.model_dump(include=AUTHORING_FIELDS) == expected.model_dump(include=AUTHORING_FIELDS)
    assert actual_warnings == warnings
    assert result.id == initial.id and result.recipe_root == initial.recipe_root
    assert result.input_sources == initial.input_sources and initial.model_dump_json() == before


@pytest.mark.parametrize("case", ["square", "same_helix_jump", "loops", "circular", "orphan"])
def test_native_topology_choices_and_postprocessing_remain_exact(case):
    data = source(width=32) if case == "square" else source()
    if case == "same_helix_jump":
        data["vstrands"][0]["scaf"] = [[-1] * 4 for _ in range(21)]
        path_into(data, "scaf", [(0, bp) for bp in [0, 1, 2, *range(5, 21)]])
    elif case == "loops":
        data["vstrands"][0]["loop"][4] = 2
        data["vstrands"][1]["skip"][5] = -1
    elif case == "circular":
        path_into(data, "scaf", [(0, bp) for bp in range(21)], circular=True)
    elif case == "orphan":
        data = module_source()
    initial, params, resolver = inputs(data)
    expected, warnings = legacy_pipeline(data)
    mapping = commands.identity_mapping(expected, commands.parse_command("cadnano-import", params))
    result, actual_warnings = commands.evaluate("cadnano-import", initial, params, resolver=resolver)
    assert result.model_dump(include=AUTHORING_FIELDS) == remap_design(expected, mapping).model_dump(include=AUTHORING_FIELDS)
    assert warnings == actual_warnings
    if case == "same_helix_jump":
        assert result.forced_ligations
    if case == "circular":
        assert any("linear" in warning for warning in actual_warnings)
    if case == "orphan":
        assert result.overhangs
        assert all(item.id.startswith(f"ovhg_inline_{item.strand_id}_") for item in result.overhangs)


def test_remapped_ids_do_not_change_derived_nucleotide_coordinates():
    from backend.core.design_geometry import _geometry_for_design

    data = module_source()
    initial, params, resolver = inputs(data)
    expected, _ = legacy_pipeline(data)
    mapping = commands.identity_mapping(expected, commands.parse_command("cadnano-import", params))
    result = commands.build("cadnano-import", initial, params, resolver=resolver)
    before = {(mapping["strand", item["strand_id"]], mapping["helix", item["helix_id"]],
               item["bp_index"], item["direction"], item.get("copy_k", 0)): item["backbone_position"]
              for item in _geometry_for_design(expected)}
    after = {(item["strand_id"], item["helix_id"], item["bp_index"], item["direction"],
              item.get("copy_k", 0)): item["backbone_position"]
             for item in _geometry_for_design(result)}
    assert after == before


def test_same_source_and_seed_reproduce_every_id_but_source_change_invalidates_all():
    initial, params, resolver = inputs()
    one = commands.build("cadnano-import", initial, params, resolver=resolver)
    renamed = commands.build("cadnano-import", initial.copy_with(id="different-document"),
                             {**params, "name_override": "Edited name"}, resolver=resolver)
    assert renamed.metadata.name == "Edited name"
    assert renamed.model_dump(include=AUTHORING_FIELDS - {"metadata"}) == one.model_dump(include=AUTHORING_FIELDS - {"metadata"})
    initial2, params2, resolver2 = inputs(raw=json.dumps(source(), indent=1).encode())
    replaced = commands.build("cadnano-import", initial2, params2, resolver=resolver2)
    for field in ("helices", "strands", "cluster_transforms"):
        assert {item.id for item in getattr(one, field)}.isdisjoint(item.id for item in getattr(replaced, field))


@pytest.mark.parametrize("change", [
    lambda p: p.pop("name_override"), lambda p: p.update(_proof_version=True),
    lambda p: p.update(importer_version=2), lambda p: p.update(lattice_import_version=True),
    lambda p: p.update(history_seed="not-a-uuid"), lambda p: p.update(identity_policy="nearest-geometry"),
    lambda p: p.update(helices=[]), lambda p: p.update(geometry={}),
    lambda p: p.update(content="{}"), lambda p: p["source"].update(path="mutable.json"),
])
def test_recipe_does_not_accept_output_or_implicit_source_substitution(change):
    _, params, _ = inputs()
    change(params)
    with pytest.raises(ValidationError):
        commands.parse_command("cadnano-import", params)


@pytest.mark.parametrize("case", ["rootless", "geometry", "history", "metadata", "historical"])
def test_only_genuinely_empty_explicit_input_can_receive_import(case):
    initial, params, resolver = inputs()
    if case == "rootless":
        initial.recipe_root = None
    elif case == "geometry":
        initial = commands.build("cadnano-import", initial, params, resolver=resolver)
    elif case == "history":
        initial.feature_log = [SnapshotLogEntry(op_kind="aptamer-import", label="Existing import", params={})]
    elif case == "metadata":
        initial.metadata.tags = ["authored"]
    else:
        initial.feature_log_cursor = -2
    before = initial.model_dump_json()
    with pytest.raises(ReferenceResolutionError):
        commands.build("cadnano-import", initial, params,
                       resolver=lambda _: pytest.fail("Nonempty host resolved source"))
    assert initial.model_dump_json() == before


def test_missing_and_corrupt_sources_never_read_recovery_or_filesystem():
    initial, params, _ = inputs()
    with pytest.raises(SourceContractError) as caught:
        commands.build("cadnano-import", initial, params)
    assert caught.value.code == "source_unavailable"
    with pytest.raises(SourceContractError) as caught:
        commands.build("cadnano-import", initial, params, resolver=lambda _: b"{}")
    assert caught.value.code == "source_integrity_mismatch"


@pytest.mark.parametrize("patch", [{"format": "scadnano"}, {"media_type": "text/plain"},
                                  {"size_bytes": limits.MAX_SOURCE_BYTES + 1}])
def test_source_format_and_size_admission_precede_resolution(patch):
    initial, params, _ = inputs()
    params["source"].update(patch)
    with pytest.raises(SourceContractError):
        commands.build("cadnano-import", initial, params,
                       resolver=lambda _: pytest.fail("Unsupported input was resolved"))


@pytest.mark.parametrize("case", ["huge_loop", "width", "many_helices", "nested", "huge_integer", "duplicate", "nonfinite", "opaque_cpd", "legacy_loop", "duplicate_grid"])
def test_excessive_or_opaque_work_is_rejected_before_native_model_construction(monkeypatch, case):
    from backend.core import cadnano

    data = source()
    raw = None
    if case == "huge_loop":
        data["vstrands"][0]["loop"][0] = limits.MAX_NUCLEOTIDES
    elif case == "width":
        data["vstrands"][0]["scaf"] = [[-1] * 4] * (limits.MAX_ARRAY_WIDTH + 1)
    elif case == "many_helices":
        data["vstrands"] *= limits.MAX_HELICES
    elif case == "nested":
        raw = ("[" * (limits.MAX_JSON_DEPTH + 1) + "0" + "]" * (limits.MAX_JSON_DEPTH + 1)).encode()
    elif case == "huge_integer":
        raw = b'{"name":1' + b'0' * 500 + b'}'
    elif case == "duplicate":
        raw = b'{"vstrands":[],"vstrands":[]}'
    elif case == "nonfinite":
        raw = b'{"name":NaN,"vstrands":[]}'
    elif case == "opaque_cpd":
        data["photoproduct_junctions"] = [{"design_coordinates": {}}]
    elif case == "legacy_loop":
        data["vstrands"][0]["scafLoop"] = [{"geometry": [0, 1, 2]}]
    else:
        data["vstrands"][1]["row"] = data["vstrands"][0]["row"]
        data["vstrands"][1]["col"] = data["vstrands"][0]["col"]
    initial, params, resolver = inputs(data, raw=raw)
    monkeypatch.setattr(cadnano, "import_cadnano", lambda *_: pytest.fail("Unadmitted source reached model construction"))
    with pytest.raises(SourceContractError):
        commands.build("cadnano-import", initial, params, resolver=resolver)


def test_fragmentation_limit_precedes_native_model_construction(monkeypatch):
    from backend.core import cadnano

    data = source(helices=1, width=512)
    for kind in ("scaf", "stap"):
        data["vstrands"][0][kind] = [[-1] * 4 for _ in range(512)]
        for bp in range(0, 512, 2):
            path = [(0, bp), (0, bp + 1)]
            path_into(data, kind, path if kind == "scaf" else path[::-1])
    initial, params, resolver = inputs(data)
    monkeypatch.setattr(cadnano, "import_cadnano", lambda *_: pytest.fail("Fragmented source reached model construction"))
    with pytest.raises(SourceContractError, match="fragmentation"):
        commands.build("cadnano-import", initial, params, resolver=resolver)


def test_existing_molecular_validation_is_not_weakened():
    data = source()
    data["vstrands"][0]["scaf"][1][:2] = [-1, -1]
    initial, params, resolver = inputs(data)
    with pytest.raises(ValueError, match="Nonreciprocal"):
        commands.build("cadnano-import", initial, params, resolver=resolver)
    data = source()
    path_into(data, "stap", [(0, bp) for bp in range(20, -1, -1)], circular=True)
    initial, params, resolver = inputs(data)
    with pytest.raises(ValueError, match="circular non-scaffold"):
        commands.build("cadnano-import", initial, params, resolver=resolver)


def test_unqualified_multi_module_cluster_selection_is_rejected_before_postprocessing(monkeypatch):
    from backend.core import cluster_autodetect

    initial, params, resolver = inputs(module_source(2, orphan=False))
    monkeypatch.setattr(cluster_autodetect, "_autodetect_clusters", lambda *_: pytest.fail("Ambiguous family reached clustering"))
    with pytest.raises(SourceContractError, match="at most one module scaffold"):
        commands.build("cadnano-import", initial, params, resolver=resolver)


def test_source_data_is_unchanged_and_source_strings_are_not_identity_references():
    data = module_source()
    original = deepcopy(data)
    initial, params, resolver = inputs(data, name_override="h_XY_0_0")
    result = commands.build("cadnano-import", initial, params, resolver=resolver)
    assert data == original
    assert result.metadata.name == "h_XY_0_0"


def test_recenter_compatibility_export_is_the_shared_unchanged_helper():
    from backend.api.crud import _recenter_design as route_helper
    assert route_helper is _recenter_design


@pytest.mark.slow
def test_cold_process_hash_seeds_preserve_complete_single_module_orphan_output():
    initial, params, resolver = inputs(module_source())
    expected = commands.build("cadnano-import", initial, params, resolver=resolver).model_dump(mode="json", include=AUTHORING_FIELDS)
    payload = json.dumps({"params": params, "source": json.dumps(module_source(), separators=(",", ":"))})
    script = """
import json, sys
from backend.api.part_cadnano_commands import build
from backend.core.part_history_contract import create_empty_part
from backend.core.part_history_proof import AUTHORING_FIELDS
request = json.loads(sys.stdin.read())
result = build('cadnano-import', create_empty_part('Import root', 'HONEYCOMB'), request['params'],
               resolver=lambda _: request['source'].encode())
print(json.dumps(result.model_dump(mode='json', include=AUTHORING_FIELDS), sort_keys=True))
"""
    for seed in ("1", "73"):
        environment = {**os.environ, "PYTHONHASHSEED": seed,
                       "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
        process = subprocess.run([sys.executable, "-c", script], input=payload, text=True,
                                 capture_output=True, check=True, timeout=5, env=environment)
        assert json.loads(process.stdout) == expected
