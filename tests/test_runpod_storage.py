"""Storage forecast for a rented RunPod run (backend/core/runpod_storage).

Pure arithmetic, no network. The cases that matter are the ones that cost money: a run that
silently overflows the network volume dies mid-segment and is paid for twice, and a forecast
that assumes an empty volume is worse than no forecast because it is trusted.
"""

from backend.core.runpod_storage import (
    GB,
    VOLUME_HEADROOM_GB,
    staging_estimate,
    storage_estimate,
)

# (steps, dcd_freq) — the shape the wizard's plan table hands over directly.
LADDER = [(240_000, 5_000), (240_000, 5_000)]
N_ATOMS = 1_310_154


def test_output_bytes_grow_with_the_run():
    short = storage_estimate(stages=LADDER, n_atoms=N_ATOMS)
    long = storage_estimate(stages=LADDER * 4, n_atoms=N_ATOMS)
    assert long["output_bytes"] > short["output_bytes"]


def test_denser_dcd_writes_more():
    sparse = storage_estimate(stages=[(240_000, 10_000)], n_atoms=N_ATOMS)
    dense = storage_estimate(stages=[(240_000, 1_000)], n_atoms=N_ATOMS)
    assert dense["output_bytes"] > sparse["output_bytes"] * 5


def test_needed_includes_the_staged_package():
    bare = storage_estimate(stages=LADDER, n_atoms=N_ATOMS)
    staged = storage_estimate(stages=LADDER, n_atoms=N_ATOMS, package_bytes=2 * GB)
    assert staged["needed_bytes"] == bare["needed_bytes"] + 2 * GB


# ── the volume fit check ─────────────────────────────────────────────────────────
def test_warns_when_the_run_will_not_fit():
    r = storage_estimate(stages=LADDER * 40, n_atoms=N_ATOMS, volume_size_gb=50)
    assert r["warn"] is True
    assert "GB" in r["reason"]


def test_no_warning_with_room_to_spare():
    r = storage_estimate(stages=[(10_000, 10_000)], n_atoms=N_ATOMS, volume_size_gb=50)
    assert r["warn"] is False
    assert r["free_after_bytes"] > VOLUME_HEADROOM_GB * GB


def test_unknown_volume_size_cannot_warn():
    """No size, no claim. Inventing a fit check is how a confident wrong number gets shipped."""
    r = storage_estimate(stages=LADDER * 40, n_atoms=N_ATOMS)
    assert r["warn"] is False
    assert r["free_bytes"] is None and r["free_after_bytes"] is None


def test_usage_is_flagged_as_unknown_when_not_supplied():
    """The RunPod REST API reports a volume's SIZE but not its USAGE — measuring free space
    needs a live pod. The forecast must say so rather than assume an empty volume."""
    unknown = storage_estimate(stages=LADDER, n_atoms=N_ATOMS, volume_size_gb=50)
    assert unknown["used_known"] is False
    assert unknown["free_bytes"] == 50 * GB  # falls back to total size

    known = storage_estimate(
        stages=LADDER, n_atoms=N_ATOMS, volume_size_gb=50, volume_used_gb=30.0
    )
    assert known["used_known"] is True
    assert known["free_bytes"] == 50 * GB - 30 * GB
    assert known["free_after_bytes"] < unknown["free_after_bytes"]


# ── staging (the cost that is pure waste) ────────────────────────────────────────
def test_staging_matches_the_measured_run():
    """RUNBOOK §6: 1.21 GB of package took ~15 min of pod time at ~$0.80/hr => ~$0.20."""
    s = staging_estimate(int(1.21 * GB), usd_per_hour=0.80)
    assert 12.0 < s["minutes"] < 20.0
    assert 0.10 < s["usd"] < 0.30


def test_staging_cost_follows_the_selected_card():
    cheap = staging_estimate(GB, usd_per_hour=0.69)
    dear = staging_estimate(GB, usd_per_hour=2.99)
    assert cheap["minutes"] == dear["minutes"]  # same upload, different meter
    assert dear["usd"] > cheap["usd"]


def test_staging_without_a_rate_reports_time_but_no_cost():
    s = staging_estimate(GB)
    assert s["minutes"] > 0
    assert s["usd"] is None


def test_staging_of_nothing_is_free():
    s = staging_estimate(0, usd_per_hour=1.0)
    assert s["bytes"] == 0 and s["minutes"] is None and s["usd"] is None
