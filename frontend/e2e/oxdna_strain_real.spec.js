import { test, expect } from '@playwright/test'
import fs from 'node:fs'

// Opt-in existing-run diagnosis. The runner owns disposable copied job metadata,
// session/cache isolation and failure-safe cleanup. No design is authored/saved.
// Screenshots and replies go only to Playwright's configured output directory.
const cases = process.env.NADOC_STRAIN_MANIFEST
  ? JSON.parse(fs.readFileSync(process.env.NADOC_STRAIN_MANIFEST, 'utf8')) : []
for (const item of cases) test(item.name, async ({ page }, info) => {
  page.setDefaultTimeout(20000)
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  await page.route('**/api/design/save**', route => route.abort())
  await page.goto('/?test=1&doc=__e2e__strain-' + item.id + '&open=' + encodeURIComponent(item.source))
  await page.waitForFunction(() => window.__nadocTest?.store.getState().currentDesign?.helices?.length > 0)
  await page.evaluate(() => window.__nadocTest.setRepresentation('beads'))
  for (const label of ['Close Feature log sidebar', 'Close Properties sidebar']) {
    const button = page.getByRole('button', { name: label, exact: true })
    if (await button.isVisible()) await button.click()
  }
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  await page.locator('#engine-selector-mount').getByRole('tab', { name: 'oxDNA', exact: true }).click()
  const row = page.locator(`#simulate-jobs-list [data-job-id="${item.id}"]`)
  await expect(row).toBeVisible({ timeout: 30000 })
  await row.click()
  console.log(item.name, 'selected')
  if (!await page.locator('#oxdna-jobs-strain-toggle').isVisible()) await page.locator('#oxdna-jobs-viz-toggle').click()
  for (const metric of ['backbone', 'wc']) {
    const reply = page.waitForResponse(r => r.url().includes(`/${item.id}/strain?`) && r.url().includes(`metric=${metric}`), { timeout: 180000 })
    await page.locator('#oxdna-jobs-strain-metric').selectOption(metric)
    if (metric === 'backbone') await page.locator('#oxdna-jobs-strain-toggle').check()
    const response = await (await reply).json()
    console.log(item.name, metric, response.ready, response.n_strain_frames)
    expect(response.ready, JSON.stringify(response)).toBe(true)
    expect(response.aggregation).toBe(item.torsion ? 'peak' : 'mean')
    expect(response.n_frames_torn).toBe(0)
    expect(response.n_strain_frames).toBeGreaterThan(1)
    fs.writeFileSync(info.outputPath(`${metric}.json`), JSON.stringify(response))
    await expect.poll(() => page.evaluate(() => window.__nadocOxdnaDisplay.mode())).toBe('strain')
    // Frame the actual mean coordinates, retaining the wheel face plus shaft depth.
    const pts = response.positions.map(p => p.backbone_position)
    const center = [0,1,2].map(k => (Math.min(...pts.map(p => p[k])) + Math.max(...pts.map(p => p[k]))) / 2)
    const span = Math.max(...[0,1,2].map(k => Math.max(...pts.map(p => p[k])) - Math.min(...pts.map(p => p[k]))))
    await page.evaluate(({center,span}) => window.__nadocTest.applyCameraPoseForTest({
      position: [center[0] + span * .15, center[1] - span * 1.65, center[2] + span * .2], target: center, up: [0,0,1],
    }), {center,span})
    await page.locator('#oxdna-jobs-strain-toggle').scrollIntoViewIfNeeded()
    await expect(page.locator('#oxdna-jobs-strain-status')).toContainText('bases coloured')
    await page.screenshot({ path: info.outputPath(`${metric}.png`) })
    const flexible = await page.evaluate(async () => {
      const { flexAnchorKey } = await import('/src/scene/flexible_arcs.js')
      const THREE = await import('/node_modules/three/build/three.module.js')
      const api = window.__nadocTest, design = api.store.getState().currentDesign
      const keyOf = flexAnchorKey(design), colors = api.getDesignRenderer().getScalarColors()
      const connections = new Map(design.flexible_connections.map(c => [c.id, c]))
      let measured = 0, mismatches = 0, tubes = 0
      api.scene.traverse(group => {
        if (group.name !== 'flexibleArcs') return
        for (const mesh of group.children) {
          const conn = connections.get(mesh.userData.connectionId)
          if (!conn) continue
          if (!mesh.isInstancedMesh) { if (mesh.material.vertexColors) tubes++; continue }
          for (let i = 0; i < mesh.count; i++) {
            const key = keyOf(conn.segment_bead_keys[i]), expected = colors[key] ?? colors[key + ':0']
            if (expected == null) continue
            measured++
            const actual = new THREE.Color()
            if (!mesh.instanceColor) { mismatches++; continue }
            mesh.getColorAt(i, actual)
            actual.multiply(mesh.material.color)
            if (actual.getHex() !== expected) mismatches++
          }
        }
      })
      return { measured, mismatches, tubes }
    })
    expect(flexible.mismatches).toBe(0)
    if (metric === 'backbone') {
      expect(flexible.measured).toBeGreaterThan(0)
      expect(flexible.tubes).toBeGreaterThan(0)
    }
    fs.writeFileSync(info.outputPath(`${metric}-flexible.json`), JSON.stringify(flexible))
    const pixels = await page.evaluate(() => window.__nadocTest.renderedPixelCensus())
    expect(pixels.colorful).toBeGreaterThan(1000)
    if (!item.torsion && metric === 'backbone') {
      const pose = await page.evaluate(() => ({ position: window.__nadocTest.camera.position.toArray(), target: window.__nadocTest.controls.target.toArray(), up: window.__nadocTest.camera.up.toArray() }))
      await page.evaluate(() => window.__nadocTest.applyCameraPoseForTest({ position: [10000,10000,10000], target: [20000,10000,10000] }))
      const blank = await page.evaluate(() => window.__nadocTest.renderedPixelCensus())
      expect(blank.colorful).toBeLessThan(pixels.colorful * .1)
      await page.evaluate(pose => window.__nadocTest.applyCameraPoseForTest(pose), pose)
    }
    const census = await page.evaluate(() => window.__nadocTest.nativeBackboneColorCensus())
    expect(census.active.length).toBeGreaterThan(10)
  }
  // Both time aggregations and the designed-ssDNA filter go through normal UI.
  const changed = page.waitForResponse(r => r.url().includes(`/${item.id}/strain?`) && r.url().includes('aggregation=' + (item.torsion ? 'mean' : 'peak')), { timeout: 180000 })
  await page.locator('#oxdna-jobs-strain-aggregation').selectOption(item.torsion ? 'mean' : 'peak')
  expect((await (await changed).json()).ready).toBe(true)
  await page.locator('#oxdna-jobs-strain-dsdna-only').check()
  await expect(page.locator('#oxdna-jobs-strain-status')).toContainText('dsDNA only')
  expect(errors).toEqual([])
})
