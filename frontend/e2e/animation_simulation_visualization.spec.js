import { test, expect } from '@playwright/test'
import fs from 'node:fs'

test.use({ viewport: { width: 900, height: 600 }, deviceScaleFactor: 0.5, screenshot: 'off', trace: 'off' })

test.afterEach(async ({ page, request }) => {
  await page.close()
  await request.delete('/api/documents/__e2e__small-plate-animation')
  fs.rmSync(new URL('../../workspace/.session/__e2e__small-plate-animation', import.meta.url), { recursive: true, force: true })
})


test('small plate ion paths retains atomistic representation through animation', async ({ page }) => {
  test.setTimeout(600000)
  const fixture = new URL('../../workspace/small_plate.nadoc', import.meta.url)
  test.skip(!fs.existsSync(fixture), 'Requires the real small_plate design and P1 Alpine trajectory')
  page.setDefaultTimeout(60000)
  page.on('console', m => { if (m.type() === 'error') console.log('browser:', m.text()) })
  // Import into an isolated document; query the original file's real jobs without
  // opening that file for autosave.
  await page.route('**/api/simulate/jobs*', async route => {
    const url = new URL(route.request().url())
    url.searchParams.set('design_source_path', 'small_plate.nadoc')
    await route.continue({ url: url.toString() })
  })
  await page.goto('/?doc=__e2e__small-plate-animation')
  await page.waitForFunction(() => window.__nadocTest)
  const content = fs.readFileSync(fixture, 'utf8')
  console.log('step: import')
  await page.evaluate(async content => {
    const api = await import('/src/api/client.js')
    await api.importDesign(content)
    document.getElementById('welcome-screen')?.classList.add('hidden')
    document.getElementById('left-panel')?.classList.remove('locked-hidden', 'hidden')
    document.querySelectorAll('#left-tab-strip .left-tab-btn').forEach(b => { b.disabled = false })
    window.__leftSidebar?.refresh?.()
  }, content)
  console.log('step: imported')
  console.log('step: tab')
  await page.locator('#left-tab-strip [data-tab="dynamics"]').click()
  // The imported document has no file path. Keep the MD panel's hidden legacy
  // filter aligned with the unified list so background polling retains the pick.
  await page.evaluate(() => {
    const all = document.getElementById('md-jobs-show-all')
    all.checked = true
    all.dispatchEvent(new Event('change', { bubbles: true }))
  })
  await page.locator('.engine-selector-btn[data-engine="namd"]').click()
  console.log('jobs', await page.locator('#simulate-jobs-list').innerText())
  await page.locator('#simulate-jobs-list').getByText('P1 Alpine', { exact: true }).click()
  if (!(await page.locator('#md-ion-paths-toggle').isVisible())) {
    await page.locator('#md-jobs-viz-toggle').click()
  }
  await page.locator('#md-ion-paths-toggle').check()
  console.log('step: ion paths selected')
  await expect(page.locator('#md-ion-paths-status')).toContainText('100%', { timeout: 420000 })
  console.log('ready', await page.locator('#md-ion-paths-status').innerText())

  await page.evaluate(() => window.__nadocTest.setRepresentation('ballstick'))
  await expect.poll(() => page.evaluate(() => window.__nadocTest.isCGVisible()), { timeout: 60000 }).toBe(false)
  await page.evaluate(() => {
    const t = window.__nadocTest
    const dr = t.getDesignRenderer()
    window.__vizBaseline = {
      beads: dr.getBackboneEntries().map(e => e.pos.toArray()),
      slabs: dr.getHelixCtrl().getSlabFrames(),
    }
    window.__cgFlashes = 0
    window.__watchCg = setInterval(() => { if (t.isCGVisible()) window.__cgFlashes++ }, 10)
  })
  // Exercise the real keyboard shortcut while the simulation owns each atom mode.
  for (const repr of ['vdw', 'ballstick', 'stick']) {
    await page.evaluate(repr => window.__nadocTest.setRepresentation(repr), repr)
    await expect.poll(() => page.evaluate(() => window.__nadocTest.isCGVisible())).toBe(false)
    await page.evaluate(() => {
      document.activeElement?.blur()
      window.__cgFlashes = 0
      const dr = window.__nadocTest.getDesignRenderer()
      window.__poseBaseline = {
        beads: dr.getBackboneEntries().map(e => e.pos.toArray()),
        slabs: dr.getHelixCtrl().getSlabFrames(),
      }
    })
    const saved = page.waitForResponse(r => r.url().includes('/design/camera-poses') && r.request().method() === 'POST')
    await page.keyboard.press('v')
    expect((await saved).ok()).toBe(true)
    await page.waitForTimeout(500)
    const state = await page.evaluate(() => {
      const t = window.__nadocTest, dr = t.getDesignRenderer()
      return {
        visible: t.isCGVisible(), flashes: window.__cgFlashes,
        mode: t.getAtomisticRenderer().getMode(),
        positionsUnchanged: JSON.stringify({
          beads: dr.getBackboneEntries().map(e => e.pos.toArray()),
          slabs: dr.getHelixCtrl().getSlabFrames(),
        }) === JSON.stringify(window.__poseBaseline),
      }
    })
    expect(state).toEqual({ visible: false, flashes: 0, mode: repr, positionsUnchanged: true })
    console.log('verified v pose capture', repr)
  }
  await page.evaluate(() => { window.__vizBaseline = window.__poseBaseline })
  // Rail clicks add sidebars; close the Dynamics column to leave room for Animation.
  await page.locator('#left-panel .sidebar-close').evaluateAll(buttons => buttons.forEach(button => button.click()))
  await page.locator('#left-tab-strip [data-tab="scene"]').dispatchEvent('click')
  if (!(await page.locator('#animation-select').isVisible())) {
    await page.locator('#animation-panel-heading').dispatchEvent('click')
  }
  await page.locator('#animation-select').selectOption({ label: 'animation 1' })
  for (const repr of ['ballstick', 'stick']) {
    await page.evaluate(repr => window.__nadocTest.setRepresentation(repr), repr)
    await expect.poll(() => page.evaluate(() => window.__nadocTest.isCGVisible())).toBe(false)
    await page.evaluate(() => { window.__cgFlashes = 0 })
    await page.locator('#anim-playpause-btn').dispatchEvent('click')
    await expect(page.locator('#anim-playpause-btn')).toHaveAttribute('title', 'Pause')
    await expect(page.locator('#anim-playpause-btn')).toHaveAttribute('title', 'Play', { timeout: 30000 })
    const result = await page.evaluate(() => {
      const t = window.__nadocTest, dr = t.getDesignRenderer()
      return {
        flashes: window.__cgFlashes, cgVisible: t.isCGVisible(),
        mode: t.getAtomisticRenderer().getMode(),
        beads: dr.getBackboneEntries().map(e => e.pos.toArray()),
        slabs: dr.getHelixCtrl().getSlabFrames(),
        baseline: window.__vizBaseline,
      }
    })
    expect(result.flashes).toBe(0)
    expect(result.cgVisible).toBe(false)
    expect(result.mode).toBe(repr)
    expect(result.beads).toEqual(result.baseline.beads)
    expect(result.slabs.length).toBe(result.baseline.slabs.length)
    let maxAxisDelta = 0
    for (let i = 0; i < result.slabs.length; i++) {
      expect(result.slabs[i].base_key).toBe(result.baseline.slabs[i].base_key)
      expect(result.slabs[i].center).toEqual(result.baseline.slabs[i].center)
      for (const axis of ['axis_x', 'axis_y', 'axis_z']) {
        for (let j = 0; j < 3; j++) {
          maxAxisDelta = Math.max(maxAxisDelta, Math.abs(result.slabs[i][axis][j] - result.baseline.slabs[i][axis][j]))
        }
      }
    }
    expect(maxAxisDelta).toBeLessThan(1e-6)
    console.log('verified animation', repr, result.beads.length, 'beads', result.slabs.length, 'slabs')
  }
  await page.locator('#anim-export-format').selectOption('gif')
  await page.locator('#anim-export-fps').fill('2')
  await page.evaluate(() => { window.__cgFlashes = 0 })
  const downloaded = page.waitForEvent('download', { timeout: 90000 })
  await page.locator('#anim-export-btn').dispatchEvent('click')
  const download = await downloaded
  expect(download.suggestedFilename()).toMatch(/\.gif$/)
  expect(await download.failure()).toBeNull()
  await expect.poll(() => page.evaluate(() => window.__nadocTest.isCGVisible())).toBe(false)
  expect(await page.evaluate(() => window.__cgFlashes)).toBe(0)
  const gif = fs.readFileSync(await download.path())
  expect(gif.subarray(0, 6).toString()).toMatch(/^GIF8[79]a$/)
  expect(gif.length).toBeGreaterThan(1000)
  await download.delete()
  await page.evaluate(() => clearInterval(window.__watchCg))
  // Full remains a coherent simulation pose when intentionally selected.
  await page.evaluate(() => window.__nadocTest.setRepresentation('full'))
  await expect.poll(() => page.evaluate(() => window.__nadocTest.isCGVisible())).toBe(true)
  const final = await page.evaluate(() => {
    const dr = window.__nadocTest.getDesignRenderer()
    dr.setHiddenNucs(new Set())
    return { slabs: dr.getHelixCtrl().getSlabFrames(), baseline: window.__vizBaseline.slabs }
  })
  expect(final.slabs.length).toBe(final.baseline.length)
  let maxAxisDelta = 0
  for (let i = 0; i < final.slabs.length; i++) {
    expect(final.slabs[i].base_key).toBe(final.baseline[i].base_key)
    expect(final.slabs[i].center).toEqual(final.baseline[i].center)
    for (const axis of ['axis_x', 'axis_y', 'axis_z']) {
      for (let j = 0; j < 3; j++) {
        maxAxisDelta = Math.max(maxAxisDelta, Math.abs(final.slabs[i][axis][j] - final.baseline[i][axis][j]))
      }
    }
  }
  // Instance matrices are Float32; decomposing and recomposing a visibility
  // update can round the axes without moving the residue.
  expect(maxAxisDelta).toBeLessThan(1e-6)
  expect(fs.readFileSync(fixture, 'utf8')).toBe(content)
  console.log('verified GIF export and Full slab registration; max axis rounding', maxAxisDelta)
})
