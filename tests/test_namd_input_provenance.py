import json
import os

import pytest
from backend.core import namd_input_provenance as proof
from backend.core.md_job import new_job
from backend.core.models import Design, ClusterRigidTransform


@pytest.fixture
def prepared(tmp_path):
    job = new_job('proof', 'mgh_slow_release', name_stem='dna', package_subdir='package')
    job.save(tmp_path)
    design = Design()
    (job.job_dir(tmp_path) / 'design.json').write_text(design.model_dump_json())
    pkg = job.package_dir(tmp_path)
    (pkg / 'forcefield').mkdir(parents=True)
    (pkg / 'output').mkdir()
    for name, value in [('dna.psf', 'psf'), ('dna.pdb', 'pdb'), ('seed.coor', 'seed'),
                        ('forcefield/a.prm', 'parameters')]:
        (pkg / name).write_text(value)
    (pkg / 'min.conf').write_text('structure dna.psf\ncoordinates dna.pdb\nparameters forcefield/a.prm\nbinCoordinates seed.coor\noutputName output/min\n')
    (pkg / 'run.conf').write_text('structure dna.psf\ncoordinates dna.pdb\nparameters forcefield/a.prm\nbinCoordinates output/min.coor\noutputName output/run\n')
    return job, tmp_path, design, pkg


def compare(fixture, design=None):
    job, ws, original, pkg = fixture
    return proof.comparison(job, ws, proof.design_digest(design or original), {'out_of_date': False})


def test_complete_receipt_and_generated_outputs(prepared):
    job, ws, d, pkg = prepared
    receipt = proof.capture(job, ws)
    assert receipt['coverage']['complete']
    assert receipt['generated_inputs'] == ['output/min.coor']
    assert compare(prepared)['input_freshness']['status'] == 'current'
    (pkg / 'output/run.dcd').write_text('trajectory')
    (pkg / 'output/min.coor').write_text('generated')
    (pkg / 'run.log').write_text('running')
    assert compare(prepared)['input_freshness']['status'] == 'current'


def test_full_model_detects_previously_omitted_transform(prepared):
    job, ws, d, _ = prepared
    proof.capture(job, ws)
    moved = d.model_copy(update={'cluster_transforms': [ClusterRigidTransform(translation=[1, 0, 0])]})
    result = compare(prepared, moved)
    assert result['input_freshness']['status'] == 'stale'
    assert result['out_of_date'] is False  # legacy selection guards remain separate
    cosmetic = d.model_copy(update={'feature_log_cursor': 5})
    cosmetic.metadata.name = 'Renamed'
    assert compare(prepared, cosmetic)['input_freshness']['status'] == 'current'


@pytest.mark.parametrize('name', ['dna.psf', 'dna.pdb', 'seed.coor', 'forcefield/a.prm', 'run.conf'])
def test_content_change_invalidates_even_same_size_and_mtime(prepared, name):
    job, ws, _, pkg = prepared
    proof.capture(job, ws)
    assert compare(prepared)['input_freshness']['status'] == 'current'
    p = pkg / name
    st = p.stat()
    p.write_bytes(b'x' * st.st_size)
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
    evidence = compare(prepared)['input_freshness']
    assert evidence['status'] == 'stale'
    assert name in evidence['changed_files']


def test_missing_added_files_and_corrupt_receipt(prepared):
    job, ws, _, pkg = prepared
    proof.capture(job, ws)
    (pkg / 'extra.conf').write_text('run 1')
    assert compare(prepared)['input_freshness']['status'] == 'stale'
    (pkg / 'extra.conf').unlink()
    (pkg / 'dna.psf').unlink()
    assert compare(prepared)['input_freshness']['status'] == 'unknown'
    (job.job_dir(ws) / proof.RECEIPT).write_text('{}')
    assert compare(prepared)['input_freshness']['status'] == 'unknown'


def test_old_jobs_never_backfilled_on_read(prepared):
    job, ws, d, _ = prepared
    legacy = {'out_of_date': False, 'input_freshness': {'status': 'unknown'}}
    result = proof.job_status(job, ws, legacy, current=proof.design_digest(d))
    assert result['input_freshness']['status'] == 'unknown'
    assert result['input_freshness']['model_match'] is True
    assert result['input_freshness']['coverage']['complete'] is False
    assert result['input_freshness']['reasons'] == ['historical_package_receipt_unavailable']
    assert not (job.job_dir(ws) / proof.RECEIPT).exists()


@pytest.mark.parametrize('reference', ['../outside.prm', '$external', 'missing.prm'])
def test_unresolved_dependencies_cannot_certify(prepared, reference):
    job, ws, _, pkg = prepared
    with (pkg / 'run.conf').open('a') as f:
        f.write('parameters ' + reference + '\n')
    receipt = proof.capture(job, ws)
    assert not receipt['coverage']['complete']
    assert compare(prepared)['input_freshness']['status'] == 'unknown'


def test_receipts_do_not_transfer_between_jobs(prepared):
    job, ws, _, _ = prepared
    proof.capture(job, ws)
    p = job.job_dir(ws) / proof.RECEIPT
    receipt = json.loads(p.read_text()); receipt['job_id'] = 'another'
    p.write_text(json.dumps(receipt))
    assert compare(prepared)['input_freshness']['status'] == 'unknown'


def test_polling_reuses_content_hashes_without_writing(prepared, monkeypatch):
    job, ws, _, _ = prepared
    proof.capture(job, ws)
    compare(prepared)
    monkeypatch.setattr(proof.hashlib, 'file_digest', lambda *a: pytest.fail('rehashing unchanged file'))
    monkeypatch.setattr(type(job), 'save', lambda *a: pytest.fail('poll wrote job'))
    assert compare(prepared)['input_freshness']['status'] == 'current'


def test_job_list_and_detail_use_receipt_without_resealing(prepared, monkeypatch):
    import asyncio
    from backend.api import routes_md
    from backend.core import design_disk_usage, oxdna_staleness
    from backend.core.md_job import MdStatus
    job, ws, design, pkg = prepared
    job.status = MdStatus.queued
    job.save(ws)
    proof.capture(job, ws)
    receipt_bytes = (job.job_dir(ws) / proof.RECEIPT).read_bytes()
    monkeypatch.setattr(routes_md, '_workspace', lambda: ws)
    monkeypatch.setattr(routes_md, '_load_job', lambda _: job)
    monkeypatch.setattr(routes_md, '_md_job_fingerprint', lambda _: 'v4:' + 'a'*64)
    monkeypatch.setattr(oxdna_staleness, 'current_active_design_fingerprint', lambda: 'v4:' + 'a'*64)
    monkeypatch.setattr(proof, 'current_design_digest', lambda: proof.design_digest(design))
    monkeypatch.setattr(design_disk_usage, 'dir_size_bytes_cached_only', lambda _: 0)
    monkeypatch.setattr(type(job), 'save', lambda *a: pytest.fail('Read wrote job'))
    row = routes_md._md_job_list_rows([job], ws, False, None)[0][0]
    assert row['input_freshness']['status'] == 'current'
    (pkg / 'forcefield/a.prm').write_text('changed')
    detail = asyncio.run(routes_md.get_md_job(job.job_id))
    assert detail['input_freshness']['status'] == 'stale'
    assert (job.job_dir(ws) / proof.RECEIPT).read_bytes() == receipt_bytes


def test_settings_changes_and_missing_active_design(prepared):
    job, ws, _, _ = prepared
    proof.capture(job, ws)
    assert proof.comparison(job, ws, None, {})['input_freshness']['status'] == 'unknown'
    job.prep_params = {'salt_mM': 200}
    evidence = compare(prepared)['input_freshness']
    assert evidence['status'] == 'stale'
    assert 'preparation_options_changed' in evidence['reasons']


def test_script_dependencies_are_not_silently_certified(prepared):
    job, ws, _, pkg = prepared
    (pkg / 'extra.tcl').write_text('set data [open /outside/inputs.txt]')
    with (pkg / 'run.conf').open('a') as f:
        f.write('tclForcesScript extra.tcl\n')
    assert not proof.capture(job, ws)['coverage']['complete']
    assert compare(prepared)['input_freshness']['status'] == 'unknown'


def test_existing_jobs_compare_saved_model_without_backfill(prepared):
    job, ws, design, pkg = prepared
    legacy = {'out_of_date': False, 'input_freshness': {'status': 'unknown'}}
    before = (job.job_dir(ws) / 'job.json').read_bytes()
    matching = proof.job_status(job, ws, legacy, current=proof.design_digest(design))
    assert matching['input_freshness']['model_match'] is True
    assert matching['input_freshness']['coverage']['complete'] is False
    moved = design.model_copy(update={'cluster_transforms': [ClusterRigidTransform(translation=[2, 0, 0])]})
    changed = proof.job_status(job, ws, legacy, current=proof.design_digest(moved))
    assert changed['input_freshness']['status'] == 'stale'
    assert not (job.job_dir(ws) / proof.RECEIPT).exists()
    assert (job.job_dir(ws) / 'job.json').read_bytes() == before
