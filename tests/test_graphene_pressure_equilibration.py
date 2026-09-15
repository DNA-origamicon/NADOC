"""New membrane relaxation, legacy preservation, preview and restart contracts."""
import json
from dataclasses import replace

import pytest

from backend.core.namd_graphene import (
    configure_graphene_equilibration, graphene_pressure_conf,
)
from backend.core import md_protocols as protocol, md_plan


def membrane():
    wall = {"dir": [0, 0, -1], "plane_point_nm": [13.3746, 13.41195, 1.2]}
    configure_graphene_equilibration(wall)
    return wall


def values(conf):
    return md_plan.parse_conf_directives(conf)


def test_minimization_sets_origin_for_first_restart_without_pressure():
    name, stages = protocol.mgh_slow_release_segments("cube")
    conf = protocol._min_conf(name, "cube", (267.492, 268.239, 242.394), False, 100, .5)
    fixed = protocol._graphene_relaxation_pressure(conf, membrane())
    assert "cellOrigin 133.746 134.1195 12\n" in fixed
    assert values(fixed)["langevinpiston"] == "off"
    assert fixed.index("cellOrigin") < fixed.index("minimize ")
    assert "settle" in stages[0].name


def test_adaptive_minimization_sets_origin_outside_chunk_loop():
    conf = protocol._min_conf("cube_min", "cube", (267.492, 268.239, 242.394),
                              False, 161600, .5, n_atoms=1615887)
    assert "while {$nadoc_min_done" in conf
    fixed = protocol._graphene_relaxation_pressure(conf, membrane())
    assert fixed.index("cellOrigin") < fixed.index("# NADOC_ADAPTIVE_MIN_BEGIN")
    assert fixed.count("cellOrigin") == 1
    assert values(fixed)["langevinpiston"] == "off"
    assert protocol._graphene_relaxation_pressure(fixed, membrane()) == fixed
    # Rewriting a package affected by the old bug also removes the loop directive.
    broken = fixed.replace("cellOrigin 133.746 134.1195 12\n", "").replace(
        "    minimize $nadoc_min_this",
        "cellOrigin 133.746 134.1195 12\n    minimize $nadoc_min_this")
    assert protocol._graphene_relaxation_pressure(broken, membrane()) == fixed


def test_entire_ladder_uses_normal_pressure_and_inherits_cell():
    _, stages = protocol.mgh_slow_release_segments("cube")
    for stage in stages:
        raw = protocol._segment_conf(stage, "cube", (267.492, 268.239, 242.394), False)
        conf = protocol._graphene_relaxation_pressure(raw, membrane())
        p = values(conf)
        assert p["langevinpiston"] == "on"
        assert p["useflexiblecell"] == p["useconstantarea"] == "yes"
        assert p["berendsenpressure"] == "off"
        assert p["langevinpistontarget"] == "1.01325"
        assert p["langevinpistonperiod"] == "1000.0"
        assert p["margin"] == "4"
        assert f"extendedSystem     output/{stage.previous}.xsc" in conf
        assert values(raw)["cellbasisvector1"] == p["cellbasisvector1"]
        assert values(raw)["cellbasisvector2"] == p["cellbasisvector2"]
        assert protocol._graphene_relaxation_pressure(conf, membrane()) == conf


def test_new_membrane_production_remains_nvt(tmp_path):
    wall = membrane()
    (tmp_path / "manifest.json").write_text(json.dumps({
        "graphene_nanopore": wall, "solvation": {"npt_allowed": True},
    }))
    assert not protocol.package_npt_allowed(tmp_path)
    conf = "cellOrigin 100 100 100\nlangevinPiston off\nextendedSystem equilibrated.xsc\nrun 200\n"
    out = graphene_pressure_conf(conf, enabled=True, wall=wall)
    assert values(out)["langevinpiston"] == "off"
    assert "extendedSystem equilibrated.xsc" in out


def test_replica_copies_equilibrated_cell_and_records_actual_ensemble(tmp_path):
    from tests.test_md_ensemble import _make_parent, _build_replica, _prod_conf, READY
    parent = _make_parent(tmp_path)
    package = parent.package_dir(tmp_path)
    path = package / 'manifest.json'
    manifest = json.loads(path.read_text())
    manifest.update(graphene_nanopore=membrane(), solvation={'carved': False, 'npt_allowed': True})
    path.write_text(json.dumps(manifest))
    child = _build_replica(tmp_path, parent)
    child_package = child.package_dir(tmp_path)
    assert (child_package/'equilibrated.xsc').read_bytes() == (package/'output'/f'{READY}.xsc').read_bytes()
    assert values(_prod_conf(child, tmp_path))['langevinpiston'] == 'off'
    saved = json.loads((child_package/'manifest.json').read_text())
    assert saved['segments'][0]['npt'] is False
    assert saved['solvation']['carved'] is False
    assert saved['graphene_nanopore']['production_ensemble'] == 'NVT'


def test_old_fixed_volume_and_non_membrane_configs_are_preserved():
    conf = "langevinPiston on\nBerendsenPressure on\nrun 20\n"
    assert graphene_pressure_conf(conf, enabled=False) == conf
    assert values(graphene_pressure_conf(conf, enabled=True, fixed_cell=True,
                                        wall={"cell_policy": "fixed_volume"}))["langevinpiston"] == "off"


@pytest.mark.parametrize("normal", [[.6, 0, .8], [0, 0, 0], [float('nan'), 0, 1]])
def test_unsupported_normal_cannot_silently_scale_the_wrong_axis(normal):
    with pytest.raises(ValueError, match="Cartesian membrane normal"):
        configure_graphene_equilibration({"dir": normal})


@pytest.mark.parametrize("axis", range(3))
@pytest.mark.parametrize("sign", [-1, 1])
def test_all_cartesian_normals_fix_only_tangential_dimensions(axis, sign):
    wall = membrane()
    wall["dir"] = [sign if i == axis else 0 for i in range(3)]
    configure_graphene_equilibration(wall)
    p = values(graphene_pressure_conf("langevinPiston on\nrun 20\n", enabled=True, wall=wall))
    assert p["fixcelldims"] == "yes"
    for i, name in enumerate("xyz"):
        assert p[f"fixcelldim{name}"] == ("no" if i == axis else "yes")
    assert p["useconstantarea"] == ("yes" if axis == 2 else "no")


def test_preview_restores_settle_and_shows_normal_pressure():
    ctx = md_plan.PlanContext(graphene=True)
    rows = md_plan.relaxation_stages(ctx)
    assert any(row["role"] == "settle" for row in rows)
    _, stages = protocol.mgh_slow_release_segments("design")
    for spec in stages:
        params = md_plan.stage_parameters(spec, ctx)
        assert params["useconstantarea"] == "yes"
        assert params["langevinpiston"] == "on"
        assert md_plan.stage_parameters(spec, replace(ctx, graphene=False))["useconstantarea"] == "no"


def test_conf_overrides_cannot_restore_isotropic_wall_scaling():
    raw = "useFlexibleCell no\nuseConstantArea no\nBerendsenPressure on\nlangevinPiston on\nrun 20\n"
    result = graphene_pressure_conf(raw, enabled=True, wall=membrane())
    assert result.count("useFlexibleCell") == result.count("useConstantArea") == 1
    assert values(result)["useconstantarea"] == "yes"
    assert values(result)["berendsenpressure"] == "off"


def test_pressure_rewrite_preserves_recovery_softening_and_margin():
    conf = "langevinPiston on\nlangevinPistonPeriod 10000\nlangevinPistonDecay 5000\nmargin 8\nrun 20\n"
    p = values(graphene_pressure_conf(conf, enabled=True, wall=membrane()))
    assert p["langevinpistonperiod"] == "10000.0"
    assert p["langevinpistondecay"] == "5000.0"
    assert p["margin"] == "8"
