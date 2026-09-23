#pragma once
#include "interaction.hpp"

namespace nadoc_vr {
// Read-only readiness mirror. Browser owns construction, revision checks and undo.
inline bool paintedCommitReady(const ToolConfigurationDraft& draft, size_t cells,
                               uint64_t configSequence, const ToolPreflightFeedback* feedback, bool hasEventChannel) {
    return hasEventChannel && draft.active() && draft.mode() == ToolMode::extrude &&
        draft.targetSelectionKind() == "none" && draft.targetIdentity().empty() &&
        draft.lengthBp() > 0 && cells > 0 && feedback && configSequence > 0 &&
        feedback->toolConfigSequence == configSequence &&
        feedback->mode == "extrude" && feedback->selectionKind == "none" &&
        feedback->identity.empty() && feedback->status == "ok";
}
inline bool extrusionCommitReady(const ToolConfigurationDraft& draft, size_t cells,
                                uint64_t sequence, const ToolPreflightFeedback* feedback, bool channel) {
    if (draft.targetSelectionKind() == "none") return paintedCommitReady(draft, cells, sequence, feedback, channel);
    return channel && draft.active() && draft.mode() == ToolMode::extrude &&
        draft.targetSelectionKind() == "end" && !draft.targetIdentity().empty() &&
        draft.lengthBp() > 0 && feedback && sequence > 0 &&
        feedback->toolConfigSequence == sequence && feedback->mode == "extrude" &&
        feedback->selectionKind == "end" && feedback->identity == draft.targetIdentity() &&
        feedback->status == "ok";
}
}
