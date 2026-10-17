"""Host-owned construction policy; never restored from requests or Design JSON.

The state facade installs configurations under its document lock. Resolving an
immutable configuration is constant time and does not create a session. This
foundation is not HTTP authentication or complete route/alias isolation.
"""

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from fastapi import HTTPException


MODES = frozenset({"compatibility", "registered_only"})
STRICT_OPERATIONS = frozenset({"batch", "verify"})


@dataclass(frozen=True)
class HostPolicyConfiguration:
    default_mode: str = "compatibility"
    document_modes: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self):
        if self.default_mode not in MODES:
            raise ValueError("Unknown host construction policy")
        copied = dict(self.document_modes)
        if any(type(doc) is not str or not doc or mode not in MODES for doc, mode in copied.items()):
            raise ValueError("Document policies need nonempty identities and known modes")
        object.__setattr__(self, "document_modes", MappingProxyType(copied))


@dataclass(frozen=True)
class SessionPolicy:
    mode: str
    profile_id: str
    generation: int

    @property
    def strict(self):
        return self.mode == "registered_only"


_configuration = (HostPolicyConfiguration(), 0)


def current_configuration():
    """Trusted embedding/test access; not a client-selectable setting."""
    return _configuration[0]


def _install_configuration(configuration):
    """State-lock-owned installation invalidates every prior admission."""
    if type(configuration) is not HostPolicyConfiguration:
        raise TypeError("Construction policy requires a host configuration object")
    global _configuration
    _configuration = (configuration, _configuration[1] + 1)
    return _configuration[1]


def resolve(doc_id):
    configuration, generation = _configuration
    mode = configuration.document_modes.get(doc_id, configuration.default_mode)
    return SessionPolicy(mode, "registered-batch-v1" if mode == "registered_only" else "compatibility-v1", generation)


def require_compatibility(doc_id, operation):
    policy = resolve(doc_id)
    if policy.strict:
        raise HTTPException(403, detail={"code": "construction_policy", "operation": operation,
            "profile": policy.profile_id, "policy_generation": policy.generation,
            "detail": "This operation has no admitted registered-only publication contract"})
    return policy


def require_evaluation(doc_id, operation):
    policy = resolve(doc_id)
    if policy.strict and operation not in STRICT_OPERATIONS:
        require_compatibility(doc_id, f"evaluation:{operation}")
    return policy
