"""CPU/CUDA backend selection + GPU→CPU fallback for live oxpy sessions."""

import pytest

from backend.core import oxdna_live_backend as lb
from backend.physics.oxdna_live import _OxpyStepper


@pytest.fixture(autouse=True)
def _clear_cache():
    lb.reset_cache()
    yield
    lb.reset_cache()


# ── preferred_backend / gpu_present ──────────────────────────────────────────


def test_preferred_backend_cuda_when_gpu_present():
    assert lb.preferred_backend(probe=lambda: True) == "CUDA"


def test_preferred_backend_cpu_when_no_gpu():
    assert lb.preferred_backend(probe=lambda: False) == "CPU"


def test_gpu_probe_is_cached_after_first_call():
    calls = []

    def probe():
        calls.append(1)
        return True

    assert lb.gpu_present(probe=probe) is True
    assert lb.gpu_present(probe=probe) is True  # cached → probe not re-run
    assert len(calls) == 1


# ── _OxpyStepper CUDA→CPU fallback ───────────────────────────────────────────


class _FakeStack:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _opener(fail_on):
    """Return an ``_open_fn(input_name)`` that raises for ``fail_on`` (simulating a
    GPU out-of-memory) and otherwise returns a (stack, mgr, field) triple."""

    def open_fn(input_name):
        if input_name == fail_on:
            raise RuntimeError("CUDA: out of memory")
        return _FakeStack(), object(), None

    return open_fn


def test_cuda_open_failure_falls_back_to_cpu(tmp_path):
    (tmp_path / "input_cpu").write_text("backend = CPU\n")  # CPU fallback staged
    st = _OxpyStepper(tmp_path, backend="CUDA", _open_fn=_opener(fail_on="input"))
    with st:
        assert st.active_backend == "CPU"
        assert st.fell_back is True
        assert "out of memory" in st.fallback_reason


def test_cuda_open_success_stays_on_cuda(tmp_path):
    (tmp_path / "input_cpu").write_text("backend = CPU\n")
    st = _OxpyStepper(tmp_path, backend="CUDA", _open_fn=_opener(fail_on="never"))
    with st:
        assert st.active_backend == "CUDA"
        assert st.fell_back is False


def test_cpu_backend_never_attempts_fallback(tmp_path):
    # A CPU session that fails to open must raise, not silently retry.
    (tmp_path / "input_cpu").write_text("backend = CPU\n")
    st = _OxpyStepper(tmp_path, backend="CPU", _open_fn=_opener(fail_on="input"))
    with pytest.raises(RuntimeError):
        st.__enter__()


def test_cuda_without_staged_cpu_input_reraises(tmp_path):
    # No input_cpu on disk → cannot fall back → original error propagates.
    st = _OxpyStepper(tmp_path, backend="CUDA", _open_fn=_opener(fail_on="input"))
    with pytest.raises(RuntimeError):
        st.__enter__()
