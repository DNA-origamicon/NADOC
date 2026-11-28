"""Bounded derived-geometry worker for interactive Corner previews.

Uses the existing disposable-worker transport/reaping boundary. The native
authoring transaction stays in its owner; only detached Full projection runs
here. No files, live sessions, saved molecular overrides or simulation jobs.
"""

import os
import pickle
import struct
import threading
from multiprocessing.shared_memory import SharedMemory
from time import monotonic

import orjson

from backend.api.part_verification_worker import VerificationWorker, _BoundedInput, RESULT_HEADER_BYTES, WorkerLimit

_INPUT_LIMIT = 16 * 1024**2
_RESULT_LIMIT = 32 * 1024**2
_PROGRESS_OFFSET = RESULT_HEADER_BYTES + _RESULT_LIMIT
_PROGRESS_SIZE = 12
_display_pair_lock = threading.Lock()


def prepare_corner_display_pair(design):
    """Populate exact native projections before the ordinary display providers.

    Serialize cold display requests so concurrent tabs do not each launch a
    pair of workers. Warm requests use the existing projection caches. Worker
    transport limits are an optimization boundary, not a new file-load limit.
    """
    from backend.core.corner_seam_placement import corner_insert_links
    if design.atomistic_reference is not None or not corner_insert_links(design):
        return
    with _display_pair_lock:
        try:
            project_corner_in_worker(design, projection_only=True)
        except ValueError:
            import logging
            logging.getLogger(__name__).warning(
                'Parallel Corner projection unavailable; using local geometry.', exc_info=True)


def _project(input_name, input_size, output_name):
    for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        os.environ[name] = '1'
    source, output = SharedMemory(name=input_name), SharedMemory(name=output_name)
    sequence = 0

    def progress(done, total):
        nonlocal sequence
        # Single writer, sequence stamp before/after the two counters. Readers
        # ignore in-progress frames; no killed process can leave a lock held.
        sequence += 2
        struct.pack_into('!I', output.buf, _PROGRESS_OFFSET, sequence-1)
        struct.pack_into('!II', output.buf, _PROGRESS_OFFSET+4, done, total)
        struct.pack_into('!I', output.buf, _PROGRESS_OFFSET, sequence)

    try:
        try:
            from backend.api.corner_preview_projection import project_corner_preview, project_corner_straight
            from backend.core.corner_seam_cache import import_fits, export_fits
            from backend.core.corner_seam_projection import import_projection, export_projection
            request = pickle.loads(source.buf[:input_size])
            import_fits(request['fits'])
            import_projection(request.get('projection'))
            view = _view(request['design'], request['straight'])
            if request.get('projection_only'):
                from backend.core.corner_seam_projection import _projection
                from backend.core.corner_seam_placement import corner_insert_links, observe_corner_placement
                with observe_corner_placement(progress):
                    _projection(view, corner_insert_links(view))
                component = {'projection_ready': True}
            else:
                component = (project_corner_straight(request['design'], on_progress=progress)
                    if request['straight'] else
                    project_corner_preview(request['design'], on_progress=progress, include_straight=False))
            result = {'issues': [], 'component': component, 'fits': export_fits(),
                      'projection': export_projection(view)}
            encoded = orjson.dumps(result, option=orjson.OPT_SERIALIZE_NUMPY)
            if len(encoded) > _RESULT_LIMIT:
                raise ValueError('Corner Full preview exceeds its geometry transport budget.')
        except Exception as error:
            encoded = orjson.dumps({'issues': [{'detail': str(error)[:2048]}]})
        output.buf[RESULT_HEADER_BYTES:RESULT_HEADER_BYTES+len(encoded)] = encoded
        struct.pack_into('!I', output.buf, 0, len(encoded))
    finally:
        source.close()
        output.close()


class CornerProjectionWorker(VerificationWorker):
    def __init__(self, design, *, straight=False, projection_only=False):
        from backend.core.corner_seam_cache import export_fits
        from backend.core.corner_seam_projection import export_projection
        self._straight = straight
        self._projection_only = projection_only
        stream = _BoundedInput(_INPUT_LIMIT)
        try:
            pickle.dump({'design': design, 'fits': export_fits(), 'straight': straight,
                         'projection_only': projection_only,
                         'projection': export_projection(_view(design, straight))},
                        stream, protocol=pickle.HIGHEST_PROTOCOL)
        except WorkerLimit as error:
            raise ValueError('Corner preview source exceeds its calculation budget.') from error
        self._initialize_input((stream.getvalue(),), _target=_project,
            _result_limit=_RESULT_LIMIT + _PROGRESS_SIZE, _name='nadoc-corner-preview')

    def progress(self):
        before, done, total = struct.unpack_from('!III', self._output.buf, _PROGRESS_OFFSET)
        after = struct.unpack_from('!I', self._output.buf, _PROGRESS_OFFSET)[0]
        return (done, total) if before == after and before % 2 == 0 and 0 <= done <= total else None

    def result(self):
        result = self._read_result()
        if result['issues']:
            raise ValueError(result['issues'][0].get('detail', 'Corner geometry worker stopped.'))
        valid = (result.get('component', {}).get('projection_ready') is True if self._projection_only else
                 'straight_positions_by_helix' in result.get('component', {}) if self._straight else
                 result.get('component', {}).get('component_kind') == 'corner-preview-dna')
        if not valid:
            raise ValueError('Corner geometry worker returned an invalid preview.')
        return result


def _view(design, straight):
    return design.model_copy(update={'deformations': [], 'cluster_transforms': []}) if straight else design


def project_corner_in_worker(design, *, on_progress=None, include_straight=True, projection_only=False):
    """Prepare both independent views concurrently, within the preview's bounds.

    The approved Full and undeformed providers are unchanged. Each disposable
    process has one numerical thread; cancellation always reaps both processes.
    """
    from backend.core.corner_seam_cache import import_fits
    from backend.core.corner_seam_projection import import_projection, prepare_cached_projection
    views = (False, True) if include_straight else (False,)
    if all(prepare_cached_projection(_view(design, straight)) for straight in views):
        if projection_only:
            return {}
        from backend.api.corner_preview_projection import project_corner_preview
        return project_corner_preview(design, on_progress=on_progress, include_straight=include_straight)
    workers, results = [], [None] * len(views)
    fractions = [0.] * len(views)
    deadline = monotonic() + 120
    try:
        workers.extend(CornerProjectionWorker(design, straight=straight,
            projection_only=projection_only) for straight in views)
        for worker in workers:
            worker.start()
        while any(result is None for result in results):
            for index, worker in enumerate(workers):
                if results[index] is not None:
                    continue
                done, total = worker.progress() or (0, 0)
                fractions[index] = max(fractions[index], done / total if total else 0.)
                if on_progress:
                    on_progress(int(1000 * sum(fractions) / len(views)), 1000)
                if monotonic() >= deadline:
                    raise ValueError('Corner Full preview exceeded its calculation time allowance.')
                if worker.wait(.025):
                    results[index] = worker.result()
                    fractions[index] = 1.
        for result in results:
            import_fits(result['fits'])
            import_projection(result.get('projection'))
        if on_progress:
            on_progress(1000, 1000)
        return {key: value for result in results for key, value in result['component'].items()}
    finally:
        for worker in workers:
            worker.close()
