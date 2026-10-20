"""Tiny Sweep source-mode matrix with later Extrude, for isolated desktop acceptance."""
from uuid import uuid4

from backend.api.crud import BundleRequest
from backend.core.part_history_contract import create_empty_part
from backend.core.sweep import SweepRequest
from tests.test_part_sweep_preview import snapshot


def fixture(mode="end"):
    if mode not in {"end", "independent", "start", "detached"}:
        raise ValueError("Unknown Sweep source mode")
    name = "__e2e__history-sweep"
    source = create_empty_part(name, "HONEYCOMB")
    source = snapshot(source, "bundle-create", BundleRequest(
        cells=[[0, 0], [0, 1]], length_bp=12, name=name,
        ligate_adjacent=False, history_seed=uuid4()).model_dump(mode="json"), "bundle")
    source = snapshot(source, "sweep", SweepRequest(
        sweep_id=str(uuid4()), cells=[[4, 4]] if mode == "independent" else [[0, 0], [0, 1]],
        points_nm=[[0, 0, 0], [0, 0, -4 if mode == "start" else 4]], ligate_adjacent=False,
        source_helix_id=None if mode == "independent" else source.helices[0].id,
        source_end="start" if mode == "start" else "end",
    ).model_dump(mode="json"), "selected-sweep")
    return snapshot(source, "extrude-segment", {
        "cells": [[8, 8]], "length_bp": 5, "plane": "XY",
        "history_seed": str(uuid4()),
    }, "later-extrusion")
