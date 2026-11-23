import hashlib

import pytest

from backend.core.namd_script import validate_static_order, rewrite_probe, log_completed
from backend.core.namd_measurements import qualification_reasons


@pytest.mark.parametrize('name, expected', [
    ('Construct4_Ext[1-1]_2xT', 'Construct4_Ext_1-1__2xT'),
    ('my design', 'my_design'),
    ('model-v1.2', 'model-v1.2'),
    ('../model;$x[exec bad]\\file\n"{}', '_model__x_exec_bad__file____'),
    ('', 'design'), (None, 'design'), ('..', 'design'),
])
def test_package_name_is_literal_and_relative(name, expected):
    from backend.core.namd_script import package_name_stem
    assert package_name_stem(name) == expected


def test_bracketed_design_prepares_admissible_minimization_and_settle(tmp_path):
    from backend.core.namd_script import package_name_stem
    from backend.core.namd_resources import configuration_memory
    from backend.core.md_protocols import SegmentSpec, _segment_conf, _min_conf

    name = package_name_stem('Construct4_Ext[1-1]_2xT')
    # Resource-reader fixture only; no molecular coordinates or simulation.
    (tmp_path / f'{name}.psf').write_text('313861 !NATOM\n')
    minimum = f'{name}_00_min_enm_k0p5'
    spec = SegmentSpec(name=f'{name}_0S_300K_NPT_settle_fixed_dna_p100',
        stage='300K NPT settle (DNA restrained)', percent=100, steps=100,
        temp=300, damping=5, scale=1, npt=True, previous=minimum,
        restraint_ref_file='restraints_dna_heavy.pdb')
    configs = [_min_conf(minimum, name, (150, 150, 150), False, 100, .5,
                         no_enm=True, n_atoms=313861),
               _segment_conf(spec, name, (150, 150, 150), False, n_atoms=313861)]
    conf = tmp_path / 'stage.conf'
    for text in configs:
        conf.write_text(text)
        result = configuration_memory(conf, detailed=False)
        assert result.supported
        assert result.atoms == 313861
    # The fix belongs in generation; the guard must still reject Tcl commands.
    conf.write_text(configs[1].replace(name, 'Construct4_Ext[1-1]_2xT'))
    with pytest.raises(ValueError, match='Dynamic Tcl'):
        configuration_memory(conf, detailed=False)


@pytest.mark.parametrize('text', ['run 100\noutputTiming 20\n',
    'minimize 100\nseed 7\nrun 100\n', 'run norepeat 100\n', 'run upto 100\n'])
def test_unqualified_execution_is_rejected(text):
    with pytest.raises(ValueError):validate_static_order(text)


def test_resource_preflight_rejects_script_before_reading_large_inputs(tmp_path):
    from backend.core.namd_resources import configuration_memory
    path=tmp_path/'probe.conf'
    path.write_text('structure missing.psf\nrun 100\noutputTiming 10\n')
    with pytest.raises(ValueError,match='initialization settings must precede'):
        configuration_memory(path)


def test_probe_repairs_explicit_settings_before_first_execution():
    text='outputName output/a\nminimize 200\nrun 500000\noutputTiming 200\nseed 7\n'
    result=rewrite_probe(text, {'outputTiming':20,'seed':8}, steps=400)
    assert result.index('outputtiming 20') < result.index('minimize')
    assert result.endswith('minimize 200\nrun 400\n')
    with pytest.raises(ValueError):rewrite_probe(text, {'seed':8}, steps=400)
    with pytest.raises(ValueError):rewrite_probe('run 100\nrun 200\n', {}, steps=400)


def test_checkpoint_or_fatal_after_output_is_not_completed(tmp_path):
    log=tmp_path/'run.log'
    for text in ['WRITING VELOCITIES TO OUTPUT FILE\n',
                 'WRITING VELOCITIES TO OUTPUT FILE\nFATAL ERROR: script failed\n',
                 'End of program\nFATAL ERROR: script failed\n']:
        log.write_text(text)
        assert not log_completed(log)
    log.write_text('WRITING VELOCITIES TO OUTPUT FILE\nEnd of program\n')
    assert log_completed(log)


def test_resume_rewrites_directives_independent_of_case(tmp_path):
    from backend.core.namd_runner import _write_resume_conf
    out=tmp_path/'output';out.mkdir()
    for suffix in ('coor','vel','xsc'):(out/f'seg.restart.{suffix}').write_text('checkpoint')
    (tmp_path/'seg.conf').write_text('outputName output/seg\nbincoordinates old\nBINVELOCITIES old\nRUN 1000\n')
    result=(tmp_path/(_write_resume_conf(tmp_path,out,'seg',400,1000)+'.conf')).read_text()
    assert 'old' not in result
    assert result.strip().endswith('600')
    validate_static_order(result)


def test_qualification_requires_success_provenance_and_outputs(tmp_path):
    conf=tmp_path/'probe.conf';conf.write_text('outputTiming 10\nrun 100\n')
    log=tmp_path/'run.log';log.write_text('End of program\n')
    raw=dict(completed=True,returncode=0,output_validation={'verified':True},
             conf_sha256=hashlib.sha256(conf.read_bytes()).hexdigest())
    provenance=dict(engine_sha256='qualified',gpu='GPU',driver='driver',threads=16)
    def reasons(r=raw,p=provenance,**kw):
        return qualification_reasons(r,provenance=p,engine_sha256='qualified',
            configuration=conf,log_path=log,**kw)
    assert reasons()==[]
    for patch in ({'completed':False},{'returncode':1},{'output_validation':{}},
                  {'output_validation':{'verified':False}}, {'guard':'stopped'},
                  {'cgroup':{'memory.events':'max 1\noom 0'}},
                  {'gpu_sampling':{'errors':['lost samples']}}, {'conf_sha256':'wrong'}):
        assert reasons({**raw,**patch})
    assert reasons(parent_completed=False)
    assert reasons(p={**provenance,'engine_sha256':None})
    assert reasons(p={**provenance,'engine_sha256':'obsolete'})
    conf.write_text('run 100\noutputTiming 10\n')
    assert any('unqualified configuration' in s for s in reasons())
