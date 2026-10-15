"""Editable recipe identities, separate from the pinned numerical ID factory.

The original feature_identity module is an existing duplex-v1 manifest member.
Keep its implementation byte-stable: adding an unrelated editing contract must
not make old numerical rows require an engine upgrade. Its existing protection
table remains the compatibility base; new editing families extend it here.
This module performs no geometry or numerical identity generation.
"""

from backend.core.feature_identity import preserve_proof_identity as _preserve_base


_PROTECTED = {
    "nanoparticle-connection-version-create": ("version_id", "nanoparticle_connection_version"),
    "nanoparticle-connection-version-patch": ("nanoparticle_connection_version",),
    "nanoparticle-connection-version-delete": ("nanoparticle_connection_version",),
}


def preserve_proof_identity(previous, updated, *, kind=None):
    """Preserve only authored output/contract slots, never invent absent ones."""
    result = _preserve_base(previous, updated, kind=kind)
    return {**result, **{key: previous[key] for key in _PROTECTED.get(kind, ()) if key in previous}}
