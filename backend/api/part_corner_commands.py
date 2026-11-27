"""Versioned Corner inputs and preflight, with explicit topology ownership.

Preflight is read-only. Publication must use the native feature recorder after
the junction evaluator has resolved and validated every planned connection.
"""

import math
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from backend.api.corner_guide import corner_guide
from backend.core.corner_plan import CornerParameters
from backend.core.corner_routing import (
    CornerRoutingPlan, DuplexCut, RoutedDomain, RoutedStrand, plan_corner_routes, occupied_duplex_spans,
)


class CornerRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    cluster_id: Annotated[str, Field(min_length=1, max_length=256, strict=True)]
    position_bp: Annotated[StrictInt, Field(ge=-1_000_000, le=1_000_000)]
    angle_deg: float = Field(ge=0, lt=180, allow_inf_nan=False)
    direction_deg: float = Field(allow_inf_nan=False)

    def parameters(self):
        return CornerParameters(self.position_bp, self.angle_deg, self.direction_deg)


class CornerCommand(CornerRequest):
    proof_version: Annotated[StrictInt, Field(ge=1, le=3)] = Field(default=3, alias='_proof_version')
    operation_id: Annotated[str, Field(min_length=1, max_length=64, strict=True)]

    def inputs(self):
        return {key: getattr(self, key) for key in CornerRequest.model_fields}


def dependencies(params):
    from backend.core.part_dependencies import Dependencies, Resource
    try:
        if params.get('_proof_version') not in (1, 2, 3):
            return Dependencies(known=False)
        command = CornerCommand.model_validate(params)
    except (ValueError, TypeError, AttributeError):
        return Dependencies(known=False)
    topology = Resource('part', 'topology')
    return Dependencies(frozenset({topology, Resource('cluster', command.cluster_id)}),
                        frozenset({topology}), barrier=True)


_evaluation_observer = ContextVar('corner_evaluation_observer', default=None)


@contextmanager
def observe_evaluation(operation_id, on_progress, check_cancel):
    """Request-local diagnostics only; never part of a recorded command input."""
    token = _evaluation_observer.set((operation_id, on_progress, check_cancel))
    try:
        yield
    finally:
        _evaluation_observer.reset(token)


def build(design, params):
    from backend.api.corner_build import build_corner
    command = CornerCommand.model_validate(params)
    observer = _evaluation_observer.get()
    progress = observer[1] if observer and observer[0] == command.operation_id else None
    return build_corner(design, command, on_progress=progress,
                        check_cancel=observer[2] if observer else None)


def preflight(design, params, *, check_cancel=None):
    """Return the geometric guide and explicit 5′→3′ route candidates.

    Integer endpoints conservatively stop before/after the continuous face;
    phase refinement and inserted bases are the subsequent calculation, not
    hidden assumptions in this quantization.
    """
    if check_cancel:
        check_cancel()
    request = CornerRequest.model_validate(params)
    guide = corner_guide(design, request.cluster_id, request.parameters())
    if request.angle_deg == 0:
        # Straight means no duplex duplication and no inserted junction bases.
        return guide, CornerRoutingPlan(tuple(RoutedStrand(s.id, s.strand_type.value,
            tuple(RoutedDomain(i, d.helix_id, 'unchanged', d.start_bp, d.end_bp, d.direction.value)
                  for i, d in enumerate(s.domains))) for s in design.strands), (), ())
    cuts = []
    helix_map = {h.id: h for h in design.helices}
    for row in guide['cuts']:
        helix = helix_map[row['helix_id']]
        if not 2 <= helix.length_bp <= 2048:
            raise ValueError('Corner indexed paths need 2–2048 duplex stations.')
        marks = {}
        for mark in helix.loop_skips:
            marks[mark.bp_index] = marks.get(mark.bp_index, 0) + mark.delta
        incoming, outgoing = math.floor(row['incoming_bp']), math.ceil(row['outgoing_bp'])
        # A seam needs an unambiguous ordinary nucleotide at each end. Retreat
        # into its own wedge past skips or multi-copy stations, retaining every
        # loop/skip mark and all copies elsewhere on that wedge.
        while marks.get(incoming, 0):
            incoming -= 1
        while marks.get(outgoing, 0):
            outgoing += 1
        cut = DuplexCut(helix.id, incoming, outgoing)
        lo, hi = helix.bp_start, helix.bp_start + helix.length_bp - 1
        if not (lo <= cut.incoming_last_bp < hi and lo < cut.outgoing_first_bp <= hi):
            raise ValueError('The corner leaves insufficient duplex material for a junction.')
        cuts.append(cut)
    from backend.core.corner_tip_support import rigid_tip_support, refine_duplex_cuts
    support = rigid_tip_support(design, [helix_map[c.helix_id] for c in cuts],
        guide['center_nm'], guide['plane_normal'], guide['rotation'], check_cancel=check_cancel,
        station_ranges=occupied_duplex_spans(design.strands))
    cuts = refine_duplex_cuts(cuts, support)
    # Refinement may land on an inserted (multi-copy) station. Keep the native
    # marks intact and retreat to an ordinary seam endpoint within that wedge.
    refined = []
    for cut in cuts:
        helix = helix_map[cut.helix_id]
        marks = {}
        for mark in helix.loop_skips:
            marks[mark.bp_index] = marks.get(mark.bp_index, 0) + mark.delta
        incoming, outgoing = cut.incoming_last_bp, cut.outgoing_first_bp
        while marks.get(incoming, 0):
            incoming -= 1
        while marks.get(outgoing, 0):
            outgoing += 1
        if not (helix.bp_start <= incoming and outgoing < helix.bp_start + helix.length_bp):
            raise ValueError('The corner leaves insufficient ordinary duplex endpoints after tip clearance.')
        refined.append(DuplexCut(helix.id, incoming, outgoing))
    routes = plan_corner_routes(design.strands, refined, request.position_bp)
    return guide, routes
