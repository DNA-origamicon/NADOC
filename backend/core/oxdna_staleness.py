"""Out-of-date detection for oxDNA jobs.

An oxDNA job is built from a frozen snapshot of the design (its ``topology.top`` +
``conf.dat`` + ``design.json`` written at creation).  If the user edits the design
afterwards, running a NEW operation that resolves the CURRENT design's selections
against the job's frozen topology crashes (particle indices fall out of range).  To
guard that, we compare a content **fingerprint** of the design at job-creation time
against the current design; a mismatch means the job is out of date.

The fingerprint covers exactly the fields an oxDNA build consumes — topology
(strands + crossovers + ligations + extensions + overhangs), sequences (carried on
the strands), and geometry SOURCES (helices + deformations; loop/skips live inside
the strands).  It deliberately EXCLUDES display-only layers — cluster transforms /
joints, camera poses, animations, metadata, the feature log, proteins, plate
layout, representation overrides — so repositioning a cluster or moving the camera
does NOT mark jobs stale; only a structural / sequence / geometry edit does.
(Cluster transforms are the Three-Layer *display* layer and never feed
``_geometry_for_design``, so they are correctly out of the build fingerprint.)
"""

from __future__ import annotations

import hashlib
import json

from backend.core.models import Design

# Design fields that determine the oxDNA build (topology.top + the relaxation seed
# geometry).  An edit to any of these can change particle count / order / position /
# sequence and so invalidates a job; everything else is display/metadata.
_FINGERPRINT_FIELDS = {
    "helices",
    "strands",
    "crossovers",
    "deformations",
    "extensions",
    "overhangs",
    "overhang_connections",
    "forced_ligations",
    "photoproduct_junctions",
}


def oxdna_design_fingerprint(design: Design) -> str:
    """Stable content hash of the oxDNA-build-relevant design fields (see module
    docstring).  Deterministic for a given design state, display-layer agnostic."""
    payload = design.model_dump(mode="json", include=_FINGERPRINT_FIELDS)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def effective_feature_log_position(design: Design) -> int | None:
    """The feature-log index a job seeded from *design* should roll back to — the
    last ACTIVE entry (``feature_log_cursor`` if it points at one, else the final
    entry).  ``None`` when the design has no feature log (nothing to roll to)."""
    n = len(design.feature_log)
    if n == 0:
        return None
    cur = design.feature_log_cursor
    if cur is not None and cur >= 0:
        return cur
    return n - 1


def job_out_of_date(job_fingerprint: str | None, current_fingerprint: str | None) -> bool:
    """True iff the job's creation fingerprint differs from the current design's.
    Unknown on either side (old job without a stored fingerprint, or no active
    design) → not flagged (we never block on a guess)."""
    if not job_fingerprint or not current_fingerprint:
        return False
    return job_fingerprint != current_fingerprint


# The fingerprint is generic over DNA designs — both oxDNA and NAMD/MD jobs build
# from the same topology/sequence/geometry fields — so MD code imports it under this
# neutral name (the ``oxdna_`` alias is kept for the existing oxDNA call sites).
design_build_fingerprint = oxdna_design_fingerprint


def current_active_design_fingerprint() -> str | None:
    """Fingerprint of the CURRENTLY active design (None if there is none).  Shared by
    the oxDNA and MD out-of-date guards.  Staleness is advisory, so ANY failure
    (no active design, or a design that won't serialize) degrades to None rather
    than 500-ing the job list."""
    from backend.api import state as design_state
    try:
        return design_build_fingerprint(design_state.get_or_404())
    except Exception:  # noqa: BLE001
        return None
