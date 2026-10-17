"""Native linker v3 restoration over the shared direct ownership contract."""


def prepare(design, body):
    from backend.api import part_connection_application_commands as linker
    from backend.api.part_connection_direct_ownership import prepare_replacement

    restored, _version, original_index, restored_index = prepare_replacement(
        design, body, slots=linker._output_slots(body), slot_path='connection_id', qualify_targets=False)
    # Check the original prefix too: removal must not make an old output ID or
    # an overlapping removal namespace appear available to a new feature.
    removed = original_index.keys() - restored_index.keys()
    linker._check_outputs(design, body, original_index, removed)
    # Exact old conflicts were validated by the shared restoration contract.
    # The native linker builder now sees the restored, connection-free pair.
    request = body.model_copy(update={'conflict_connection_ids': []})
    selected, _ = linker._select_inputs(restored, request, restored_index)
    return restored, request, selected
