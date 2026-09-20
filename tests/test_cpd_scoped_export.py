"""CPD overlays must not override ordinary DNA, even through wildcard expansion."""

import pytest

from experiments.cpd_published_comparator.scope_cis_syn_export import scope_parameters


def test_cpd_scope_keeps_mixed_junctions_and_drops_standard_impropers():
    text = """* Fixture
*
ATOMS
MASS -1 CS001 12.011
MASS -1 CN7 12.011
BONDS
CN7 CN8 100 1.4
CS001 CN8 100 1.4
ANGLES
CS001 CN7 ON6 50 109 20 2.4
IMPROPERS
CN3T CN1 CN3 CN9 14 0 0
CS001 CN1 CN3 CN9 14 0 0
NONBONDED nbxmod 5 -
cutnb 14 ctofnb 12 ctonnb 10
CN7 0 -0.02 1.9
CS001 0 -0.02 1.9
NBFIX
CS001 CLGR1 -0.4 3.88
CN7 CLGR1 -0.4 3.88
END
"""
    scoped = scope_parameters(text)
    assert "CN3T CN1 CN3 CN9" not in scoped
    assert "MASS -1 CN7" not in scoped
    assert "CN7 CN8 100" not in scoped
    assert "CS001 CN8 100" in scoped
    assert "CS001 CN7 ON6 50 109 20 2.4" in scoped
    assert "CS001 CN1 CN3 CN9" in scoped
    assert "CS001 CLGR1 -0.4 3.88" in scoped
    assert "CN7 CLGR1 -0.4 3.88" not in scoped
    assert scoped.endswith("END\n")
    assert scope_parameters(scoped) == scoped


def test_unknown_parameter_section_is_rejected():
    with pytest.raises(ValueError, match="Unrecognized"):
        scope_parameters("CMAP\nCS001 CS002 CS003 CS004 24\n")
