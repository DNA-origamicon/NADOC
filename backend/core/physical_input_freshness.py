"""Advisory physical-input evidence, separate from recipe or scientific validity.

Legacy fingerprints omit consumed inputs, solver builds and packaged source
bytes. Their equality can never certify complete freshness. This adapter adds
no model traversal, file access, caching, job mutation or simulation execution.
"""

import re


_FINGERPRINT = re.compile(r"(?:(v[0-9]{1,4}):)?([0-9a-f]{64})")
_REVIEWED_LEGACY = frozenset({"v2", "v3", "v4"})


def _parse(value):
    if type(value) is not str or len(value) > 70:
        return None
    match = _FINGERPRINT.fullmatch(value)
    return match.groups() if match else None


def legacy_input_freshness(job_fingerprint, current_fingerprint, *, engine):
    """Report only what the existing partial projection can establish.

    A known difference suffices for stale; equality leaves overall status unknown
    because complete physical inputs were never recorded. An absent/malformed or
    different-version digest is not comparable. Engine identifies the consumer,
    not additional coverage of the old shared DNA projection.
    """
    if engine not in {"oxdna", "namd"}:
        raise ValueError("Unsupported physical-input consumer")
    reasons = ["incomplete_input_provenance"]
    match = None
    before, after = _parse(job_fingerprint), _parse(current_fingerprint)
    if job_fingerprint is None or current_fingerprint is None or job_fingerprint == "" or current_fingerprint == "":
        reasons.append("missing_model_evidence")
    elif before is None or after is None:
        reasons.append("invalid_model_evidence")
    elif before[0] != after[0]:
        reasons.append("incomparable_model_projection")
    elif before[0] not in _REVIEWED_LEGACY:
        reasons.append("unsupported_model_projection")
    else:
        match = before[1] == after[1]
        if not match:
            reasons.append("model_projection_changed")
    return {"status": "stale" if match is False else "unknown",
            "model_match": match, "reasons": reasons,
            "coverage": {"complete": False, "kind": "legacy_model_fingerprint",
                         "profile": before[0] if before and after and before[0] == after[0] else None},
            "compared_to": {"engine": engine, "subject": "active_part_model"}}


def legacy_job_status(job_fingerprint, current_fingerprint, *, engine):
    """Add explicit evidence while retaining the existing compatibility boolean.

    The boolean remains the old guard's advisory predicate, including historical
    test/sentinel strings; it must not be interpreted as a complete current label.
    Selection guards and preparation receipts have a separate migration contract.
    """
    from backend.core.oxdna_staleness import job_out_of_date

    return {"out_of_date": job_out_of_date(job_fingerprint, current_fingerprint),
            "input_freshness": legacy_input_freshness(job_fingerprint, current_fingerprint, engine=engine)}
