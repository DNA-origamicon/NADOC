import { test, expect } from '@playwright/test'

test('strand automation hides beads, cones and slabs in 2hb_2xT', async ({ page }) => {
  test.setTimeout(60_000)
  await page.goto('/?doc=e2e-strand-visibility')
  await page.waitForSelector('#canvas')
  await page.waitForFunction(() => Boolean(window.__nadocTest?.visibility))
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const response = await fetch('/api/library/content?path=2hb_2xT.nadoc')
    const { content } = await response.json()
    const design = JSON.parse(content)
    design.metadata.identity_last_known_path = null
    await api.importDesign(JSON.stringify(design))
    window.__nadocTest.visibility.unhideAll()
    await window.__nadocTest.visibility.flush()
    document.getElementById('welcome-screen')?.classList.add('hidden')
  })
  await expect.poll(() => page.evaluate(() =>
    window.__nadocTest?.store.getState().currentGeometry?.length ?? 0),
  { timeout: 25_000 }).toBeGreaterThan(0)

  const strandId = await page.evaluate(() =>
    window.__nadocTest.store.getState().currentDesign.strands
      .find(s => s.strand_type !== 'scaffold')?.id)
  expect(strandId).toBeTruthy()

  await expect.poll(() => page.evaluate(id =>
    window.__nadocTest.visibility.strandRenderStats(id).beads, strandId))
    .toBeGreaterThan(0)

  const before = await page.evaluate(id => window.__nadocTest.visibility.strandRenderStats(id), strandId)
  expect(before.visibleBeads).toBeGreaterThan(0)
  expect(before.visibleSlabs).toBeGreaterThan(0)

  await page.screenshot({ path: 'test-results/strand-visibility-2hb_2xT-before.png', fullPage: true })

  await page.evaluate(id => window.__nadocTest.visibility.hideStrands([id]), strandId)
  const hidden = await page.evaluate(id => window.__nadocTest.visibility.strandRenderStats(id), strandId)
  expect(hidden).toMatchObject({ visibleBeads: 0, visibleCones: 0, visibleSlabs: 0 })

  await page.evaluate(() => window.__nadocTest.visibility.undo())
  const restored = await page.evaluate(id => window.__nadocTest.visibility.strandRenderStats(id), strandId)
  expect(restored.visibleBeads).toBe(before.visibleBeads)
  expect(restored.visibleSlabs).toBe(before.visibleSlabs)

  // Visual artifact retained on failure by Playwright; this explicit shot also
  // makes the real 2hb fixture easy to inspect in local validation runs.
  await page.evaluate(id => window.__nadocTest.visibility.hideStrands([id]), strandId)
  await page.screenshot({ path: 'test-results/strand-visibility-2hb_2xT-after.png', fullPage: true })

  // The same hidden-base state survives representation switches. Heavy reps
  // load asynchronously, so wait for the switch to settle before capturing.
  for (const repr of ['cylinders', 'vdw', 'surface']) {
    await page.evaluate(r => window.__nadocTest.setRepresentation(r), repr)
    await page.waitForTimeout(repr === 'cylinders' ? 400 : 1800)
    expect(await page.evaluate(() => window.__nadocTest.visibility.hiddenBaseKeys().length)).toBeGreaterThan(0)
    await page.screenshot({ path: `test-results/strand-visibility-2hb_2xT-${repr}.png`, fullPage: true })
  }

})

test('hide, close session, and library-reopen keeps 3D and orbit usable', async ({ page }) => {
  test.setTimeout(60_000)
  const savedName = 'e2e__hidden_strand_reload.nadoc'
  const pageErrors = []
  page.on('pageerror', error => pageErrors.push(error.message))

  // Create a disposable library copy; all remaining opens/closes are driven by
  // the same UI controls as the reported workflow.
  await page.goto('/?doc=e2e-hidden-strand-close-reopen')
  await page.waitForFunction(() => Boolean(window.__nadocTest?.visibility))
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const response = await fetch('/api/library/content?path=2hb_2xT.nadoc')
    const { content } = await response.json()
    const design = JSON.parse(content)
    design.metadata.identity_last_known_path = null
    design.visibility_state = { hidden_base_keys: [], shown_base_keys: [], hidden_cluster_ids: [] }
    await api.uploadLibraryFile(JSON.stringify(design), 'e2e__hidden_strand_reload.nadoc')
  })
  await page.reload()
  await page.waitForFunction(() => Boolean(window.__nadocTest?.visibility))

  const row = page.locator(`#welcome-screen .lib-file-row[title="${savedName}"]`).first()
  await row.waitFor({ state: 'visible', timeout: 25_000 })
  await row.click()
  await expect(page.locator('#welcome-screen')).toHaveClass(/hidden/, { timeout: 25_000 })
  await expect.poll(() => page.evaluate(() =>
    window.__nadocTest.store.getState().currentGeometry?.length ?? 0)).toBeGreaterThan(0)

  const strandId = await page.evaluate(() =>
    window.__nadocTest.store.getState().currentDesign.strands
      .find(s => s.strand_type !== 'scaffold')?.id)
  await page.evaluate((strandId) => {
    window.__nadocTest.visibility.hideStrands([strandId])
  }, strandId)

  // Close immediately, deliberately without an automation flush: Close Session
  // itself must drain the in-flight hide and save it before teardown.
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-close-session')
  await expect(page.locator('#welcome-screen')).toBeVisible({ timeout: 25_000 })
  expect(await page.evaluate(() => window.__nadocTest.controlsEnabled())).toBe(true)
  // Reproduce the reported poisoned-orbit state. Opening must recover rather
  // than normalizing NaN and propagating it through fit-to-view forever.
  await page.evaluate(() => window.__nadocTest.poisonCameraForTest())

  const reopenRow = page.locator(`#welcome-screen .lib-file-row[title="${savedName}"]`).first()
  await reopenRow.waitFor({ state: 'visible', timeout: 25_000 })
  await reopenRow.click()
  await expect(page.locator('#welcome-screen')).toHaveClass(/hidden/, { timeout: 25_000 })
  await expect.poll(() => page.evaluate(() =>
    window.__nadocTest.store.getState().currentGeometry?.length ?? 0),
  { timeout: 25_000 }).toBeGreaterThan(0)
  await expect.poll(() => page.evaluate(id =>
    window.__nadocTest.visibility.strandRenderStats(id).beads, strandId))
    .toBeGreaterThan(0)
  expect(await page.evaluate(id => window.__nadocTest.visibility.strandRenderStats(id), strandId))
    .toMatchObject({ visibleBeads: 0, visibleCones: 0, visibleSlabs: 0 })
  const visibleStrandId = await page.evaluate(hiddenId =>
    window.__nadocTest.store.getState().currentDesign.strands.find(s => s.id !== hiddenId)?.id,
  strandId)
  await expect.poll(() => page.evaluate(id =>
    window.__nadocTest.visibility.strandRenderStats(id).visibleBeads, visibleStrandId))
    .toBeGreaterThan(0)
  expect(await page.evaluate(() => window.__nadocTest.controlsEnabled())).toBe(true)
  expect(await page.evaluate(() => {
    const d = window.__nadocTest.viewerDiagnostic()
    return [...d.camera.position, ...d.camera.target].every(Number.isFinite)
  })).toBe(true)
  expect(pageErrors).toEqual([])
  await page.screenshot({
    path: 'test-results/strand-visibility-close-reopen-visible.png', fullPage: true,
  })

  // A post-reload visibility edit proves the controller and backend session are
  // still live rather than merely rendering a frozen saved frame.
  // Poison it again immediately before the real sidebar action: Unhide All
  // itself must recover the view, not rely on a prior file-open fit.
  await page.evaluate(() => window.__nadocTest.poisonCameraForTest())
  await page.click('#unhide-all-btn')
  await expect.poll(() => page.evaluate(id =>
    window.__nadocTest.visibility.strandRenderStats(id).visibleBeads, strandId))
    .toBeGreaterThan(0)
  await page.evaluate(() => window.__nadocTest.visibility.flush())
  const afterUnhide = await page.evaluate(() => window.__nadocTest.viewerDiagnostic())
  expect([...afterUnhide.camera.position, ...afterUnhide.camera.target].every(Number.isFinite)).toBe(true)
  expect(afterUnhide.hiddenBaseKeys).toEqual([])
  for (const id of await page.evaluate(() =>
    window.__nadocTest.store.getState().currentDesign.strands.map(s => s.id))) {
    const stats = await page.evaluate(strandId =>
      window.__nadocTest.visibility.strandRenderStats(strandId), id)
    expect(stats.visibleBeads).toBe(stats.beads)
    expect(stats.visibleSlabs).toBe(stats.slabs)
  }
})
