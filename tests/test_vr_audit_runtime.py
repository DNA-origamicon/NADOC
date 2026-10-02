from tools.vr_workflows.audit_runtime import numbers,pressure


def test_host_counters_preserve_units_and_separate_swap_in_from_swap_out(tmp_path):
    path=tmp_path/'meminfo'
    path.write_text('MemAvailable: 123456 kB\nSwapFree: 23456 kB\nignored: text\n')
    assert numbers(path)=={'MemAvailable':123456,'SwapFree':23456}
    before={'pswpin_pages':100,'pswpout_pages':200,'shm_used_bytes':2000}
    after={'pswpin_pages':110,'pswpout_pages':200,'shm_used_bytes':1000}
    assert pressure(before,after)=={'swap_in_pages':10,'swap_out_pages':0,'shm_growth_bytes':-1000}
