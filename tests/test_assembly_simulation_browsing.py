"""Assembly recommendations/job browsing must not require a simulation projection."""
from unittest.mock import Mock

from backend.api.assembly_simulation_facts import assembly_simulation_facts, simulation_facts
from backend.api.routes_simulate import _finish_simulate_nodes
from backend.core.models import Assembly, PartInstance, PartSourceInline, PartSourceFile
from tests.conftest import make_6hb_design


def test_counts_sources_once_without_flattening():
    part = make_6hb_design(length_bp=21)
    assembly = Assembly(instances=[
        PartInstance(id=str(i), source=PartSourceFile(path="part.nadoc"), visible=i < 30)
        for i in range(31)
    ])
    loader = Mock(return_value=part)
    proteins, count = assembly_simulation_facts(assembly, loader)
    assert (proteins, count) == (simulation_facts(part)[0], simulation_facts(part)[1] * 30)
    loader.assert_called_once()


def test_one_instance_matches_part_facts():
    part = make_6hb_design(length_bp=21)
    assembly = Assembly(instances=[PartInstance(source=PartSourceInline(design=part))])
    assert assembly_simulation_facts(assembly, lambda source: source.design) == simulation_facts(part)


def test_job_identity_without_loaded_design(tmp_path, monkeypatch):
    from backend.api import state
    monkeypatch.setattr(state, 'get_or_404', Mock(side_effect=AssertionError('must not read a part')))
    nodes = [{'project_id': 'flat_assembly', 'job_id': 'mine'}, {'project_id': 'other', 'job_id': 'other'}]
    assert _finish_simulate_nodes(nodes, tmp_path, None, False, 'flat_assembly') == nodes[:1]
    assert _finish_simulate_nodes(nodes, tmp_path, None, True, 'flat_assembly') == nodes


def test_assembly_recommendation_never_reads_or_replaces_active_design(monkeypatch):
    import asyncio
    from backend.api import assembly_state, state
    from backend.api import routes_simulate
    from backend.core import md_vram

    part = make_6hb_design(length_bp=21)
    assembly = Assembly(instances=[PartInstance(source=PartSourceInline(design=part))])
    monkeypatch.setattr(assembly_state, 'get_assembly', lambda: assembly)
    monkeypatch.setattr(state, 'get_or_404', Mock(side_effect=AssertionError('part context read')))
    monkeypatch.setattr(state, 'load_design', Mock(side_effect=AssertionError('part context replaced')))
    monkeypatch.setattr(md_vram, 'detect_gpu_activity', lambda _: {})
    monkeypatch.setattr(md_vram, 'gpu_contention_summary', lambda *a, **k: {})
    result = asyncio.run(routes_simulate.get_recommendation(assembly=True))
    assert result['n_nucleotides'] == simulation_facts(part)[1]
