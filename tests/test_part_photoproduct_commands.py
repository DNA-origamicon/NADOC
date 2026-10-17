"""Ordinary photoproduct replay cannot bypass the bounded conversion contract."""

import pytest

from backend.api.part_photoproduct_commands import build
from backend.core.part_history_contract import create_empty_part


def test_ordinary_adapter_rejects_conversion_before_placement_or_preflight(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("Ordinary photoproduct replay reached a conversion/preflight builder")

    monkeypatch.setattr("backend.core.cpd_design.convert_extra_pair", forbidden)
    monkeypatch.setattr("backend.core.photoproducts.preflight_photoproduct", forbidden)
    source = create_empty_part("CPD contract boundary", "HONEYCOMB")
    before = source.model_dump_json()
    params = {
        "method": "convert", "base_keys": ["__xb__:crossing:0", "__xb__:crossing:1"],
        "stereochemistry": "cis-syn", "history_seed": "a8a3bea5-1a9d-43cc-a70b-61e0c7736bd6",
    }
    with pytest.raises(ValueError, match="requires method='preflight'"):
        build("photoproduct-create", source, params)
    assert source.model_dump_json() == before
