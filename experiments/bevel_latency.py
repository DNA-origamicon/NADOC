"""Read-only source, real in-memory Bevel commands; no authored files are saved."""
from pathlib import Path
from time import perf_counter
import json

from backend.api import crud, state, headless_build as hb
from backend.api.routes_bevel import CreateBevelRequest, create_bevel, edit_bevel, bevel_source
from backend.api.corner_preview_projection import project_corner_preview
from backend.core.models import Design


def run(path, verify=False, profile=False):
    raw = path.read_bytes()
    source = Design.model_validate_json(raw)
    with hb.scratch_session(source.lattice_type):
        state.set_design(source)
        started = perf_counter()
        project_corner_preview(source)
        print('Initial source Full + straight load:', perf_counter()-started, flush=True)
        owner = source.cluster_transforms[0].id
        def body(position):
            design, revision = state.get_design_with_revision()
            return CreateBevelRequest(cluster_id=owner, position_bp=position, angle_deg=20,
                direction_deg=30, expected_design_id=design.id, expected_revision=revision)
        def measure(label, action):
            import cProfile, pstats, gc
            collections, gc_started = [], [0.]
            def collection(phase, details):
                if phase == 'start':
                    gc_started[0] = perf_counter()
                else:
                    collections.append(perf_counter()-gc_started[0])
            profiler = cProfile.Profile() if profile else None
            started = perf_counter()
            if profiler:
                profiler.enable()
            gc.callbacks.append(collection)
            try:
                result = action()
            finally:
                gc.callbacks.remove(collection)
            from fastapi.responses import ORJSONResponse
            if isinstance(result, dict):
                result = ORJSONResponse(result)
            if profiler:
                profiler.disable()
            print(json.dumps({'operation': label, 'seconds': perf_counter()-started,
                              'gc_seconds': sum(collections)}), flush=True)
            if profiler:
                pstats.Stats(profiler).strip_dirs().sort_stats('cumulative').print_stats(12)
        measure('apply_without_preview', lambda: create_bevel(body(150)))
        first_cut = state.get_or_404().model_copy(deep=True)
        measure('undo', crud.undo_design)
        measure('redo', crud.redo_design)
        measure('open_edit', lambda: bevel_source(body(150), state.get_or_404().feature_log[-1].id,
                                                compact_geometry=True))
        measure('edit', lambda: edit_bevel(state.get_or_404().feature_log[-1].id, body(145)))
        measure('delete', lambda: crud.delete_feature(len(state.get_or_404().feature_log)-1))
        measure('undo_delete', crud.undo_design)
        measure('revert', lambda: crud.revert_to_before_feature(len(state.get_or_404().feature_log)-1))
        if verify:
            fast = project_corner_preview(first_cut)
            from backend.core.atomistic_cache import clear_atomistic_cache
            from backend.core.corner_seam_cache import clear_fit_cache
            from backend.core.corner_seam_projection import clear_projection_cache
            clear_atomistic_cache(); clear_fit_cache(); clear_projection_cache()
            exact = project_corner_preview(first_cut)
            assert fast == exact
            from backend.api.part_proof_commands import execute, dependencies
            from backend.core.part_history_contract import assess_part_history
            proof = assess_part_history(Design.model_validate_json(first_cut.model_dump_json()),
                                       execute=execute, dependencies=dependencies)
            assert proof['status'] == 'verified', proof
            print('Independent projection exact; recorded process verified', flush=True)
    assert path.read_bytes() == raw


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--profile', action='store_true')
    args = parser.parse_args()
    run(args.source, args.verify, args.profile)
