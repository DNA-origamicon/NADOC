import { test, expect } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import { randomUUID } from 'node:crypto'
import { loadScaffoldedPart } from './helpers/scene_harness.js'

test('domain cluster joint rotation survives preview and confirmation', async ({ page }) => {
  test.setTimeout(240_000)
  await loadScaffoldedPart(page, { doc: 'e2e-domain-joint', name: 'domain-joint' })
  if (process.env.NADOC_JOINT_FIXTURE) {
    const design = JSON.parse(await readFile(process.env.NADOC_JOINT_FIXTURE, 'utf8'))
    design.id = randomUUID()
    design.metadata = { ...design.metadata, name: '__e2e__domain-joint', identity_last_known_path: null }
    await page.evaluate(async content => {
      await window.__nadocTest.setRepresentation('beads')
      const api = await import('/src/api/client.js')
      await api.importDesign(content)
    }, JSON.stringify(design))
  }
  const ids = await page.evaluate(async useFixture => {
    const api = await import('/src/api/client.js')
    const t = window.__nadocTest
    if (useFixture) {
      const d = t.store.getState().currentDesign
      const c = d.cluster_transforms.find(c => c.id === d.feature_log.at(-1).cluster_id)
      const j = d.cluster_joints.find(j => j.cluster_id === c.id)
      await t.activateDesignMoveTool(c.id)
      return { c: c.id, j: j.id }
    }
    const s = t.store.getState().currentDesign.strands.find(s => s.domains.length)
    await api.createCluster({ name: 'Domain cluster', helix_ids: [s.domains[0].helix_id], domain_ids: [{ strand_id: s.id, domain_index: 0 }] })
    const c = t.store.getState().currentDesign.cluster_transforms.at(-1)
    await api.createJoint(c.id, { axis_origin: [0,0,0], axis_direction: [0,1,0] })
    const j = t.store.getState().currentDesign.cluster_joints.at(-1)
    await t.activateDesignMoveTool(c.id)
    return { c: c.id, j: j.id }
  }, !!process.env.NADOC_JOINT_FIXTURE)
  const positions = () => page.evaluate(() => window.__nadocTest.getDesignRenderer().getBackboneEntries().map(e => {
    const a = e.instMesh.instanceMatrix.array, i = e.id * 16
    return { logical: e.pos.toArray(), rendered: [a[i+12],a[i+13],a[i+14]] }
  }))
  const before = await positions()
  await page.locator('#mr-pivot-sel').selectOption(ids.j)
  await page.locator('#mr-ja').fill('60')
  await page.locator('#mr-ja').dispatchEvent('change')
  const preview = await positions()
  const maxDelta = (a, b) => Math.max(...a.map((p, i) =>
    Math.max(...p.rendered.map((v, axis) => Math.abs(v - b[i].rendered[axis])))))
  expect(maxDelta(preview, before)).toBeGreaterThan(1)
  await page.locator('#mr-ja').blur()
  const count = await page.evaluate(() => window.__nadocTest.store.getState().currentDesign.feature_log.length)
  await page.locator('#mr-apply-btn').dispatchEvent('click')
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentDesign.feature_log.length), { timeout: 60_000 }).toBe(count + 1)
  const after = await positions()
  expect(after.length).toBe(preview.length)
  expect(maxDelta(after, preview)).toBeLessThan(.0001)
  // An actual simulation overlay must still restore the newly committed pose.
  await page.evaluate(() => {
    const t = window.__nadocTest, renderer = t.getDesignRenderer()
    const updates = t.store.getState().currentGeometry.map(n => ({ ...n,
      backbone_position: n.backbone_position.map(v => v + 10) }))
    renderer.applyFemPositions(updates)
  })
  expect((await positions()).at(-1).rendered).not.toEqual(after.at(-1).rendered)
  await page.evaluate(() => window.__nadocTest.getDesignRenderer().applyFemPositions(null))
  const restored = await positions()
  expect(maxDelta(restored, after)).toBeLessThan(.0001)
  if (!process.env.NADOC_JOINT_FIXTURE) {
    await page.evaluate(async () => (await import('/src/api/client.js')).getGeometry())
    const reloaded = await positions()
    expect(maxDelta(reloaded, after)).toBeLessThan(.0001)
  }
  // Frame the resulting pose from rendered bounds for a useful review image.
  await page.evaluate(() => {
    const t = window.__nadocTest, entries = t.getDesignRenderer().getBackboneEntries()
    const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity]
    for (const e of entries) e.pos.toArray().forEach((v, i) => { lo[i] = Math.min(lo[i], v); hi[i] = Math.max(hi[i], v) })
    const target = lo.map((v, i) => (v + hi[i]) / 2)
    const span = Math.max(10, Math.hypot(...lo.map((v, i) => hi[i] - v)))
    t.applyCameraPoseForTest({ target, position: target.map((v, i) => v + [1.2, .4, .3][i] * span) })
  })
  await page.screenshot({ path: '/tmp/nadoc-joint-rotation-committed.png' })
})
