"""Worker shutdown owns native children and completes their cleanup."""
import subprocess
import sys
import threading
import pytest

from backend.api import vr_lifecycle


@pytest.fixture(autouse=True)
def private_ownership(monkeypatch):
    monkeypatch.setattr(vr_lifecycle, "_owned", {})


def test_shutdown_stops_owned_process_and_waits_for_cleanup(tmp_path):
    process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
    marker = tmp_path/'sidecar'
    marker.write_text('owned')
    def cleanup():
        process.wait()
        marker.unlink()
    thread = threading.Thread(target=cleanup)
    thread.start()
    vr_lifecycle.track(process, thread)
    try:
        vr_lifecycle.shutdown()
        assert process.poll() is not None
        assert not thread.is_alive()
        assert not marker.exists()
        vr_lifecycle.shutdown()  # repeated lifespan teardown is harmless
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        thread.join()


def test_shutdown_does_not_signal_finished_process(monkeypatch):
    from types import SimpleNamespace
    def unexpected(*args):
        raise AssertionError('Must not signal a recycled PID')
    monkeypatch.setattr(vr_lifecycle.os, 'killpg', unexpected)
    vr_lifecycle.track(SimpleNamespace(pid=123, poll=lambda:0), SimpleNamespace(is_alive=lambda:False))
    vr_lifecycle.shutdown()
