"""The unapproved attachment candidate is isolated and keeps contact exclusions."""

from types import SimpleNamespace

import numpy as np
import pytest

from experiments.attachment_bond_candidate import fit_shortest_root_bond
from experiments.attachment_clearance_review import (
    candidate_obstacles, candidate_host_obstacles, diagnostic_candidate,
)


@pytest.mark.parametrize("provider", [candidate_obstacles, candidate_host_obstacles])
def test_separate_overhang_is_not_a_covalently_adjacent_root_contact(provider):
    version = SimpleNamespace(strand_id="new-handle", overhang_id="new-target")
    def row(strand, overhang, x):
        return {"strand_id": strand, "overhang_id": overhang,
                "backbone_position": [x, 0, 0], "base_position": [x, 0.1, 0]}
    geometry = [row("new-handle", "new-handle-oh", 0.1),
                row("host", "new-target", 0.2),
                row("host", None, 0.3),
                row("existing-handle", "existing-handle-oh", 0.4),
                row("other-host", "existing-target", 0.5),
                row("other-parent-strand", None, 0.7),
                row("distant-body", None, 3.0)]
    tree = provider(geometry, version, np.zeros(3), [[0.6, 0, 0]])
    assert tree.query([[0.4, 0, 0], [0.5, 0, 0], [0.6, 0, 0], [3, 0, 0]])[0].tolist() == [0, 0, 0, 0]
    assert tree.query([[0.1, 0, 0], [0.2, 0, 0], [0.3, 0, 0]])[0].min() > 0
    assert (tree.query([[0.7, 0, 0]])[0][0] == 0) == (provider is candidate_host_obstacles)


@pytest.mark.parametrize("raises", [False, True])
@pytest.mark.parametrize("provider", [candidate_obstacles, candidate_host_obstacles])
def test_candidate_restores_production_on_normal_and_failed_exit(raises, provider):
    from backend.api import nanoparticle_attachment

    original = nanoparticle_attachment.duplex_obstacles
    try:
        with diagnostic_candidate(provider):
            assert nanoparticle_attachment.duplex_obstacles is provider
            if raises:
                raise RuntimeError("diagnostic failed")
    except RuntimeError:
        assert raises
    assert nanoparticle_attachment.duplex_obstacles is original


@pytest.mark.parametrize("raises", [False, True])
def test_candidate_restores_fit_policy_on_normal_and_failed_exit(raises):
    from backend.api import nanoparticle_attachment
    original = nanoparticle_attachment.fit_swing
    try:
        with diagnostic_candidate(candidate_host_obstacles, fit_shortest_root_bond):
            assert nanoparticle_attachment.fit_swing is fit_shortest_root_bond
            if raises:
                raise RuntimeError("diagnostic failed")
    except RuntimeError:
        assert raises
    assert nanoparticle_attachment.fit_swing is original


@pytest.mark.slow
@pytest.mark.parametrize("provider, fit_provider", [
    (candidate_obstacles, None), (candidate_host_obstacles, None),
    (candidate_host_obstacles, fit_shortest_root_bond),
])
def test_isolated_platform_candidate_passes_original_connection_contract(provider, fit_provider):
    from backend.core.models import LatticeType
    from tests.test_generator_connections import test_multiple_connections_close_without_moving_centers

    with diagnostic_candidate(provider, fit_provider):
        test_multiple_connections_close_without_moving_centers("platform", LatticeType.HONEYCOMB, 3)
