"""Unit tests for backend/core/cluster_config.py — pure, offline."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from backend.core import cluster_config as cc


def test_alpine_profile_shape():
    p = cc.alpine_profile()
    assert p.name == "alpine"
    assert p.host == "login.rc.colorado.edu"
    assert p.scheduler == "slurm"
    assert p.default_partition == "ah200"  # GPU-first; H200 since 2026-08-06
    assert "$USER" in p.project_base and "$USER" in p.scratch_base
    assert p.su_per_gpu_hour == pytest.approx(108.2)
    assert p.su_per_core_hour == pytest.approx(1.0)


def test_alpine_partitions_and_qos_lookup():
    p = cc.alpine_profile()
    aa100 = p.partition("aa100")
    assert aa100 is not None and aa100.kind == "gpu" and aa100.gpus == 3
    assert p.partition("nope") is None
    normal = p.qos("cpu-normal")
    assert normal is not None and normal.max_walltime_h == 24
    assert p.qos("cpu-long").max_walltime_h == 168
    # The bare names were retired with amilan in the 2026 rename.
    assert p.qos("normal") is None and p.qos("long") is None


def test_qos_for_is_partition_kind_aware():
    # Alpine namespaces QoS by partition family: gpu-* and (since the 2026 rename)
    # cpu-*.  SLURM rejects the bare names on both.
    p = cc.alpine_profile()
    assert p.qos_for("gpu", "normal").name == "gpu-normal"
    assert p.qos_for("gpu", "long").name == "gpu-long"
    assert p.qos_for("cpu", "normal").name == "cpu-normal"
    assert p.qos_for("cpu", "long").name == "cpu-long"
    assert p.default_qos == "gpu-normal"


def test_qos_tiers_for_kind_splits_gpu_and_cpu():
    p = cc.alpine_profile()
    gpu = {q.name for q in p.qos_tiers_for_kind("gpu")}
    cpu = {q.name for q in p.qos_tiers_for_kind("cpu")}
    assert gpu == {"gpu-normal", "gpu-long", "gpu-testing"}
    assert "cpu-normal" in cpu and "cpu-long" in cpu and "testing" in cpu
    assert not any(n.startswith("gpu-") for n in cpu)  # no gpu-* leaks into CPU


def test_qos_tiers_for_partition_respects_allow_list():
    # acpu is live-confirmed to accept ONLY cpu-normal/cpu-long.
    p = cc.alpine_profile()
    acpu = {q.name for q in p.qos_tiers_for_partition("acpu")}
    assert acpu == {"cpu-normal", "cpu-long"}  # no testing/mem/compile offered
    aa100 = {q.name for q in p.qos_tiers_for_partition("aa100")}
    assert aa100 == {"gpu-normal", "gpu-long", "gpu-testing"}
    assert p.qos_tiers_for_partition("nope") == []


def test_resolve_paths_substitutes_user_and_job():
    p = cc.alpine_profile()
    paths = cc.resolve_paths(p, "jojo", "md_42")
    assert paths["project_dir"] == "/projects/jojo/nadoc_jobs/md_42"
    assert paths["scratch_dir"] == "/scratch/alpine/jojo/nadoc_jobs/md_42"
    assert "$USER" not in paths["project_dir"]


def test_resolve_paths_requires_user_and_job():
    p = cc.alpine_profile()
    with pytest.raises(ValueError):
        cc.resolve_paths(p, "", "md_42")
    with pytest.raises(ValueError):
        cc.resolve_paths(p, "jojo", "")


def test_load_profiles_defaults_to_alpine(tmp_path):
    profiles = cc.load_profiles(tmp_path)  # no clusters.json present
    assert set(profiles) == {"alpine"}


def test_load_profiles_reads_custom_file_and_keeps_alpine(tmp_path):
    (tmp_path / "clusters.json").write_text(
        json.dumps(
            [
                {
                    "name": "summit",
                    "host": "summit.example.edu",
                    "project_base": "/proj/$USER",
                    "scratch_base": "/scratch/$USER",
                    "default_partition": "gpu",
                    "default_qos": "normal",
                }
            ]
        )
    )
    profiles = cc.load_profiles(tmp_path)
    assert set(profiles) == {"alpine", "summit"}
    assert profiles["summit"].host == "summit.example.edu"


def test_load_profiles_ignores_malformed_json(tmp_path):
    (tmp_path / "clusters.json").write_text("{ not valid json")
    assert set(cc.load_profiles(tmp_path)) == {"alpine"}


def test_load_profiles_skips_bad_entries(tmp_path):
    (tmp_path / "clusters.json").write_text(
        json.dumps([{"name": "broken"}])
    )  # missing keys
    profiles = cc.load_profiles(tmp_path)
    assert set(profiles) == {"alpine"}


def test_get_profile_unknown_raises(tmp_path):
    with pytest.raises(KeyError):
        cc.get_profile("nonexistent", tmp_path)


def test_modules_for_picks_gpu_build_on_gpu_target():
    p = cc.alpine_profile()
    assert "namd/3.0.1_cpu" in p.modules_for(gpu=False)
    assert "namd/3.0.1_gpu" in p.modules_for(gpu=True)
    assert "namd/3.0.1_cpu" not in p.modules_for(gpu=True)


def test_modules_for_falls_back_when_no_gpu_set():
    p = replace(cc.alpine_profile(), gpu_module_loads=[])
    # No GPU module set → GPU target reuses the CPU module_loads (and would warn).
    assert p.modules_for(gpu=True) == p.module_loads


def test_gpu_module_loads_roundtrips_through_json(tmp_path):
    (tmp_path / "clusters.json").write_text(
        json.dumps(
            [
                {
                    "name": "myclust",
                    "host": "h",
                    "project_base": "/p/$USER",
                    "scratch_base": "/s/$USER",
                    "default_partition": "g",
                    "default_qos": "n",
                    "module_loads": ["namd/x_cpu"],
                    "gpu_module_loads": ["cuda/12.4", "namd/x_gpu"],
                }
            ]
        )
    )
    prof = cc.load_profiles(tmp_path)["myclust"]
    assert prof.gpu_module_loads == ["cuda/12.4", "namd/x_gpu"]
    assert prof.modules_for(gpu=True) == ["cuda/12.4", "namd/x_gpu"]


def test_profile_with_gpu_modules_is_nonmutating():
    p = cc.alpine_profile()
    gpu = cc.profile_with_gpu_modules(p, ["gcc/14.2.0", "cuda/12.4", "namd/3.0.1_gpu"])
    assert gpu.module_loads[-1] == "namd/3.0.1_gpu"
    assert p.module_loads[-1] == "namd/3.0.1_cpu"  # original untouched


# ── 2026 GPU expansion (ah200 / artxpro6000) ──────────────────────────────────


def test_new_gpu_partitions_present_with_correct_gres():
    p = cc.alpine_profile()
    ah200 = p.partition("ah200")
    assert ah200 is not None
    assert ah200.kind == "gpu" and ah200.gpus == 4
    assert ah200.gres_type == "h200"  # sbatch --gres=gpu:h200:N
    assert ah200.max_cores == 128 and ah200.mem_per_core_gb == pytest.approx(12.0)

    rtx = p.partition("artxpro6000")
    assert rtx is not None
    assert rtx.gres_type == "rtx_pro_6000" and rtx.gpus == 4


def test_new_gpu_partitions_reject_gpu_testing():
    """ah200/artxpro6000 offer only gpu-normal + gpu-long — gpu-testing is
    aa100/ami100 only, and offering it would produce a rejected sbatch."""
    p = cc.alpine_profile()
    for name in ("ah200", "artxpro6000"):
        tiers = {q.name for q in p.qos_tiers_for_partition(name)}
        assert tiers == {"gpu-normal", "gpu-long"}
    assert "gpu-testing" in {q.name for q in p.qos_tiers_for_partition("aa100")}


def test_new_gpu_partitions_carry_their_own_billing_rate():
    """A profile-wide A100 SU rate under-quotes an H200 job several-fold."""
    p = cc.alpine_profile()
    assert p.partition("ah200").su_per_gpu_hour > p.su_per_gpu_hour
    assert p.partition("artxpro6000").su_per_gpu_hour > p.su_per_gpu_hour
    # Unchanged partitions keep 0.0 → fall back to the profile-wide rate.
    assert p.partition("aa100").su_per_gpu_hour == 0.0


def test_partition_su_rate_roundtrips_through_json(tmp_path):
    (tmp_path / "clusters.json").write_text(
        json.dumps(
            [
                {
                    "name": "myclust",
                    "host": "h",
                    "project_base": "/p/$USER",
                    "scratch_base": "/s/$USER",
                    "default_partition": "g",
                    "default_qos": "n",
                    "partitions": [
                        {
                            "name": "g",
                            "kind": "gpu",
                            "max_cores": 128,
                            "gres_type": "h200",
                            "su_per_gpu_hour": 334.0,
                        }
                    ],
                }
            ]
        )
    )
    prof = cc.load_profiles(tmp_path)["myclust"]
    assert prof.partition("g").su_per_gpu_hour == pytest.approx(334.0)


def test_workspace_clusters_json_has_not_drifted_from_the_embedded_profile():
    """workspace/clusters.json OVERWRITES the embedded alpine profile wholesale
    (load_profiles), so a partition added only in Python is invisible to the running
    app.  Guard the trap: shared partitions must agree, and the GPU submission
    targets must all be present."""
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "workspace" / "clusters.json"
    if not path.is_file():
        pytest.skip("no workspace/clusters.json in this checkout")
    entries = json.loads(path.read_text())
    alpine = next((e for e in entries if e.get("name") == "alpine"), None)
    if alpine is None:
        pytest.skip("workspace/clusters.json defines no alpine profile")

    on_disk = {p["name"]: p for p in alpine.get("partitions", [])}
    embedded = cc.alpine_profile()

    for name in ("aa100", "ami100", "al40", "ah200", "artxpro6000"):
        assert name in on_disk, (
            f"{name} missing from workspace/clusters.json — it shadows the embedded "
            f"profile, so the app will not offer this partition"
        )
    for name, entry in on_disk.items():
        ref = embedded.partition(name)
        if ref is None:
            continue  # a deliberate local-only partition is fine
        assert entry.get("kind") == ref.kind, f"{name}: kind drifted"
        assert entry.get("gres_type", "") == ref.gres_type, f"{name}: gres_type drifted"
        assert entry.get("allowed_qos", []) == ref.allowed_qos, (
            f"{name}: allowed_qos drifted"
        )
