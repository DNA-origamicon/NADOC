
from backend.core.namd_resources import estimate_memory, configuration_memory, health_memory_mib


def test_mode_and_settings_change_the_budget():
    resident=estimate_memory(1_936_696)
    offload=estimate_memory(1_936_696,gpu_resident=False)
    assert resident.ram_mib > offload.ram_mib
    assert resident.gpu_mib > offload.gpu_mib
    assert estimate_memory(313861,pairlist=24).gpu_mib > 2008
    assert estimate_memory(313861,extra_bonds=1_999_121).ram_mib > 1388
    assert resident.ram_mib > 6595
    # Compact health reader measured 765 MiB on this fixture.
    assert 765 < health_memory_mib(1_936_696) < 1500


def test_unknown_configuration_is_not_certified():
    assert not estimate_memory(4_000_000).supported
    assert not estimate_memory(300_000,pairlist=30).supported
    assert not estimate_memory(300_000,pme_spacing=1).supported


def test_velocity_reseed_has_same_memory_budget_as_temperature_start(tmp_path):
    # Production children emit this before run 0. It reuses the velocity array;
    # accepting it must not admit arbitrary Tcl or post-initialization changes.
    import pytest
    (tmp_path/'model.psf').write_text('PSF\n\n 313861 !NATOM\n')
    conf = tmp_path/'reseed.conf'
    base = 'structure model.psf\ntemperature 300\n'
    conf.write_text(base + 'run 0\n')
    original = configuration_memory(conf, fallback_box=[150]*3)
    conf.write_text(base + 'reinitvels 300\nrun 0\n')
    assert configuration_memory(conf, fallback_box=[150]*3) == original
    for invalid in ('reinitvels [exec bad]\nrun 0\n', 'run 0\nreinitvels 300\n'):
        conf.write_text(base + invalid)
        with pytest.raises(ValueError):
            configuration_memory(conf, fallback_box=[150]*3)


def test_configuration_reads_topology_and_actual_mode(tmp_path):
    (tmp_path/'model.psf').write_text('PSF\n\n 313861 !NATOM\n')
    conf=tmp_path/'run.conf'
    conf.write_text('set name model\nstructure $name.psf\nGPUresident on\n'
                    'pairlistdist 24\nPMEGridSpacing 1.5\nrun 100\n')
    result=configuration_memory(conf,fallback_box=[150,150,150])
    assert result.atoms==313861 and result.gpu_resident
    assert result.supported and result.gpu_mib>2008


def test_allocation_forecast_accepts_future_checkpoint_with_known_box(tmp_path):
    (tmp_path/'x.psf').write_text('100000 !NATOM\n')
    conf=tmp_path/'x.conf';conf.write_text('structure x.psf\nextendedSystem later.xsc\nPMEGridSpacing 1\n')
    assert configuration_memory(conf,fallback_box=[100,100,200]).supported


def test_workflow_holds_the_largest_stage_and_analysis_until_exit(tmp_path, monkeypatch):
    import asyncio
    import json
    from types import SimpleNamespace
    from backend.core import namd_runner as runner, memory_budget as budget, namd_resources as resources
    from backend.core.md_job import MdStatus
    monkeypatch.setenv('NADOC_MEMORY_BUDGET_DIR',str(tmp_path/'memory'))
    monkeypatch.setattr(budget.psutil,'virtual_memory',lambda:SimpleNamespace(available=16*1024**3))
    (tmp_path/'manifest.json').write_text(json.dumps({'minimization':{'name':'min'}}))
    monkeypatch.setattr(runner,'segments_from_manifest',lambda _: (None,[SimpleNamespace(name='late')]))
    monkeypatch.setattr(resources,'configuration_memory',lambda p,**kw:
        resources.MemoryEstimate(100000,False,2000 if p.stem=='late' else 1000,1000,True))
    job=SimpleNamespace(protocol='standard',devices='cpu',threads=16,status=MdStatus.queued,
                        package_dir=lambda _:tmp_path,save=lambda _:None)
    async def run(*args):
        lease=runner._WORKFLOW_MEMORY.get()
        assert lease.amount == (2000 + health_memory_mib(100000))*1024**2
        assert budget.simulation_active()
        await asyncio.sleep(0)
        assert budget.simulation_active()
        # A changed stage cannot borrow the RAM reserved for health evaluation.
        monkeypatch.setattr(resources, 'configuration_memory', lambda *a, **kw:
            resources.MemoryEstimate(100000, False, 2001, 1000, True))
        rc, pid = await runner._run_namd_async('must-not-run', 'late', tmp_path,
            tmp_path/'late.log', devices='', threads=16)
        assert rc == 75 and pid is None
        assert 'exceeds the reserved' in (tmp_path/'late.log').read_text()
    monkeypatch.setattr(runner,'_run_job_reserved',run)
    asyncio.run(runner.run_job(job,tmp_path))
    assert not budget.simulation_active()


def test_unknown_stage_prevents_any_simulation_launch(tmp_path,monkeypatch):
    import asyncio,json
    from types import SimpleNamespace
    from backend.core import namd_runner as runner
    from backend.core.md_job import MdStatus
    (tmp_path/'manifest.json').write_text(json.dumps({'minimization':{'name':'missing'}}))
    monkeypatch.setattr(runner,'segments_from_manifest',lambda _: (None,[]))
    async def forbidden(*args):
        raise AssertionError('unverified simulation launched')
    monkeypatch.setattr(runner,'_run_job_reserved',forbidden)
    job=SimpleNamespace(protocol='standard',devices='cpu',threads=16,status=MdStatus.queued,
                        package_dir=lambda _:tmp_path,save=lambda _:None)
    asyncio.run(runner.run_job(job,tmp_path))
    assert job.status == MdStatus.failed
    assert 'before launch' in job.error
