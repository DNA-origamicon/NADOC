import json
from backend.core.md_job import new_job
from backend.core.md_surface_display import surface_prep_params


def test_child_reads_its_own_surface_without_parent_and_refreshes_after_preparation(tmp_path):
    job = new_job('child', 'test', name_stem='child', package_subdir='package')
    job.parent_job_id = 'missing-parent'
    assert surface_prep_params(job, tmp_path) == {}
    p = job.package_dir(tmp_path); p.mkdir(parents=True)
    path = p / 'manifest.json'
    path.write_text(json.dumps({'graphene_nanopore': {'surface_axis': '-z', 'pore_diameter_nm': 0, 'layers': 2}}))
    assert surface_prep_params(job, tmp_path) == {
        'graphene_nanopore': True, 'graphene_surface_axis': '-z',
        'graphene_pore_diameter_nm': 0, 'graphene_layers': 2,
    }
    path.write_text(json.dumps({'graphene_nanopore': {'pore_diameter_nm': 4.25}}))
    assert surface_prep_params(job, tmp_path)['graphene_pore_diameter_nm'] == 4.25
    path.write_text('{')
    assert surface_prep_params(job, tmp_path) == {}


def test_legacy_axis_is_inferred_from_saved_cartesian_normal(tmp_path):
    job = new_job('old', 'test', name_stem='old', package_subdir='package')
    p = job.package_dir(tmp_path); p.mkdir(parents=True)
    (p / 'manifest.json').write_text(json.dumps({'graphene_nanopore': {'dir': [0, 0, 1], 'pore_diameter_nm': 0}}))
    assert surface_prep_params(job, tmp_path)['graphene_surface_axis'] == '-z'
