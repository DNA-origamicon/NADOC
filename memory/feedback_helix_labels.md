---
type: feedback
status: active
authority: canonical
---
# Use visible helix labels

User instruction (2026-10-27): always refer to helices by their visible labels
(e.g.39,40,41), never internal identifiers such as h_XY_#_#. Internal IDs are
not visible to the user. Apply this to explanations, tables, diagrams, tooltips,
and other user-facing UI. Resolve the same label/fallback numbering used by the
viewer; retain IDs only internally for data joins. Do not infer labels from ID
suffixes. If mapping is unavailable, say it is unknown rather than exposing IDs.
