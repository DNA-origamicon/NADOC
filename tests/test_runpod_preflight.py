"""RunPod pre-flight — refuse to rent a pod we already know cannot run the job.

Every check here maps to a failure that ALREADY happened on a real, billing pod. The
whole point is that they become a red row in the UI instead of a charge on the card.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.core import runpod_preflight as pf
from backend.core.runpod_script import GPU_TYPES, NAMD_BUILD_ARCHS, GpuType

SIXHB = 225_504
VOLUME = "77pnhye88p"

GOOD_STOCK = {
    "NVIDIA GeForce RTX 4090": {"stock": "Low", "on_demand": 0.34},
    "NVIDIA RTX 6000 Ada Generation": {"stock": "Medium", "on_demand": 0.74},
}
NO_STOCK = {
    "NVIDIA GeForce RTX 4090": {"stock": None, "on_demand": 0.34},
    "NVIDIA RTX 6000 Ada Generation": {"stock": None, "on_demand": 0.74},
}


def _ok(**over):
    kw = dict(
        connected=True, network_volume_id=VOLUME, ssh_key_present=True,
        stock=GOOD_STOCK, n_atoms=SIXHB,
    )
    kw.update(over)
    return pf.evaluate(**kw)


class TestGpuTable:
    def test_the_cheapest_card_leads_the_fallback_list(self):
        """At SECURE prices the 4090 ($0.69) undercuts the 32 GB PRO 4500 ($0.74).

        The PRO 4500 used to lead because at the COMMUNITY price the two TIED at $0.34,
        making its extra VRAM + HIGH stock a free tiebreak. The real prices break the
        tie, and the list is a FALLBACK chain — so leading with the scarce-but-cheaper
        card is free: RunPod falls through to the PRO 4500 when no 4090 is available.
        """
        assert GPU_TYPES[0].label == "RTX 4090"
        assert GPU_TYPES[0].usd_per_hour == 0.69
        assert GPU_TYPES[1].label == "RTX PRO 4500"   # the fallback that is always there
        assert GPU_TYPES[1].vram_mb > GPU_TYPES[0].vram_mb

    def test_every_offered_card_is_an_arch_the_binary_can_run(self):
        """An A100 (sm_80) rented fine and died at step 0 with 'no kernel image is
        available'. NEVER offer a card the binary cannot run — the multi-arch build
        covers Ada (sm_89) and Blackwell (sm_120), and nothing else."""
        for g in GPU_TYPES:
            assert g.sm in NAMD_BUILD_ARCHS, f"{g.label} is {g.sm}"

    def test_both_architectures_are_actually_offered(self):
        archs = {g.sm for g in GPU_TYPES}
        assert archs == {"sm_89", "sm_120"}


class TestHappyPath:
    def test_everything_green(self):
        pre = _ok()
        assert pre.ok is True
        assert [c.key for c in pre.checks] == [
            "api_key", "volume", "ssh_key", "namd_arch", "gpu_stock", "sizing",
        ]
        assert pf.blocking_reason(pre) == ""

    def test_reports_stock_and_price_per_card(self):
        gpus = {g["label"]: g for g in _ok().gpus}
        assert gpus["RTX 4090"]["stock"] == "Low"
        assert gpus["RTX 4090"]["available"] is True
        assert gpus["RTX 6000 Ada"]["usd_per_hour"] == 0.74

    def test_says_out_loud_that_stock_is_global_not_per_datacenter(self):
        """A volume PINS the pod to its datacenter (EU-RO-1). A card in stock worldwide
        can still be unavailable there — preflight can prove a NO, never a YES. If the UI
        implied otherwise it would be lying."""
        note = _ok().note.lower()
        assert "global" in note
        assert "eu-ro-1" in note


class TestEachFailureBlocks:
    def test_not_connected(self):
        pre = _ok(connected=False)
        assert not pre.ok
        assert "API key" in pf.blocking_reason(pre)

    def test_no_network_volume(self):
        """Without the volume the pod has no NAMD and no packages — an empty box."""
        pre = _ok(network_volume_id=None)
        assert not pre.ok
        assert "volume" in pf.blocking_reason(pre).lower()

    def test_no_ssh_key(self):
        """The pod boots, reports RUNNING, exposes port 22 — and refuses every
        connection. This wasted a launch."""
        pre = _ok(ssh_key_present=False)
        assert not pre.ok
        assert "SSH" in pf.blocking_reason(pre)

    def test_no_gpu_in_stock(self):
        """RunPod answers 500 'There are no instances currently available'. Better to
        say so before renting than to discover it at create time."""
        pre = _ok(stock=NO_STOCK)
        assert not pre.ok
        assert "GPU availability" in pf.blocking_reason(pre)

    def test_stock_lookup_failed_is_a_failed_check_not_a_crash(self):
        pre = _ok(stock=None)
        assert not pre.ok
        assert "stock" in pf.blocking_reason(pre).lower()

    def test_a_wrong_arch_card_in_the_table_fails_the_arch_check(self):
        """Guard against someone re-adding an A100 without rebuilding NAMD."""
        bad = (GpuType("NVIDIA A100 80GB PCIe", "A100 80GB", 81_920, 1.19, "sm_80"),)
        pre = pf.evaluate(
            connected=True, network_volume_id=VOLUME, ssh_key_present=True,
            stock={"NVIDIA A100 80GB PCIe": {"stock": "High"}}, allowed=bad,
        )
        assert not pre.ok
        assert "cannot run" in pf.blocking_reason(pre)

    def test_a_system_too_big_for_any_card_is_refused(self):
        pre = _ok(n_atoms=200_000_000)
        assert not pre.ok
        assert "fits a GPU" in pf.blocking_reason(pre)

    def test_every_failure_is_named_in_the_blocking_reason(self):
        pre = pf.evaluate(
            connected=False, network_volume_id=None, ssh_key_present=False,
            stock=None, n_atoms=SIXHB,
        )
        reason = pf.blocking_reason(pre)
        for word in ("API key", "Network volume", "SSH key", "GPU availability"):
            assert word in reason


class TestStockFetch:
    def test_parses_graphql_stock(self):
        payload = {"data": {"gpuTypes": [
            {"id": "NVIDIA GeForce RTX 4090", "displayName": "RTX 4090",
             "memoryInGb": 24,
             "lowestPrice": {"stockStatus": "Low", "uninterruptablePrice": 0.34,
                             "minimumBidPrice": 0.34}},
        ]}}
        transport = httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
        stock = asyncio.run(pf.fetch_gpu_stock("k", transport=transport))
        assert stock["NVIDIA GeForce RTX 4090"]["stock"] == "Low"
        assert stock["NVIDIA GeForce RTX 4090"]["on_demand"] == 0.34

    def test_sends_the_key_as_a_query_param_with_a_browser_user_agent(self):
        """Cloudflare 403s (error 1010) on python's default UA, and this endpoint takes
        the key as a QUERY PARAM, not a Bearer header. Both learned the hard way."""
        seen = {}

        def handler(req):
            seen["url"] = str(req.url)
            seen["ua"] = req.headers.get("user-agent", "")
            return httpx.Response(200, json={"data": {"gpuTypes": []}})

        asyncio.run(pf.fetch_gpu_stock("SECRET", transport=httpx.MockTransport(handler)))
        assert "api_key=SECRET" in seen["url"]
        assert "Mozilla" in seen["ua"]

    @pytest.mark.parametrize("status", [None, "", "None"])
    def test_absent_stock_means_unavailable(self, status):
        assert pf.in_stock({"stock": status}) is False

    @pytest.mark.parametrize("status", ["Low", "Medium", "High"])
    def test_any_named_stock_level_counts_as_available(self, status):
        assert pf.in_stock({"stock": status}) is True


def test_gpu_table_is_strictly_cheapest_first():
    """The table IS the fallback priority order handed to RunPod as `gpuTypeIds`. If it
    is not price-sorted, a mid-priced card gets skipped in favour of a dearer one — which
    is exactly the mistake that rented a $1.39/hr A100 for a duplex."""
    prices = [g.usd_per_hour for g in GPU_TYPES]
    assert prices == sorted(prices), [(g.label, g.usd_per_hour) for g in GPU_TYPES]
