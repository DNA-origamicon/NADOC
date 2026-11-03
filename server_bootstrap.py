"""Dedicated Uvicorn process factory, before lifespan or requests can run.

The imported route/model graph lives for the server's lifetime. Repeatedly
traversing it during full cyclic collections stalls publication even when very
little garbage is reclaimed. Collect import temporaries once, then exclude that
startup graph from subsequent scans. Session/job/request objects created after
this boundary remain normally collectible; thresholds and automatic GC stay intact.

Keep this out of backend.api.main: importing the app into a test or an embedding
must not freeze that host's heap. Call the factory only to start a dedicated server.
"""
import gc

_application = None


def create_app():
    global _application
    if _application is None:
        from backend.api.main import app

        gc.collect()
        gc.freeze()
        _application = app
    return _application
