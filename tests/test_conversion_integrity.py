"""Molecular-inventory and review contracts for C1–C7."""

import copy
import json

import pytest

from backend.core.lattice import make_bundle_design
from backend.core.cadnano import export_cadnano, import_cadnano
from backend.core.scadnano import export_scadnano, import_scadnano
from backend.core.interchange_compatibility import compatibility_report
from backend.core.models import StrandExtension
from backend.core.seamed_router import auto_scaffold_seamed


def bundle():
    return make_bundle_design([(0, 0), (0, 1)], 84)


def source():
    return export_scadnano(bundle())


def test_cadnano_nonreciprocal_link_rejected():
    data = export_cadnano(bundle())
    data["vstrands"][0]["scaf"][1][0:2] = [-1, -1]
    with pytest.raises(ValueError, match="Nonreciprocal"):
        import_cadnano(data)


def test_cadnano_same_helix_jump_retains_exact_path():
    data = export_cadnano(bundle())
    h = data["vstrands"][0]
    h["scaf"][2][2:] = [h["num"], 5]
    h["scaf"][5][:2] = [h["num"], 2]
    h["scaf"][3:5] = [[-1] * 4, [-1] * 4]
    out, _ = import_cadnano(data)
    s = next(s for s in out.strands if s.is_scaffold and s.domains[0].start_bp == 0)
    assert [(d.start_bp, d.end_bp) for d in s.domains] == [(0, 2), (5, 83)]
    assert len(out.forced_ligations) == 1
    again, _ = import_cadnano(export_cadnano(out))
    assert sorted(
        sum(abs(d.end_bp - d.start_bp) + 1 for d in s.domains) for s in again.strands
    ) == [82, 84, 84, 84]


def test_circular_cadnano_scaffold_keeps_all_bases():
    data = export_cadnano(bundle())
    h = data["vstrands"][0]
    h["scaf"][0][:2] = [h["num"], 83]
    h["scaf"][83][2:] = [h["num"], 0]
    out, warnings = import_cadnano(data)
    assert (
        sum(
            sum(abs(d.end_bp - d.start_bp) + 1 for d in s.domains)
            for s in out.strands
            if s.is_scaffold
        )
        == 168
    )
    assert any("linear" in w and "all bases retained" in w for w in warnings)


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda d: d.update(grid="unknown"), "grid"),
        (lambda d: d["helices"][1].update(idx=0), "Duplicate"),
        (lambda d: d["strands"][0]["domains"][0].update(end=0), "bounds"),
        (lambda d: d["strands"][0]["domains"][0].update(helix=999), "unknown helix"),
        (lambda d: d["strands"][0]["domains"].append({"loopout": 3}), "loopout"),
        (
            lambda d: d["strands"][-1].update(circular=True, is_scaffold=False),
            "circular",
        ),
        (
            lambda d: d["strands"][0]["domains"][0].update(insertions=[[4, 1]]),
            "Asymmetric",
        ),
    ],
)
def test_unsupported_scadnano_rejected(mutation, match):
    data = source()
    mutation(data)
    with pytest.raises(ValueError, match=match):
        import_scadnano(data)


def test_conflicting_insertions_rejected_and_symmetric_preserved():
    data = source()
    touching = [d for s in data["strands"] for d in s["domains"] if d["helix"] == 0]
    for d, n in zip(touching, (1, 2)):
        d["insertions"] = [[4, n]]
    with pytest.raises(ValueError, match="Conflicting"):
        import_scadnano(data)
    for d in touching:
        d["insertions"] = [[4, 2]]
    out, _ = import_scadnano(data)
    assert out.helices[0].loop_skips[0].delta == 2


@pytest.mark.parametrize(
    "target,exporter", [("cadnano", export_cadnano), ("scadnano", export_scadnano)]
)
def test_junction_bases_and_periodic_intent_blocked(target, exporter):
    from backend.core.models import ForcedLigation

    d, _ = auto_scaffold_seamed(
        make_bundle_design([(0, 0), (0, 1), (1, 0), (1, 1)], 84)
    )
    d.crossovers[0].extra_bases = "TT"
    a, b = d.crossovers[0].half_a, d.crossovers[0].half_b
    d.forced_ligations.append(
        ForcedLigation(
            three_prime_helix_id=a.helix_id,
            three_prime_bp=a.index,
            three_prime_direction=a.strand,
            five_prime_helix_id=b.helix_id,
            five_prime_bp=b.index,
            five_prime_direction=b.strand,
            is_periodic_seam=True,
        )
    )
    report = compatibility_report(d, target)
    assert {"junction_extra_bases", "periodic_seams"} <= {
        i["code"] for i in report["issues"]
    }
    assert report["blocked"]
    with pytest.raises(ValueError):
        exporter(d)


def test_scadnano_keeps_extension_sequence_on_unassigned_strand():
    d = bundle()
    d.extensions.append(
        StrandExtension(strand_id=d.strands[0].id, end="three_prime", sequence="TTT")
    )
    before = d.model_dump()
    out, _ = import_scadnano(export_scadnano(d))
    assert out.extensions[0].sequence == "TTT"
    assert out.strands[0].sequence == "N" * 84
    assert d.model_dump() == before
    assert compatibility_report(d, "cadnano")["blocked"]
    assert not compatibility_report(d, "scadnano")["blocked"]


def test_report_inventories_all_present_nadoc_only_fields():
    from backend.core.models import ClusterRigidTransform

    d = bundle()
    d.cluster_transforms.append(
        ClusterRigidTransform(id="cluster", helix_ids=[d.helices[0].id])
    )
    d.strands[0].name = "deliberate name"
    d.strands[0].sequence = "A" * 84
    before = copy.deepcopy(d.model_dump())
    report = compatibility_report(d, "cadnano")
    assert {
        "cluster_transforms",
        "strand_annotations",
        "sequences",
        "helix_geometry",
    } <= {i["code"] for i in report["issues"]}
    assert d.model_dump() == before
    assert report["token"] == compatibility_report(d, "cadnano")["token"]
    d.strands[0].notes = "changed"
    assert report["token"] != compatibility_report(d, "cadnano")["token"]


def test_import_failure_preserves_current_document_and_history(monkeypatch):
    from backend.api import state
    from backend.api.crud import import_scadnano_design, ScadnanoImportRequest
    from fastapi import HTTPException

    monkeypatch.setattr(state, "_sessions", {})
    state.load_design(bundle())
    before = copy.deepcopy(state.get_or_404().model_dump())
    data = source()
    data["strands"][0]["domains"].append({"loopout": 3})
    with pytest.raises(HTTPException) as exc:
        import_scadnano_design(ScadnanoImportRequest(content=json.dumps(data)))
    assert exc.value.status_code == 400
    assert state.get_or_404().model_dump() == before


def test_api_requires_current_review_and_blocks_molecular_loss(monkeypatch):
    from fastapi.testclient import TestClient
    from backend.api.main import app
    from backend.api import state

    monkeypatch.setattr(state, "_sessions", {})
    state.load_design(bundle())
    client = TestClient(app)
    base = "/api/design/export/"
    report = client.get(base + "compatibility/cadnano").json()
    assert client.get(base + "cadnano").status_code == 409
    assert (
        client.get(
            base + "cadnano", params={"compatibility_token": report["token"]}
        ).status_code
        == 200
    )
    state.get_or_404().strands[0].name = "changed after review"
    assert (
        client.get(
            base + "cadnano", params={"compatibility_token": report["token"]}
        ).status_code
        == 409
    )
    d = state.get_or_404()
    d.extensions.append(
        StrandExtension(strand_id=d.strands[0].id, end="three_prime", sequence="TT")
    )
    report = client.get(base + "compatibility/cadnano").json()
    assert report["blocked"]
    assert (
        client.get(
            base + "cadnano", params={"compatibility_token": report["token"]}
        ).status_code
        == 422
    )


@pytest.mark.parametrize("same_helix", [False, True])
@pytest.mark.parametrize("assigned", [False, True])
def test_scadnano_loopout_preserves_inventory_and_sequence(same_helix, assigned):
    from backend.core.sequences import strand_sequence_length

    data = source()
    data["strands"] = [
        {
            "is_scaffold": True,
            "domains": [
                {"helix": 0, "forward": True, "start": 0, "end": 8},
                {"loopout": 3},
                {
                    "helix": 0 if same_helix else 1,
                    "forward": True,
                    "start": 8,
                    "end": 16,
                },
            ],
        }
    ]
    if assigned:
        data["strands"][0]["sequence"] = "A" * 8 + "TTT" + "C" * 8
    out, _ = import_scadnano(data)
    assert strand_sequence_length(out, out.strands[0]) == 16
    assert out.strands[0].sequence == ("A" * 8 + "C" * 8 if assigned else None)
    assert [x.extra_bases for x in [*out.crossovers, *out.forced_ligations]] == [
        "TTT" if assigned else "NNN"
    ]


@pytest.mark.parametrize(
    "exporter,target", [(export_cadnano, "cadnano"), (export_scadnano, "scadnano")]
)
def test_real_periodic_route_is_not_silently_converted(exporter, target):
    from backend.core.polymer_router import route_for_polymerization

    d, _ = auto_scaffold_seamed(
        make_bundle_design([(0, 0), (0, 1), (1, 0), (1, 1)], 168)
    )
    d, _ = route_for_polymerization(d)
    assert any(f.is_periodic_seam for f in d.forced_ligations)
    before = d.model_dump()
    assert compatibility_report(d, target)["blocked"]
    with pytest.raises(ValueError, match="Periodic seams"):
        exporter(d)
    assert d.model_dump() == before


@pytest.mark.parametrize(
    "field", ["5prime_modification", "3prime_modification", "internal_modifications"]
)
def test_scadnano_json_chemical_modifications_not_silently_discarded(field):
    d = source()
    d["strands"][0][field] = (
        {"1": "/iBiodT/"} if field == "internal_modifications" else "/5Biosg/"
    )
    with pytest.raises(ValueError, match=field):
        import_scadnano(d)


def test_export_report_includes_saved_setup_and_provenance():
    d = bundle()
    d.metadata.author = "Scientist"
    d.metadata.peg_surface = {"setup": "saved"}
    codes = {i["code"] for i in compatibility_report(d, "scadnano")["issues"]}
    assert {"metadata_author", "metadata_peg_surface"} <= codes
