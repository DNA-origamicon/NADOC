import { test, expect } from '@playwright/test'

// Browser transaction tier: genuine desktop preview/commit/undo and throwaway
// backend. The absent headset feedback transport alone is intercepted. This is
// deliberately not evidence of controller acquisition or an OpenXR submission.
test('ScryWrite browser-correlated Cluster Cancel / Confirm / Undo', async ({ page }, testInfo) => {
  test.setTimeout(90_000)
  const acknowledgements = []
  await page.route('**/api/vr/tool-execution-feedback', async route => {
    acknowledgements.push(route.request().postDataJSON())
    await route.fulfill({ json: { published: true } })
  })
  await page.goto('/?doc=__e2e__scrywrite-transaction&scrywrite=inspect')
  await page.waitForFunction(() => window.__nadocTest?.scrywrite != null)
  const fixture = await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const { store } = await import('/src/state/store.js')
    await api.createDesign('__e2e__scrywrite-transaction')
    await api.addBundleSegment({ cells: [[0, 0]], lengthBp: 21 })
    const design = store.getState().currentDesign
    const strand = design.strands.find(s => s.domains?.length)
    if (!strand) throw new Error('fixture has no strand')
    await api.createCluster({ name: 'ScryWrite target',
      helix_ids: [strand.domains[0].helix_id],
      domain_ids: [{ strand_id: strand.id, domain_index: 0 }] })
    const cluster = store.getState().currentDesign.cluster_transforms.at(-1)
    const nuc = store.getState().currentGeometry.find(n => n.strand_id === strand.id)
    if (!nuc) throw new Error('fixture has no geometry')
    const identity = encodeURIComponent(['nuc', nuc.strand_id || '_', Number(nuc.domain_index || 0),
      nuc.helix_id || '_', Number(nuc.bp_index || 0), nuc.direction || '_', Number(nuc.copy_k || nuc.ext_k || 0)].join(':'))
    const ref = { kind: 'cluster', id: cluster.id }
    window.__nadocTest.scrywrite.select(ref)
    const { vrInitialSelectionOwnerTokens } = await import('/src/scene/selection_hit_resolver.js')
    return { clusterId: cluster.id, targetIdentity: identity, targetKind: 'cluster',
      targetOwnerTokens: vrInitialSelectionOwnerTokens(ref) }
  })
  const snapshot = () => page.evaluate(() => window.__nadocTest.scrywrite.snapshot())
  const persisted = () => page.evaluate(async () => {
    const response = await fetch('/api/design', { headers: { 'X-NADOC-Doc': '__e2e__scrywrite-transaction' } })
    if (!response.ok) throw new Error('design read failed')
    return (await response.json()).design
  })
  let sequence = 0
  const event = action => page.evaluate(e => window.__nadocTest.scrywrite.dispatch(e),
    { type: 'tool', mode: 'move_rotate', action, sequence: ++sequence, ...fixture })
  const transform = () => page.evaluate(() => window.__nadocTest.scrywrite.dispatch({
    type: 'tool_transform', matrix: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 2, 3, 4, 1],
  }))
  const baseline = await persisted()
  await event('activate')
  await event('preview')
  await expect.poll(async () => (await snapshot()).shell.stage).toBe('preview')
  await transform()
  await expect.poll(async () => (await snapshot()).pendingClusterTransforms.some(c => c.pending != null)).toBe(true)
  await event('cancel')
  await expect.poll(async () => (await snapshot()).pendingClusterTransforms.every(c => c.pending == null)).toBe(true)
  const cancelled = await persisted()
  expect(cancelled.cluster_transforms).toEqual(baseline.cluster_transforms)
  expect(cancelled.feature_log).toEqual(baseline.feature_log)
  await event('preview')
  await transform()
  await expect.poll(async () => (await snapshot()).pendingClusterTransforms.some(c => c.pending != null)).toBe(true)
  await event('confirm')
  await expect.poll(async () => (await snapshot()).transaction.committed?.featureLogEntryId).toBeTruthy()
  const committed = await persisted()
  const state = await snapshot()
  expect(committed.feature_log.at(-1).id).toBe(state.transaction.committed.featureLogEntryId)
  const oldCluster = baseline.cluster_transforms.find(c => c.id === fixture.clusterId)
  const newCluster = committed.cluster_transforms.find(c => c.id === fixture.clusterId)
  newCluster.translation.forEach((v, i) => expect(v - oldCluster.translation[i]).toBeCloseTo([2, 3, 4][i], 6))
  expect(acknowledgements.some(a => a.status === 'succeeded' && a.tool_action === 'confirm' &&
    a.feature_log_entry_id === committed.feature_log.at(-1).id)).toBe(true)
  await event('undo')
  await expect.poll(async () => (await snapshot()).transaction.committed).toBeNull()
  const undone = await persisted()
  expect(undone.cluster_transforms).toEqual(baseline.cluster_transforms)
  expect(undone.feature_log).toEqual(baseline.feature_log)
  await testInfo.attach('scrywrite-browser-transaction.json', {
    body: Buffer.from(JSON.stringify({ fixture, baseline, committed, undone, acknowledgements, browser: await snapshot() }, null, 2)),
    contentType: 'application/json',
  })
  expect((await snapshot()).trace.some(e => e.kind === 'execution_verdict' && e.tool_action === 'undo' && e.status === 'succeeded')).toBe(true)
})
