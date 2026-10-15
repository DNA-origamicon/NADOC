"""Structured native-command failures shared by replay and repair diagnostics."""

from collections.abc import Iterable, Mapping
from copy import deepcopy
from typing import Literal, TypedDict


class CommandReference(TypedDict):
    kind: str
    identity: str
    parameter_path: list[str | int]


class ReferenceResolutionError(ValueError):
    """An authored target is missing or no longer satisfies its selection.

    Parameter paths address command inputs, so a repair editor can offer a
    replacement without parsing an exception message or recorded geometry.
    """

    def __init__(
        self,
        detail: str,
        *,
        references: Iterable[Mapping[str, object]],
        code: Literal["missing_reference", "invalid_selection"] = "missing_reference",
    ):
        super().__init__(detail)
        self.code = code
        self.references = tuple(deepcopy(dict(reference)) for reference in references)

    def as_issue(self) -> dict:
        return {
            "code": self.code,
            "detail": str(self),
            "references": [deepcopy(reference) for reference in self.references],
        }
