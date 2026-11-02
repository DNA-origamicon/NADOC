"""Display adapter keeps detector identities and never changes molecular geometry."""
from dataclasses import asdict

import numpy as np
import pytest

from backend.core.atomistic import Atom, AtomisticModel
from backend.core.piercing_display import display_piercings
from backend.core.ring_piercing import SUGAR_RING


def specimen(x=0.0):
    atoms = []
    for i, name in enumerate(SUGAR_RING):
        theta = i * 2 * np.pi / 5
        atoms.append(Atom(i, name, name[0], 'DT', 'A', 1,
            .23 * np.cos(theta), .23 * np.sin(theta), 0., 's', 'h', -5, 'FORWARD',
            extension_id='tail', ext_k=2))
    for name, z, k in [("O3'", -.2, 2), ('P', .2, 1)]:
        atoms.append(Atom(len(atoms), name, name[0], 'DT', 'A', 1,
            x, 0., z, 's', 'h', -5, 'FORWARD', extension_id='tail', ext_k=k))
    return AtomisticModel(atoms, [(5, 6)])


def test_piercing_without_backbone_clash_preserves_exact_ring_and_tail_identity():
    model = specimen()
    before = asdict(model)
    report = display_piercings(model)
    assert report['count'] == 1 and not report['truncated']
    hit = report['hits'][0]
    assert [a['name'] for a in hit['bond']] == ["O3'", 'P']
    assert [a['ext_k'] for a in hit['bond']] == [2, 1]
    assert [a['name'] for a in hit['ring']] == list(SUGAR_RING)
    assert {a['extension_id'] for a in report['nucleotides']} == {'tail'}
    assert {a['ext_k'] for a in report['nucleotides']} == {1, 2}
    assert asdict(model) == before


def test_clean_and_empty_models_do_not_report_piercings():
    for model in [specimen(1.), AtomisticModel([], [])]:
        report = display_piercings(model)
        assert report['count'] == 0 and report['hits'] == []
        assert report['nucleotides'] == [] and not report['truncated']


def test_report_limit_is_explicit_and_does_not_claim_complete_count():
    report = display_piercings(specimen(), limit=0)
    assert report['count'] == 0 and report['truncated']
    assert report['hits'] == []


def test_clash_endpoint_adds_separate_piercing_report_from_display_model(monkeypatch):
    from backend.api import routes_display_geometry as routes
    from backend.core import clash
    from backend.core.models import Design
    design = Design()
    monkeypatch.setattr(routes.design_state, 'get_or_404', lambda: design)
    monkeypatch.setattr(clash, 'clash_report', lambda *a, **kw: clash.ClashReport())
    monkeypatch.setattr(routes, '_display_atomistic_model', lambda d: specimen())
    assert 'piercing' not in routes.get_clashes()
    report = routes.get_clashes(include_piercings=True)
    assert report['count'] == 0 and report['clashes'] == []
    assert report['piercing']['count'] == 1


def test_piercing_failure_is_not_reported_as_clean(monkeypatch):
    from backend.api import routes_display_geometry as routes
    from backend.core import clash
    from backend.core.models import Design
    monkeypatch.setattr(routes.design_state, 'get_or_404', lambda: Design())
    monkeypatch.setattr(clash, 'clash_report', lambda *a, **kw: clash.ClashReport())
    def fail(d):
        raise ValueError('incomplete atoms')
    monkeypatch.setattr(routes, '_display_atomistic_model', fail)
    with pytest.raises(ValueError, match='incomplete atoms'):
        routes.get_clashes(include_piercings=True)
