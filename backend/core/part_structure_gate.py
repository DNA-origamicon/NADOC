"""Explicit candidate admission, kept out of local geometry preview paths."""

from backend.core.part_command_errors import CommandContractError
from backend.core.part_structure import assess_structure


class PartStructureError(CommandContractError):
    def __init__(self, assessment):
        self.assessment = assessment
        self.status = "failed" if assessment["status"] == "invalid" else "unverified"
        super().__init__("Part structural references are invalid or could not be completely checked",
                         code="invalid_structure" if self.status == "failed" else "structure_incomplete")

    def as_issue(self):
        return {**super().as_issue(), "structure": self.assessment}


def require_valid_structure(design, *, checkpoint=None):
    assessment = assess_structure(design, checkpoint=checkpoint)
    if assessment["status"] != "valid":
        raise PartStructureError(assessment)
    return assessment
