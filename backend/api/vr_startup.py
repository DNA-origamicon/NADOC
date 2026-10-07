"""Atomic startup progress shared with the headset, independent of browser polling."""
from pathlib import Path


def publish(path: Path, phase: str, percent: int, detail: str) -> None:
    temporary = path.with_suffix(path.suffix + '.next')
    temporary.write_text(f'{phase} {percent}\n{detail.replace(chr(10), " ")}\n')
    temporary.chmod(0o600)
    temporary.replace(path)


def prepare_scene(body, scene_path, progress_path, process, event_path=None):
    # Imported lazily to avoid the route/module dependency cycle.
    from backend.api import routes_vr as vr
    import time

    candidate = None
    started = time.time()
    try:
        from backend.api.routes_placement_integrity import require_native_placement_review_clear
        require_native_placement_review_clear(event_path=event_path)
        def progress(percent, detail):
            if process.poll() is not None:
                raise RuntimeError('VR viewer closed during loading')
            publish(progress_path, 'loading', percent, detail)

        # Freeze topology once so desktop edits cannot mix revisions mid-export.
        design = vr.design_state.get_or_404().model_copy(deep=True)
        candidate = vr._write_scene_snapshot(producer=lambda write_line: vr._snapshot(
            body, line_writer=write_line, progress=progress, design_snapshot=design, representations={"full"}))
        if process.poll() is not None:
            return
        require_native_placement_review_clear(event_path=event_path)
        candidate.replace(scene_path)
        publish(progress_path, 'ready', 85, 'Reading and validating scene')
        with vr._STATE_LOCK:
            state = vr._read_state()
            if state and state['pid'] == process.pid:
                state.update(snapshot_started_at=started, snapshot_ready_at=time.time())
                vr._write_state(state)
        if event_path is not None:
            from backend.api.vr_representation_loading import serve
            serve(body, event_path, process)
    except Exception as exc:
        from backend.core.native_full_placement import NativePlacementError
        if isinstance(exc, NativePlacementError):
            from backend.api.routes_placement_integrity import record_native_placement_failure
            record_native_placement_failure(exc, phase="native-vr-startup", event_path=event_path,
                                            context={"viewer_pid": process.pid})
        if process.poll() is None:
            publish(progress_path, 'error', 0, str(exc))
    finally:
        if candidate is not None:
            candidate.unlink(missing_ok=True)
        if process.poll() is not None:
            scene_path.unlink(missing_ok=True)
            progress_path.unlink(missing_ok=True)
            progress_path.with_suffix(progress_path.suffix + '.next').unlink(missing_ok=True)
