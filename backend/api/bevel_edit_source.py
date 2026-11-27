"""Read-only Bevel input from independently replayed commands, without recovery encoding."""
from fastapi import HTTPException


def replay_source(source, index):
    from backend.api.part_proof_commands import execute, dependencies
    from backend.core.part_history_contract import assess_part_history
    from backend.core.part_history_proof import command_rows
    from backend.core.part_replay_cache import ReplayChain

    log = source.feature_log[:index]
    stop = sum(1 for _ in command_rows(source.model_copy(update={'feature_log': log}), 2000))
    executor = ReplayChain.for_design(source).wrap(execute)
    count, prefix = 0, None

    def capture(kind, current, params):
        nonlocal count, prefix
        if count == stop:
            # Display-only source: preserve its actual upstream history. Editing
            # still regenerates recovery snapshots in the ordinary transaction.
            prefix = current.model_copy(update={'id': source.id, 'feature_log': log}, deep=True)
        count += 1
        return executor(kind, current, params)

    proof = assess_part_history(source, execute=capture, dependencies=dependencies)
    if proof['status'] not in {'verified', 'reproduced_import'} or prefix is None:
        raise HTTPException(409, detail='The Bevel input history could not be replayed.')
    return prefix
