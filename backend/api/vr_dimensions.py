"""Document-bound native measurement journal, independent of browser polling."""
import json
import logging
import threading
import uuid
from pathlib import Path
import numpy as np
from backend.api.doc_context import get_current_doc, set_current_doc, reset_current_doc
from backend.api.routes_dimensions import apply_changes, source
from backend.core.dimensions import Dimension, DimensionChanges

_bindings = {}
_log = logging.getLogger(__name__)


class DimensionBinding:
    def __init__(self, event_path, kind, rotation):
        self.path = str(event_path)
        self.kind = kind
        self.doc = get_current_doc()
        document = source(kind).get_or_404()
        self.document_id = document.id
        self.rotation = np.asarray(rotation, dtype=float)
        self.sequence = 0
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.thread = None
        prefix = uuid.uuid4().hex
        lines = [f'NADOC_DIMENSIONS_1 {prefix} {len(document.dimensions)}']
        for entry in document.dimensions:
            coordinates = [float(v) for p in (entry.a, entry.b) for v in self.rotation @ p]
            lines.append(f'{entry.id} {json.dumps(entry.name, ensure_ascii=False)} {int(entry.visible)} ' + ' '.join(format(v, '.17g') for v in coordinates))
        Path(self.path+'.dimensions-seed').write_text('\n'.join(lines)+'\n')
        Path(self.path+'.dimensions-seed').chmod(0o600)

    def consume(self):
        with self.lock:
            path = Path(self.path+'.dimensions-pending')
            if not path.exists():
                return
            if path.stat().st_size > 4*1024*1024:
                raise ValueError('Dimension journal exceeds 4 MB.')
            operations = json.loads(path.read_text())
            if not isinstance(operations, list) or len(operations)>20000:
                raise ValueError('Invalid dimension journal.')
            upserts, deleted = {}, set()
            sequence = self.sequence
            for operation in operations:
                seq = operation['sequence']
                if type(seq) is not int or seq<=0:
                    raise ValueError('Invalid dimension sequence.')
                if seq <= self.sequence:
                    continue
                if seq <= sequence:
                    raise ValueError('Dimension journal is out of order.')
                sequence = seq
                if 'upsert' in operation:
                    entry = Dimension.model_validate(operation['upsert'])
                    entry.a = tuple(self.rotation.T @ entry.a)
                    entry.b = tuple(self.rotation.T @ entry.b)
                    upserts[entry.id]=entry
                    deleted.discard(entry.id)
                else:
                    key=operation['delete']
                    if not isinstance(key,str):
                        raise ValueError('Invalid dimension deletion.')
                    upserts.pop(key,None)
                    deleted.add(key)
            if sequence == self.sequence:
                return
            token=set_current_doc(self.doc)
            try:
                apply_changes(self.kind,DimensionChanges(document_id=self.document_id,
                    upsert=list(upserts.values()),delete=list(deleted)))
            finally:
                reset_current_doc(token)
            temporary=Path(self.path+'.dimensions-ack.tmp')
            temporary.write_text(str(sequence))
            temporary.replace(self.path+'.dimensions-ack')
            self.sequence=sequence

    def run(self):
        last_error = None
        while not self.stop.wait(.1):
            try:
                self.consume()
                last_error = None
            except Exception as error:
                if str(error) == last_error:
                    continue
                last_error = str(error)
                _log.exception('Could not save native dimensions for %s', self.document_id)


def prepare(event_path, assembly_active, rotation):
    binding=DimensionBinding(event_path,'assembly' if assembly_active else 'design',rotation)
    _bindings[str(event_path)]=binding


def start(event_path):
    binding=_bindings[str(event_path)]
    binding.thread=threading.Thread(target=binding.run,daemon=True,name='nadoc-vr-dimensions')
    binding.thread.start()


def finish(event_path):
    binding=_bindings.pop(str(event_path),None)
    if not binding:
        return
    binding.stop.set()
    if binding.thread:
        binding.thread.join(timeout=2)
    try:
        binding.consume()
    except Exception:
        _log.exception('Retaining unsaved VR dimension journal at %s',binding.path)
        return
    for suffix in ('seed','pending','pending.tmp','ack','ack.tmp'):
        Path(binding.path+'.dimensions-'+suffix).unlink(missing_ok=True)
