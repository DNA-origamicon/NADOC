import { test, expect } from '@playwright/test'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import path from 'node:path'

test.skip(!process.env.NADOC_PHYSICAL_VR_TEST, 'explicit physical runtime opt-in')
const base = process.env.NADOC_E2E_API_BASE
const execFileAsync = promisify(execFile)
let pid
test.afterEach(async ({ request }) => {
  const status = await (await request.get(`${base}/api/vr/status`)).json()
  if (pid && status.pid === pid) {
    await request.post(`${base}/api/vr/stop`)
    await expect.poll(async () => (await (await request.get(`${base}/api/vr/status`)).json()).running,
      { timeout: 20_000 }).toBe(false)
  }
})

test('VR Sweep free-draws an S, edits fitted points, and edits and undo/redoes desktop history', async ({ page, request }) => {
  await page.setViewportSize({ width: 1600, height: 1000 })
  // Observation hold outside measured controller motion: retain the real pending UI.
  await page.route('**/api/design/sweep', async route => {
    await new Promise(resolve => setTimeout(resolve, 10_000))
    await route.continue()
  })
  const errors = []
  const responses = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('response', async response => {
    if (/\/api\/vr\/|\/design\/(sweep|features\/|undo|redo)/.test(response.url())) {
      try { responses.push({ url: response.url(), status: response.status(), body: await response.text() }) } catch {}
    }
  })
  await page.goto('/?test=1&doc=__e2e__vr-sweep&scrywrite=transactions')
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', '__e2e__VR Sweep')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  await page.getByRole('button', { name: 'Help', exact: true }).click()
  const launch = page.waitForResponse(response => response.url().endsWith('/api/vr/launch')
    && response.request().method() === 'POST', { timeout: 100_000 })
  await page.click('#menu-help-view-vr')
  const launched = await launch
  expect(launched.ok(), await launched.text()).toBe(true)
  let status
  await expect.poll(async () => {
    status = await (await request.get(`${base}/api/vr/status`)).json()
    if (status.pid) pid = status.pid
    return status.running && !!status.scrywrite_socket
  }, { timeout: 30_000 }).toBe(true)
  const evidence = process.env.NADOC_VR_SWEEP_EVIDENCE || path.join(process.env.SCRYWRITE_TEST_WORKSPACE, 'sweep-evidence')
  try {
    const result = await execFileAsync(path.resolve('..', '.venv/bin/python'), ['-m', 'tools.vr_workflows.sweep_probe', status.scrywrite_socket, evidence], {
      cwd: path.resolve('..'), encoding: 'utf8', timeout: 240_000, env: process.env, maxBuffer: 4*1024*1024,
    })
    if (result.stdout) console.log(result.stdout)
    if (result.stderr) console.log(result.stderr)
  } finally {
    await page.waitForTimeout(200)
    mkdirSync(evidence, { recursive: true })
    writeFileSync(path.join(evidence, 'browser-responses.json'), JSON.stringify({ errors, responses }, null, 2))
  }
  const finalDraft = JSON.parse(readFileSync(path.join(evidence, 'ready-to-confirm.json'), 'utf8')).sweep
  const readDesign = () => page.evaluate(async () => {
    const state = (await import('/src/state/store.js')).store.getState()
    const history = await (await import('/src/api/client.js'))._request('GET', '/design/feature-log/full')
    return { ...state.currentDesign, feature_log: history.feature_log, axes: state.currentHelixAxes }
  })
  const design = await readDesign()
  expect(design.helices).toHaveLength(2)
  expect(design.feature_log).toHaveLength(1)
  expect(design.feature_log[0]).toMatchObject({ feature_type: 'snapshot', op_kind: 'sweep' })
  expect(design.feature_log[0].params.points_nm).toHaveLength(finalDraft.points_nm.length)
  for (let i = 0; i < finalDraft.points_nm.length; i++)
    for (let axis = 0; axis < 3; axis++)
      expect(design.feature_log[0].params.points_nm[i][axis]).toBeCloseTo(finalDraft.points_nm[i][axis], 3)
  expect(design.deformations).toHaveLength(1)
  expect(design.deformations[0].type).toBe('sweep')
  expect(design.feature_log[0].design_snapshot_gz_b64).toBeTruthy()
  expect(design.feature_log[0].post_state_gz_b64).toBeTruthy()

  // Exit through the normal UI before desktop editing so background rendering
  // resumes and the saved images show the actual editable curve and preview.
  await page.getByRole('button', { name: 'Help', exact: true }).click()
  await expect(page.locator('#menu-help-view-vr')).toHaveAttribute('aria-pressed', 'true')
  const stopped = page.waitForResponse(response => response.url().endsWith('/api/vr/stop')
    && response.request().method() === 'POST')
  await page.click('#menu-help-view-vr')
  expect((await stopped).ok()).toBe(true)
  await expect(page.locator('#menu-help-view-vr')).toHaveAttribute('aria-pressed', 'false')
  await expect.poll(async () => (await (await request.get(`${base}/api/vr/status`)).json()).running).toBe(false)
  // Give the floating editor its own space beside the curve. Reframe after
  // opening the feature log so both the entire S and its controls stay visible.
  await page.setViewportSize({ width: 1920, height: 1080 })
  const featureRow = page.locator('#feature-log-panel-body [data-fl-row="1"]')
  if (!await featureRow.isVisible()) await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
  await expect(featureRow).toBeVisible()
  await expect(featureRow).toContainText(design.feature_log[0].label)
  await page.locator('#canvas').focus()
  await page.keyboard.press('f')

  const stages = []
  const axisSamples = current => current.helices.map(h => ({ id: h.id, samples: current.axes?.[h.id]?.samples }))
  const snapshot = async (name, current) => {
    current ??= await readDesign()
    stages.push({ name, helices: current.helices.map(h => h.id), samples: axisSamples(current),
      features: current.feature_log.map(e => ({ id: e.id, op_kind: e.op_kind, params: e.params })) })
    writeFileSync(path.join(evidence, 'desktop-history.json'), JSON.stringify(stages, null, 2))
    if (process.env.NADOC_VR_DEMO === '1')
      await page.waitForTimeout(Number(process.env.NADOC_VR_DEMO_HOLD || 3) * 1000)
    await page.screenshot({ path: path.join(evidence, `${name}.png`) })
  }
  await snapshot('desktop-created', design)

  // Open the real Feature Log editor; no API or test-only mutation is used.
  await featureRow.getByRole('button', { name: '✎' }).click()
  await expect(page.locator('#sweep-panel')).toBeVisible()
  await expect(page.locator('#sweep-step')).toContainText('2/2')
  const pointIndex = Math.max(1, Math.floor(finalDraft.points_nm.length / 2))
  await page.getByRole('option', { name: new RegExp(`^Point ${pointIndex} `) }).click()
  const xInput = page.getByRole('spinbutton', { name: 'Point X (nm)' })
  expect(Number(await xInput.inputValue())).toBe(Math.trunc(finalDraft.points_nm[pointIndex][0]*100)/100)
  const editedX = Number((Number(await xInput.inputValue()) + 3).toFixed(4))
  await xInput.fill(String(editedX))
  await expect(page.locator('#sweep-apply')).toBeEnabled()
  await expect(page.locator('#sweep-status')).toContainText('bp per helix')
  await snapshot('desktop-edit-preview')
  const editResponse = page.waitForResponse(response => response.url().endsWith('/design/features/0/edit')
    && response.request().method() === 'POST')
  await page.click('#sweep-apply')
  expect((await editResponse).ok()).toBe(true)
  await expect(page.locator('#sweep-panel')).not.toBeVisible()
  const edited = await readDesign()
  const featureId = design.feature_log[0].id
  const assertFeature = (current, points) => {
    expect(current.feature_log).toHaveLength(1)
    expect(current.feature_log[0].id).toBe(featureId)
    expect(current.feature_log[0].params.sweep_id).toBe(design.feature_log[0].params.sweep_id)
    expect(current.feature_log[0].params.points_nm).toEqual(points)
    expect(current.helices.map(h => h.id)).toEqual(design.helices.map(h => h.id))
    expect(current.deformations).toHaveLength(1)
    expect(current.deformations[0].params.points_nm).toEqual(points)
  }
  const editedPoints = structuredClone(design.feature_log[0].params.points_nm)
  editedPoints[pointIndex][0] = editedX
  assertFeature(edited, editedPoints)
  for (const helix of design.helices) {
    expect(design.axes?.[helix.id]?.samples.length).toBeGreaterThan(2)
    expect(edited.axes?.[helix.id]?.samples).not.toEqual(design.axes[helix.id].samples)
  }
  await snapshot('desktop-edited', edited)

  const historyAction = async action => {
    await page.mouse.move(900, 600)
    await page.locator('#menu-item-edit > button').hover()
    await expect(page.locator(`#menu-edit-${action}`)).toBeVisible()
    const response = page.waitForResponse(r => r.url().endsWith(`/design/${action}`)
      && r.request().method() === 'POST')
    await page.click(`#menu-edit-${action}`)
    expect((await response).ok()).toBe(true)
  }
  await historyAction('undo')
  await expect.poll(async () => (await readDesign()).feature_log[0]?.params.points_nm)
    .toEqual(design.feature_log[0].params.points_nm)
  const undoEdit = await readDesign()
  assertFeature(undoEdit, design.feature_log[0].params.points_nm)
  expect(axisSamples(undoEdit)).toEqual(axisSamples(design))
  await snapshot('desktop-undo-edit', undoEdit)
  await historyAction('undo')
  await expect.poll(async () => (await readDesign()).helices.length).toBe(0)
  const undoCreation = await readDesign()
  expect(undoCreation.feature_log).toHaveLength(0)
  expect(undoCreation.deformations).toHaveLength(0)
  await snapshot('desktop-undo-creation', undoCreation)
  await historyAction('redo')
  await expect.poll(async () => (await readDesign()).helices.length).toBe(2)
  const redoCreation = await readDesign()
  assertFeature(redoCreation, design.feature_log[0].params.points_nm)
  expect(axisSamples(redoCreation)).toEqual(axisSamples(design))
  await snapshot('desktop-redo-creation', redoCreation)
  await historyAction('redo')
  await expect.poll(async () => (await readDesign()).feature_log[0]?.params.points_nm).toEqual(editedPoints)
  const redoEdit = await readDesign()
  assertFeature(redoEdit, editedPoints)
  expect(axisSamples(redoEdit)).toEqual(axisSamples(edited))
  await snapshot('desktop-redo-edit', redoEdit)
  writeFileSync(path.join(evidence, 'browser-responses.json'), JSON.stringify({ errors, responses }, null, 2))
  expect(errors).toEqual([])
})
