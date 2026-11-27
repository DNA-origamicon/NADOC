"""Bounded Corner backend benchmark using native, recorded construction.

Run: just validate-safe uv run python -m scripts.benchmark_corner
Creates only in-memory scratch documents; no parts, captures or simulations.
Reports initial, identical-input and changed-direction previews for 168 bp
6HB and flat square bundles. Each ready result includes both display views.
Browser rendering and HTTP transport are deliberately outside these timings.
"""

import json
from time import perf_counter


def main():
    # Keep application imports out of multiprocessing's spawned main module.
    from backend.api import headless_build as hb, state
    from backend.api.corner_preview import evaluate_corner_preview
    from backend.core.atomistic_cache import clear_atomistic_cache
    from backend.core.corner_seam_cache import clear_fit_cache
    from backend.core.models import LatticeType

    cases = [
        ('6HB', [[0, 1], [1, 1], [1, 2], [1, 3], [0, 3], [0, 2]], LatticeType.HONEYCOMB),
        ('1x8 SQ', [[0, i] for i in range(8)], LatticeType.SQUARE),
    ]
    for label, cells, lattice in cases:
        with hb.scratch_session(lattice):
            hb.create_bundle(cells, 168, lattice=lattice, separate_fresh_extrusions=False)
            hb.add_cluster('__e2e__Corner benchmark', [h.id for h in state.get_or_404().helices], log=True)
            source, _ = state.copy_for_persist()
            owner = next(c for c in source.cluster_transforms if c.name == '__e2e__Corner benchmark')
            before = source.model_dump_json()
            inputs = dict(cluster_id=owner.id, position_bp=84, angle_deg=90, direction_deg=0)
            clear_atomistic_cache()
            clear_fit_cache()
            for condition in ('cold', 'repeat', 'changed'):
                if condition == 'changed':
                    inputs['direction_deg'] = 15
                milestones = {}

                def progress(event):
                    if event['percent'] in (20, 30, 100):
                        milestones.setdefault(event['percent'], event['elapsed_seconds'])

                started = perf_counter()
                packet, candidate = evaluate_corner_preview(source, inputs, on_progress=progress)
                elapsed = perf_counter() - started
                assert candidate.feature_log[-1].id == packet['feature_id']
                assert state.get_or_404().model_dump_json() == before
                print(json.dumps({
                    'case': label, 'condition': condition, 'seconds': elapsed,
                    'routing_and_recording_seconds': milestones[30],
                    'projection_seconds': milestones[100] - milestones[30],
                }), flush=True)
    clear_atomistic_cache()
    clear_fit_cache()


if __name__ == '__main__':
    main()
