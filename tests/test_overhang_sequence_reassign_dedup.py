"""The overhang PATCH / generate-random endpoints re-derive staple sequences
(`assign_staple_sequences`) on every sequence write. The connection-CREATION flow sets
BOTH overhangs then immediately applies (which re-derives once with the FINAL topology),
so the intermediate re-derivations are redundant — `defer_reassign` skips them. These pins
prove the flag skips the re-derivation and that the default still re-derives.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import backend.core.sequences as seqmod
from backend.api import state as design_state
from backend.api.main import app
from backend.api.routes import _demo_design
from backend.core.models import Design

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "relax_2x2_binding.nadoc"
# Untracked fixture with no headless builder yet (design-automation AF-FIXTURES) — skip cleanly
# where it's absent (a fresh checkout / the other computer) instead of erroring.
pytestmark = pytest.mark.skipif(
    not _FIXTURE.exists(),
    reason="relax_2x2_binding.nadoc missing (untracked; regen via AF-FIXTURES builder)")


@pytest.fixture
def _counter(monkeypatch):
    calls = {"n": 0}
    orig = seqmod.assign_staple_sequences

    def _counted(design):
        calls["n"] += 1
        return orig(design)

    monkeypatch.setattr(seqmod, "assign_staple_sequences", _counted)
    yield calls
    design_state.set_design(_demo_design())


def _sequenced_two_overhang_design():
    d = Design.model_validate(json.loads(_FIXTURE.read_text()))
    # strip the applied binding/duplex/cluster so the two overhangs are free.
    d = d.model_copy(update={
        "overhang_bindings": [], "duplexes": [],
        "cluster_transforms": [c for c in d.cluster_transforms
                               if not c.overhang_duplex_driver_id],
    })
    return d, d.overhangs[0].id, d.overhangs[1].id


def test_defer_reassign_skips_the_staple_re_derivation(_counter):
    d, a, _b = _sequenced_two_overhang_design()
    design_state.set_design(d)
    client = TestClient(app)
    client.post("/api/design/assign-scaffold-sequence", json={"scaffold_name": "M13mp18"})
    _counter["n"] = 0

    # Deferred write → no re-derivation.
    r = client.patch(f"/api/design/overhang/{a}", json={"sequence": "ACGTACGT", "defer_reassign": True})
    assert r.status_code == 200, r.text
    assert _counter["n"] == 0

    # Default write → exactly one re-derivation (the standalone-edit behaviour).
    r = client.patch(f"/api/design/overhang/{a}", json={"sequence": "ACGTACGT"})
    assert r.status_code == 200, r.text
    assert _counter["n"] == 1


def test_connection_creation_flow_re_derives_once_not_thrice(_counter):
    """End-to-end: set both overhang sequences (deferred) then apply — the whole
    connection creation re-derives staples EXACTLY once (the apply), not once per set."""
    d, a, b = _sequenced_two_overhang_design()
    design_state.set_design(d)
    client = TestClient(app)
    client.post("/api/design/assign-scaffold-sequence", json={"scaffold_name": "M13mp18"})
    _counter["n"] = 0

    client.patch(f"/api/design/overhang/{a}", json={"sequence": "ACGTACGT", "defer_reassign": True})
    client.patch(f"/api/design/overhang/{b}", json={"sequence": "ACGTACGT", "defer_reassign": True})
    client.post("/api/design/connection-versions",
                json={"overhang_a_id": a, "overhang_b_id": b, "connection_type": "root-to-root"})
    vid = design_state.get_or_404().connection_versions[-1].id
    client.post(f"/api/design/connection-versions/{vid}/apply")

    assert _counter["n"] == 1, f"expected one staple re-derivation, got {_counter['n']}"
