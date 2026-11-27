"""Batch-boundary failures and replay rejection, without launching MATLAB."""

import ast
import inspect
import json

import pytest

from tools.magicdna import prepare_freeform, prepare_matlab
from tools.magicdna.freeform import compare_builds, graph_report, quote


def source_fixture(module, root):
    tree = ast.parse(inspect.getsource(module.patch_source))
    pairs = next(
        ast.literal_eval(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "patches" for t in node.targets)
    )
    for relative, replacements in pairs.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        # The predecessor bug occurs in both native lattice compilers.
        anchors = [old for old, _ in replacements]
        if module is prepare_matlab and relative == "class/hyperbundle.m":
            anchors.insert(0, anchors[0])
        path.write_bytes(
            ("\r\n".join(anchors))
            .replace("\n", "\r\n")
            .replace("\r\r\n", "\r\n")
            .encode()
        )
    return pairs


@pytest.mark.parametrize("module", [prepare_freeform, prepare_matlab])
def test_patches_idempotent_and_fail_closed(module, tmp_path):
    pairs = source_fixture(module, tmp_path)
    first = module.patch_source(tmp_path)
    second = module.patch_source(tmp_path)
    assert {k: v["after_sha256"] for k, v in first.items()} == {
        k: v["after_sha256"] for k, v in second.items()
    }
    assert all(v["before_sha256"] == v["after_sha256"] for v in second.values())
    # An unrecognized later file must not partially patch earlier files.
    source_fixture(module, tmp_path)
    (tmp_path / list(pairs)[-1]).write_text("unrecognized upstream revision")
    before = {p: p.read_bytes() for p in tmp_path.rglob("*.m")}
    with pytest.raises(ValueError):
        module.patch_source(tmp_path)
    assert before == {p: p.read_bytes() for p in before}


def routing():
    return {
        "vstrands": [
            {
                "num": 0,
                "row": 0,
                "col": 0,
                "scaf": [[-1, -1, 0, 1], [0, 0, -1, -1]],
                "stap": [[0, 1, -1, -1], [-1, -1, 0, 0]],
                "loop": [0, 0],
                "skip": [0, 0],
            }
        ]
    }


def test_graph_rejects_broken_predecessor_and_empty_routes(tmp_path):
    path = tmp_path / "routing.json"
    data = routing()
    path.write_text(json.dumps(data))
    report = graph_report(path)
    assert report["scaf"]["strands"] == report["stap"]["strands"] == 1
    data["vstrands"][0]["scaf"][1][1] = 1
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Nonreciprocal"):
        graph_report(path)
    data = routing()
    data["vstrands"][0]["stap"] = [[-1] * 4] * 2
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Empty stap"):
        graph_report(path)


def test_graph_retains_circular_topology(tmp_path):
    data = routing()
    data["vstrands"][0]["scaf"] = [[0, 1, 0, 1], [0, 0, 0, 0]]
    path = tmp_path / "routing.json"
    path.write_text(json.dumps(data))
    assert graph_report(path)["scaf"]["circular"] == 1


@pytest.mark.parametrize("mutation", ["geometry", "process", "indel"])
def test_replay_rejects_material_drift(tmp_path, mutation):
    first, replay = tmp_path / "first", tmp_path / "replay"
    report = dict(
        bundle_geometry=[1],
        frames=[2],
        curve_points=[3],
        helix_count_per_bundle=[6],
        scaffolds=1,
        staples=1,
    )
    for p in (first, replay):
        p.mkdir()
        (p / "report.json").write_text(json.dumps(report))
        (p / "process.json").write_text('[{"command":"Sketch"}]')
        (p / "routingHC.json").write_text(json.dumps(routing()))
    compare_builds(first, replay, "HC")
    if mutation == "geometry":
        report["bundle_geometry"] = [99]
        (replay / "report.json").write_text(json.dumps(report))
    elif mutation == "process":
        (replay / "process.json").write_text("[]")
    else:
        data = routing()
        data["vstrands"][0]["loop"][0] = 1
        (replay / "routingHC.json").write_text(json.dumps(data))
    with pytest.raises(ValueError, match="replay changed"):
        compare_builds(first, replay, "HC")


def test_matlab_powershell_literal_quoting():
    assert quote("a'b $HOME `x`") == "'a''b $HOME `x`'"
