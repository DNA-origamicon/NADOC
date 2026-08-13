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
Editor-only reference geometry is projected out for the same reason: every
simulation preparer removes it before writing its frozen design snapshot.
"""

from __future__ import annotations

import hashlib
import json
import threading

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

_FINGERPRINT_VERSION = "v3"

# Job cards ask for the current fingerprint on every status refresh.  Serialising a
# multi-thousand-strand design can take seconds (and holds the GIL), so doing the same
# work on every websocket/REST poll can make unrelated lightweight endpoints appear
# hung while a large MD package is being prepared.  A design session already exposes a
# monotonic revision; cache exactly one hash per (document, revision).
_CURRENT_FP_CACHE: dict[tuple[str, int, int], str | None] = {}
_CURRENT_FP_CACHE_LOCK = threading.Lock()


def oxdna_design_fingerprint(design: Design) -> str:
    """Stable content hash of the oxDNA-build-relevant design fields (see module
    docstring).  Deterministic for a given design state, display-layer agnostic."""
    # Jobs are built from this exact projection.  Hashing the unprojected editor
    # design made a job created from a design with reference backdrop geometry
    # appear stale immediately: the job snapshot contained only active DNA while
    # the status endpoint compared it with active + reference DNA.
    design = design.without_reference_geometry()
    payload = design.model_dump(mode="json", include=_FINGERPRINT_FIELDS)
    # Strand colours are persisted on the Strand model so they survive a file
    # round-trip, but they do not affect topology, sequence, seed coordinates, or
    # any simulation input.  Hashing them made a purely cosmetic recolour mark all
    # existing jobs out of date.  Keep the rest of each strand intact (including
    # domains and sequence), and remove only the presentation field.
    for strand in payload.get("strands", []):
        strand.pop("color", None)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"{_FINGERPRINT_VERSION}:{hashlib.sha256(raw).hexdigest()}"


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


def job_out_of_date(
    job_fingerprint: str | None, current_fingerprint: str | None
) -> bool:
    """True iff the job's creation fingerprint differs from the current design's.
    Unknown on either side (old job without a stored fingerprint, or no active
    design) → not flagged (we never block on a guess)."""
    if not job_fingerprint or not current_fingerprint:
        return False
    # An unversioned hash came from the former colour-inclusive algorithm. It
    # cannot be compared meaningfully with the current version: the only difference may be a
    # cosmetic colour, or there may be no difference at all after an upgrade.
    # Callers with a frozen job snapshot derive a v2 hash before reaching here;
    # callers without one degrade to "unknown" instead of showing a false alert.
    if (
        current_fingerprint.startswith(f"{_FINGERPRINT_VERSION}:")
        and len(job_fingerprint) == 64
        and not job_fingerprint.startswith(f"{_FINGERPRINT_VERSION}:")
    ):
        return False
    # A version bump means the canonical projection changed. Hashes produced by
    # different algorithms are incomparable; old jobs degrade to unknown rather
    # than all becoming falsely stale after an upgrade.
    if ":" in job_fingerprint and ":" in current_fingerprint:
        if job_fingerprint.split(":", 1)[0] != current_fingerprint.split(":", 1)[0]:
            return False
    return job_fingerprint != current_fingerprint


def _design_identity(design: "Design | None"):
    """(name, lattice, n_helices, n_strands) — the coarse identity used to tell a
    WHOLLY different loaded design apart from an edit of the same one.  None-safe."""
    if design is None:
        return None
    design = design.without_reference_geometry()
    name = getattr(getattr(design, "metadata", None), "name", None)
    lattice = str(getattr(design, "lattice_type", "")).split(".")[-1].lower()
    return (name or "untitled", lattice, len(design.helices), len(design.strands))


def describe_staleness(
    job_design: "Design | None",
    current_design: "Design | None",
    *,
    stage: str = "prepared",
) -> str:
    """Human-readable reason a job is out of date, DISTINGUISHING the two cases the
    old single message conflated:

    * a *different* design is loaded (name / lattice / helix+strand count differ) —
      rolling the feature log cannot help; the user must open the job's design;
    * the *same* design was edited (identity matches, fingerprint differs) — roll the
      feature log back or prepare a new run.

    Falls back to the generic message when either design is unavailable."""
    generic = (
        f"The design has changed since this job was {stage}. Roll the design "
        "back to the job's run state, or prepare a new run, first."
    )
    ji, ci = _design_identity(job_design), _design_identity(current_design)
    if ji is None or ci is None:
        return generic
    jn, jl, jh, js = ji
    cn, cl, ch, cs = ci
    if ji != ci:
        return (
            f"A different design is loaded: the app currently has '{cn}' "
            f"({cl} lattice, {ch} helices, {cs} strands), but this job was "
            f"{stage} from '{jn}' ({jl} lattice, {jh} helices, {js} strands). "
            f"Open '{jn}' to continue this run."
        )
    return (
        f"'{jn}' has been edited since this job was {stage} (same name and size, "
        "but its topology / sequence / geometry changed). Roll the feature log "
        "back to the run state, or prepare a new run."
    )


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
    from backend.api.doc_context import get_current_doc

    try:
        design, revision = design_state.get_design_with_revision()
        if design is None:
            return None
        key = (get_current_doc(), id(design), revision)
        with _CURRENT_FP_CACHE_LOCK:
            if key in _CURRENT_FP_CACHE:
                return _CURRENT_FP_CACHE[key]
        fingerprint = design_build_fingerprint(design)
        # A mutation may have landed while the expensive serialization ran.  Never
        # publish that result under a stale revision; the next poll computes the new one.
        current, current_revision = design_state.get_design_with_revision()
        if current is not design or current_revision != revision:
            return current_active_design_fingerprint()
        with _CURRENT_FP_CACHE_LOCK:
            # Retain only the newest revision for this document.  This keeps the cache
            # bounded during long editing sessions without coupling state.py to this
            # advisory staleness helper.
            stale = [cached for cached in _CURRENT_FP_CACHE if cached[0] == key[0]]
            for cached in stale:
                _CURRENT_FP_CACHE.pop(cached, None)
            _CURRENT_FP_CACHE[key] = fingerprint
        return fingerprint
    except Exception:  # noqa: BLE001
        return None
