"""Document-bound view-volume controls and live outline feed for native VR."""
import json
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from backend.api import state
from backend.api.doc_context import set_current_doc, reset_current_doc
from backend.core.models import ViewVolume

_bindings = {}


def quoted(value):
    # C++ std::quoted uses literal whitespace and only escapes quote/backslash.
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'



class VolumeBinding:
    def __init__(self, event_path, rotation):
        import threading
        from backend.api.doc_context import get_current_doc
        self.path = str(event_path)
        self.doc = get_current_doc()
        self.document_id = state.get_or_404().id
        self.rotation = np.asarray(rotation)
        self.sequence = 0
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.thread = None
        self.last_state = None
        self.consume()

    def run(self):
        import logging
        last_error = None
        while not self.stop.wait(.1):
            try:
                self.consume()
                last_error = None
            except Exception as error:
                if str(error) != last_error:
                    logging.getLogger(__name__).exception('Could not sync view volumes for %s', self.document_id)
                    last_error = str(error)

    def consume(self):
        with self.lock:
            token = set_current_doc(self.doc)
            try:
                document = state.get_or_404()
                if document.id != self.document_id:
                    raise ValueError('View-volume document is no longer active.')
                path = Path(self.path + '.volumes-pending')
                sequence = self.sequence
                if path.exists():
                    if path.stat().st_size > 4 * 1024 * 1024:
                        raise ValueError('Volume journal exceeds 4 MB.')
                    operations = json.loads(path.read_text())
                    if not isinstance(operations, list) or len(operations) > 20000:
                        raise ValueError('Invalid volume journal.')
                    fresh = []
                    for op in operations:
                        seq = op['sequence']
                        if type(seq) is not int or seq <= 0:
                            raise ValueError('Invalid volume sequence.')
                        if seq <= self.sequence:
                            continue
                        if seq <= sequence:
                            raise ValueError('Volume journal is out of order.')
                        sequence = seq
                        if op['action'] not in ('create', 'delete', 'outline', 'enabled', 'transform') or not isinstance(op['id'], str):
                            raise ValueError('Invalid volume action.')
                        if op['action'] == 'create':
                            point = self.rotation.T @ np.asarray(op['center'], dtype=float)
                            radius = float(op['radius'])
                            if point.shape != (3,) or not np.isfinite(point).all() or not np.isfinite(radius) or radius <= 0:
                                raise ValueError('Invalid volume bounds.')
                            op = {**op, 'volume': ViewVolume(id=op['id'], name='Hex volume' if op['shape'] == 'hexagonal' else 'Square volume', shape=op['shape'], min_corner=tuple(point-radius), max_corner=tuple(point+radius))}
                        elif op['action'] == 'transform':
                            point = np.asarray(op['center'], dtype=float)
                            half = np.asarray(op['half'], dtype=float)
                            quaternion = np.asarray(op['rotation'], dtype=float)
                            if (point.shape != (3,) or half.shape != (3,) or quaternion.shape != (4,)
                                    or not np.isfinite(point).all() or not np.isfinite(half).all()
                                    or not np.isfinite(quaternion).all() or (half <= 0).any()
                                    or not .999 <= np.linalg.norm(quaternion) <= 1.001):
                                raise ValueError('Invalid volume transform.')
                            point = self.rotation.T @ point
                            quaternion = Rotation.from_matrix(self.rotation.T @ Rotation.from_quat(quaternion).as_matrix()).as_quat()
                            op = {**op, 'geometry': dict(min_corner=tuple(point-half), max_corner=tuple(point+half), rotation=tuple(quaternion))}
                        elif op['action'] in ('outline', 'enabled') and type(op.get('value')) is not bool:
                            raise ValueError('Invalid volume switch.')
                        fresh.append(op)
                    if fresh:
                        def apply(design):
                            if design.id != self.document_id:
                                raise ValueError('View-volume document is no longer active.')
                            records = {v.id: v.model_copy(deep=True) for v in design.view_volumes}
                            for op in fresh:
                                key = op['id']
                                if op['action'] == 'create':
                                    records.setdefault(key, op['volume'])
                                elif op['action'] == 'delete':
                                    records.pop(key, None)
                                elif op['action'] == 'transform' and key in records:
                                    records[key] = ViewVolume.model_validate({**records[key].model_dump(), **op['geometry']})
                                elif key in records:
                                    setattr(records[key], 'outline_visible' if op['action'] == 'outline' else 'enabled', op['value'])
                            design.view_volumes = list(records.values())
                        document, _ = state.mutate_display_metadata(apply)
                # Send transformed corners, avoiding quaternion/normalization ambiguity.
                lines = [f'NADOC_VOLUMES_3 {sequence} {len(document.view_volumes)}']
                for v in document.view_volumes:
                    lo, hi = np.array(v.min_corner), np.array(v.max_corner)
                    center, half = (lo+hi)/2, (hi-lo)/2
                    x,y,z,w = v.rotation
                    rotation = np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)], [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)], [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])
                    ring = [(np.cos(i*np.pi/3)*min(half[:2]),np.sin(i*np.pi/3)*min(half[:2])) for i in range(6)] if v.shape == 'hexagonal' else [(-half[0],-half[1]),(half[0],-half[1]),(half[0],half[1]),(-half[0],half[1])]
                    points = [self.rotation @ (center + rotation @ [a,b,c]) for c in (-half[2],half[2]) for a,b in ring]
                    pose = [*(self.rotation @ center), *half, *Rotation.from_matrix(self.rotation @ rotation).as_quat()]
                    lines.append(' '.join([quoted(v.id), quoted(v.name), str(int(v.outline_visible)), str(int(v.enabled)), str(len(ring)), quoted(v.representation), quoted(v.coloring), str(v.opacity)] + [format(float(c), '.17g') for c in pose] + [format(float(c), '.17g') for p in points for c in p]))
                value = '\n'.join(lines)+'\n'
                if value != self.last_state:
                    temporary = Path(self.path+'.volumes-state.tmp')
                    temporary.write_text(value)
                    temporary.chmod(0o600)
                    temporary.replace(self.path+'.volumes-state')
                    self.last_state = value
                self.sequence = sequence
            finally:
                reset_current_doc(token)


def prepare(event_path, assembly_active, rotation):
    if not assembly_active:
        _bindings[str(event_path)] = VolumeBinding(event_path, rotation)


def start(event_path):
    import threading
    binding = _bindings.get(str(event_path))
    if binding:
        binding.thread = threading.Thread(target=binding.run, daemon=True, name='nadoc-vr-volumes')
        binding.thread.start()


def finish(event_path):
    binding = _bindings.pop(str(event_path), None)
    if not binding:
        return
    binding.stop.set()
    if binding.thread:
        binding.thread.join(timeout=2)
    try:
        binding.consume()
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Retaining unsaved view-volume journal at %s', binding.path)
        return
    for suffix in ('state','state.tmp','pending','pending.tmp'):
        Path(binding.path+'.volumes-'+suffix).unlink(missing_ok=True)
