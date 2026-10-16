"""Lossless admission for document identities used as cache directory names.

Legacy request context resolution remains separate. These checks never trim,
rename or truncate an identity, so two accepted identities cannot collapse to
one path component on the supported case-sensitive filesystem.
"""

import re


MAX_DOCUMENT_ID_LENGTH = 80
_DOCUMENT_ID = re.compile(r"[A-Za-z0-9_.-]{1,80}")


class UnsafeDocumentIdentity(ValueError):
    code = "unsafe_document_identity"

    def __init__(self):
        super().__init__(
            "Document cache identity must be 1–80 ASCII letters, digits, underscores, "
            "hyphens or periods, and cannot be '.' or '..'"
        )


def require_document_identity(doc_id: str) -> str:
    """Return the unchanged safe identity or refuse before path construction."""
    if (type(doc_id) is not str or len(doc_id) > MAX_DOCUMENT_ID_LENGTH
            or doc_id in {".", ".."} or _DOCUMENT_ID.fullmatch(doc_id) is None):
        raise UnsafeDocumentIdentity()
    return doc_id
