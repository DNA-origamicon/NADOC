"""Sizing respects explicit user choices, never local memory or free-run duration."""

from types import SimpleNamespace

import numpy as np
import pytest

from backend.api.routes_md import CreateJobRequest
from backend.core import md_box_preview, md_vram, namd_solvate
from backend.core.models import Design

ROD = (
    "ATOM      1  P   ADE A   1       0.000   0.000   0.000  1.00  0.00      D000\n"
    "ATOM      2  P   ADE A   2     700.000  40.000  80.000  1.00  0.00      D000\nEND\n"
)


@pytest.fixture(autouse=True)
def no_hardware_resize(monkeypatch):
    # A tiny memory budget used to trigger both the padding trim and bbox downgrade.
    monkeypatch.setattr(md_vram, "detect_host_ram_mb", lambda: 1)
    monkeypatch.setattr(md_vram, "detect_vram_mb", lambda *_: 1)
    md_box_preview._calculated_box.cache_clear()
    yield
    md_box_preview._calculated_box.cache_clear()


@pytest.mark.parametrize("mode", ["rotation", "bbox"])
@pytest.mark.parametrize("devices", ["0", "cpu"])
def test_preview_preserves_padding_and_mode_without_fallback_warning(
    monkeypatch, mode, devices
):
    monkeypatch.setattr(md_box_preview, "_design_pdb", lambda _: ROD)
    result = md_box_preview.preview_box(
        Design(), CreateJobRequest(padding_nm=2.0, box_mode=mode, devices=devices)
    )
    _, expected = namd_solvate._recenter_pdb_in_padded_box(ROD, 2.0, mode)
    assert result["padding_nm"] == 2.0
    assert result["box_mode"] == mode
    np.testing.assert_allclose(result["calculated_nm"], expected, atol=0.001)
    assert result["sizing_notes"] == []
    if mode == "rotation":
        assert min(result["calculated_nm"]) > 74  # must not collapse to a thin bbox


@pytest.mark.parametrize("mode", ["rotation", "bbox"])
@pytest.mark.parametrize("free_ns", [None, 4.8, 200.0])
@pytest.mark.parametrize("box_size", [None, (None, 90.0, None)])
def test_preparation_passes_selected_sizing_to_solvation(
    monkeypatch, mode, free_ns, box_size
):
    # Stop at the native-solvation boundary: no solvent allocation or native process.
    monkeypatch.setattr(namd_solvate, "_check_ff_files", lambda: None)
    monkeypatch.setattr(namd_solvate, "export_pdb", lambda *a, **k: ROD)
    monkeypatch.setattr(namd_solvate, "complete_psf", lambda *a, **k: "PSF")
    monkeypatch.setattr(
        namd_solvate, "audit_psf", lambda *a, **k: SimpleNamespace(passed=True)
    )

    class ReachedSolvation(Exception):
        pass

    def solvate(pdb, padding, tmpdir, **kwargs):
        assert padding == 2.0
        assert kwargs["box_mode"] == mode
        assert kwargs.get("box_size_nm") == box_size
        _, cell = namd_solvate._recenter_pdb_in_padded_box(
            pdb, padding, mode, box_size_nm=box_size
        )
        if mode == "rotation":
            assert min(cell) > 74
        if box_size:
            assert cell[1] == 90.0
        raise ReachedSolvation

    monkeypatch.setattr(namd_solvate, "_gmx_solvate", solvate)
    with pytest.raises(ReachedSolvation):
        namd_solvate.build_namd_solvated_package(
            Design(),
            padding_nm=2.0,
            box_mode=mode,
            free_ns=free_ns,
            box_size_nm=box_size,
        )
