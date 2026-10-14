import { test, expect } from '@playwright/test'
import { makeVRJoinFixture, importVRJoinFixture } from './helpers/vr_join_fixture.js'

// Persistent inventory: private __e2e__ parts and their .nadoc-projects revision
// stores are removed by global-teardown, even on failure. Session cache is off.
// All screenshots/traces use the configured Archive output. The isolated Vite
// bridge credential is removed by global-teardown. VR transport is intercepted,
// so this never writes sidecars or takes over a physical viewer.
test.use({ deviceScaleFactor: 0.5, viewport: { width: 1600, height: 1000 } })

test('VR Join previews a cluster pose, cancels, applies desktop routing once and undoes', async ({ page }, info) => {
  test.setTimeout(180_000)
  const fixture = makeVRJoinFixture()
  const errors = [], selections = [], joins = [], execution = [], applied = [], refreshes = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/api/vr/**', route => route.fulfill({ json: { running: false, published: true } }))
  for (const [path, output] of [['feedback', selections], ['join-feedback', joins], ['tool-execution-feedback', execution], ['scene-refresh', refreshes]]) {
    await page.route(`**/api/vr/${path}`, async route => {
      output.push(route.request().postDataJSON())
      await route.fulfill({ json: { published: true, acknowledged: true, scene_revision: 1 } })
    })
  }
  page.on('request', request => {
    if (request.url().endsWith('/cluster-join/apply')) applied.push(request.postDataJSON())
  })
  await importVRJoinFixture(page, fixture, '__e2e__vr-join')
  const design = () => page.evaluate(() => window.__nadocTest.store.getState().currentDesign)
  const dispatch = event => page.evaluate(event => window.__nadocTest.scrywrite.dispatch(event), event)
  const identity = await page.evaluate(() => {
    const state = window.__nadocTest.store.getState()
    const cluster = state.currentDesign.cluster_transforms.find(c => c.id === 'join_cluster_1')
    const n = state.currentGeometry.find(n => cluster.helix_ids.includes(n.helix_id) && n.bp_index === 48)
    if (!n) throw new Error('Join fixture has no selectable donor nucleotide')
    return `nuc:${n.strand_id}:${n.domain_index}:${n.helix_id}:${n.bp_index}:${n.direction}:${n.copy ?? 0}:slab`
  })
  const before = await design()
  await dispatch({ type: 'selection_level', level: 'base' })
  await dispatch({ type: 'tool', mode: 'join', action: 'activate', sequence: 1, targetKind: 'none', targetIdentity: null, targetOwnerTokens: [] })
  await expect.poll(() => page.evaluate(() => window.__nadocTest.getSelectionLevel())).toBe('cluster')
  await dispatch({ type: 'select', sequence: 1, identities: [identity] })
  await expect.poll(() => selections.at(-1)?.selection_kind).toBe('cluster')
  const selection = selections.at(-1)
  const target = { targetKind: selection.selection_kind, targetIdentity: selection.identity, targetOwnerTokens: selection.owner_tokens }
  const preview = sequence => dispatch({ type: 'tool', mode: 'join', action: 'preview', sequence, ...target,
    transformMatrix: fixture.matrix, transformSequence: sequence })

  await preview(2)
  await expect.poll(() => joins.at(-1)?.valid, { timeout: 45_000 }).toBe(true)
  expect(joins.at(-1).connection_count).toBeGreaterThan(0)
  expect(joins.at(-1).bridges.length).toBeGreaterThan(1)
  expect((await design()).cluster_transforms).toEqual(before.cluster_transforms)
  expect((await design()).strands).toEqual(before.strands)
  await page.screenshot({ path: info.outputPath('join-preview.png') })
  await dispatch({ type: 'tool', mode: 'join', action: 'cancel', sequence: 3, ...target })
  await expect.poll(() => joins.at(-1)?.status).toBe('cancelled')
  expect((await design()).cluster_transforms).toEqual(before.cluster_transforms)
  expect((await design()).strands).toEqual(before.strands)
  expect(applied).toHaveLength(0)

  await dispatch({ type: 'tool', mode: 'join', action: 'activate', sequence: 4, ...target })
  await preview(5)
  await expect.poll(() => joins.at(-1)?.valid, { timeout: 45_000 }).toBe(true)
  await dispatch({ type: 'tool', mode: 'join', action: 'confirm', sequence: 6, ...target,
    transformMatrix: fixture.matrix, transformSequence: 5 })
  await expect.poll(() => execution.some(e => e.tool_sequence === 6 && e.status === 'succeeded'), { timeout: 60_000 }).toBe(true)
  expect(applied).toHaveLength(1)
  expect(applied[0]).toMatchObject({ mode: 'free', moving_cluster_id: 'join_cluster_1' })
  expect(applied[0].world_translation).toEqual(fixture.matrix.slice(12, 15))
  const after = await design()
  expect(after.strands.filter(s => s.strand_type === 'scaffold')).toHaveLength(1)
  expect(after.cluster_transforms.find(c => c.id === 'join_cluster_0')).toEqual(before.cluster_transforms.find(c => c.id === 'join_cluster_0'))
  expect(after.cluster_transforms.find(c => c.id === 'join_cluster_1')).not.toEqual(before.cluster_transforms.find(c => c.id === 'join_cluster_1'))
  expect(after.strands.filter(s => s.strand_type === 'staple')).toEqual(before.strands.filter(s => s.strand_type === 'staple'))
  expect(after.feature_log.at(-1).op_kind).toBe('cluster-join')
  expect(refreshes.length).toBeGreaterThan(0)
  await page.screenshot({ path: info.outputPath('join-applied.png') })

  await dispatch({ type: 'tool', mode: 'join', action: 'undo', sequence: 7, ...target })
  await expect.poll(() => execution.some(e => e.tool_sequence === 7 && e.status === 'succeeded')).toBe(true)
  expect((await design()).cluster_transforms).toEqual(before.cluster_transforms)
  expect((await design()).strands).toEqual(before.strands)
  await page.evaluate(async () => (await import('/src/api/client.js')).redo())
  expect((await design()).cluster_transforms).toEqual(after.cluster_transforms)
  expect((await design()).strands).toEqual(after.strands)
  expect(errors).toEqual([])
})
