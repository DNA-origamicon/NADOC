"""Value-ranked, availability/arch/VRAM-aware RunPod GPU selection (backend/core/runpod_select).

Pure-function tests (no network) — these encode the RUNBOOK §7 lessons this session re-learned:
the git build has no sm_120, small boxes want a cheap-but-not-glacial card, out-of-stock cards
must drop, and live prices override the pinned table.
"""
from backend.core.runpod_select import (
    Candidate, estimate_rate, load_rate_registry, ms_per_matom, pick_cards,
    record_rate, same_tier, select_cards,
)

SMALL = 1_310_154      # VoltronCore compact box
HUGE = 11_305_826      # VoltronCore full box


def _labels(cands):
    return [c.label for c in cands]


# ── arch gating (the step-0 "no kernel image" trap) ──────────────────────────────
def test_git_build_excludes_sm120():
    cands = select_cards(SMALL, build="git", prefer="value")
    assert cands, "git build should have compatible cards"
    assert all(c.sm != "sm_120" for c in cands), "git build has NO sm_120 (5090/Blackwell)"


def test_release_build_includes_sm120():
    sms = {c.sm for c in select_cards(SMALL, build="release", prefer="value")}
    assert "sm_120" in sms, "the multi-arch 3.0.2 tar carries sm_120"


def test_unknown_build_raises():
    import pytest
    with pytest.raises(ValueError):
        select_cards(SMALL, build="nope")


# ── the two-axis value rule (RUNBOOK §7) ─────────────────────────────────────────
def test_balanced_small_box_picks_4090_sweet_spot():
    """The session's manual choice, derived: fast enough AND cheap — not the glacial 3090
    (pure value) nor the over-priced H100 (pure speed)."""
    top = select_cards(SMALL, build="git", prefer="balanced")[0]
    assert top.label == "RTX 4090"


def test_prefer_modes_diverge():
    value = select_cards(SMALL, build="git", prefer="value")[0]
    speed = select_cards(SMALL, build="git", prefer="speed")[0]
    balanced = select_cards(SMALL, build="git", prefer="balanced")[0]
    assert value.label == "RTX 3090"          # cheapest $/ns, but slow
    assert speed.label.startswith("H100")     # fastest ns/day, but pricey
    assert balanced.label == "RTX 4090"       # the compromise


def test_balanced_excludes_glacial_cheap_card():
    """A slow Ampere card below the speed floor must NOT be the balanced pick even though it is
    the cheapest $/ns."""
    balanced = select_cards(SMALL, build="git", prefer="balanced")
    assert "RTX 3090" not in _labels(balanced[:1])


# ── VRAM fit ─────────────────────────────────────────────────────────────────────
def test_vram_floor_excludes_small_cards_on_huge_box():
    small_card = next(c for c in select_cards(SMALL, build="git", prefer="value")
                      if c.label == "RTX 3090")
    assert small_card.vram_mb == 24_576
    huge = select_cards(HUGE, build="git", prefer="value")
    assert "RTX 3090" not in _labels(huge), "24 GB cannot hold the 11.3M box resident"


# ── live stock + price ───────────────────────────────────────────────────────────
def test_out_of_stock_excluded_when_stock_given():
    # 4090 out (stock None), 6000 Ada in
    stock = {
        "NVIDIA GeForce RTX 4090": {"stock": None, "on_demand": 0.69},
        "NVIDIA RTX 6000 Ada Generation": {"stock": "High", "on_demand": 0.80},
    }
    labels = _labels(select_cards(SMALL, build="git", stock=stock, prefer="balanced"))
    assert "RTX 4090" not in labels          # out of stock
    assert "RTX 6000 Ada" in labels          # in stock


def test_unknown_stock_not_excluded():
    # stock=None => availability unknown => still offered (RunPod 500s if truly none)
    cands = select_cards(SMALL, build="git", stock=None, prefer="balanced")
    assert cands and all(c.available is None for c in cands)


def test_live_price_overrides_indicative():
    stock = {"NVIDIA GeForce RTX 4090": {"stock": "High", "on_demand": 0.55}}
    c = next(c for c in select_cards(SMALL, build="git", stock=stock) if c.label == "RTX 4090")
    assert c.usd_per_hour == 0.55 and c.live_price is True


def test_max_price_filter():
    cheap = select_cards(SMALL, build="git", max_usd_per_hour=0.70, prefer="speed")
    assert all(c.usd_per_hour <= 0.70 for c in cheap)
    assert not any(c.label.startswith("H100") for c in cheap)   # H100 priced out


# ── estimate_rate ────────────────────────────────────────────────────────────────
def test_estimate_rate_offload_slower_than_resident():
    res = estimate_rate("sm_89", SMALL, 0.69, resident=True)
    off = estimate_rate("sm_89", SMALL, 0.69, resident=False)
    assert off["ns_day"] < res["ns_day"]
    assert off["usd_per_ns"] > res["usd_per_ns"]


def test_estimate_rate_unknown_arch_is_none():
    assert estimate_rate("sm_999", SMALL, 0.69) is None
    assert estimate_rate("sm_89", SMALL, 0.0) is None            # no price


def test_estimate_rate_scales_with_atoms():
    small = estimate_rate("sm_89", SMALL, 0.69)
    huge = estimate_rate("sm_89", HUGE, 0.69)
    assert huge["ms_step"] > small["ms_step"]
    assert huge["ns_day"] < small["ns_day"]


# ── learned per-arch rate registry ───────────────────────────────────────────────
def test_record_rate_running_mean(tmp_path):
    p = tmp_path / "rates.json"
    record_rate("sm_89", SMALL, 14.3, path=p)      # per-Matom 10.9
    record_rate("sm_89", SMALL, 21.5, path=p)      # per-Matom 16.4
    reg = load_rate_registry(p)
    assert reg["sm_89"]["n"] == 2
    assert abs(reg["sm_89"]["ms_per_matom"] - (14.3 + 21.5) / 2 / (SMALL / 1e6)) < 0.05


def test_ms_per_matom_prefers_learned_above_threshold():
    assert ms_per_matom("sm_89", registry={"sm_89": {"ms_per_matom": 11.0, "n": 3}}) == 11.0
    # below the sample floor -> conservative static prior (15.0), not the thin learned value
    assert ms_per_matom("sm_89", registry={"sm_89": {"ms_per_matom": 11.0, "n": 1}}) == 15.0
    assert ms_per_matom("sm_89") == 15.0            # no registry -> static


def test_estimate_rate_uses_learned_registry():
    static = estimate_rate("sm_89", SMALL, 0.69)
    learned = estimate_rate("sm_89", SMALL, 0.69,
                            registry={"sm_89": {"ms_per_matom": 10.9, "n": 5}})
    assert learned["ns_day"] > static["ns_day"]     # learned 10.9 < static 15 -> faster


def test_load_rate_registry_missing_returns_empty(tmp_path):
    assert load_rate_registry(tmp_path / "nope.json") == {}


def test_record_rate_resilient_to_bad_inputs(tmp_path):
    p = tmp_path / "r.json"
    record_rate("", 0, 0, path=p)                   # invalid -> no-op, no raise
    record_rate("sm_89", -1, 5, path=p)
    record_rate("sm_89", SMALL, 0, path=p)
    assert load_rate_registry(p) == {}              # nothing written


# ── same_tier fallback bounding ──────────────────────────────────────────────────
def test_same_tier_trims_poor_value():
    ranked = select_cards(SMALL, build="git", prefer="value")
    tier = same_tier(ranked, factor=1.5)
    best = ranked[0].usd_per_ns_est
    assert tier[0] is ranked[0]
    assert all(c.usd_per_ns_est <= best * 1.5 for c in tier)
    assert len(tier) <= len(ranked)
