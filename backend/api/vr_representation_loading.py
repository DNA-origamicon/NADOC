"""On-demand immutable VR representation exports, with counted-work progress."""
import time
from pathlib import Path

from backend.core.vr_representation_geometry import REPRESENTATIONS


class Superseded(Exception):
    pass


def read_request(event_path):
    try:
        fields = Path(str(event_path) + '.repr-request').read_text().split()
        if len(fields) != 5 or fields[:2] != ['NADOCVR_REP_REQUEST', '1']:
            return None
        sequence, generation = int(fields[2]), int(fields[4])
        if sequence <= 0 or generation < 0 or fields[3] not in (*REPRESENTATIONS, "cancel"):
            return None
        return sequence, fields[3], generation
    except (OSError, ValueError):
        return None


def publish(event_path, request, phase, percent, records, detail):
    seq, rep, generation = request
    path = Path(str(event_path) + '.repr-status')
    temporary = path.with_suffix(path.suffix + '.next')
    temporary.write_text(f'NADOCVR_REP_STATUS 1 {seq} {generation} {rep} {phase} {percent:.3f} {records}\n{str(detail).replace(chr(10), " ")}\n')
    temporary.chmod(0o600)
    temporary.replace(path)


def export_request(body, event_path, process, request):
    from backend.api import routes_vr as vr
    from backend.api.doc_context import get_current_doc
    from backend.api import state
    from backend.api.routes_placement_integrity import require_native_placement_review_clear

    require_native_placement_review_clear(event_path=event_path)

    seq, rep, generation = request
    source = None
    last_update = 0.0
    last_percent = 0.0
    records = 0
    design, revision = state.copy_doc_for_persist(get_current_doc())
    if design is None:
        raise ValueError('The part is no longer available')

    def progress(percent, detail):
        nonlocal last_update, last_percent
        if process.poll() is not None or read_request(event_path) != request:
            raise Superseded()
        # Preparation/export occupies 0..75%; native parsing/upload owns the rest.
        value = max(last_percent, min(75.0, percent * 75 / 85))
        now = time.monotonic()
        if now-last_update >= .05 or percent >= 82:
            publish(event_path, request, 'loading', value, 0, detail)
            last_update, last_percent = now, value

    def produce(write):
        def counted(line):
            nonlocal records
            records += 1
            write(line)
        vr._snapshot(body.model_copy(update={'representation': rep}), line_writer=counted,
                     design_snapshot=design, representations={ {'beads':'full', 'vdw':'ballstick'}.get(rep,rep) },
                     progress=progress)

    try:
        publish(event_path, request, 'loading', 0, 0, 'Preparing representation')
        source = vr._write_scene_snapshot(producer=produce)
        current, current_revision = state.get_design_with_revision()
        if current is None or current.id != design.id or current_revision != revision:
            raise ValueError('Part changed during loading. Select the representation to retry.')
        progress(85, 'Export complete')
        destination = Path(str(event_path) + f'.repr-{seq}')
        require_native_placement_review_clear(event_path=event_path)
        source.replace(destination)
        publish(event_path, request, 'ready', 75, records, 'Parsing and validating')
    finally:
        if source is not None:
            source.unlink(missing_ok=True)


def serve(body, event_path, process):
    previous = 0
    try:
        while process.poll() is None:
            request = read_request(event_path)
            if request and request[0] > previous:
                previous = request[0]
                if request[1] == 'cancel':
                    continue
                try:
                    export_request(body, event_path, process, request)
                except Superseded:
                    pass
                except Exception as exc:
                    from backend.core.native_full_placement import NativePlacementError
                    if isinstance(exc, NativePlacementError):
                        from backend.api.routes_placement_integrity import record_native_placement_failure
                        record_native_placement_failure(exc, phase="native-vr-representation", event_path=event_path,
                            context={"request_sequence": request[0], "representation": request[1], "scene_generation": request[2]})
                    if process.poll() is None and read_request(event_path) == request:
                        publish(event_path, request, 'error', 0, 0, getattr(exc, 'detail', str(exc)))
                # An obsolete parser cannot install after the request changes.
                event = Path(event_path)
                for old in event.parent.glob(event.name + '.repr-*'):
                    suffix = old.name.removeprefix(event.name + '.repr-')
                    if suffix.isdigit() and int(suffix) < previous:
                        old.unlink(missing_ok=True)
            time.sleep(.05)
    finally:
        cleanup(event_path)


def cleanup(event_path):
    event = Path(event_path)
    for path in event.parent.glob(event.name + '.repr-*'):
        suffix = path.name.removeprefix(event.name + '.repr-')
        if suffix.isdigit() or suffix in ('request', 'request.next', 'status', 'status.next'):
            path.unlink(missing_ok=True)
