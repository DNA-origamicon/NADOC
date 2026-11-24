import { test, expect } from '@playwright/test'
import { beadCandidates, trackConsoleErrors } from './helpers/scene_harness.js'

// Continuous trace screenshots contend with WebGL software rendering and skew
// the preview-latency measurement. Failure screenshots and assertions remain.
test.use({ trace: 'off' })

async function waitReady(popup) {
  await expect.poll(async () => ({ ready: await popup.locator('.def-btn.primary').isEnabled(),
    status: await popup.locator('[role=status]').textContent() }), { timeout: 30_000 })
    .toMatchObject({ ready: true })
}

// Artifact inventory: native UI/API authoring only; all possible autosaved
// parts use __e2e__corner-tool and are removed (with project revision stores)
// by global-teardown.js. Session caching is disabled by playwright.config.js.
// No standalone design, screenshot or simulation output is written by this spec.
for (const crossSection of [
  { name: '6HB', lattice: 'HONEYCOMB', cells: [[0, 1], [1, 1], [1, 2], [1, 3], [0, 3], [0, 2]], step: '7' },
  { name: '1x8 SQ', lattice: 'SQUARE', cells: Array.from({ length: 8 }, (_, i) => [0, i]), step: '8' },
  { name: '6HB nicked', lattice: 'HONEYCOMB', cells: [[0, 1], [1, 1], [1, 2], [1, 3], [0, 3], [0, 2]], step: '7', nick: true },
  { name: '6HB routed', lattice: 'HONEYCOMB', cells: [[0, 1], [1, 1], [1, 2], [1, 3], [0, 3], [0, 2]], step: '7', routed: true },
]) test(`Corner ${crossSection.name}: cluster pick, Full preview, apply and history edit`, async ({ page }, testInfo) => {
  test.setTimeout(240_000)
  const errors = trackConsoleErrors(page)
  await page.setViewportSize({ width: 1600, height: 1000 })
  await page.goto('/?doc=__e2e__corner-tool')
  await page.waitForFunction(() => !!window.__nadocTest?.store)
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.locator('#menu-file-new').click()
  await page.locator('#new-design-name').fill('__e2e__corner-tool')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  await page.waitForFunction(() => window.__nadocTest.store.getState().currentDesign?.metadata?.name === '__e2e__corner-tool')
  await page.evaluate(async crossSection => {
    const api = await import('/src/api/client.js')
    await api.createBundle({ cells: crossSection.cells,
      lengthBp: 168, name: '__e2e__corner-tool', latticeType: crossSection.lattice })
    if (crossSection.nick) {
      await api.addNick({ helixId: window.__nadocTest.store.getState().currentDesign.helices[0].id,
        bpIndex: 83, direction: 'FORWARD' })
    }
    if (crossSection.routed) {
      await api.autoScaffoldSeamless()
      await api.assignScaffoldSequence('M13mp18')
      await api.assignStapleSequences()
    }
    window.__nadocTest.applyCameraPoseForTest({ target: [3, 3, 28], position: [70, 18, 28] })
  }, crossSection)
  await page.getByRole('button', { name: 'Tools', exact: true }).hover()
  const initialPreview = page.waitForResponse(response => response.url().includes('/corner/preview'))
  await page.locator('#menu-tools-corner').click()
  const popup = page.locator('.tool-popup[data-tool-panel="corner-panel"]')
  await expect(popup).toBeVisible()
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().selection.level)).toBe('cluster')
  await page.mouse.move(800, 700)
  const candidates = await beadCandidates(page)
  expect(candidates.length).toBeGreaterThan(0)
  for (const point of candidates.slice(0, 25)) {
    await page.mouse.click(point.x, point.y)
    if (await page.locator('#corner-positionBp').isEnabled()) break
  }
  await expect(page.locator('#corner-positionBp')).toBeEnabled()
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().selection.level)).toBe('default')
  await expect(page.locator('#corner-positionBp')).toHaveAttribute('step', crossSection.step)
  await expect.poll(() => page.evaluate(() => !!window.__nadocTest.scene.getObjectByName('corner-cylinder-preview')),
    { timeout: 2000 }).toBe(true)
  try {
    await waitReady(popup)
  } catch (error) {
    console.log('Corner first-preview status:', await popup.locator('[role=status]').textContent())
    console.log('Corner console errors:', errors)
    throw error
  }
  const initialEvents = (await (await initialPreview).text()).trim().split('\n').map(line => JSON.parse(line))
  console.log(`Corner ${crossSection.name} cold server preview seconds:`,
    initialEvents.filter(event => event.type === 'progress').at(-1)?.elapsed_seconds)
  await expect.poll(() => page.evaluate(() => !!window.__nadocTest.scene.getObjectByName('corner-full-preview'))).toBe(true)
  // Exercise native number-control stepping from off-grid typed values. A
  // step attribute alone snaps to a multiple instead of adding the requested step.
  const position = page.locator('#corner-positionBp')
  await position.fill('83')
  await position.press('ArrowUp')
  await expect(position).toHaveValue(String(83 + Number(crossSection.step)))
  await page.locator('#corner-positionNm').press('ArrowDown')
  await expect(position).toHaveValue('83')
  await page.locator('#corner-angleDeg').fill('85')
  await page.locator('#corner-angleDeg').press('ArrowUp')
  await expect(page.locator('#corner-angleDeg')).toHaveValue('100')
  await page.locator('#corner-directionDeg').fill('7')
  await page.locator('#corner-directionDeg').press('ArrowUp')
  await expect(page.locator('#corner-directionDeg')).toHaveValue('22')
  await position.fill('84')
  await page.locator('#corner-angleDeg').fill('90')
  await page.locator('#corner-directionDeg').fill('0')
  await waitReady(popup)
  const before = await page.evaluate(() => window.__nadocTest.store.getState().currentDesign.feature_log.length)
  const oldSeams = await page.evaluate(() => window.__nadocTest.store.getState().currentDesign.forced_ligations.length)
  await page.evaluate(() => {
    const fetch = window.fetch
    window.fetch = async (...args) => {
      const response = await fetch(...args)
      if (!String(args[0]).includes('/corner/preview')) return response
      const getReader = response.body.getReader.bind(response.body)
      response.body.getReader = (...readerArgs) => {
        const reader = getReader(...readerArgs), read = reader.read.bind(reader)
        reader.read = async () => {
          const result = await read()
          if (result.value) window.__cornerLastRead = performance.now()
          return result
        }
        return reader
      }
      return response
    }
    const input = document.getElementById('corner-directionDeg')
    input.addEventListener('input', () => {
      const started = performance.now()
      const status = document.querySelector('#corner-panel [role=status]')
      const observer = new MutationObserver(() => {
        if (status.textContent !== 'Full corner preview ready.') return
        observer.disconnect()
        window.__cornerMeasured = { inputToReadyMs: performance.now() - started,
          lastChunkToReadyMs: performance.now() - window.__cornerLastRead }
        requestAnimationFrame(() => requestAnimationFrame(() => {
          window.__cornerMeasured.inputToPaintMs = performance.now() - started
          window.__cornerMeasured.transportMs = performance.getEntriesByType('resource')
            .filter(entry => entry.name.includes('/corner/preview')).at(-1)?.duration
        }))
      })
      observer.observe(status, { childList: true, characterData: true, subtree: true })
    }, { once: true, capture: true })
  })
  const started = Date.now()
  await page.locator('#corner-directionDeg').fill('15')
  await waitReady(popup)
  console.log(`Corner ${crossSection.name} parameter-to-Full preview: ${Date.now() - started} ms`)
  await page.waitForFunction(() => window.__cornerMeasured?.inputToPaintMs != null)
  console.log('Corner browser timing:', await page.evaluate(() => window.__cornerMeasured))
  await page.evaluate(() => window.__nadocTest.applyCameraPoseForTest({
    target: [12, 4, 18], position: [65, 65, 95],
  }))
  const screenshot = testInfo.outputPath('corner-preview.png')
  await page.screenshot({ path: screenshot })
  console.log(`Corner visual check: ${screenshot}`)
  await popup.locator('.def-btn.primary').click()
  await expect(popup).not.toBeVisible({ timeout: 30_000 })
  const after = await page.evaluate(() => {
    const d = window.__nadocTest.store.getState().currentDesign
    return { features: d.feature_log.length, kind: d.feature_log.at(-1).op_kind,
      seams: d.forced_ligations.length, helices: d.helices.length }
  })
  const count = crossSection.cells.length
  expect(after).toEqual({ features: before + 1, kind: 'corner', seams: oldSeams + 2 * count - (crossSection.nick ? 1 : 0), helices: 2 * count })
  const fittedDisplay = await page.evaluate(() => {
    const state = window.__nadocTest.store.getState()
    const unique = new Map()
    for (const nuc of state.currentGeometry) for (const [id, rows] of Object.entries(nuc.corner_inserts ?? {})) unique.set(id, rows)
    const expected = [...unique.values()].flatMap(rows => Object.values(rows).map(row => row.backbone_position))
    const mesh = window.__nadocTest.scene.getObjectByName('xoverExtraBeads')
    const actual = []
    for (let i = 0; i < (mesh?.count ?? 0); i++) {
      actual.push(Array.from(mesh.instanceMatrix.array.slice(16*i + 12, 16*i + 15)))
    }
    return { seams: unique.size, allPlaced: expected.length > 0 && expected.every(point =>
      actual.some(value => Math.hypot(...value.map((v, i) => v-point[i])) < 1e-5)) }
  })
  expect(fittedDisplay).toEqual({ seams: after.seams - oldSeams, allPlaced: true })
  console.log(`Corner ${crossSection.name}: Apply and rendered seam positions verified`)
  await page.evaluate(async () => (await import('/src/api/client.js')).undo())
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentDesign.helices.length)).toBe(count)
  await page.evaluate(async () => (await import('/src/api/client.js')).redo())
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentDesign.helices.length)).toBe(2 * count)
  console.log(`Corner ${crossSection.name}: undo/redo verified`)
  const featureId = await page.evaluate(() => window.__nadocTest.store.getState().currentDesign.feature_log.at(-1).id)
  await page.locator('#fl-list button[title^="Edit Corner:"]').last().click()
  await expect(popup.locator('h2')).toHaveText('Edit Corner')
  await expect(page.locator('#corner-angleDeg')).toHaveValue('90')
  const editedPreview = page.waitForResponse(response => response.url().includes('/corner/preview?feature_id=')
    && response.request().postDataJSON()?.angle_deg === 75)
  await page.locator('#corner-angleDeg').fill('75')
  await expect.poll(async () => ({ ready: await popup.locator('.def-btn.primary').isEnabled(),
    status: await popup.locator('[role=status]').textContent() }), { timeout: 30_000 }).toMatchObject({ ready: true })
  const editEvents = (await (await editedPreview).text()).trim().split('\n').map(line => JSON.parse(line))
  const editProgress = editEvents.filter(event => event.type === 'progress')
  expect(editProgress[0].percent).toBe(0)
  expect(editProgress.at(-1).percent).toBe(100)
  expect(editProgress.slice(0, -1).every(event => event.percent < 100)).toBe(true)
  expect(editProgress.map(event => event.percent)).toEqual(editProgress.map(event => event.percent).sort((a, b) => a - b))
  expect(editProgress.some(event => event.remaining_seconds > 0)).toBe(true)
  expect(editEvents.at(-1).type).toBe('ready')
  await popup.locator('.def-btn.primary').click()
  await expect(popup).not.toBeVisible({ timeout: 30_000 })
  expect(await page.evaluate(() => {
    const d = window.__nadocTest.store.getState().currentDesign
    return { id: d.feature_log.at(-1).id, angle: d.feature_log.at(-1).params.angle_deg,
      count: d.feature_log.length, helices: d.helices.length }
  })).toEqual({ id: featureId, angle: 75, count: before + 1, helices: 2 * count })
  console.log(`Corner ${crossSection.name}: history edit verified`)
  // Delete/revert (including undo after each), saved-file reopen and independent
  // replay have their own focused scenario in corner_persistence.spec.js.
  expect(errors).toEqual([])
})
