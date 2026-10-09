import { test, expect } from '@playwright/test'
import { loadScaffoldedPart, trackConsoleErrors } from './helpers/scene_harness.js'

// Real editor commands and backend assessment; no simulation is launched.
// Persistence: __e2e__ readiness part + its revision store, cleaned on all exits
// by global-teardown. Browser reports/traces use artifact-cleanup-reporter.
const API = `${process.env.NADOC_E2E_API_BASE || 'http://127.0.0.1:8002'}/api`
const badge = page => page.locator('[data-role="design-readiness"]')
const trigger = page => page.locator('[data-role="readiness-trigger"]')

async function refreshDesign(page, doc) {
  await page.evaluate(docId => {
    const channel = new BroadcastChannel('nadoc-design')
    channel.postMessage({ type: 'design-changed', source: 'readiness-e2e', docId })
    channel.close()
  }, doc)
}

async function expectAnchored(page, host) {
  await expect.poll(async () => {
    const canvas = await page.locator(host).boundingBox()
    const pill = await badge(page).boundingBox()
    return canvas && pill ? Math.abs(canvas.x + canvas.width - pill.x - pill.width - 12) : 999
  }).toBeLessThan(2)
}

test('readiness commands, shared views, resizing and simulation navigation', async ({ page, context }) => {
  test.setTimeout(90_000)
  const errors = trackConsoleErrors(page)
  const doc = `e2e-readiness-${Date.now()}`
  const headers = { 'X-NADOC-Doc': doc }
  await page.goto(`/?doc=${doc}`)
  await expect(page.locator('#welcome-screen')).toBeVisible()
  await expect(badge(page)).not.toBeVisible()
  await loadScaffoldedPart(page, { doc, name: 'design_readiness' })
  const { design } = await (await page.request.get(`${API}/design`, { headers })).json()
  const strand = design.strands.find(s => s.strand_type === 'scaffold')
  const scaffold = strand.domains[0]
  const direction = scaffold.direction === 'FORWARD' ? 'REVERSE' : 'FORWARD'
  const added = await page.request.post(`${API}/design/strands`, {
    headers,
    data: { strand_type: 'staple', domains: [{ helix_id: scaffold.helix_id,
      start_bp: direction === 'FORWARD' ? 0 : 31,
      end_bp: direction === 'FORWARD' ? 31 : 0, direction }] },
  })
  expect(added.ok()).toBe(true)
  await refreshDesign(page, doc)
  await expect(trigger(page)).toContainText('2/4 readiness')
  await expect(badge(page)).toHaveAttribute('data-state', 'incomplete')
  await expectAnchored(page, '#canvas-area')
  await page.locator('#right-tab-toggle').click()
  await expectAnchored(page, '#canvas-area')
  await page.locator('#right-tab-toggle').click()
  await expectAnchored(page, '#canvas-area')
  await trigger(page).hover()
  await expect(page.locator('.design-readiness__popover')).toBeVisible()
  await expect(page.locator('[data-step-id="scaffold_routing"] kbd')).toHaveText('1')
  await expect(page.locator('[data-step-id="staple_routing"] kbd')).toHaveText('2')
  await expect(page.locator('[data-step-id="scaffold_sequence"] kbd')).toHaveText('5')
  await expect(page.locator('[data-step-id="staple_sequences"] kbd')).toHaveText('6')
  await page.locator('[data-action="scaffold_sequence"]').click()
  await expect(page.locator('#assign-scaffold-modal-body')).toBeVisible()
  await page.getByRole('button', { name: 'Apply', exact: true }).click()
  await expect(trigger(page)).toContainText('3/4 readiness')

  // Complete the last real command in the separate cadnano host.
  const pathview = await context.newPage()
  const pathErrors = trackConsoleErrors(pathview)
  await pathview.goto(`/cadnano-editor.html?doc=${doc}`)
  await expect(trigger(pathview)).toContainText('3/4 readiness')
  await trigger(pathview).hover()
  await pathview.locator('[data-action="staple_sequences"]').click()
  await expect(trigger(pathview)).toContainText('4/4 readiness')
  await expect(badge(pathview)).toHaveAttribute('data-state', 'simulation_recommended')
  await expect(trigger(pathview)).toContainText('Sim recommended')
  await expectAnchored(pathview, '#pathview-container')
  await pathview.setViewportSize({ width: 900, height: 600 })
  await expectAnchored(pathview, '#pathview-container')
  await trigger(pathview).hover()
  const panel = await pathview.locator('.design-readiness__panel').boundingBox()
  const host = await pathview.locator('#pathview-container').boundingBox()
  expect(panel.y + panel.height).toBeLessThanOrEqual(host.y + host.height)

  // A standalone pathview has no opener: the fallback must hydrate the existing
  // backend document and reveal controls, not create a fresh document or job.
  const popupPromise = pathview.waitForEvent('popup')
  await pathview.locator('[data-action="simulation"]').click()
  const simulationPage = await popupPromise
  const simulationErrors = trackConsoleErrors(simulationPage)
  await expect(simulationPage.locator('#welcome-screen')).not.toBeVisible()
  await expect(trigger(simulationPage)).toContainText('Sim recommended')
  await expect(simulationPage.locator('#tab-content-dynamics')).toBeVisible()
  expect(new URL(simulationPage.url()).searchParams.get('doc')).toBe(doc)

  // Only the response is substituted to exercise the final visual state; the
  // backend suite checks actual job provenance, stages, staleness and failures.
  await simulationPage.route('**/api/design/readiness', async route => {
    const response = await route.fetch()
    const report = await response.json()
    await route.fulfill({ json: { ...report, state: 'ready', simulation: {
      complete: true, action: 'simulation', engine: 'mrdna', kind: 'Fine',
      detail: 'Matching Fine simulation completed (visual test fixture).',
    } } })
  })
  await simulationPage.evaluate(() => window.dispatchEvent(new Event('nadoc:sim-jobs-changed')))
  await expect(badge(simulationPage)).toHaveAttribute('data-state', 'ready')
  await expect(badge(simulationPage)).not.toBeVisible()
  await simulationPage.unroute('**/api/design/readiness')
  await simulationPage.evaluate(() => window.dispatchEvent(new Event('nadoc:sim-jobs-changed')))
  await expect(badge(simulationPage)).toHaveAttribute('data-state', 'simulation_recommended')
  await expect(badge(simulationPage)).toBeVisible()

  const sidebarClose = simulationPage.locator('#left-panel .sidebar-close:visible')
  while (await sidebarClose.count()) await sidebarClose.first().click()
  await simulationPage.locator('#photo-tab-btn').click()
  await simulationPage.locator('#photo-lighting-enabled').check()
  await expect(badge(simulationPage)).not.toBeVisible()
  await simulationPage.locator('#photo-lighting-enabled').uncheck()
  await expect(badge(simulationPage)).toBeVisible()
  // Enter the actual video export path and cancel during preparation: no file
  // or expensive render is produced, and the overlay must restore on rejection.
  const captureVisibility = await simulationPage.evaluate(async () => {
    const { exportVideo } = await import('/src/scene/export_video.js')
    let hiddenDuringPreparation = false
    try {
      await exportVideo({ animation: {}, player: { stop() {}, play: async () => {
        hiddenDuringPreparation = document.querySelector('[data-role="design-readiness"]').hidden
        throw new Error('Intentional test cancellation')
      } } })
    } catch (error) {
      if (error.message !== 'Intentional test cancellation') throw error
    }
    return hiddenDuringPreparation
  })
  expect(captureVisibility).toBe(true)
  await expect(badge(simulationPage)).toBeVisible()

  // These views have finished their checks. Close them before deleting their
  // shared backend session so pending refreshes cannot race session teardown.
  await pathview.close()
  await page.close()
  await simulationPage.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await simulationPage.locator('#menu-file-close-session').click()
  await expect(simulationPage.locator('#welcome-screen')).toBeVisible()
  await expect(badge(simulationPage)).not.toBeVisible()

  expect(errors, errors.join('\n')).toEqual([])
  expect(pathErrors, pathErrors.join('\n')).toEqual([])
  expect(simulationErrors, simulationErrors.join('\n')).toEqual([])
})


test('extrusion needs scaffold and staple routing before readiness passes', async ({ page }) => {
  const doc = `e2e-readiness-extrusion-${Date.now()}`
  const headers = { 'X-NADOC-Doc': doc }
  await loadScaffoldedPart(page, { doc, name: 'readiness_extrusion' })
  const snapshot = await (await page.request.get(`${API}/design`, { headers })).json()
  const response = await page.request.post(`${API}/design/frame-extrusion`, {
    headers,
    data: { expected_design_id: snapshot.design.id, expected_revision: snapshot.revision,
      cells: [[2, 0], [2, 1], [3, 0], [3, 1]], length_bp: 84, plane: 'XY' },
  })
  expect(response.ok(), await response.text()).toBe(true)
  await refreshDesign(page, doc)
  await trigger(page).hover()
  for (const id of ['scaffold_routing', 'staple_routing']) {
    const step = page.locator(`[data-step-id="${id}"]`)
    await expect(step).toHaveAttribute('data-complete', 'false')
    await expect(step.locator(`[data-action="${id}"]`)).toBeEnabled()
  }
  await expect(page.locator('[data-step-id="scaffold_routing"]')).toContainText('Autoscaffold')
  await expect(page.locator('[data-step-id="staple_routing"]')).toContainText('Full Autostaple')
  await expect(page.locator('[data-step-id="topology"]')).toHaveCount(0)
  await expect(trigger(page)).toContainText('0/4 readiness')

  // Backend tests cover actual integrity failures; substitute the report here
  // to verify the negative score and the issue-only row in the browser.
  await page.route('**/api/design/readiness', async route => {
    const response = await route.fetch()
    const report = await response.json()
    await route.fulfill({ json: { ...report, integrity_penalty: -1, score: -1,
      steps: report.steps.map(step => step.id === 'topology'
        ? { ...step, complete: false, detail: 'Review invalid extensions.',
          issues: ['Extension references a missing strand.'] } : step),
    } })
  })
  await refreshDesign(page, doc)
  await expect(trigger(page)).toContainText('-1/4 readiness')
  await trigger(page).hover()
  await expect(page.locator('[data-step-id="topology"]')).toContainText('−1 point')
  await page.locator('[data-action="validation"]').click()
  await expect(page.locator('[data-readiness-issues]')).toContainText('Extension references a missing strand.')
})
