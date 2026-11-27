"""Real editor construction, graph conservation, fail-closed scope and replay."""

import json

import pytest

from backend.api import headless_build as hb, state
from backend.core.models import Design, LatticeType
from backend.core.part_history_contract import create_empty_part
from backend.core.part_history_proof import command_rows
from scripts.agent_structure_guard import audit, publish
from tools.magicdna.convert import (
    export_bundle,
    import_bundle,
    read_export,
    write_export,
)
from tools.magicdna.routing import UnsupportedBundle, read_graph, signature

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module", params=["HONEYCOMB", "SQUARE"])
def bundle(request):
    lt = LatticeType(request.param)
    cells = (
        [(0, 1), (1, 1), (1, 2), (1, 3), (0, 3), (0, 2)]
        if lt == LatticeType.HONEYCOMB
        else [(r, c) for r in range(3) for c in range(6)]
    )
    with hb.scratch_session(lt):
        state.load_design(create_empty_part("MagicDNA converter test", lt))
        hb.create_bundle(cells, 84 if lt == LatticeType.HONEYCOMB else 96, lattice=lt)
        hb.auto_scaffold()
        result = hb.full_autostaple(custom_sequence="ACGT" * 1000)
        yield result.model_copy(deep=True)


def test_reconstruction_replays_all_native_operations_and_conserves_directed_graph(
    bundle, tmp_path
):
    raw, report = export_bundle(bundle)
    reconstructed, result = import_bundle(raw, bundle.lattice_type, upstream=bundle)
    from backend.core.cadnano import export_cadnano

    assert signature(json.loads(raw)) == signature(export_cadnano(reconstructed))
    assert result["nucleotides"] == report["nucleotides"]
    rows = list(command_rows(reconstructed, 2000))
    assert len(rows) > len(reconstructed.helices)
    assert {kind for _, kind, _ in rows} <= {
        "helix-add-at-cell",
        "strand-add",
        "crossover-place",
        "loop-skip-insert",
    }
    assert not reconstructed.forced_ligations
    assert len(reconstructed.input_sources) == 2
    publish(reconstructed, tmp_path / "rebuilt.nadoc")
    reopened = Design.model_validate_json((tmp_path / "rebuilt.nadoc").read_bytes())
    result = audit(reopened)
    assert result
    assert reopened.feature_log


def test_export_package_retains_original_history_and_sequences(bundle, tmp_path):
    folder = tmp_path / "package"
    write_export(bundle, folder)
    restored = read_export(folder)
    assert restored.model_dump_json() == bundle.model_dump_json()
    data = json.loads((folder / "routing.json").read_bytes())
    # One changed indel must not quietly restore the old source document.
    data["vstrands"][0]["loop"][40] = 1
    (folder / "routing.json").write_text(json.dumps(data))
    with pytest.raises(UnsupportedBundle, match="AGENT_PROCESS_REQUIRED"):
        read_export(folder)


def test_invalid_pointer_and_noncanonical_junction_fail_before_authoring(bundle):
    raw, _ = export_bundle(bundle)
    data = json.loads(raw)
    target = next(e for h in data["vstrands"] for e in h["scaf"] if e[2] >= 0)
    target[3] += 1
    with pytest.raises((UnsupportedBundle, ValueError)):
        import_bundle(json.dumps(data).encode(), bundle.lattice_type)


def test_explicit_wrong_lattice_is_rejected(bundle):
    raw, _ = export_bundle(bundle)
    with pytest.raises(UnsupportedBundle):
        read_graph(
            raw,
            "SQUARE" if bundle.lattice_type == LatticeType.HONEYCOMB else "HONEYCOMB",
        )


def test_source_tampering_is_rejected(bundle, tmp_path):
    write_export(bundle, tmp_path / "package")
    source = tmp_path / "package" / "source.nadoc"
    source.write_bytes(source.read_bytes() + b" ")
    with pytest.raises(UnsupportedBundle, match="digest mismatch"):
        read_export(tmp_path / "package")


def test_recorded_single_base_indels_reconstruct(bundle):
    from backend.api.part_native_commands import build_loop

    raw, _ = export_bundle(bundle)
    unassigned, _ = import_bundle(raw, bundle.lattice_type, upstream=bundle)
    with hb.scratch_session(bundle.lattice_type):
        state.load_design(unassigned)
        for bp, delta in [(45, 1), (50, -1)]:
            params = {
                "helix_id": unassigned.helices[0].id,
                "bp_index": bp,
                "delta": delta,
            }
            state.mutate_with_minor_log(
                op_subtype="loop-skip-insert",
                label="Test indel",
                params=params,
                fn=lambda d, p=params: build_loop("loop-skip-insert", d, p),
            )
        modified = state.get_or_404().model_copy(deep=True)
    raw, _ = export_bundle(modified)
    rebuilt, _ = import_bundle(raw, bundle.lattice_type, upstream=modified)
    again, _ = export_bundle(rebuilt)
    assert signature(json.loads(raw)) == signature(json.loads(again))


def test_noncanonical_twist_is_rejected(bundle):
    changed = bundle.model_copy(deep=True)
    changed.helices[0].twist_per_bp_rad += 0.01
    with pytest.raises((UnsupportedBundle, ValueError, RuntimeError)):
        export_bundle(changed)
