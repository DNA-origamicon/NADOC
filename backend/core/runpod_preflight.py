"""Can this job actually run on RunPod? Answer BEFORE renting anything.

Every failure below has already happened on a real, billing pod. The point of this module
is that they become a red row in the UI instead of a charge on the card.

    api_key         RunPod rejected the key           -> nothing works
    volume          no network volume                 -> pod boots with no NAMD, no packages
    ssh_key         no local private key              -> pod boots, refuses every connection
    namd_arch       card's arch != the binary's arch  -> rents fine, dies at step 0
    gpu_stock       no allowed card in stock          -> 500 "no instances currently available"
    sizing          system too big for any card       -> would rent and OOM

Stock comes from RunPod's GraphQL API (the REST v1 API exposes no availability endpoint at
all — /gpus, /availability, /datacenters are all 400). ⚠️ It is a GLOBAL figure: a network
volume PINS the pod to its datacenter (ours: EU-RO-1), so "in stock" worldwide still does
not guarantee a card *there*. Preflight can prove a NO; it cannot prove a YES. Say so.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Optional

import httpx

from backend.core.runpod_script import (
    GPU_TYPES,
    NAMD_BUILD_ARCHS,
    GpuType,
    plan_execution,
)

GRAPHQL_URL = "https://api.runpod.io/graphql"

# Cloudflare 403s (error 1010) on a default python user-agent, and the GraphQL endpoint
# wants the key as a QUERY PARAM, not a Bearer header. Both learned the hard way.
_UA = "Mozilla/5.0 (X11; Linux x86_64) NADOC/1.0"

_STOCK_QUERY = (
    "query { gpuTypes { id displayName memoryInGb "
    "lowestPrice(input:{gpuCount:1}) { uninterruptablePrice minimumBidPrice stockStatus } } }"
)

# RunPod reports stock as None / "Low" / "Medium" / "High".
_OUT_OF_STOCK = {None, "", "None"}


@dataclass
class Check:
    key: str
    ok: bool
    label: str
    detail: str = ""


@dataclass
class Preflight:
    ok: bool
    checks: list[Check] = field(default_factory=list)
    gpus: list[dict] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "checks": [asdict(c) for c in self.checks],
            "gpus": self.gpus,
            "note": self.note,
        }


async def fetch_gpu_stock(
    api_key: str, *, transport: Optional[httpx.AsyncBaseTransport] = None
) -> dict[str, dict]:
    """{gpu_id: {stock, on_demand, spot, vram_gb}} from RunPod's GraphQL API."""
    async with httpx.AsyncClient(transport=transport, timeout=20.0) as client:
        resp = await client.post(
            f"{GRAPHQL_URL}?api_key={api_key}",
            content=json.dumps({"query": _STOCK_QUERY}),
            headers={"Content-Type": "application/json", "User-Agent": _UA},
        )
    resp.raise_for_status()
    rows = ((resp.json() or {}).get("data") or {}).get("gpuTypes") or []
    out: dict[str, dict] = {}
    for row in rows:
        price = row.get("lowestPrice") or {}
        out[str(row.get("id"))] = {
            "stock": price.get("stockStatus"),
            "on_demand": price.get("uninterruptablePrice"),
            "spot": price.get("minimumBidPrice"),
            "vram_gb": row.get("memoryInGb"),
            "display": row.get("displayName"),
        }
    return out


async def fetch_balance(
    api_key: str, *, transport: Optional[httpx.AsyncBaseTransport] = None
) -> dict:
    """The account balance — the one number that silently kills a run.

    RunPod destroys every pod the instant the balance hits zero, so a multi-day run that
    dies at 80% for want of credit wastes everything spent to that point. The setup wizard
    shows this so the user tops up BEFORE renting.

    Balance lives ONLY on the legacy GraphQL API (``myself { clientBalance }``) — the REST
    v1 API exposes no billing endpoint. Same quirks as ``fetch_gpu_stock``: key as a query
    param, a browser User-Agent (Cloudflare 403s ``error code: 1010`` on a bare python UA —
    that is a bot-block, NOT a bad key). Never raises: an unreadable balance is
    ``{"available": False, "reason": ...}``, because the caller is an endpoint, not a gate.
    """
    query = "query { myself { clientBalance currentSpendPerHr } }"
    try:
        async with httpx.AsyncClient(transport=transport, timeout=20.0) as client:
            resp = await client.post(
                f"{GRAPHQL_URL}?api_key={api_key}",
                content=json.dumps({"query": query}),
                headers={"Content-Type": "application/json", "User-Agent": _UA},
            )
        if resp.status_code in (401, 403):
            body = resp.text[:120]
            reason = f"HTTP {resp.status_code}"
            if "1010" in body:
                reason += " (Cloudflare bot-block, not a bad key)"
            return {"available": False, "reason": reason}
        if resp.status_code != 200:
            return {"available": False, "reason": f"HTTP {resp.status_code}"}
        body = resp.json() or {}
        if body.get("errors"):
            return {"available": False, "reason": f"GraphQL error: {body['errors']}"}
        me = (body.get("data") or {}).get("myself") or {}
        return {
            "available": True,
            "balance": float(me["clientBalance"]),
            "spend_per_hr": float(me.get("currentSpendPerHr") or 0.0),
        }
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        return {"available": False, "reason": str(exc)}


def in_stock(entry: Optional[dict]) -> bool:
    return bool(entry) and entry.get("stock") not in _OUT_OF_STOCK


def evaluate(
    *,
    connected: bool,
    network_volume_id: Optional[str],
    ssh_key_present: bool,
    stock: Optional[dict[str, dict]],
    n_atoms: Optional[int] = None,
    allowed: tuple[GpuType, ...] = GPU_TYPES,
    s3_transfer_ok: bool = True,
    s3_transfer_detail: str = "configured",
) -> Preflight:
    """Pure. Turn the raw facts into pass/fail rows. No I/O, fully unit-tested."""
    checks: list[Check] = []

    checks.append(
        Check(
            "api_key",
            connected,
            "RunPod API key",
            "connected" if connected else "not connected — enter your API key",
        )
    )
    checks.append(
        Check(
            "volume",
            bool(network_volume_id),
            "Network volume",
            network_volume_id
            or "none set — the pod would have no NAMD and no packages",
        )
    )
    checks.append(
        Check(
            "s3_transfer",
            s3_transfer_ok,
            "S3 volume transfer",
            s3_transfer_detail,
        )
    )
    checks.append(
        Check(
            "ssh_key",
            ssh_key_present,
            "SSH key",
            "~/.ssh/id_ed25519 found"
            if ssh_key_present
            else "no private key — the pod would boot and refuse every connection",
        )
    )

    # Architecture: the shipped table must never contain a card the binary can't run.
    bad = [g.label for g in allowed if g.sm not in NAMD_BUILD_ARCHS]
    checks.append(
        Check(
            "namd_arch",
            not bad,
            "NAMD build matches GPUs",
            f"binary is {'/'.join(NAMD_BUILD_ARCHS)}; all offered cards match"
            if not bad
            else f"{', '.join(bad)} cannot run the {'/'.join(NAMD_BUILD_ARCHS)} build",
        )
    )

    gpus: list[dict] = []
    if stock is None:
        checks.append(
            Check(
                "gpu_stock",
                False,
                "GPU availability",
                "could not query RunPod for stock",
            )
        )
    else:
        any_stock = False
        for gpu in allowed:
            entry = stock.get(gpu.key)
            ok = in_stock(entry)
            any_stock |= ok
            gpus.append(
                {
                    "key": gpu.key,
                    "label": gpu.label,
                    "vram_mb": gpu.vram_mb,
                    "sm": gpu.sm,
                    "stock": (entry or {}).get("stock"),
                    "usd_per_hour": (entry or {}).get("on_demand") or gpu.usd_per_hour,
                    "available": ok,
                }
            )
        names = ", ".join(f"{g['label']} ({g['stock'] or 'none'})" for g in gpus)
        checks.append(
            Check(
                "gpu_stock",
                any_stock,
                "GPU availability",
                names if any_stock else f"no allowed card in stock — {names}",
            )
        )

    if n_atoms:
        plan = plan_execution(n_atoms)
        checks.append(
            Check(
                "sizing",
                plan["gpu"] is not None,
                "System fits a GPU",
                plan["reason"],
            )
        )

    return Preflight(
        ok=all(c.ok for c in checks),
        checks=checks,
        gpus=gpus,
        note=(
            "Stock is RunPod's GLOBAL figure. Your network volume pins the pod to its "
            "datacenter (EU-RO-1), so a card can be 'in stock' worldwide and still be "
            "unavailable there. Preflight can prove a NO; it cannot promise a YES."
        ),
    )


def failed_checks(pre: Preflight) -> list[Check]:
    return [c for c in pre.checks if not c.ok]


def blocking_reason(pre: Preflight) -> str:
    """One line for the 400 that refuses to launch a job."""
    bad = failed_checks(pre)
    if not bad:
        return ""
    return "RunPod pre-flight failed: " + "; ".join(
        f"{c.label} — {c.detail}" for c in bad
    )
