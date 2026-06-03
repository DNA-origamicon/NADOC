/**
 * Aksel staple-scoring report formatters extracted from main.js. Pure: read a
 * plain report object, return string[] lines. Unit-tested in aksel_format.test.js.
 */

/** Lines for the staple-score report summary. */
export function formatScoreSummary(report) {
  const s = report?.summary ?? {}
  return [
    `Staples: ${s.staple_count ?? 0} (${s.scored_staple_count ?? 0} scored)`,
    `Bound nt: ${s.total_bound_nt ?? 0}`,
    `Length violations: ${s.length_violation_count ?? 0}`,
    `Warnings: ${s.warning_count ?? 0}`,
    `Q: ${s.Q_origami == null ? 'n/a' : Number(s.Q_origami).toExponential(3)}`,
  ]
}

/** Lines for the precursor-graph report summary. */
export function formatGraphSummary(report) {
  const s = report?.summary ?? {}
  return [
    `Precursors: ${s.complete_precursor_count ?? 0}/${s.precursor_count ?? 0} complete`,
    `Candidate edges: ${s.edge_count ?? 0}`,
    `Best bound nt: ${s.best_total_bound_nt ?? 0}`,
    `Best Q: ${s.best_Q_origami == null ? 'n/a' : Number(s.best_Q_origami).toExponential(3)}`,
  ]
}
