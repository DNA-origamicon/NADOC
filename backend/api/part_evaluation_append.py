"""One source proof and one recovery budget for an atomic feature append."""

from backend.api import state
from backend.api.part_recipe_prefix import ReplayPrefix
from backend.api.part_native_commands import PATTERN_COMMANDS
from backend.api.part_geometry_inputs import KINDS as EXTRUSIONS, normalize_creation, bind_prefix
from backend.core.models import SnapshotLogEntry
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import assess_part_history
from backend.core.part_history_proof import ProofBudgetExceeded, command_rows, root_design


COATING_KIND = "streptavidin-coating"


def _reservation(source, request):
    if request.kind != COATING_KIND:
        return 1, 2000
    from backend.api.part_coating_append import CreateRequest, DeleteRequest, MAX_HISTORY_ROWS, parse_request

    body = parse_request(request.params)
    needed = 2 if isinstance(body, CreateRequest) or (
        isinstance(body, DeleteRequest) and any(
            particle.id == body.nanoparticle_id and particle.coating is not None
            for particle in source.nanoparticles)) else 1
    return needed, MAX_HISTORY_ROWS


def _legacy_definition(current, request, header):
    inputs = dict(request.params)
    if request.kind in {"photoproduct-create", "duplex-relax"}:
        inputs["history_seed"] = header["identity"]
    if request.kind == "duplex-relax":
        from backend.api.part_duplex_commands import prepare_command
        params = prepare_command(request.kind, current, inputs)
    else:
        from backend.api.part_cpd_commands import prepare_command
        params = prepare_command(request.kind, inputs)
    label = {"photoproduct-create": "Convert native extra thymines to CPD",
             "photoproduct-relax": "Relax native CPD bonds", "duplex-relax": "Relax native duplex"}[request.kind]
    return header["identity"], request.kind, label, params


def append_features(source, request, header, executor, dependencies, *, metadata=None):
    """Append input definitions after independently proving the existing recipe.

    Combined coating creation/deletion publishes no intermediate state. Existing
    prefix execution and new rows share one cumulative recovery budget.
    """
    if request.kind in EXTRUSIONS:
        if (type(header.get("extrusion_recording_version")) is not int
                or header["extrusion_recording_version"] != 1
                or type(header.get("source_revision")) is not int
                or header["source_revision"] != request.expected_revision
                or header.get("source_design_id") != source.id
                or header.get("expected_kind") != request.kind
                or header.get("expected_feature_id") != header.get("identity")):
            raise CommandContractError("Extrusion append requires its owned context", code="invalid_capture_context")
        inputs = normalize_creation(request.kind, request.params, identity=header["identity"])
    if request.kind == COATING_KIND:
        if (type(header.get("source_revision")) is not int or header["source_revision"] < 0
                or header.get("source_design_id") != source.id):
            raise CommandContractError("Coating append is missing its trusted capture context",
                                       code="invalid_capture_context")
        if request.expected_revision != header["source_revision"]:
            raise CommandContractError("Coating append belongs to a different captured revision",
                                       code="source_changed")
    if request.kind in PATTERN_COMMANDS:
        if (type(header.get("pattern_recording_version")) is not int
                or header["pattern_recording_version"] != 1
                or source.group_organization is None
                or type(header.get("source_revision")) is not int
                or header["source_revision"] != request.expected_revision
                or header.get("source_design_id") != source.id):
            raise CommandContractError("Pattern append requires its owned captured context",
                                       code="invalid_capture_context")
    if request.kind == "overhang-bulk":
        from backend.api.part_connection_recipe_recording import require_context
        require_context(source, request, header)
    needed, limit = _reservation(source, request)
    try:
        # Reserve every new row BEFORE replay, recovery, file reads or packing.
        # The ordinary 2000-entry allowance also counts routing group headers.
        for _ in command_rows(source, limit - needed):
            pass
    except ValueError as error:
        if str(error) == "entry_limit":
            raise ProofBudgetExceeded("Appending features exceeds the recipe entry budget") from error
        raise

    prefix = ReplayPrefix(source, len(source.feature_log))
    last = None

    def run(kind, current, params):
        nonlocal last
        last = prefix.execute(executor, kind, current, params)
        return last

    proof = assess_part_history(source, execute=run, dependencies=dependencies)
    if proof["status"] not in {"verified", "reproduced_import"}:
        return proof
    current = (last if last is not None else root_design(source.recipe_root, input_sources=source.input_sources)).copy_with(
        id=source.id, feature_log=prefix.log,
    )
    compiled = None
    if request.kind == COATING_KIND:
        from backend.api.part_coating_append import compile_steps, prepare_sources

        # New assets are selected in this existing worker after old evidence
        # passes proof. Historical replay/repack never reads the installed files.
        prepared = prepare_sources(request.params)
        compiled = compile_steps(current, request.params, prepared, history_seed=header["identity"])
        current = current.copy_with(input_sources=compiled.input_sources)
        definitions = [(step.identity, step.kind, step.label, step.params) for step in compiled.steps]
    elif request.kind in EXTRUSIONS:
        params = bind_prefix(request.kind, inputs, current)
        definitions = [(header["identity"], request.kind, request.kind, params)]
    elif request.kind in PATTERN_COMMANDS:
        from backend.api.pattern_features import pattern_label

        params = {**request.params, "_proof_version": 1, "history_seed": header["identity"]}
        definitions = [(header["identity"], request.kind, pattern_label(request.kind, params), params)]
    elif request.kind == "overhang-bulk":
        definitions = [(header["identity"], request.kind, "Connection version", request.params)]
    else:
        definitions = [_legacy_definition(current, request, header)]
    if len(definitions) != needed:
        raise CommandContractError("Compiled append differs from its reserved feature count",
                                   code="invalid_append_plan")
    log = list(prefix.log)
    for identity, kind, label, params in definitions:
        updated = executor(kind, current, params)
        if request.kind in EXTRUSIONS:
            updated = updated.copy_with(id=source.id)
        pre, pre_size = state.encode_design_snapshot(current)
        post, post_size = state.encode_design_snapshot(updated)
        prefix.budget.charge(pre, post)
        log.append(SnapshotLogEntry(
            id=identity, timestamp=header["timestamp"], op_kind=kind, label=label,
            params=params, design_snapshot_gz_b64=pre, snapshot_size_bytes=pre_size,
            post_state_gz_b64=post, post_state_size_bytes=post_size,
        ))
        current = updated.copy_with(feature_log=list(log), feature_log_cursor=-1, feature_log_sub_cursor=None)
    if compiled is not None and metadata is not None:
        metadata["append"] = {"kind": COATING_KIND, "action": request.params["action"],
                              "feature_ids": [step.identity for step in compiled.steps],
                              "nanoparticle_id": compiled.nanoparticle_id}
    if request.kind in PATTERN_COMMANDS:
        from backend.core.part_structure_gate import require_valid_structure
        from backend.core.part_verification_capture import admit

        admit(current, preserve_entry_types=True)
        require_valid_structure(current)
    if request.kind in EXTRUSIONS:
        from backend.core.part_recipe_publication import preserve_document_state
        current = preserve_document_state(source, current)
    return current
