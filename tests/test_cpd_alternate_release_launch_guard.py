import pytest

from experiments.cpd_anti_additive.launch_corrected_alternate_release_v2 import (
    blocking_units, require_resources,
)


def test_admission_path_is_not_a_calculation_identity():
    # systemd-run defaults Description to the command, including its Archive path.
    listing = ('nadoc-alternate-release-v2-admit.service loaded active running '
               '/python /Archive/cpd-corrected-cis-anti-i-refinement-v1/runner.py\n')
    assert 'cpd-' in listing and '-watch' not in listing  # Original guard rejected this.
    assert blocking_units(listing) == []


def test_real_calculations_block_even_with_watch_word_in_description():
    listing = ('cpd-corrected-anti1-job.service loaded active running /path/-watch/data\n'
               'cpd-corrected-anti1-job-watch.service loaded active running monitor\n')
    assert blocking_units(listing) == ['cpd-corrected-anti1-job.service']


def test_native_job_with_status_bullet_still_blocks():
    assert blocking_units('● cpd-native.service loaded active running\n') == ['cpd-native.service']
    assert blocking_units('\n  unrelated.service loaded active running\n') == []


@pytest.mark.parametrize('memory,disk', [(12*1024**3-1, 40*1024**3),
                                       (16*1024**3, 30*1024**3-1)])
def test_resource_requirements_not_weakened(memory, disk):
    with pytest.raises(RuntimeError, match='Insufficient headroom'):
        require_resources(memory, disk)


def test_original_resource_boundary_is_preserved():
    require_resources(12*1024**3, 30*1024**3)
