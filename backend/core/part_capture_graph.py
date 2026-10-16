"""Shared bounded graph accounting; callers own projection and copy policy.

The ordinary proof path retains its historical accounting and cycle handling.
An archive can add a rejecting shape check and cycle/depth checks; that check
cannot select fewer children, change charges, or bypass resource limits.
"""

from pydantic import BaseModel


class CaptureLimit(ValueError):
    pass


class CaptureShapeError(ValueError):
    pass


class GraphBudget:
    def __init__(self, *, max_nodes, max_bytes, seconds, clock):
        self.remaining = [max_nodes, max_bytes]
        self.clock = clock
        self.deadline = clock() + seconds if seconds is not None else None

    def charge(self, value, copy_memo=None, *, scalar_atoms=False,
               copy_scalar_atoms=False, validate=None, reject_cycles=False):
        from backend.core.part_capture_copy import scalar_atom_charge, seed_scalar_atom_copy

        remaining, deadline, clock = self.remaining, self.deadline, self.clock
        pending = [(value, False)] if reject_cycles else [value]
        pending_values = 1
        seen, active = set(), set()
        while pending:
            if reject_cycles:
                item, leaving = pending.pop()
                if leaving:
                    active.remove(id(item))
                    continue
                pending_values -= 1
            else:
                item = pending.pop()
            remaining[0] -= 1
            if remaining[0] < 0 or remaining[1] < 0 or (deadline is not None and clock() > deadline):
                raise CaptureLimit("Part verification capture budget exceeded")
            if validate is not None:
                validate(item)
            if isinstance(item, str):
                remaining[1] -= len(item) * 4
            elif isinstance(item, (BaseModel, dict, list, tuple)):
                identity = id(item)
                if reject_cycles and identity in active:
                    raise CaptureShapeError("Preparation archive contains a cycle")
                if identity in seen:
                    continue
                seen.add(identity)
                if reject_cycles:
                    if len(active) >= 64:
                        raise CaptureShapeError("Preparation archive nesting exceeds 64 containers")
                    active.add(identity)
                    pending.append((item, True))
                waiting = pending_values if reject_cycles else len(pending)
                if isinstance(item, BaseModel):
                    children = item.__dict__.values()
                    if scalar_atoms:
                        scalar_charge = (seed_scalar_atom_copy(item, copy_memo) if copy_scalar_atoms
                                         else scalar_atom_charge(item))
                        if scalar_charge is not None:
                            nodes, size = scalar_charge
                            if nodes + waiting > remaining[0]:
                                raise CaptureLimit("Part verification capture node budget exceeded")
                            remaining[0] -= nodes
                            remaining[1] -= size
                            if remaining[1] < 0 or (deadline is not None and clock() > deadline):
                                raise CaptureLimit("Part verification capture budget exceeded")
                            continue
                elif isinstance(item, dict):
                    if len(item) * 2 > remaining[0]:
                        raise CaptureLimit("Part verification capture node budget exceeded")
                    children = (*item.keys(), *item.values())
                else:
                    children = item
                if len(children) + waiting > remaining[0]:
                    raise CaptureLimit("Part verification capture node budget exceeded")
                if reject_cycles:
                    pending.extend((child, False) for child in children)
                    pending_values += len(children)
                else:
                    pending.extend(children)
        if remaining[1] < 0:
            raise CaptureLimit("Part verification capture byte budget exceeded")

    def finish(self):
        if self.deadline is not None and self.clock() > self.deadline:
            raise CaptureLimit("Part verification capture time budget exceeded")
