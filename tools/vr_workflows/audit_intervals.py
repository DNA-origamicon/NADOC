"""Opt-in reach boundaries written after playback, never during timed samples."""
from functools import wraps
import json
import os
import time


def display_state(live):
    view=live.state.get('view_tools',{})
    version,flags=view.get('version'),view.get('flags')
    return dict(observed_frame=live.state.get('frame'),view_tools_version=version,view_tools_flags=flags,
                scene_override=bool(version and flags!=256) if version is not None and flags is not None else None)


def record_reach(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        path=os.environ.get('NADOC_VR_AUDIT_INTERVALS')
        if not path: return function(*args, **kwargs)
        live=args[0] if args else kwargs['live']
        display_start=display_state(live)
        start=time.time()*1000
        frame=live.state.get('frame')
        error=None
        try:
            return function(*args, **kwargs)
        except Exception as failure:
            error=str(failure)
            raise
        finally:
            end=time.time()*1000
            with open(path,'a') as output:
                output.write(json.dumps(dict(name=f'reach-{os.getpid()}-{frame}',start_ms=start,end_ms=end,
                    representation=live.state.get('representation'),display_start=display_start,display_end=display_state(live),error=error))+'\n')
    return wrapped


from contextlib import contextmanager


@contextmanager
def operation(live, label):
    """Record whole-operation latency separately from complete-frame attribution."""
    path=os.environ.get('NADOC_VR_AUDIT_INTERVALS')
    if not path:
        yield
        return
    display_start=display_state(live)
    start=time.time()*1000
    frame=live.state.get('frame')
    error=None
    try:
        yield
    except Exception as failure:
        error=str(failure)
        raise
    finally:
        end=time.time()*1000
        with open(path,'a') as output:
            output.write(json.dumps(dict(name=f'{label}-{os.getpid()}-{frame}',kind=label,
                start_ms=start,end_ms=end,operation_latency_ms=end-start,
                input_to_ready_ms=(end-live.last_edit_input_ms
                    if start-1000 <= getattr(live,'last_edit_input_ms',0) <= end else None),
                representation=live.state.get('representation'),display_start=display_start,display_end=display_state(live),error=error))+'\n')
