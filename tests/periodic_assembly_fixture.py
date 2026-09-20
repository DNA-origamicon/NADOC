"""Rebuild polymer regression specimens through the same headless routes as the UI."""

import json
from functools import lru_cache
from pathlib import Path

from backend.api import headless_build as hb, headless_assembly_build as hab, state
from backend.api.routes_scaffold_routing import route_for_polymerization_endpoint
from backend.core.models import LatticeType


@lru_cache(maxsize=2)
def _build(name):
    recipe = json.loads(
        (Path(__file__).parent / "fixtures/periodic_bundle_recipes.json").read_text()
    )[name]
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(
            [tuple(c) for c in recipe["cells"]],
            recipe["length_bp"],
            name=name,
            lattice=LatticeType.HONEYCOMB,
        )
        hb.auto_scaffold()
        hb.full_autostaple()
        route_for_polymerization_endpoint()
        hb.assign_scaffold_sequence()
        hb.assign_staple_sequences()
        part = state.get_or_404().model_copy(deep=True)
    with hab.assembly_scratch_session():
        assembly = hab.add_inline_instance(part, name=name)
        assembly = hab.polymerize_periodic(assembly.instances[0].id, count=3)
        return part, assembly.model_copy(deep=True)


def periodic_assembly(name="smallO"):
    part, assembly = _build(name)
    return part.model_copy(deep=True), assembly.model_copy(deep=True)
