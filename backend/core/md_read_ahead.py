"""Overlap one exact DCD prefix read with the current frame's alignment.

Two prefix arrays at most; no resampling, coordinate conversion, or reordering.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager


class _ReadAhead:
    def __init__(self, reader, indices):
        self.reader = reader
        self.indices = iter(indices)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='md-dcd-read')
        self.next_index = None
        self.pending = None
        self._advance()

    def _advance(self):
        self.next_index = next(self.indices, None)
        self.pending = (self.pool.submit(self.reader.frame, self.next_index)
                        if self.next_index is not None else None)

    def frame(self, index):
        if index != self.next_index or self.pending is None:
            return self.reader.frame(index)
        result = self.pending.result()
        self._advance()  # the HDD reads the next frame while NumPy aligns this one
        return result

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=True)


@contextmanager
def read_ahead(ctx, indices):
    reader = ctx.get('dcd_prefix')
    if reader is None:
        yield
        return
    ahead = _ReadAhead(reader, indices)
    ctx['dcd_prefix'] = ahead
    try:
        yield
    finally:
        ctx['dcd_prefix'] = reader
        ahead.close()
