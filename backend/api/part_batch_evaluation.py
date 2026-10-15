"""Batch-only adapters for the existing capture and isolated evaluation host."""

from backend.core.part_command_errors import CommandContractError


# This is a host qualification gate, not a client/environment override. The
# pure evaluator and spawned regression tests can run without public admission.
REGISTERED_BATCH_ENABLED = False


def capture_batch(design, request, *, revision, preserve_entry_types=True):
    """Run under the caller's state lock, with the ordinary fixed capture budget."""
    if not REGISTERED_BATCH_ENABLED:
        raise CommandContractError("Registered batches are not enabled on this server",
                                   code="registered_batch_unavailable")
    if type(revision) is not int or revision < 0:
        raise CommandContractError("Batch capture needs a trusted revision", code="invalid_capture_context")
    body = request.batch
    if (body.expected_design_id != design.id or body.expected_revision != revision
            or (request.expected_revision is not None and request.expected_revision != revision)):
        raise CommandContractError("Batch belongs to a different part or captured revision", code="batch_conflict")
    from time import monotonic
    from backend.api.part_batch_publication_scope import admit_batch_source
    from backend.core.part_verification_capture import capture

    # A coating or any other source family cannot silently grant a batch a
    # larger capture profile. No source classification or retry is necessary.
    deadline = monotonic() + 0.025
    admit_batch_source(design, body.commands)
    return capture(design, preserve_entry_types=preserve_entry_types,
                   seconds=max(0, deadline - monotonic()))


def evaluate_batch(source, request, header, *, executor, dependency_resolver):
    """Adapt trusted captured context; the pure batch owns its one source proof."""
    from backend.api.part_registered_batch import prepare_batch

    if (type(header.get("source_revision")) is not int or header["source_revision"] < 0
            or header.get("source_design_id") != source.id
            or type(header.get("identity")) is not str or type(header.get("timestamp")) is not str):
        raise CommandContractError("Batch is missing its trusted capture context", code="invalid_capture_context")
    return prepare_batch(source, request.model_dump(mode="json"),
        source_revision=header["source_revision"], history_seed=header["identity"], timestamp=header["timestamp"],
        executor=executor, dependency_resolver=dependency_resolver)
