import json
from pathlib import Path

import numpy as np
import pytest

from backend.core.namd_peg_relax import relax_segments, prepare_relax
from backend.core.namd_peg_health import polymer_plateau


def test_fast_schedule_preserves_time_grafts_and_fixed_cell():
    specs = relax_segments()
    assert specs[0].steps*specs[0].timestep_fs == 25000
    assert sum(s.steps*s.timestep_fs for s in specs[1:]) == 4800000
    assert [s.percent for s in specs[1:]] == [10, 50, 100]
    assert all(not s.npt and s.scale == 5 for s in specs)
    assert all(s.timestep_fs == 4 for s in specs[1:])
    with pytest.raises(ValueError):
        relax_segments(float('nan'))


def test_solvent_energy_plateau_alone_cannot_skip_polymer_relaxation():
    energies = [dict(POTENTIAL=-10000.) for _ in range(30)]
    settled = np.full((30, 4), 8.)
    assert polymer_plateau(energies, settled, settled)[0]
    drifting = settled.copy(); drifting[-5:, 2] = 12
    assert not polymer_plateau(energies, drifting, settled)[0]
    assert not polymer_plateau(energies, settled, drifting)[0]
    assert not polymer_plateau(energies, [], [])[0]
    assert not polymer_plateau([{'POTENTIAL': float('nan')}]*30, settled, settled)[0]
    assert not polymer_plateau(energies, settled[:10], settled[:10])[0]


def test_prepared_native_case_hmr_and_force_continuity(tmp_path):
    # Read-only saved native fixture; this test never launches an engine.
    import shutil
    source = Path('workspace/md_jobs/654049290521')
    if not source.exists():
        pytest.skip('prepared PEG qualification fixture not present')
    from backend.core.md_job import MdJob
    from experiments.peg_namd.structure import read_pair
    shutil.copytree(source, tmp_path/'md_jobs/654049290521')
    job = prepare_relax(tmp_path, '654049290521', duration_ps=100)
    package = job.package_dir(tmp_path)
    a = read_pair(package/'system.psf', package/'system.pdb')
    b = read_pair(package/'system_hmr.psf', package/'system.pdb')
    mass_a = np.array([float(v[7]) for v in a['atoms']])
    mass_b = np.array([float(v[7]) for v in b['atoms']])
    assert mass_b.sum() == pytest.approx(mass_a.sum(), abs=1e-4)
    water = [i for i, v in enumerate(a['atoms']) if v[3] == 'TIP3']
    assert np.array_equal(mass_a[water], mass_b[water])
    assert (mass_b > 0).all()
    manifest = json.loads((package/'manifest.json').read_text())
    for spec in manifest['segments']:
        conf = (package/f"{spec['name']}.conf").read_text()
        assert 'GPUresident on' in conf and 'langevinPiston off' in conf
        assert 'tclForcesScript wall.tcl' in conf and 'conskfile grafts.pdb' in conf
        assert 'constraintScaling 5' in conf and 'rigidBonds all' in conf
    assert 'structure system_hmr.psf' in (package/'peg_relax_p10.conf').read_text()
    assert 'temperature 294' in (package/'peg_relax_p10.conf').read_text()
    assert not list((package/'output').iterdir())
    assert MdJob.load(job.job_id, tmp_path).early_stop_relax
    assert manifest['seed'] == 29
    from backend.core.namd_peg_relax import validate_relax_package
    validate_relax_package(package)
    (package/'wall.tcl').write_text('# changed')
    with pytest.raises(ValueError, match='input changed'):
        validate_relax_package(package)


def test_native_warmup_completion_does_not_require_final_energy_print(tmp_path):
    from backend.core.namd_peg_health import assess_segment
    package = Path('workspace/md_jobs/48c1995afbd5/package')
    if not (package/'output/peg_warm_p100.dcd').exists():
        pytest.skip('native warm-up fixture unavailable')
    import shutil
    shutil.copytree(package, tmp_path/'package')
    result = assess_segment(tmp_path/'package', 'peg_warm_p100')
    assert result['safe']
    assert result['max_force_energy_error_kcal_mol'] < .001
