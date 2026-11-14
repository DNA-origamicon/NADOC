"""Coalesce identical flex requests; cancel only when the last viewer leaves."""
import asyncio
from dataclasses import dataclass


@dataclass
class _Flight:
    task: asyncio.Task
    viewers: int = 0


_flights = {}
_gates = {}


async def subscribe(key, request, calculate):
    group = key[:2] if isinstance(key, tuple) else key
    gate = _gates.setdefault(group, asyncio.Lock())
    async with gate:
        # A new range replaces the same view. Finish the previous worker's
        # cancellation before admitting its replacement, so late cleanup cannot
        # cancel the replacement by (job, representation).
        for previous_key, previous in list(_flights.items()):
            previous_group = previous_key[:2] if isinstance(previous_key, tuple) else previous_key
            if previous_key != key and previous_group == group and not previous.task.done():
                previous.task.cancel()
                await asyncio.gather(previous.task, return_exceptions=True)
        flight = _flights.get(key)
        if flight is None or flight.task.done():
            flight = _Flight(asyncio.create_task(calculate()))
            _flights[key] = flight
        flight.viewers += 1
    try:
        while not flight.task.done():
            if request is not None and await request.is_disconnected():
                raise asyncio.CancelledError()
            await asyncio.wait({flight.task}, timeout=0.25)
        return flight.task.result()
    finally:
        flight.viewers -= 1
        if not flight.viewers:
            if not flight.task.done():
                flight.task.cancel()
                await asyncio.gather(flight.task, return_exceptions=True)
            if _flights.get(key) is flight:
                _flights.pop(key, None)
