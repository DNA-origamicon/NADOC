import { test, expect } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import { randomUUID } from 'node:crypto'
import { loadScaffoldedPart } from './helpers/scene_harness.js'

const camera = page => page.evaluate(() => window.__nadocTest.viewerDiagnostic().camera)
const distance = pose => Math.hypot(...pose.position.map((v, i) => v - pose.target[i]))

test('F frames visible content after hiding a long cluster, and restores it on show', async ({ page }) => {
  test.setTimeout(180_000)
  page.setDefaultTimeout(15_000)
  if (process.env.NADOC_NAV_FIXTURE) {
    const design = JSON.parse(await readFile(process.env.NADOC_NAV_FIXTURE, 'utf8'))
    design.id = randomUUID() // isolate the copy from saved simulation-job associations
    design.metadata = { ...design.metadata, name: '__e2e__hidden-navigation', identity_last_known_path: null }
    design.visibility_state = { hidden_base_keys: [], shown_base_keys: [], hidden_cluster_ids: [] }
    await loadScaffoldedPart(page, { doc: 'e2e-hidden-navigation', name: 'hidden-navigation' })
    await page.evaluate(async content => {
      const api = await import('/src/api/client.js')
      await window.__nadocTest.setRepresentation('beads')
      await api.importDesign(content)
      document.getElementById('welcome-screen')?.classList.add('hidden')
    }, JSON.stringify(design))
  } else {
    await loadScaffoldedPart(page, { doc: 'e2e-hidden-navigation', name: 'hidden-navigation' })
    const headers = { 'Content-Type': 'application/json', 'X-NADOC-Doc': 'e2e-hidden-navigation' }
    await page.request.post('/api/design/helix-at-cell', { headers, data: { row: 1, col: 0, length_bp: 20 } })
    const { design } = await (await page.request.get('/api/design', { headers })).json()
    const short = design.helices.at(-1)
    await page.request.post('/api/design/scaffold-domain-paint', {
      headers, data: { helix_id: short.id, lo_bp: 0, hi_bp: 19 },
    })
    await page.evaluate(async () => {
      const api = await import('/src/api/client.js')
      const d = window.__nadocTest.store.getState().currentDesign
      await api.createCluster({ name: 'Long arm', helix_ids: [d.helices.find(h => h.length_bp === 200).id] })
    })
  }
  await page.waitForFunction(() => window.__nadocTest.getDesignRenderer().getBackboneEntries().length > 0)
  await page.screenshot({ path: '/tmp/nadoc-navigation-loaded.png' })
  const clusterId = await page.evaluate(() => {
    const t = window.__nadocTest
    const d = t.store.getState().currentDesign
    const longest = d.helices.reduce((a, b) => a.length_bp >= b.length_bp ? a : b)
    return d.cluster_transforms.find(c => c.helix_ids.includes(longest.id)).id
  })
  await page.locator('#right-tab-strip [data-tab="clustering"]').click()
  await page.evaluate(() => document.activeElement?.blur())
  await page.keyboard.press('f')
  const before = await camera(page)
  // Use the real Movable Clusters eye button, choosing the long-arm row by order.
  const rowIndex = await page.evaluate(id => window.__nadocTest.store.getState().currentDesign
    .cluster_transforms.findIndex(c => c.id === id), clusterId)
  const hide = page.locator('#cluster-list button[title="Hide cluster"]').nth(rowIndex)
  // Large fixtures use the same DOM handler without traversing the dense
  // structure with the headless browser's pointer on the way to the sidebar.
  if (process.env.NADOC_NAV_FIXTURE) await hide.dispatchEvent('click')
  else await hide.click()
  await page.evaluate(() => document.activeElement?.blur())
  await page.keyboard.press('f')
  const after = await camera(page)
  expect(distance(after)).toBeLessThan(distance(before) * .8)
  // Independently measure visible rendered nucleotide centers, not authored hidden positions.
  const expected = await page.evaluate(async () => {
    const { isVisibleInstance } = await import('/src/scene/base_pick.js')
    const entries = window.__nadocTest.getDesignRenderer().getBackboneEntries()
    const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity]
    for (const e of entries) {
      if (!isVisibleInstance(e.instMesh, e.id)) continue
      for (let i = 0; i < 3; i++) {
        const value = e.pos.getComponent(i)
        lo[i] = Math.min(lo[i], value); hi[i] = Math.max(hi[i], value)
      }
    }
    return lo.map((v, i) => (v + hi[i]) / 2)
  })
  after.target.forEach((v, i) => expect(v).toBeCloseTo(expected[i], 3))
  await page.screenshot({ path: '/tmp/nadoc-hidden-navigation.png' })
  const show = page.locator('#cluster-list button[title="Show cluster"]')
  if (process.env.NADOC_NAV_FIXTURE) await show.dispatchEvent('click')
  else await show.click()
  await page.evaluate(() => document.activeElement?.blur())
  await page.keyboard.press('f')
  expect(distance(await camera(page))).toBeCloseTo(distance(before), 3)
})
