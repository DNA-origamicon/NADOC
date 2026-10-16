"""Native saved recipes never acquire inferred authoring changes on opening."""

import pytest

from backend.api import crud, state
from backend.core import models
from backend.core.models import Design
from backend.core.part_history_proof import AUTHORING_FIELDS
from tests.test_native_protein_input_proof import imported_part


@pytest.mark.parametrize("rooted", [False, True])
def test_json_legacy_backfill_runs_only_for_rootless_documents(monkeypatch, rooted):
    design, _ = imported_part()
    if not rooted:
        design.recipe_root = None
    calls = []
    monkeypatch.setattr(models, "_reclassify_invalid_crossovers", lambda d: calls.append("reclassify"))
    monkeypatch.setattr(models, "_backfill_dropped_junctions", lambda d: calls.append("backfill"))
    restored = Design.from_json(design.to_json())
    assert restored.model_dump(include=AUTHORING_FIELDS) == design.model_dump(include=AUTHORING_FIELDS)
    assert calls == ([] if rooted else ["reclassify", "backfill"])


@pytest.mark.parametrize("empty", [False, True], ids=["populated-organization", "empty-organization"])
def test_rootless_explicit_organization_json_load_preserves_authored_absence(monkeypatch, empty):
    from backend.core import backbone_continuations, crossover_positions
    from backend.core.part_group_organization import build
    from tests.test_group_organization_commands import organize, source

    design = source()
    design = build("group-organize", design, organize(design))
    if empty:
        design.group_organization = design.group_organization.model_copy(update={"groups": []})
    assert design.recipe_root is None and design.group_organization is not None
    assert not design.crossovers and not design.forced_ligations
    original = design.model_dump(mode="json")
    payload = design.to_json()

    def unexpected(*_args, **_kwargs):
        pytest.fail("Explicit organization must load without legacy topology inference")

    monkeypatch.setattr(backbone_continuations, "backbone_continuation_edges", unexpected)
    monkeypatch.setattr(crossover_positions, "extract_crossovers_from_strands", unexpected)
    monkeypatch.setattr(models, "_reclassify_invalid_crossovers", unexpected)
    monkeypatch.setattr(models, "_backfill_dropped_junctions", unexpected)
    restored = Design.from_json(payload)
    assert restored.model_dump(mode="json") == original
    assert restored.recipe_root is None  # Loading does not grant native provenance.
    assert design.model_dump(mode="json") == original


@pytest.mark.parametrize("via_file", [False, True])
@pytest.mark.parametrize("rooted", [False, True])
def test_open_preserves_recipe_state_and_retains_legacy_migrations(monkeypatch, tmp_path, via_file, rooted):
    from backend.core import lattice, lattice_frame_compatibility, validator

    design, _ = imported_part()
    if not rooted:
        design.recipe_root = None
    migrations = []
    for module, name in [
        (lattice_frame_compatibility, "repair_lattice_frame_membership"),
        (lattice, "migrate_split_staple_domains"), (lattice, "autodetect_all_overhangs"),
        *[(crud, name) for name in ("_fix_stale_ovhg_pivots", "_backfill_sub_domains_if_empty",
          "_derive_duplexes_if_empty", "_materialize_duplex_clusters_on_load", "_recompute_flexible_connections")],
    ]:
        def migrate(d, name=name):
            migrations.append(name)
            return d
        monkeypatch.setattr(module, name, migrate)
    installed = []
    monkeypatch.setattr(state, "load_design", installed.append)
    monkeypatch.setattr(validator, "validate_design", lambda d: "checked")
    monkeypatch.setattr(crud, "_design_response", lambda d, report, **kw: (d, report, kw))
    if via_file:
        path = tmp_path / "native.nadoc"
        path.write_text(design.to_json())
        response = crud.load_design(crud.FilePathRequest(path=str(path)))
    else:
        response = crud._install_loaded_design(design)
    assert len(installed) == 1
    assert installed[0].model_dump(include=AUTHORING_FIELDS) == design.model_dump(include=AUTHORING_FIELDS)
    assert installed[0].input_sources == design.input_sources
    assert response[1:] == ("checked", {"full_feature_log": False})
    assert len(migrations) == (0 if rooted else 8)


def test_response_formatting_does_not_add_or_repair_native_clusters(monkeypatch):
    from backend.core.models import ClusterRigidTransform
    from backend.core.part_history_proof import import_root
    from tests.test_part_duplex_commands import source

    design = source(equal=True, binding=True)
    design.recipe_root = import_root(design)
    monkeypatch.setattr(state, "set_design_silent", lambda d: pytest.fail("Response mutated native recipe"))
    assert not design.cluster_transforms
    assert crud._ensure_default_cluster(design) is design
    empty_cluster = ClusterRigidTransform(id="authored-empty", auto_created=True, is_default=True)
    design = design.copy_with(cluster_transforms=[empty_cluster])
    assert crud._ensure_default_cluster(design) is design
    assert not design.cluster_transforms[0].helix_ids
