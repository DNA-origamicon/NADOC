"""Compact SNUPI static FEM display sidecar."""

import struct


def test_legacy_display_derives_and_reuses_cfrm_sidecar(tmp_path):
    from backend.core.snupi_runner import load_display_bin

    job_dir = tmp_path / "job"
    job_dir.mkdir()
    (job_dir / "display.json").write_text(
        '{"solver":"linear","positions":['
        '{"helix_id":"h0","bp_index":2,"direction":"FORWARD","copy":0,'
        '"backbone_position":[1,2,3],"nx":1,"ny":0,"nz":0,'
        '"tx":0,"ty":0,"tz":1}],"axis":[]}'
    )
    first = load_display_bin(job_dir)
    assert first is not None
    assert struct.unpack_from("<IIII", first) == (0x4D524643, 1, 1, 0)
    assert (job_dir / "display.bin").read_bytes() == first
    assert load_display_bin(job_dir) == first
