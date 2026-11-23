---
type: feedback
status: active
authority: canonical
---
# Use visible helix labels

Reinforced by the user (2026-11-22): **cell coordinates must never be used to
refer to a helix**. This applies to conversation, diagnostic examples, reports,
tables, diagrams and UI, even when investigating lattice-coordinate defects.
Always resolve the visible helix label from the exact saved/open design being
discussed. Pair examples should read "Helix 1 ↔ Helix 0 at bp 90", not use
coordinate tuples. Internal coordinates remain implementation data, not helix
names. When versions may differ, verify document identity and state before
restating an example; matching filenames alone do not establish the same design.

User instruction (2026-10-27): always refer to helices by their visible labels
(e.g.39,40,41), never internal identifiers such as h_XY_#_#. Internal IDs are
not visible to the user. Apply this to explanations, tables, diagrams, tooltips,
and other user-facing UI. Resolve the same label/fallback numbering used by the
viewer; retain IDs only internally for data joins. Do not infer labels from ID
suffixes. If mapping is unavailable, say it is unknown rather than exposing IDs.
