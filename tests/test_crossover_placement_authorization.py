"""Authorization lock for production crossover-extra-base placement.

This is intentionally a fingerprint, not a claim that the current geometry is correct. It makes
an atom-placement proposal remain a proposal: candidate work must use the isolated Molecular
Placement Audit path until the user has inspected its A/B evidence and explicitly authorized
promotion. There is deliberately no ``--update`` command.

See ``docs/molecular_placement_audit.md`` and
``memory/feedback_geometry_change_authorization.md``.
"""

from __future__ import annotations

import hashlib
import json

import numpy as np

from backend.core.atomistic_helpers import crossover_extra_base_placements


# Owner-authorized 2026-08-12 after v7 Molecular Placement Audit review on
# 2hb_2xT, 6hb_2xT, and 2x3SQx32_2xT. The v6 rigid-residue pose fingerprint is
# unchanged; v7 adds only the final symmetric flexible-phosphate clearance.
_AUTHORIZED_PRODUCTION_FINGERPRINT = "da9995a2db1889e6d08ced945ebf6832"


def _placement_fingerprint() -> str:
    point_a = np.array([0.125, -0.375, 0.625])
    point_b = np.array([2.125, 0.875, -0.25])
    axis_a = np.array([0.2, -0.1, 1.0])
    axis_b = np.array([-0.15, 0.25, 1.0])
    cases = [
        (1, False, False),
        (1, False, True),
        (1, True, False),
        (1, True, True),
        (2, False, False),
        (2, True, False),
        (2, False, True),
        (2, True, True),
        (3, False, False),
        (3, True, False),
    ]
    rows = []
    for count, sim_reversed, local_frame_reversed in cases:
        placements = crossover_extra_base_placements(
            point_a,
            point_b,
            axis_a,
            axis_b,
            count,
            sim_reversed=sim_reversed,
            local_frame_reversed=local_frame_reversed,
        )
        rows.append(
            {
                "case": [count, sim_reversed, local_frame_reversed],
                "placements": [
                    {
                        key: (
                            placement[key]
                            if key in {"geometric_index", "sim_k"}
                            else np.asarray(placement[key]).round(12).tolist()
                        )
                        for key in (
                            "geometric_index",
                            "sim_k",
                            "center",
                            "tangent",
                            "chain_tangent",
                            "frame_rotation",
                            "bow",
                        )
                    }
                    for placement in placements
                ],
            }
        )
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":"))
    return hashlib.blake2b(payload.encode(), digest_size=16).hexdigest()


def test_production_crossover_placement_requires_demonstrated_authorization():
    actual = _placement_fingerprint()
    assert actual == _AUTHORIZED_PRODUCTION_FINGERPRINT, (
        "Production crossover-extra-base placement changed without the demonstrated "
        "authorization gate. Do not update this fingerprint while proposing a candidate. "
        "Restore production placement, show the candidate through the Molecular Placement "
        "Audit, and change this lock only after the user explicitly authorizes that candidate. "
        f"Expected {_AUTHORIZED_PRODUCTION_FINGERPRINT}, got {actual}."
    )


def test_authorization_lock_can_go_red_on_pose_drift(monkeypatch):
    original = crossover_extra_base_placements

    def shifted_placements(*args, **kwargs):
        placements = original(*args, **kwargs)
        for placement in placements:
            placement["center"] = placement["center"] + np.array([0.001, 0.0, 0.0])
        return placements

    monkeypatch.setattr(
        "tests.test_crossover_placement_authorization.crossover_extra_base_placements",
        shifted_placements,
    )
    assert _placement_fingerprint() != _AUTHORIZED_PRODUCTION_FINGERPRINT
