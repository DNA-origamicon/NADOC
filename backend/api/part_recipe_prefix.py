"""Retain one independently replayed prefix for an explicit history edit.

No saved output is read, and no state is cached between revisions or requests.
The prefix's recovery bytes are re-encoded while source verification executes it.
Keep the state before the selected top-level entry and, only for child input
binding, the state after its earlier siblings. Both are request-local and bounded
by the existing source/capture admission; neither becomes saved authority.
"""

from backend.api import state
from backend.core.design_diff import encode_child_diff
from backend.core.part_overlay_commands import KINDS as OVERLAY_KINDS
from backend.api.part_recovery_budget import RecoveryBudget


class ReplayPrefix:
    def __init__(self, source, count, *, budget=None, sub_index=None):
        self.source = source
        self.count = count
        self.log = []
        self.design = None
        self.child_index = 0
        self.children = []
        self.pre = None
        self.budget = budget or RecoveryBudget()
        self.sub_index = sub_index
        self.selected_child_index = 0
        self.child_design = None

    def execute(self, executor, kind, current, params):
        if len(self.log) == self.count:
            if self.design is None:
                self.design = current.copy_with(
                    id=self.source.id, feature_log=list(self.log)
                ).model_copy(deep=True)
            if self.sub_index is not None and self.child_design is None:
                if self.selected_child_index == self.sub_index:
                    # Reference context after earlier siblings, not a separately
                    # certified recipe or persisted construction authority.
                    self.child_design = current.copy_with(id=self.source.id,
                        feature_log=list(self.log)).model_copy(deep=True)
                self.selected_child_index += 1
            return executor(kind, current, params)
        entry = self.source.feature_log[len(self.log)]
        if entry.feature_type in OVERLAY_KINDS:
            updated = executor(kind, current, params)
            if kind == "deformation":
                entry = entry.model_copy(
                    update={"op_snapshot": updated.deformations[-1]}
                )
            self.log.append(entry)
            return updated
        if self.pre is None:
            self.pre = state.encode_design_snapshot(
                current.copy_with(id=self.source.id)
            )
            self.budget.charge(self.pre[0])
        updated = executor(kind, current, params)
        if entry.feature_type == "routing-cluster":
            child = entry.children[self.child_index]
            a, r, m, size = encode_child_diff(current, updated)
            self.budget.charge(a, r, m)
            self.children.append(
                child.model_copy(
                    update={
                        "diff_added_b64": a,
                        "diff_removed_b64": r,
                        "diff_modified_b64": m,
                        "diff_size_bytes": size,
                    }
                )
            )
            self.child_index += 1
            if self.child_index < len(entry.children):
                return updated
            changes = {
                "children": self.children,
                "pre_state_gz_b64": self.pre[0],
                "pre_state_size_bytes": self.pre[1],
                "diffs_evicted": False,
            }
        else:
            changes = {
                "design_snapshot_gz_b64": self.pre[0],
                "snapshot_size_bytes": self.pre[1],
                "diff_added_b64": "",
                "diff_removed_ids": [],
                "diff_modified_b64": "",
                "pre_state_from_previous": False,
            }
        post, size = state.encode_design_snapshot(updated.copy_with(id=self.source.id))
        self.budget.charge(post)
        self.log.append(
            entry.model_copy(
                update={
                    **changes,
                    "post_state_gz_b64": post,
                    "post_state_size_bytes": size,
                    "evicted": False,
                }
            )
        )
        self.pre, self.children, self.child_index = None, [], 0
        return updated
