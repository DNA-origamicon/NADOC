"""Workflow readiness regressions: no engines, native jobs, or workspace fixtures."""

import json

import pytest

from backend.core.design_readiness import finish_readiness, standard_readiness
from backend.core.models import (
    Crossover, Design, HalfCrossover, LoopSkip, NativeResidue, StrandExtension, StrandType,
)
from backend.core.oxdna_staleness import design_build_fingerprint
from backend.core.readiness_jobs import completed_simulation, completed_simulation_kind
from backend.core.sequences import strand_sequence_length
from tests.conftest import make_minimal_design


def sequenced_design(**kwargs):
    design = make_minimal_design(**kwargs)
    for strand in design.strands:
        strand.sequence = "A" * strand_sequence_length(design, strand)
    return design


def steps(report):
    return {step["id"]: step for step in report["steps"]}


def save_job(workspace, design, *, folder="cando_jobs", job_id="fine", snapshot=True, **updates):
    path = workspace / folder / job_id
    path.mkdir(parents=True, exist_ok=True)
    data = {
        "job_id": job_id, "status": "completed", "project_id": design.id,
        "design_fingerprint": design_build_fingerprint(design), "nonlinear": True,
        "stages": [{"name": "nonlinear", "status": "done"}],
        **updates,
    }
    (path / "job.json").write_text(json.dumps(data))
    if snapshot:
        (path / "design.json").write_text(design.to_json())
    return path


def test_empty_and_reference_only_have_no_ring():
    assert not standard_readiness(None)["available"]
    assert not standard_readiness(Design())["available"]
    design = make_minimal_design()
    for strand in design.strands:
        strand.is_reference = True
    assert not standard_readiness(design)["available"]


def test_standard_steps_and_simulation_are_separate_and_read_only():
    design = make_minimal_design()
    before = design.model_dump()
    report = standard_readiness(design)
    assert report["completed_steps"] == 2
    assert report["total_steps"] == 4
    assert report["state"] == "incomplete"
    assert design.model_dump() == before
    ready = standard_readiness(sequenced_design())
    assert ready["completed_steps"] == 4
    assert ready["state"] == "simulation_recommended"
    assert finish_readiness(ready, {"complete": True})["state"] == "ready"
    assert finish_readiness(report, {"complete": True})["state"] == "incomplete"


def test_missing_scaffold_and_linkers_do_not_satisfy_routing():
    design = sequenced_design(with_scaffold=False)
    assert not steps(standard_readiness(design))["scaffold_routing"]["complete"]
    design = sequenced_design()
    design.strands[1].strand_type = StrandType.LINKER
    assert not steps(standard_readiness(design))["staple_routing"]["complete"]


def test_intentionally_unpaired_scaffold_and_multiple_scaffolds_are_allowed():
    design = sequenced_design(n_helices=2)
    original = design.strands[0]
    design.strands.append(original.model_copy(update={
        "id": "scaf2", "domains": [original.domains[0].model_copy(update={"helix_id": "h1"})],
    }))
    assert standard_readiness(design)["state"] == "simulation_recommended"
    design.strands[1].domains[0].start_bp = 20
    design.strands[1].sequence = "A" * 21
    assert standard_readiness(design)["state"] == "simulation_recommended"


def test_native_oligos_have_no_scaffold_obligation():
    design = sequenced_design(with_scaffold=False)
    design.helices[0].native_residues = [NativeResidue(bp_index=0, base="A", source_residue="A1", atoms={})]
    report = standard_readiness(design)
    assert report["total_steps"] == 2
    assert report["state"] == "simulation_recommended"
    assert not steps(report)["scaffold_routing"]["applicable"]


def test_insertions_deletions_and_terminal_extensions_use_sequence_contract():
    design = sequenced_design()
    design.helices[0].loop_skips = [LoopSkip(bp_index=5, delta=1)]
    assert not steps(standard_readiness(design))["scaffold_sequence"]["complete"]
    for strand in design.strands:
        strand.sequence = "A" * strand_sequence_length(design, strand)
    assert standard_readiness(design)["state"] == "simulation_recommended"
    design.helices[0].loop_skips = [LoopSkip(bp_index=5, delta=-1)]
    for strand in design.strands:
        strand.sequence = "A" * strand_sequence_length(design, strand)
    design.extensions = [StrandExtension(strand_id="stap", end="five_prime", modification="biotin")]
    assert standard_readiness(design)["state"] == "simulation_recommended"
    design.extensions[0].sequence = "AN"
    assert not steps(standard_readiness(design))["staple_sequences"]["complete"]


def test_missing_base_same_length_and_duplicate_occupancy_are_incomplete():
    design = sequenced_design()
    design.strands[1].sequence = "N" + design.strands[1].sequence[1:]
    assert not steps(standard_readiness(design))["staple_sequences"]["complete"]
    design = sequenced_design()
    design.strands.append(design.strands[1].model_copy(update={"id": "duplicate"}))
    report = standard_readiness(design)
    assert not steps(report)["topology"]["complete"]
    assert not steps(report)["staple_routing"]["complete"]
    assert steps(report)["staple_routing"]["action"] == "validation"
    assert any("occupancy" in issue for issue in steps(report)["topology"]["issues"])


@pytest.mark.parametrize("missing", [False, True])
def test_dangling_crossover_records_cannot_be_hidden_by_simulation_projection(missing):
    design = sequenced_design()
    design.crossovers = [Crossover(
        half_a=HalfCrossover(helix_id="missing" if missing else "h0", index=0, strand="FORWARD"),
        half_b=HalfCrossover(helix_id="h0", index=0, strand="REVERSE"),
    )]
    report = standard_readiness(design)
    assert not steps(report)["topology"]["complete"]
    assert not steps(report)["scaffold_routing"]["complete"]


@pytest.mark.parametrize(("engine", "fields", "kind"), [
    ("cando", {"nonlinear": True, "stages": [{"name": "nonlinear", "status": "done"}]}, "Fine"),
    ("cando", {"kind": "autorefine", "nonlinear": True, "stages": [{"name": "autorefine", "status": "done"}]}, "Fine"),
    ("cando", {"nonlinear": False, "stages": [{"name": "linear", "status": "done"}]}, None),
    ("snupi", {"nonlinear": True, "stages": [{"name": "nonlinear", "status": "done"}]}, "Fine"),
    ("snupi", {"dynamics": True, "stages": [{"name": "dynamics", "status": "done"}]}, None),
    ("mrdna", {"stages": [{"name": "fine", "status": "done", "steps": 100}]}, "Fine"),
    ("mrdna", {"stages": [{"name": "coarse", "status": "done", "steps": 100}]}, None),
    ("oxdna", {"stages": [{"kind": "production", "status": "done", "steps": 100}]}, "Production"),
    ("oxdna", {"stages": [{"kind": "equil", "status": "done", "steps": 100}]}, None),
    ("namd", {"run_kind": "production", "segments": [{"name": "part1", "steps": 100, "status": "done"}]}, "Production"),
    ("namd", {"segments": [{"name": "relax", "steps": 100, "status": "done"}]}, None),
    ("namd", {"run_kind": "production", "segments": [{"name": "part1", "steps": 100, "status": "done", "skipped": True}]}, None),
    ("lammps", {"steps": 100}, "Production"),
])
def test_simulation_kind_requires_completed_fine_or_production(engine, fields, kind):
    assert completed_simulation_kind(engine, {"status": "completed", **fields}) == kind
    for status in ("queued", "preparing", "running", "failed", "stopped"):
        assert completed_simulation_kind(engine, {"status": status, **fields}) is None


def test_simulation_requires_current_content_and_identity_and_ignores_cosmetics(tmp_path):
    design = sequenced_design()
    save_job(tmp_path, design)
    assert completed_simulation(design, tmp_path)["complete"]
    design.strands[0].color = "#ff0000"
    assert completed_simulation(design, tmp_path)["complete"]
    copied = design.model_copy(update={"id": "unrelated"})
    assert not completed_simulation(copied, tmp_path)["complete"]
    design.strands[0].sequence = "C" + design.strands[0].sequence[1:]
    result = completed_simulation(design, tmp_path)
    assert not result["complete"]
    assert result["stale_runs"] == 1


def test_unknown_provenance_is_not_a_current_match(tmp_path):
    design = sequenced_design()
    save_job(tmp_path, design, snapshot=False, design_fingerprint=None)
    result = completed_simulation(design, tmp_path)
    assert not result["complete"]
    assert result["unknown_runs"] == 1


def test_legacy_job_snapshot_and_namd_parent_are_reusable(tmp_path):
    design = sequenced_design()
    save_job(tmp_path, design, folder="md_jobs", job_id="parent", status="completed", design_fingerprint=None)
    save_job(tmp_path, design, folder="md_jobs", job_id="production", snapshot=False,
             design_fingerprint=None, parent_job_id="parent", run_kind="production",
             segments=[{"name": "prod", "status": "done", "steps": 100}])
    result = completed_simulation(design, tmp_path)
    assert result["complete"]
    assert result["job_id"] == "production"


def test_completed_metadata_refresh_and_corrupt_sibling_do_not_hide_success(tmp_path):
    design = sequenced_design()
    path = save_job(tmp_path, design, status="running")
    assert not completed_simulation(design, tmp_path)["complete"]
    data = json.loads((path / "job.json").read_text())
    data["status"] = "completed"
    (path / "job.json").write_text(json.dumps(data))
    broken = tmp_path / "oxdna_jobs" / "broken"
    broken.mkdir(parents=True)
    (broken / "job.json").write_text("{broken")
    assert completed_simulation(design, tmp_path)["complete"]


def test_archive_metadata_does_not_write_cache_or_change_job_files(tmp_path):
    design = sequenced_design()
    archive = tmp_path / "archive" / "fine"
    archive.mkdir(parents=True)
    (archive / "job.json").write_text(json.dumps({
        "job_id": "fine", "status": "completed", "project_id": design.id,
        "design_fingerprint": design_build_fingerprint(design), "nonlinear": True,
        "stages": [{"name": "nonlinear", "status": "done"}],
    }))
    root = tmp_path / "cando_jobs"
    root.mkdir()
    (root / ".archive_index.json").write_text(json.dumps({"fine": str(archive)}))
    before = {str(path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert completed_simulation(design, tmp_path)["complete"]
    assert before == {str(path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}


def test_malformed_archive_entry_does_not_hide_a_live_completed_job(tmp_path):
    design = sequenced_design()
    save_job(tmp_path, design)
    (tmp_path / "cando_jobs" / ".archive_index.json").write_text('{"broken": null}')
    assert completed_simulation(design, tmp_path)["complete"]


def test_lammps_can_prove_current_design_through_immutable_revision(tmp_path):
    from backend.core.project_revisions import ProjectRevisionStore

    design = sequenced_design()
    revision = ProjectRevisionStore(tmp_path).commit(
        design, loadout_id="test", loadout_name="Test", parent_revision_id=None, expected_head=None,
    )
    save_job(tmp_path, design, folder="lammps_jobs", snapshot=False, design_fingerprint=None,
             design_revision_id=revision.revision_id, steps=100)
    result = completed_simulation(design, tmp_path)
    assert result["complete"]
    assert result["engine"] == "lammps"
    design.strands[0].sequence = "C" * len(design.strands[0].sequence)
    assert not completed_simulation(design, tmp_path)["complete"]


@pytest.mark.parametrize("plane", ["XY", "XZ", "YZ"])
def test_extruded_precursors_require_routing_even_when_sequenced(plane):
    from backend.core.lattice import make_bundle_design

    design = make_bundle_design([(0, 0), (0, 1)], 84, plane=plane)
    for strand in design.strands:
        strand.sequence = 'A' * strand_sequence_length(design, strand)
    # Readiness survives saving, loading and cosmetic edits.
    design = Design.from_json(design.to_json())
    before = design.model_dump()
    report = steps(standard_readiness(design))
    for key, command in [('scaffold_routing', 'Autoscaffold'), ('staple_routing', 'Full Autostaple')]:
        assert not report[key]['complete']
        assert report[key]['action'] == key
        assert command in report[key]['detail']
    assert report['scaffold_sequence']['complete']
    assert report['staple_sequences']['complete']
    assert design.model_dump() == before


def test_legacy_extrusion_precursors_are_not_authored_routes():
    from backend.core.lattice import make_bundle_design

    data = make_bundle_design([(0, 0)], 42).model_dump()
    for strand in data['strands']:
        strand.pop('routing_seed')
    report = steps(standard_readiness(Design.model_validate(data)))
    assert not report['scaffold_routing']['complete']
    assert not report['staple_routing']['complete']


def test_manual_nicking_counts_without_automatic_command_history():
    from backend.core.lattice import make_bundle_design, make_nick

    design = make_bundle_design([(0, 0)], 42)
    for strand in list(design.strands):
        domain = strand.domains[0]
        design = make_nick(design, domain.helix_id, 20, domain.direction)
    assert not design.feature_log
    report = steps(standard_readiness(design))
    assert report['scaffold_routing']['complete']
    assert report['staple_routing']['complete']


def test_new_precursors_invalidate_previously_routed_design():
    from backend.core.lattice import make_bundle_design

    design = sequenced_design()
    extra = make_bundle_design([(0, 1)], 42)
    design = design.copy_with(helices=design.helices + extra.helices,
                              strands=design.strands + extra.strands)
    report = steps(standard_readiness(design))
    assert not report['scaffold_routing']['complete']
    assert not report['staple_routing']['complete']


def test_integrity_checks_current_content_beyond_routing():
    design = sequenced_design()
    report = steps(standard_readiness(design))
    assert report['topology']['label'] == 'Design integrity'
    assert 'duplicate IDs' in report['topology']['detail']
    design.extensions = [StrandExtension(strand_id='missing', end='five_prime', modification='biotin')]
    report = steps(standard_readiness(design))
    assert report['scaffold_routing']['complete']
    assert report['staple_routing']['complete']
    assert not report['topology']['complete']
    assert any('does not exist' in issue for issue in report['topology']['issues'])


def test_readiness_provenance_does_not_change_simulation_fingerprint():
    design = sequenced_design()
    fingerprint = design_build_fingerprint(design)
    design.strands[0].routing_seed = [design.strands[0].domains[0].model_copy(deep=True)]
    assert design_build_fingerprint(design) == fingerprint
    design.strands[0].routing_seed = []
    assert design_build_fingerprint(design) == fingerprint


def test_placement_remapping_does_not_route_precursors():
    from backend.core.lattice import make_bundle_design

    design = make_bundle_design([(0, 0)], 42)
    design.helices[0].id = 'placed-helix'
    design.helices[0].bp_start = 100
    for strand in design.strands:
        domain = strand.domains[0]
        domain.helix_id = 'placed-helix'
        domain.start_bp += 100
        domain.end_bp += 100
    report = steps(standard_readiness(design))
    assert not report['scaffold_routing']['complete']
    assert not report['staple_routing']['complete']


def test_integrity_only_subtracts_one_point_and_repair_restores_it():
    design = sequenced_design()
    clean = standard_readiness(design)
    assert clean['total_steps'] == clean['completed_steps'] == clean['score'] == 4
    assert clean['integrity_penalty'] == 0
    design.extensions = [
        StrandExtension(strand_id='missing', end='five_prime', modification='biotin'),
        StrandExtension(strand_id='also-missing', end='three_prime', modification='biotin'),
    ]
    broken = standard_readiness(design)
    assert broken['completed_steps'] == broken['total_steps'] == 4
    assert broken['integrity_penalty'] == -1
    assert broken['score'] == 3
    assert broken['state'] == 'incomplete'
    # Recalculation, including completed simulation evidence, never compounds or
    # bypasses the single integrity penalty.
    repeated = finish_readiness(broken, {'complete': True})
    assert repeated['score'] == 3
    assert repeated['state'] == 'incomplete'
    design.extensions = []
    fixed = standard_readiness(design)
    assert fixed['score'] == 4
    assert fixed['integrity_penalty'] == 0
    assert fixed['state'] == 'simulation_recommended'


def test_integrity_penalty_can_make_the_score_negative():
    design = make_minimal_design(with_scaffold=False, with_staple=False)
    report = standard_readiness(design)
    assert report['completed_steps'] == 0
    assert report['total_steps'] == 4
    assert report['score'] == report['integrity_penalty'] == -1
