"""Exact authoring and recipe parity at the existing JSON worker boundary."""

from backend.core.models import Design
from backend.core.part_history_proof import AUTHORING_FIELDS, digest


RECIPE_FIELDS = frozenset({"recipe_root", "feature_log", "input_sources",
                          "feature_log_cursor", "feature_log_sub_cursor"})


class CandidateDecodeError(ValueError):
    def __init__(self, code, detail):
        self.code = code
        super().__init__(detail)


def decode_candidate(data):
    """Decode once, preserving the established job commit parity checks.

    This checks the bounded worker transport, not native reproducibility. The
    caller must separately own source proof, admission and final publication.
    """
    expected_recipe = digest({name: data[name] for name in RECIPE_FIELDS})
    expected_authoring = digest({name: data[name] for name in AUTHORING_FIELDS})
    candidate = Design.model_validate(data)
    if digest(candidate.model_dump(mode="json", include=AUTHORING_FIELDS)) != expected_authoring:
        raise CandidateDecodeError("candidate_decode_changed_authoring",
            "Candidate changed during decoding; evaluation cannot be committed")
    if digest(candidate.model_dump(mode="json", include=RECIPE_FIELDS)) != expected_recipe:
        raise CandidateDecodeError("candidate_decode_changed_recipe",
            "Recipe changed during decoding; evaluation cannot be committed")
    return candidate, expected_authoring, expected_recipe
