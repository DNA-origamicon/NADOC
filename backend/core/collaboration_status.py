"""Bounded, shared reachability probes; never transfers project or library data."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from functools import lru_cache
import ipaddress
from pathlib import Path
import socket
import time
from urllib.parse import urlsplit, urlunsplit

import httpx

from backend.core.collaboration_peers import Peer, PeerRegistry

_STATUS_TTL_SECONDS = 10.0
_PROBE_TIMEOUT_SECONDS = 8.0
_DNS_TIMEOUT_SECONDS = 1.0
_CACHE_LIMIT = 32
_cached: OrderedDict[tuple, tuple[float, dict]] = OrderedDict()
_in_flight: dict[tuple, asyncio.Task] = {}


@lru_cache(maxsize=1)
def _ssl_context():
    return httpx.create_ssl_context()


async def _probe_peer(workspace: Path, peer: Peer) -> dict:
    async def probe():
        # Constructing an HTTPS client loads certificate files synchronously.
        # Keep that disk work off the event loop along with registry I/O and DNS.
        context = await asyncio.to_thread(_ssl_context)
        async with httpx.AsyncClient(timeout=3, verify=context) as client:
            async def reachable(url):
                try:
                    response = await client.get(url + "/api/collaboration/identity")
                    response.raise_for_status()
                    return True
                except httpx.HTTPError:
                    return False

            if await reachable(peer.base_url):
                return {**peer.public(), "online": True}

            parsed = urlsplit(peer.base_url)
            host = parsed.hostname or ""
            try:
                address = ipaddress.ip_address(host)
                if address.version == 4 and address in ipaddress.ip_network("100.64.0.0/10"):
                    host = (await asyncio.wait_for(
                        asyncio.to_thread(socket.gethostbyaddr, str(address)),
                        _DNS_TIMEOUT_SECONDS,
                    ))[0].rstrip(".")
            except (ValueError, OSError, TimeoutError):
                pass
            if host.casefold().endswith(".ts.net"):
                authority = f"{host}:{parsed.port}" if parsed.port else host
                candidates = dict.fromkeys(
                    urlunsplit((scheme, authority, "", "", ""))
                    for scheme in ("https", parsed.scheme)
                )
                for candidate in candidates:
                    if candidate == peer.base_url or not await reachable(candidate):
                        continue
                    updated = await asyncio.to_thread(
                        PeerRegistry(workspace).register,
                        peer_id=peer.id, name=peer.name, base_url=candidate, token=peer.token,
                    )
                    return {**updated.public(), "online": True}
            return {**peer.public(), "online": False}

    try:
        return await asyncio.wait_for(probe(), _PROBE_TIMEOUT_SECONDS)
    except TimeoutError:
        return {**peer.public(), "online": False}


async def peer_statuses(workspace: Path) -> dict:
    """Coalesce tabs' polls and cache completed probes briefly, including offline peers.

    Registry content is part of the key so pairing, removal and credential/address
    changes invalidate results immediately. In-flight tasks are loop-local; completed
    results contain only public metadata and can be reused across test/server loops.
    A disconnected HTTP caller must not cancel a probe shared by other tabs.
    """
    workspace = Path(workspace)
    peers = await asyncio.to_thread(PeerRegistry(workspace).list)
    key = (str(workspace), tuple(peers))
    cached = _cached.get(key)
    if cached is not None and time.monotonic() - cached[0] < _STATUS_TTL_SECONDS:
        return cached[1]
    flight_key = (asyncio.get_running_loop(), key)
    task = _in_flight.get(flight_key)
    if task is None:
        async def collect():
            result = {"peers": await asyncio.gather(*(_probe_peer(workspace, p) for p in peers))}
            _cached[key] = (time.monotonic(), result)
            _cached.move_to_end(key)
            while len(_cached) > _CACHE_LIMIT:
                _cached.popitem(last=False)
            return result

        task = asyncio.create_task(collect())
        _in_flight[flight_key] = task

        def finished(done):
            _in_flight.pop(flight_key, None)
            if not done.cancelled():
                done.exception()  # retrieve failures even if every HTTP caller disconnected

        task.add_done_callback(finished)
    return await asyncio.shield(task)
