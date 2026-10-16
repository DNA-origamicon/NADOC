"""Same-session owned DNA preparation input; no jobs, I/O or proof authority."""

from dataclasses import dataclass, field
from time import monotonic
from weakref import ref

from fastapi import HTTPException

from backend.api import doc_context, state
from backend.core import oxdna_preparation_inputs as inputs
from backend.core.part_capture_graph import CaptureLimit
from backend.core.part_command_errors import CommandContractError


_KEY = object()
_OPTION_FIELDS = frozenset({"execution_target", "interaction_type", "backend", "engine_variant",
                            "surface", "anchors", "surface_anchors", "surface_strands", "stage_overrides"})


@dataclass(frozen=True)
class CapturedPreparation:
    supported: bool
    design: object
    doc_id: str
    design_id: str
    source_revision: int
    session_identity: str
    _reason: str = field(repr=False)
    _source: object = field(repr=False, compare=False)
    _session: object = field(repr=False, compare=False)
    _key: object = field(repr=False, compare=False)
    _owner: object = field(default=None, repr=False, compare=False)

    @property
    def coverage(self):
        return {"status": "unknown", "complete": False, "native_editable": False,
                "reasons": [{"code": "physical_inputs_unverified", "detail": self._reason}]}


def _options_reason(options):
    if (type(options) is not dict or len(options) != len(_OPTION_FIELDS)
            or any(type(key) is not str for key in options) or options.keys() != _OPTION_FIELDS):
        return "Preparation classification requires the reviewed server option fields"
    for name, allowed in (("execution_target", {"local"}), ("interaction_type", {"DNA2"}),
                          ("backend", {"CPU", "CUDA"}), ("engine_variant", {"auto"})):
        if type(options[name]) is not str or options[name] not in allowed:
            return f"Owned DNA preparation has not reviewed {name}"
    for name in ("surface", "surface_strands"):
        if options[name] is not None:
            return f"Owned DNA preparation has not reviewed {name}"
    for name in ("anchors", "surface_anchors"):
        if type(options[name]) is not list or options[name]:
            return f"Owned DNA preparation has not reviewed {name}"
    if type(options["stage_overrides"]) is not dict or options["stage_overrides"]:
        return "Owned DNA preparation has not reviewed stage overrides"
    return None


def _record(doc, session, source, design_id, design, reason):
    captured = CapturedPreparation(design is not None, design, doc, design_id, session.revision,
        session.identity, reason, ref(source), ref(session), _KEY)
    object.__setattr__(captured, "_owner", ref(captured))
    return captured


def capture_current(options, *, expected_revision=None):
    """No lazy session creation; the complete source is copied while locked."""
    if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 0):
        raise HTTPException(422, detail="Expected preparation revision must be a nonnegative integer")
    with state._lock:
        doc = doc_context.get_current_doc()
        session = state._sessions.get(doc)
        if session is None or session.design is None:
            raise HTTPException(404, detail="No active design.")
        source = state._mutable_design(session.design)
        if expected_revision is not None and session.revision != expected_revision:
            raise HTTPException(409, detail="Design changed before preparation capture.")
        started = monotonic()
        try:
            design_id = inputs.source_identity(source)
        except inputs.CaptureShapeError as error:
            raise HTTPException(422, detail=str(error)) from error
        reason = _options_reason(options)
        try:
            if reason:
                return _record(doc, session, source, design_id, None, reason)
            if monotonic() - started > inputs.CAPTURE_SECONDS:
                raise CaptureLimit("Preparation source classification exceeded its capture allowance")
            owned = inputs.capture_archive(source)
            projected = owned.without_reference_geometry()
            if monotonic() - started > inputs.CAPTURE_SECONDS:
                raise CaptureLimit("Preparation capture exceeded its complete time allowance")
        except inputs.UnsupportedPreparation as error:
            return _record(doc, session, source, design_id, None, str(error))
        except CaptureLimit as error:
            raise CommandContractError(str(error), code="oxdna_input_capture_limit") from error
        return _record(doc, session, source, design_id, projected,
            "The owned model lacks complete packaged-file, solver and attempt input receipts")


def require_current(captured):
    """Guard once before lineage/package side effects, not after later edits."""
    if (type(captured) is not CapturedPreparation or captured._key is not _KEY
            or captured._owner is None or captured._owner() is not captured):
        raise HTTPException(409, detail="Preparation input lacks its original host capture")
    if not captured.supported:
        raise HTTPException(422, detail="This preparation profile has no owned input")
    with state._lock:
        doc = doc_context.get_current_doc()
        session = state._sessions.get(doc)
        source = captured._source()
        if (doc != captured.doc_id or session is None or session is not captured._session()
                or session.identity != captured.session_identity or session.revision != captured.source_revision
                or source is None or session.design is not source):
            raise HTTPException(409, detail="Design or document session changed before preparation")
        try:
            identity_matches = inputs.source_identity(source) == captured.design_id
        except inputs.CaptureShapeError:
            identity_matches = False
        if not identity_matches:
            raise HTTPException(409, detail="Design or document session changed before preparation")
