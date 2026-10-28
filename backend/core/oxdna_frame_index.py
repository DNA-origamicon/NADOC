"""Small byte-offset indexes for seeking into large oxDNA text trajectories."""
from array import array
from collections import OrderedDict
from pathlib import Path
import re
import threading

_CACHE = OrderedDict()
_LOCK = threading.Lock()
_MAX_BYTES = 16 * 1024 * 1024


def trajectory_offsets(path):
    path = Path(path)
    stat = path.stat()
    key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns)
    with _LOCK:
        hit = _CACHE.get(key)
        if hit is not None:
            _CACHE.move_to_end(key)
            return hit
    offsets = array('Q')
    # Retain just enough overlap to recognize a header split across chunks.
    tail, position = b'', 0
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            data = tail + chunk
            base = position - len(tail)
            if position == 0 and data.startswith(b't '):
                offsets.append(0)
            for match in re.finditer(b'\nt ', data):
                offset = base + match.start() + 1
                if not offsets or offset > offsets[-1]:
                    offsets.append(offset)
            position += len(chunk)
            tail = data[-2:]
    with _LOCK:
        # A changing trajectory should not leave its older index versions behind.
        for old in list(_CACHE):
            if old[0] == key[0]:
                del _CACHE[old]
        if len(offsets) * offsets.itemsize <= _MAX_BYTES:
            _CACHE[key] = offsets
            while sum(len(v) * v.itemsize for v in _CACHE.values()) > _MAX_BYTES or len(_CACHE) > 64:
                _CACHE.popitem(last=False)
    return offsets
