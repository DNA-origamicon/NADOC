"""Bounded derived-geometry worker for interactive Corner previews.

Uses the existing disposable-worker transport/reaping boundary. The native
authoring transaction stays in its owner; only detached Full projection runs
here. No files, live sessions, saved molecular overrides or simulation jobs.
"""

import os
import pickle
import struct
from multiprocessing.shared_memory import SharedMemory
from time import monotonic

import orjson

from backend.api.part_verification_worker import VerificationWorker, _BoundedInput, RESULT_HEADER_BYTES, WorkerLimit

_INPUT_LIMIT = 16 * 1024**2
_RESULT_LIMIT = 32 * 1024**2
_PROGRESS_OFFSET = RESULT_HEADER_BYTES + _RESULT_LIMIT
_PROGRESS_SIZE = 12


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
            from backend.api.corner_preview_projection import project_corner_preview
            from backend.core.corner_seam_cache import import_fits, export_fits
            request = pickle.loads(source.buf[:input_size])
            import_fits(request['fits'])
            component = project_corner_preview(request['design'], on_progress=progress)
            result = {'issues': [], 'component': component, 'fits': export_fits()}
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
    def __init__(self, design):
        from backend.core.corner_seam_cache import export_fits
        stream = _BoundedInput(_INPUT_LIMIT)
        try:
            pickle.dump({'design': design, 'fits': export_fits()}, stream, protocol=pickle.HIGHEST_PROTOCOL)
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
        if result.get('component', {}).get('component_kind') != 'corner-preview-dna':
            raise ValueError('Corner geometry worker returned an invalid preview.')
        return result


def project_corner_in_worker(design, *, on_progress=None):
    from backend.core.corner_seam_cache import import_fits
    worker = CornerProjectionWorker(design)
    deadline = monotonic() + 120
    last_progress = (0, 0)
    try:
        worker.start()
        while True:
            last_progress = worker.progress() or last_progress
            if on_progress:
                on_progress(*last_progress)
            if monotonic() >= deadline:
                raise ValueError('Corner Full preview exceeded its calculation time allowance.')
            if worker.wait(.05):
                break
        if on_progress:
            on_progress(*(worker.progress() or last_progress))
        result = worker.result()
        import_fits(result['fits'])
        return result['component']
    finally:
        worker.close()
