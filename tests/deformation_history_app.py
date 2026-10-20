"""Test-only app: production routing/middleware without production job startup.

Only the dedicated S03 launcher imports this factory in a server process. Nothing
in backend/ imports it. Fixtures are bounded native recipes, never saved user models.
"""

from contextlib import asynccontextmanager, nullcontext
from hashlib import sha256
import json
import os

from fastapi import FastAPI, HTTPException

from tests.extrude_matrix_fixture import FAMILIES

FIXTURES = {"repair-sweep-source", "repair-extrude-source", "history-scoped-order", "history-reorder","extrude-large", "extrude-blocked", "sweep-large", "extrude-nick-batch", "routing", "bend-large", "bend", "twist", "bend-nick", "twist-nick", "bend-chain", "bend-sweep", "twist-sweep", "sweep-extrude", "sweep-independent", "sweep-start", "sweep-detached", "sweep-nick", "sweep-nick-batch", "extrude-chain", "bend-limit", "bend-over-limit", "bend-legacy", "bend-legacy-snapshots", "bend-fixed", *FAMILIES}


def fixture(kind):
    from uuid import uuid4

    from backend.api.crud import BundleRequest
    from backend.core.models import DeformationLogEntry, DeformationOp, MinorMutationLogEntry, RoutingClusterLogEntry, SnapshotLogEntry
    from backend.core.part_history_contract import create_empty_part
    from tests.test_part_deformation_preview import _append

    if kind not in FIXTURES:
        raise ValueError("Unknown fixture")
    if kind in {'repair-sweep-source', 'repair-extrude-source'}:
        from tests.test_part_geometry_reference_repair import fixture as repair_fixture
        family, field = ('sweep', 'source_helix_id') if kind == 'repair-sweep-source' else ('extrude-continuation', 'source_frame_id')
        return repair_fixture(family, field)[1]
    if kind == "history-scoped-order":
        from tests.test_part_history_reorder import scoped_sweep_source
        return scoped_sweep_source()
    if kind == "history-reorder":
        from backend.api.crud import _build_bundle
        from backend.api.part_proof_commands import execute
        from backend.core.models import ClusterRigidTransform
        from backend.core.part_history_proof import import_root
        source = _build_bundle([(0, 0)], BundleRequest(cells=[[0, 0]], length_bp=21, name="__e2e__history-reorder"))
        source.cluster_transforms.extend(ClusterRigidTransform(id=i) for i in ["a", "b", "c"])
        source.recipe_root = import_root(source)
        log = []
        for identity in ["a", "b", "c"]:
            params = {"joint_id": identity, "cluster_id": identity, "local_axis_origin": [0, 0, 0],
                      "local_axis_direction": [0, 0, 1], "_proof_version": 1}
            source = execute("joint-place", source, params)
            log.append(RoutingClusterLogEntry(id=identity, children=[MinorMutationLogEntry(
                id=identity + "-child", op_subtype="joint-place", label=identity, params=params)]))
        return source.copy_with(feature_log=log)
    if kind == "sweep-large":
        from backend.core.sweep import SweepRequest
        from tests.test_part_sweep_preview import snapshot
        from tests.test_group_lineage_resize_pipeline import minor
        source = create_empty_part("__e2e__history-sweep-large", "HONEYCOMB")
        source = snapshot(source, "sweep", SweepRequest(
            sweep_id=str(uuid4()), cells=[[r, c] for r in range(6) for c in range(3)],
            points_nm=[[0, 0, 0], [0, 0, 171.36]], ligate_adjacent=False,
        ).model_dump(mode="json"), "selected-sweep")
        return minor(source, "nick-batch", {"nicks": [
            {"helix_id": source.helices[0].id, "bp_index": 200, "direction": "FORWARD"}]})
    if kind in {"extrude-nick-batch", "extrude-blocked", "extrude-large"}:
        from tests.test_part_extrusion_edit_routes import append
        from tests.test_group_lineage_resize_pipeline import minor
        source = create_empty_part("__e2e__history-extrude", "HONEYCOMB")
        source = append(source, "extrude-frame", {
            "history_seed": str(uuid4()),
            "cells": [[r, c] for r in range(6) for c in range(3)] if kind == "extrude-large" else [[0, 0]],
            "length_bp": 504 if kind == "extrude-large" else 14,
            "plane": "XY", "translation_nm": [4, 0, 0],
            "expected_design_id": source.id, "expected_revision": 0,
        }, "selected-extrude")
        source = minor(source, "nick-batch", {"nicks": [
            {"helix_id": source.helices[0].id, "bp_index": bp, "direction": "FORWARD"}
            for bp in (1, 10)]})
        source.feature_log[-1].children[0].label = "Output nick pair"
        if kind == "extrude-blocked":
            source = minor(source, "nick-batch", {"nicks": [
                {"helix_id": source.helices[0].id, "bp_index": 3, "direction": "FORWARD"}]})
            source.feature_log[-1].children[-1].label = "Later nick"
        return source
    if kind in {"sweep-nick", "sweep-nick-batch"}:
        from tests.test_part_sweep_preview_sessions import recipe
        return recipe(downstream="batch" if kind.endswith("-batch") else True, name="__e2e__history-sweep")
    if kind in FAMILIES:
        from tests.extrude_matrix_fixture import fixture as matrix_fixture
        return matrix_fixture(kind)
    if kind == "bend-large":
        # C8 representative large part: 18-helix x 504 bp honeycomb, scaffolded,
        # autostapled, with one routed whole-bundle bend (S61 latency evidence).
        from backend.api import headless_build as hb, state as design_state
        from backend.core.models import LatticeType

        with hb.scratch_session():
            design_state.load_design(create_empty_part("__e2e__history-bend", "HONEYCOMB"))
            hb.create_bundle([(r, c) for r in range(6) for c in range(3)], 504, lattice=LatticeType.HONEYCOMB)
            hb.auto_scaffold(seamless=True)
            hb.full_autostaple()
            hb.add_bend(100, 200, curvature_deg_per_bp=0.3,
                        affected_helix_ids=[h.id for h in design_state.get_or_404().helices])
            return design_state.get_or_404()
    if kind == "routing":
        # Autostapled 6HB with one positional (v2) staple-end resize: routing step
        # editor and region autostaple browser checks.
        from backend.api import headless_build as hb, state as design_state
        from backend.core.models import LatticeType

        with hb.scratch_session():
            design_state.load_design(create_empty_part("__e2e__history-bend", "HONEYCOMB"))
            hb.create_bundle([(0, 0), (0, 1), (1, 0), (1, 1), (2, 0), (2, 1)], 84, lattice=LatticeType.HONEYCOMB)
            hb.auto_scaffold(seamless=True)
            hb.full_autostaple()
            design = design_state.get_or_404()
            staple = min((s for s in design.strands if s.strand_type.value == "staple" and len(s.domains) >= 2),
                         key=lambda s: max(max(d.start_bp, d.end_bp) for d in s.domains))
            hb.resize_strand_end(staple.id, staple.domains[0].helix_id, "5p", -1)
            return design_state.get_or_404()
    if kind == "extrude-chain":
        source = fixture("bend-sweep")
        row = source.feature_log[0]
        row.evicted = True
        row.design_snapshot_gz_b64 = "poisoned-before"
        row.post_state_gz_b64 = "poisoned-after"
        return source
    if kind == "bend-legacy":
        # Same native rows without an explicit recipe root, like pre-overhaul saved
        # files: the isolated editor refuses it and the legacy editor takes over.
        return fixture("bend").copy_with(recipe_root=None)
    if kind == "bend-legacy-snapshots":
        # Pre-overhaul shape with recovery snapshots: unseeded bundle row, bend
        # without a proof version, no recipe root. Convertible (bend stays editable).
        from backend.api.state import encode_design_snapshot
        from backend.core.part_history_proof import root_design
        native = fixture("bend")
        bundle_row, bend_row = native.feature_log
        empty = root_design(native.recipe_root)
        after_bundle = part_proof_commands_execute(bundle_row, empty)
        pre, _ = encode_design_snapshot(empty)
        post, _ = encode_design_snapshot(after_bundle)
        legacy_bundle = bundle_row.model_copy(update={
            "params": {k: v for k, v in bundle_row.params.items() if k not in {"_proof_version", "history_seed"}},
            "design_snapshot_gz_b64": pre, "post_state_gz_b64": post, "evicted": False})
        return native.copy_with(recipe_root=None, feature_log=[legacy_bundle, bend_row.model_copy(update={"proof_version": None})])
    if kind == "bend-fixed":
        # A downstream fixed-endpoint bend overlapping the edited bend: changing
        # the upstream curvature makes it unregenerable (contract C4).
        from backend.core import deformation
        source = fixture("bend")
        helices = [deformation.effective_helix_for_geometry(h, source) for h in source.helices]
        start = min(h.bp_start for h in helices)
        ends = [tuple(float(x) for x in deformation._frame_at_bp(source, bp - start, helices)[0]) for bp in (10, 20)]
        fixed = DeformationOp(id="fixed-bend", type="bend", plane_a_bp=10, plane_b_bp=20,
                              affected_helix_ids=[h.id for h in source.helices], cluster_ids=[],
                              params={"kind": "bend", "curvature_deg_per_bp": .25, "direction_deg": 0, "endpoints": ends})
        later = DeformationLogEntry(id="fixed-feature", deformation_id=fixed.id, op_snapshot=fixed, proof_version=1)
        source = _append(source, later)
        source.feature_log[-1] = later.model_copy(update={"op_snapshot": source.deformations[-1]})
        return source
    if kind in {"sweep-extrude", "sweep-independent", "sweep-start", "sweep-detached"}:
        from tests.sweep_history_fixture import fixture as sweep_fixture
        return sweep_fixture("end" if kind == "sweep-extrude" else kind.removeprefix("sweep-"))
    variant = kind
    kind = "twist" if kind in {"twist", "twist-sweep", "twist-nick"} else "bend"
    name = f"__e2e__history-{kind}"
    source = create_empty_part(name, "HONEYCOMB")
    count = {"bend-chain": 4, "bend-limit": 16, "bend-over-limit": 17}.get(variant, 1)
    length = 32 if count >= 16 else 42
    params = BundleRequest(cells=[[0, col] for col in range(count)], length_bp=length, name=name,
                           history_seed=uuid4()).model_dump(mode="json")
    source = _append(source, SnapshotLogEntry(
        op_kind="bundle-create", label="Native bounded bundle",
        params={**params, "_proof_version": 1},
    ))
    op = DeformationOp(
        id="preview-operation", type=kind, plane_a_bp=4, plane_b_bp=min(32, length - 4),
        affected_helix_ids=[helix.id for helix in source.helices],
        params={"kind": kind, **({"curvature_deg_per_bp": .25, "direction_deg": 0}
                               if kind == "bend" else {"total_degrees": 8})},
    )
    entry = DeformationLogEntry(id="edited-feature", deformation_id=op.id,
                                op_snapshot=op, proof_version=1)
    source = _append(source, entry)
    source.feature_log[-1] = entry.model_copy(update={"op_snapshot": source.deformations[-1]})
    if variant == "bend-chain":
        later = DeformationOp(id="later-twist", type="twist", plane_a_bp=6, plane_b_bp=28,
                              affected_helix_ids=[helix.id for helix in source.helices],
                              params={"kind": "twist", "total_degrees": 8})
        suffix = DeformationLogEntry(id="later-feature", deformation_id=later.id,
                                    op_snapshot=later, proof_version=1)
        source = _append(source, suffix)
        source.feature_log[-1] = suffix.model_copy(update={"op_snapshot": source.deformations[-1]})
    if variant in {"bend-sweep", "twist-sweep"}:
        from tests.test_bend_sweep_history import append_attached_sweep
        source = append_attached_sweep(source)
    if variant in {"bend-nick", "twist-nick"}:
        # Reuse the existing native nick convention and identity rules.
        child = MinorMutationLogEntry(
            id="nick-child", op_subtype="nick", label="Downstream native nick",
            params={"_proof_version": 1, "helix_id": source.helices[0].id,
                    "bp_index": 7, "direction": "FORWARD"},
        )
        row = RoutingClusterLogEntry(id="downstream-nick", children=[child], evicted=True,
            pre_state_gz_b64="poisoned-routing-before", post_state_gz_b64="poisoned-routing-after")
        updated = _append(source, child)
        source = updated.copy_with(feature_log=[*source.feature_log, row])
        source.feature_log[0].evicted = True
        source.feature_log[0].design_snapshot_gz_b64 = "poisoned-before"
        source.feature_log[0].post_state_gz_b64 = "poisoned-after"
    return source


def part_proof_commands_execute(entry, design):
    from backend.api.part_proof_commands import execute
    from backend.core.part_overlay_commands import command_input
    kind, params = command_input(entry)
    return execute(kind, design, params)


def cold_replay(source):
    """Test oracle: execute only explicit root and authored command inputs."""
    from backend.core.part_history_proof import root_design, command_rows
    from backend.api.part_proof_commands import execute

    expected = root_design(source.recipe_root, input_sources=source.input_sources)
    for _, kind, params in command_rows(source, 100):
        expected = execute(kind, expected, params)
    return expected


def create_app():
    sealed = os.environ.get("NADOC_HISTORY_E2E_SEALED") == "1"
    from tests import sealed_history_fixture as sealed_fixture

    from backend.api import assembly, doc_context, main, state
    from backend.api import part_deformation_preview_sessions as host
    from backend.api import routes_part_deformation_preview as routes
    from backend.api import routes_part_sweep_preview as sweep_routes

    @asynccontextmanager
    async def lifespan(_app):
        assert sweep_routes.SWEEP_PREVIEW_ENABLED, "Sweep production preview must be enabled"
        previous = routes.DEFORMATION_PREVIEW_ENABLED
        routes.DEFORMATION_PREVIEW_ENABLED = True
        try:
            with sealed_fixture.enabled() if sealed else nullcontext():
                yield
        finally:
            host.clear_for_testing()
            for identity in tuple(state._sessions):
                if identity.startswith("__e2e__history-"):
                    state.drop_doc(identity)
            routes.DEFORMATION_PREVIEW_ENABLED = previous

    # Copy route list; never add fixture routes to main.app or replace its lifespan.
    from starlette.middleware import Middleware
    middleware = [Middleware(sealed_fixture.FixtureDispatch, *item.args, **item.kwargs)
                  if sealed and item.cls is sealed_fixture.StrictPartDispatch else item
                  for item in main.app.user_middleware]
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None,
                  middleware=middleware,
                  exception_handlers=dict(main.app.exception_handlers), lifespan=lifespan)

    def require_doc():
        if doc_context.get_current_doc() not in {"__e2e__history-bend", "__e2e__history-twist"}:
            raise HTTPException(403, "Only the two isolated history fixtures are admitted")

    @app.post("/api/__e2e__/history/seed/{kind}")
    def seed(kind: str):
        require_doc()
        if kind not in FIXTURES:
            raise HTTPException(422, "Unknown fixture")
        if sealed:
            if kind not in {"bend", "twist"}:
                raise HTTPException(422, "Sealed desktop fixtures are Bend/Twist only")
            sealed_fixture.seed(fixture(kind))
            return {"ok": True, "sealed": True}
        state.load_design(fixture(kind))
        # Nonempty redo is essential: Cancel must preserve it, Apply must clear it.
        state.set_design(state.get_or_404().copy_with())
        state.undo()
        return {"ok": True}

    @app.get("/api/__e2e__/history/checkpoint")
    def checkpoint():
        require_doc()
        def digest(value):
            return sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

        if sealed:
            result = sealed_fixture.checkpoint()
        else:
            with state._lock:
                session = state._session()
                result = {"design": session.design.model_dump(mode="json"),
                          "revision": session.revision,
                          "history": [digest(d.model_dump(mode="json")) for d in session.history],
                          "redo": [digest(d.model_dump(mode="json")) for d in session.redo]}
        workspace = assembly._WORKSPACE_DIR
        result["files"] = {str(p.relative_to(workspace)): sha256(p.read_bytes()).hexdigest()
                           for p in workspace.rglob("*") if p.is_file()}
        return result

    @app.get("/api/__e2e__/history/proof")
    def proof():
        require_doc()
        from backend.api.part_proof_commands import dependencies, execute
        from backend.core.part_history_contract import assess_part_history

        if sealed:
            source = sealed_fixture.source()
        else:
            with state._lock:
                source = state._session().design.model_copy(deep=True)
        result = assess_part_history(source, execute=execute, dependencies=dependencies)
        if source.feature_log[-1].id == "downstream-nick" or source.feature_log[0].id == "selected-sweep":
            from backend.core.design_geometry import _geometry_for_design
            from tests.test_part_deformation_preview import authoring
            expected = cold_replay(source)
            result["cold_replay"] = {
                "authoring": authoring(expected), "geometry": _geometry_for_design(expected),
                "authoring_equal": authoring(source) == authoring(expected),
                "geometry_equal": _geometry_for_design(source) == _geometry_for_design(expected),
            }
        return result

    @app.get("/api/__e2e__/history/resources")
    def resources():
        require_doc()
        import psutil

        with host._lock:
            retained = {"sessions": len(host._entries), "tombstones": len(host._tombstones),
                        "document_sessions": int(doc_context.get_current_doc() in host._entries)}
        return {**retained, "rss_bytes": psutil.Process().memory_info().rss}

    @app.delete("/api/__e2e__/history/close")
    def close():
        require_doc()
        state.drop_doc(doc_context.get_current_doc())
        return {"ok": True}

    # Production has a final static mount: fixture routes must precede it.
    app.router.routes.extend(main.app.routes)
    return app
