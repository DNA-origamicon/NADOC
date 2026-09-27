"""Protect native DNA terms and prevent methyl-cap transfer into full DNA."""

from experiments.cpd_anti_additive.prepare_dna_topology_v2 import transfer_key


ALIASES = {
    'BASE': {'role':'1:N1', 'original_type':'NG2S0'},
    'SUGAR': {'role':"1:C1'", 'original_type':'CN7B'},
    'CAP': {'role':'1:CM', 'original_type':'CG331'},
}


def test_attachment_maps_sugar_without_changing_lesion_type():
    assert transfer_key(('BASE', 'SUGAR', 'HN7'), ALIASES)==('BASE', 'CN7B', 'HN7')


def test_parent_sugar_and_phosphate_are_not_overridden():
    assert transfer_key(('SUGAR', 'HN7'), ALIASES) is None
    assert transfer_key(('P', 'ON2', 'CN8B'), ALIASES) is None


def test_caps_never_enter_full_dna_parameters():
    assert transfer_key(('BASE', 'CAP'), ALIASES) is None
