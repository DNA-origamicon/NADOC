"""Unsupported identity-free reconstruction must fail before any engine starts."""

import asyncio

import pytest

pytestmark = pytest.mark.native_placement


def test_legacy_mrdna_websocket_fails_before_design_or_engine_access(monkeypatch):
    from backend.api import ws

    def forbidden():
        pytest.fail("Retired one-shot route must not access a live design or start a model")

    monkeypatch.setattr(ws.design_state, "get_design", forbidden)
    messages = []

    class Socket:
        async def accept(self):
            messages.append("accepted")

        async def send_json(self, value):
            messages.append(value)

        async def close(self):
            messages.append("closed")

    asyncio.run(ws.mrdna_relax_ws(Socket()))
    assert messages[0] == "accepted" and messages[-1] == "closed"
    assert messages[1]["type"] == "mrdna_error"
    assert messages[1]["code"] == "LEGACY_MRDNA_UNSUPPORTED"
    assert "managed mrDNA job" in messages[1]["message"]
    assert not any(isinstance(value, dict) and "positions" in value for value in messages)


def test_retired_identity_free_copy_and_slab_reconstructors_are_absent():
    from backend.core import mrdna_runner

    assert not hasattr(mrdna_runner, "_expanded_nucleotide_records")
    assert not hasattr(mrdna_runner, "_add_relaxed_frames")
