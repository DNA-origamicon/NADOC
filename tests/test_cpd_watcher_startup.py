"""Watcher arming is driven by atomic file events, including startup races."""
import os
from threading import Timer

import pytest

from experiments.cpd_anti_additive.launch import wait_for_watcher
from experiments.cpd_published_comparator.trigger_dna_review import save


def test_waits_for_atomic_arm_receipt(tmp_path):
    receipt = dict(state='armed', watcher_pid=os.getpid())
    writer = Timer(.02, save, args=(tmp_path/'completion_wake.json', receipt))
    writer.start()
    try:
        assert wait_for_watcher(tmp_path, timeout=2) == receipt
    finally:
        writer.join()


def test_already_armed_receipt_is_not_missed(tmp_path):
    receipt = dict(state='armed', watcher_pid=os.getpid())
    save(tmp_path/'completion_wake.json', receipt)
    assert wait_for_watcher(tmp_path, timeout=0) == receipt


def test_stale_arm_receipt_does_not_admit_native_work(tmp_path, monkeypatch):
    save(tmp_path/'completion_wake.json', dict(state='armed', watcher_pid=123))
    monkeypatch.setattr('experiments.cpd_anti_additive.launch.process_identity', lambda pid: None)
    with pytest.raises(RuntimeError, match='command not started'):
        wait_for_watcher(tmp_path, timeout=.01)
