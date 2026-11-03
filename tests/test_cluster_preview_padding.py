"""Cluster sizing must follow the committed solvent padding."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

from backend.api import routes_cluster, state
from backend.core import md_vram


def test_slurm_preview_passes_padding_to_solvent_estimate(monkeypatch):
    design = Mock()
    design.without_reference_geometry.return_value = design
    monkeypatch.setattr(state, "get_or_404", lambda: design)
    monkeypatch.setattr(
        routes_cluster.cluster_config, "load_profiles",
        lambda _: {"alpine": SimpleNamespace(name="alpine")},
    )
    estimate = Mock(return_value=None)
    monkeypatch.setattr(md_vram, "estimate_profile_from_design", estimate)
    result = asyncio.run(routes_cluster.cluster_slurm_preview(
        routes_cluster.SlurmPreviewRequest(padding_nm=3.5,box_mode="bbox",box_size_nm=[31]*3,salt_mode="custom",ion_conc_mM=150,mg_conc_mM=5)
    ))
    assert result["sized"] is False
    estimate.assert_called_once_with(design, padding_nm=3.5,box_mode="bbox",box_size_nm=(31,31,31),nacl_mM=150,mgcl2_mM=5)
