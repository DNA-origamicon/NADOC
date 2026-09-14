from backend.core.namd_process import is_segment_command


def test_native_process_and_slurm_match_only_real_config_arguments():
    assert is_segment_command(b"/opt/namd3\0+p1\0stage.conf\0", "stage")
    assert is_segment_command(b"srun\0/opt/namd3\0stage.resume2.conf\0", "stage")
    assert not is_segment_command(
        b"bash\0-c\0python script.py # namd stage.conf\0", "stage"
    )
    assert not is_segment_command(
        b"python\0audit.py\0/opt/namd3\0stage.conf\0", "stage"
    )
    assert not is_segment_command(b"namd3\0stage_p100.conf\0", "stage_p10")
