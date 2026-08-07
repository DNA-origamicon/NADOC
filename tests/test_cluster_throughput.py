"""Learned cluster throughput store (Phase 5 of alpine-cluster-submission)."""

from __future__ import annotations

from backend.core import cluster_throughput as ct


def test_size_bucket_edges():
    assert ct.size_bucket(10_000) == "0-50000"
    assert ct.size_bucket(50_000) == "50000-100000"
    assert ct.size_bucket(100_000) == "100000-200000"
    assert ct.size_bucket(180_000) == "100000-200000"
    assert ct.size_bucket(2_500_000) == "2000000+"


def test_update_record_first_sample_seeds():
    rec = ct.update_record(None, 16.0)
    assert rec == {"ns_per_day": 16.0, "n_samples": 1}


def test_update_record_running_mean():
    rec = ct.update_record({"ns_per_day": 10.0, "n_samples": 1}, 20.0)
    assert rec["ns_per_day"] == 15.0
    assert rec["n_samples"] == 2
    rec = ct.update_record(rec, 30.0)      # (15*2 + 30)/3 = 20
    assert rec["ns_per_day"] == 20.0
    assert rec["n_samples"] == 3


def test_record_and_lookup_roundtrip(tmp_path):
    assert ct.lookup_throughput(tmp_path, cluster="alpine", partition="aa100", n_atoms=150_000) is None
    ct.record_throughput(tmp_path, cluster="alpine", partition="aa100", n_atoms=150_000, ns_per_day=16.0)
    ct.record_throughput(tmp_path, cluster="alpine", partition="aa100", n_atoms=190_000, ns_per_day=20.0)
    # Same size bucket (100k-200k) → averaged.
    assert ct.lookup_throughput(tmp_path, cluster="alpine", partition="aa100", n_atoms=120_000) == 18.0
    # Different partition / bucket → independent (no value yet).
    assert ct.lookup_throughput(tmp_path, cluster="alpine", partition="acpu", n_atoms=150_000) is None
    assert ct.lookup_throughput(tmp_path, cluster="alpine", partition="aa100", n_atoms=2_000_000) is None


def test_record_ignores_bad_values(tmp_path):
    ct.record_throughput(tmp_path, cluster="alpine", partition="aa100", n_atoms=150_000, ns_per_day=0.0)
    ct.record_throughput(tmp_path, cluster="alpine", partition="aa100", n_atoms=150_000, ns_per_day=-5.0)
    assert ct.lookup_throughput(tmp_path, cluster="alpine", partition="aa100", n_atoms=150_000) is None


def test_lookup_missing_store_is_none(tmp_path):
    assert ct.lookup_throughput(tmp_path / "nope", cluster="alpine", partition="aa100", n_atoms=1) is None
