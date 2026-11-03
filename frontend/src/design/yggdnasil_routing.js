import report from './yggdnasil_routing.json'
import cylinderReport from './yggdnasil_cylinder_routing.json'
export const CYLINDER_ROUTING_REPORT = cylinderReport
const cylinders = new Map(cylinderReport.records.flatMap(r => r.keys.map(key => [key, r])))
const records = new Map(report.records.map(r => [r.key, r]))
export const ROUTING_LABELS = {
  parity_obstruction: 'Excluded · parity imbalance',
  no_path: 'Excluded · no helix traversal',
  path_found: 'Traversal found · full routing untested',
  unresolved: 'Unresolved · search limit reached',
  not_screened: 'Not screened',
}
export function routingScreen(entry) {
  if (entry.shape === 'hollow') {
    const even = entry.points.filter(p => (p.row + p.col) % 2 === 0).length
    const record = entry.sources.map(s => cylinders.get(s.key)).find(Boolean)
    const fallback = { even, odd: entry.helices - even, path: null,
      status: Math.abs(2 * even - entry.helices) > 1 ? 'parity_obstruction' : 'unresolved' }
    const result = record || fallback
    return { ...result, excluded: ['parity_obstruction', 'no_path'].includes(result.status),
      label: !record && result.status === 'unresolved' ? 'Unresolved · native traversal not yet screened' : ROUTING_LABELS[result.status] }
  }
  const key = `${entry.lattice}:${entry.sources[0].center}:${entry.helices}`
  const record = records.get(key) || { status: 'not_screened', path: null }
  return { ...record, excluded: ['parity_obstruction', 'no_path'].includes(record.status), label: ROUTING_LABELS[record.status] }
}
export function routingTotals(entries) {
  const totals = { total: 0, excluded: 0, path_found: 0, unresolved: 0, parity: 0, no_path: 0 }
  for (const entry of entries) {
    const screen = routingScreen(entry)
    totals.total += entry.count
    if (screen.excluded) totals.excluded += entry.count
    if (screen.status === 'parity_obstruction') totals.parity += entry.count
    else if (screen.status === 'no_path') totals.no_path += entry.count
    else if (screen.status === 'path_found') totals.path_found += entry.count
    else totals.unresolved += entry.count
  }
  return totals
}
export function routingExport(atlas) {
  return { ...atlas, routingScreen: {
    scope: report.scope, interpretation: report.interpretation,
    budget_per_footprint: report.budget_per_footprint, source_sha256: report.source_sha256,
    totals: routingTotals(atlas.entries),
  }, entries: atlas.entries.map(entry => ({ ...entry, routing: routingScreen(entry) })) }
}
