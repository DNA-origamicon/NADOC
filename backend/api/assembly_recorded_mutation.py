"""Record a complete in-memory user command after all derived updates finish."""

from backend.api import assembly_state
from backend.api.assembly_history_transaction import apply_history_change


def apply_recorded_change(evaluate, *, op_kind, label, params):
    from backend.api.assembly import _apply_assembly_mutation_with_feature_log

    def record():
        source = assembly_state.get_or_404()
        assembly_state.set_assembly_silent(source.model_copy(deep=True))
        evaluate()
        candidate = assembly_state.get_or_404()
        assembly_state.set_assembly_silent(source)
        _apply_assembly_mutation_with_feature_log(
            candidate, op_kind=op_kind, label=label, params=params,
        )

    return apply_history_change(record)
