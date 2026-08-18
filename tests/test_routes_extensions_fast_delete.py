from types import SimpleNamespace

from backend.api import routes_extensions


def _extension(ext_id: str):
    return SimpleNamespace(id=ext_id)


def test_batch_delete_skips_cluster_reconciliation(monkeypatch):
    design = SimpleNamespace(extensions=[_extension("e1"), _extension("e2")])
    calls = []

    monkeypatch.setattr(routes_extensions.design_state, "get_or_404", lambda: design)
    monkeypatch.setattr(
        routes_extensions.design_state,
        "mutate_with_reconcile",
        lambda _fn: (_ for _ in ()).throw(AssertionError("cluster reconciliation must not run")),
    )

    def mutate_and_validate(fn):
        calls.append("fast")
        fn(design)
        return design, object()

    monkeypatch.setattr(routes_extensions.design_state, "mutate_and_validate", mutate_and_validate)
    monkeypatch.setattr(routes_extensions, "_design_response_with_geometry", lambda current, _report, **_kw: {"design": current})

    routes_extensions.delete_strand_extensions_batch(
        routes_extensions.StrandExtensionBatchDeleteRequest(ext_ids=["e1"])
    )

    assert calls == ["fast"]
    assert [ext.id for ext in design.extensions] == ["e2"]


def test_single_delete_skips_cluster_reconciliation(monkeypatch):
    design = SimpleNamespace(extensions=[_extension("e1")])
    monkeypatch.setattr(routes_extensions.design_state, "get_or_404", lambda: design)
    monkeypatch.setattr(
        routes_extensions.design_state,
        "mutate_with_reconcile",
        lambda _fn: (_ for _ in ()).throw(AssertionError("cluster reconciliation must not run")),
    )

    def mutate_and_validate(fn):
        fn(design)
        return design, object()

    monkeypatch.setattr(routes_extensions.design_state, "mutate_and_validate", mutate_and_validate)
    monkeypatch.setattr(routes_extensions, "_design_response_with_geometry", lambda current, _report, **_kw: {"design": current})

    routes_extensions.delete_strand_extension("e1")

    assert design.extensions == []
