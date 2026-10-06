import pytest
from experiments.cpd_anti_additive.native_log_v3 import parse_log


def test_restart_energy_before_first_header(tmp_path):
    p = tmp_path/'native.log'
    p.write_text('ENERGY: 55000 -12.4 299\nETITLE: TS POTENTIAL TEMP\n'
                 'ENERGY: 100000 -13.2 300\nEnd of program\n')
    rows = parse_log(p)
    assert rows[0] == dict(TS=55000, POTENTIAL=-12.4, TEMP=299)
    assert len(rows) == 2


@pytest.mark.parametrize('text', [
    'ENERGY: 55000 -12.4 299\nEnd of program\n',
    'ETITLE: TS POTENTIAL\nENERGY: 55000 nan\nEnd of program\n',
    'ETITLE: TS POTENTIAL\nENERGY: 55000 -12 300\nEnd of program\n',
    'ETITLE: TS POTENTIAL\nENERGY: 55000 -12\nETITLE: TS TEMP\nEnd of program\n',
    'ETITLE: TS POTENTIAL\nENERGY: 55000 -12\nFATAL ERROR\nEnd of program\n',
])
def test_invalid_native_evidence_rejected(tmp_path, text):
    p = tmp_path/'native.log'; p.write_text(text)
    with pytest.raises(AssertionError):
        parse_log(p)
