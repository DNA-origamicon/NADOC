import { test, expect } from '@playwright/test'
import path from 'node:path'
import { readFileSync, existsSync } from 'node:fs'
import { createHash } from 'node:crypto'

// Existing designs are read-only. No simulations or authored structures are created.
for (const fixture of [
  { name: 'small', file: 'Examples/6hb_test.nadoc' },
  { name: 'voltron', file: 'workspace/VoltronCoreArmV2.nadoc', job: '34992198f43a' },
]) test(`shared display frame: ${fixture.name}`, async ({ page }, testInfo) => {
  test.setTimeout(180000)
  const file = path.resolve(process.cwd(), '..', fixture.file)
  test.skip(!existsSync(file), 'Local read-only fixture unavailable')
  const hash = () => createHash('sha256').update(readFileSync(file)).digest('hex')
  const before = hash()
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  try {
    await page.addInitScript(() => localStorage.setItem('nadoc:preferences:v1', JSON.stringify({ autosave: false })))
    await page.route('**/api/design/save**', r => r.fulfill({ status: 409, json: { detail: 'Read-only test' } }))
    await page.setViewportSize({ width: 1600, height: 1000 })
    await page.goto('/?doc=__e2e__display-geometry')
    await page.waitForFunction(() => !!window.__nadocTest)
    await page.evaluate(async file => {
      await (await import('/src/api/client.js')).loadDesign(file)
      document.getElementById('welcome-screen').classList.add('hidden')
      await window.__nadocTest.setRepresentation('full')
    }, file)
    if (fixture.job) {
      const result = await page.evaluate(id => window.__nadocOxdnaDisplay.displayJob(id, true), fixture.job)
      console.log('job result', JSON.stringify(result))
      expect(result.ok, JSON.stringify(result)).toBe(true)
    } else {
      await page.evaluate(() => {
        const r = window.__nadocTest.getDesignRenderer()
        r.applyFemPositions(r.getBackboneEntries().map(e => ({
          ...e.nuc, copy: e._copy ?? 0, backbone_position: e.pos.toArray().map(v => v + 10),
        })), 2)
      })
    }
    const audit = await page.evaluate(() => {
      const api = window.__nadocTest, r = api.getDesignRenderer(), view = api.getUnfoldView()
      const frame = r.getDisplayGeometry()
      const measure = () => {
        let checked = 0, maxError = 0
        for (const arc of view.getArcEntries()) {
          const points = arc.getPositions()
          if (!points.length || points.every(p => p.distanceTo(points[0]) < 1e-8)) continue
          if (arc.fromNuc?.is_reference || arc.toNuc?.is_reference) continue
          for (const [n, actual] of [[arc.fromNuc, points[0]], [arc.toNuc, points.at(-1)]]) {
            const expected = frame.position(n)
            if (expected) { checked++; maxError = Math.max(maxError, expected.distanceTo(actual)) }
          }
        }
        return { checked, maxError }
      }
      const first = measure()
      for (let i = 0; i < 5; i++) {
        view.refreshArcVisibility()
        r.setDesignVisible(false)
        r.setDesignVisible(true)
        view.setHiddenNucs(new Set())
      }
      const refreshed = measure()
      // Negative control: a displaced real GPU line buffer must fail this audit.
      const mesh = view.getArcRoot().children.find(c => c.geometry?.attributes.position)
      const pos = mesh.geometry.attributes.position
      for (let i = 0; i < pos.count; i++) pos.setX(i, pos.getX(i) + 5)
      const broken = measure()
      view.refreshArcVisibility()
      const restored = measure()
      // Fit the observation camera to the displayed frame, including simulation motion.
      const points = r.getBackboneEntries().map(e => e.pos)
      const lo = [0,1,2].map(i => Math.min(...points.map(p => p.getComponent(i))))
      const hi = [0,1,2].map(i => Math.max(...points.map(p => p.getComponent(i))))
      const center = lo.map((v,i) => (v+hi[i])/2)
      const radius = Math.hypot(...hi.map((v,i) => v-lo[i]))/2
      api.applyCameraPoseForTest({target:center,position:[center[0]+radius,center[1]+radius*.7,center[2]+radius*2.8]})
      const pixels = api.renderedPixelCensus()
      // The tiny fixture's two connections are occluded by full-detail slabs.
      // Isolate the real line layer for its pixel check, then restore the model.
      const helixRoot = r.getHelixCtrl().root, wasVisible = helixRoot.visible
      helixRoot.visible = false
      const arcsOnly = api.renderedPixelCensus()
      view.getArcRoot().visible = false
      const noArcs = api.renderedPixelCensus()
      view.getArcRoot().visible = true
      helixRoot.visible = wasVisible
      api.renderViewerFrameForTest()
      return { first, refreshed, broken, restored, pixels, arcsOnly, noArcs }
    })
    console.log(fixture.name, JSON.stringify(audit))
    for (const key of ['first', 'refreshed', 'restored']) {
      expect(audit[key].checked).toBeGreaterThan(0)
      expect(audit[key].maxError).toBeLessThan(0.0001)
    }
    expect(audit.broken.maxError).toBeGreaterThan(1)
    expect(audit.pixels.colorful).toBeGreaterThan(100)
    expect(audit.noArcs.pixelHash).not.toBe(audit.arcsOnly.pixelHash)
    await page.screenshot({ path: testInfo.outputPath(`display-${fixture.name}.png`) })
    expect(errors).toEqual([])
  } finally { expect(hash()).toBe(before) }
})
