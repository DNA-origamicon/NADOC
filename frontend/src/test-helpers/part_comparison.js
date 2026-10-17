/** Small display-only fixtures shared by comparison tests; no candidate Design. */
export const comparisonContext = () => ({ docId: 'origin', designId: 'part', loadoutId: 'main',
  revision: 4, editable: true, cursor: -1, subCursor: null })

export const comparisonBinding = () => ({ context: comparisonContext(), jobId: 'job', draftId: 'draft', generation: 3 })

export function readyRepairState() {
  const context = comparisonContext()
  return { context, loaded: true, busy: null, ready: true, requiresReview: false,
    draft: { draft_id: 'draft', generation: 3, actions: [] }, publication: null, refreshNeeded: false,
    job: { id: 'job', operation: 'repair', context, draftId: 'draft', generation: 3,
      response: { status: 'complete', stale: false, source_busy: false, result: { status: 'ready' } } } }
}

export function comparisonEnvelope() {
  const pane = diameter => ({ units: 'nm',
    particles: [{ id: 'gold', kind: 'gold_nanosphere', diameter_nm: diameter,
      pose: [0, -1, 0, 4, 1, 0, 0, -2, 0, 0, 1, 3, 0, 0, 0, 1],
      authored_visible: false, display_color: '#eac13b' }],
    proteins: [{ id: 'protein', asset_id: 'asset', authored_visible: true, representation: 'trace',
      atoms: [{ serial: 1, helix_id: '__protein__protein', name: 'CA', chain_id: 'A', x: 2, y: -1, z: 6 },
        { serial: 2, helix_id: '__protein__protein', name: 'N', chain_id: 'A', x: 2, y: 0, z: 6 }] }],
    bounds_nm: { minimum: [4 - diameter / 2, -2 - diameter / 2, 3 - diameter / 2],
      maximum: [4 + diameter / 2, -2 + diameter / 2, 3 + diameter / 2] }, unplaced_asset_ids: ['unused'] })
  return { status: 'projected', issues: [], projection_version: 1,
    scope: 'uncoated-particles-free-proteins-v1',
    comparison_basis: 'published_materialized_authoring_vs_evaluated_recipe',
    coverage: { complete: true, scientific_qualification: false,
      visibility: 'all_authored_placements', excluded_layers: ['physical', 'presentation'] },
    job_id: 'job', design_id: 'part', source_revision: 4, expires_in_seconds: 60,
    repair_draft: { draft_id: 'draft', generation: 3 }, published: pane(10), proposed: pane(12) }
}

export function deferredComparison() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
