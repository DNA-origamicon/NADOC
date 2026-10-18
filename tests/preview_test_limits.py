"""Test-scale preview allowances for bounding-mechanism tests.

Production allowances were raised to ordinary origami part sizes on October 18,
2026. Tests that verify refusals happen *before* native work use tiny fixtures,
so they pin the original small allowances here instead of building parts large
enough to exceed the production values. Production values are covered by
tests/test_deformation_preview_real_scale.py.
"""

import pytest


@pytest.fixture
def preview_test_scale_limits(monkeypatch):
    from backend.api import part_deformation_preview as preview
    from backend.api import part_deformation_preview_dto as dto
    from backend.api import part_deformation_preview_sessions as host
    from backend.core import part_dna_comparison as comparison
    from backend.core import part_dna_comparison_contract as contract

    for name, value in {"MAX_COMMANDS": 128, "MAX_HELICES": 16, "MAX_SLOTS": 1024,
                        "MAX_OPERATIONS": 64, "MAX_BP_SPAN": 1024, "MAX_PATH_SAMPLES": 1024,
                        "SECONDS": 1.0, "MAX_CAPTURE_NODES": 30_000,
                        "MAX_CAPTURE_BYTES": 2_000_000}.items():
        monkeypatch.setattr(preview, name, value)
    for name, value in {"MAX_HELICES": 16, "MAX_STRANDS": 128, "MAX_DOMAINS": 256,
                        "MAX_OPERATIONS": 64, "MAX_SLOTS": 1024, "MAX_SELECTORS": 512,
                        "MAX_PATH_STATIONS": 1024, "MAX_AXIS_POINTS": 2048}.items():
        monkeypatch.setattr(contract, name, value)
        if hasattr(comparison, name):  # imported by value
            monkeypatch.setattr(comparison, name, value)
    monkeypatch.setattr(dto, "MAX_OUTPUT_NODES", 200_000)
    monkeypatch.setattr(dto, "MAX_OUTPUT_BYTES", 2_000_000)
    monkeypatch.setattr(host, "APPLY_SECONDS", 5.0)
    monkeypatch.setattr(host, "CAPTURE_SECONDS", 0.025)
