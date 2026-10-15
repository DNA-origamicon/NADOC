"""Typed, append-incremental command dependencies; no snapshot decoding."""
from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class Resource:
    kind: str
    identity: str


@dataclass(frozen=True)
class Dependencies:
    reads: frozenset[Resource] = frozenset()
    writes: frozenset[Resource] = frozenset()
    known: bool = True
    barrier: bool = False


class DependencyIndex:
    """O(resource references) append, O(affected edges) impact queries.

    Unknown contracts form barriers: impact is conservative, never independent
    merely because a contract is absent. Edits invalidate the affected suffix;
    this index is local to a captured recipe, never shared between revisions.
    """
    def __init__(self):
        self.rows = []
        self.parents = {}
        self.children = {}
        self.writers = {}
        self.frontier = set()
        self.barrier = None
        self.complete = True

    def append(self, feature_id, contract):
        if feature_id in self.parents:
            raise ValueError("duplicate feature identity")
        parents = {self.writers[r] for r in contract.reads | contract.writes if r in self.writers}
        if self.barrier is not None:
            parents.add(self.barrier)
        if not contract.known or contract.barrier:
            parents.update(self.frontier)
            self.barrier = feature_id
            if not contract.known:
                self.complete = False
        self.parents[feature_id] = parents
        self.children[feature_id] = set()
        for parent in parents:
            self.children[parent].add(feature_id)
        self.frontier.difference_update(parents)
        self.frontier.add(feature_id)
        for resource in contract.writes:
            self.writers[resource] = feature_id
        self.rows.append((feature_id, contract))

    def affected(self, feature_ids):
        pending = list(feature_ids)
        reached = set(pending)
        while pending:
            for child in self.children.get(pending.pop(), ()):
                if child not in reached:
                    reached.add(child)
                    pending.append(child)
        return reached

    def invalidate_from(self, position):
        if not 0 <= position <= len(self.rows):
            raise ValueError("invalid dependency prefix")
        prefix = self.rows[:position]
        self.__init__()
        for feature_id, contract in prefix:
            self.append(feature_id, contract)

    def as_dict(self):
        return {"complete": self.complete,
                "parents": {key: sorted(value) for key, value in self.parents.items()}}
