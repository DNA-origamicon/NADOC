import { test, expect } from '@playwright/test'
import { readFileSync, rmSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { assemblyInstanceCandidates } from './helpers/scene_harness.js'

const TEST_NAME = '__e2e__BigO-poly'
const TEST_FILE = `${TEST_NAME}.nass`
const TEST_PATH = resolve(process.cwd(), '..', 'workspace', TEST_FILE)

test.beforeAll(() => {
  const source = JSON.parse(readFileSync(resolve(process.cwd(), '..', 'workspace', 'BigO-poly.nass'), 'utf8'))
  source.metadata.name = TEST_NAME
  writeFileSync(TEST_PATH, JSON.stringify(source, null, 2))
})
test.afterAll(() => rmSync(TEST_PATH, { force: true }))

test('BigO assembly loads with organized right-sidebar controls', async ({ page }) => {
  test.setTimeout(120_000)
  const errors = []
  page.on('pageerror', error => errors.push(String(error)))

  const assemblyUrl = `/?doc=__e2e__bigo-sidebar&open=${TEST_FILE}&open-type=assembly`
  await page.goto(assemblyUrl)
  await page.waitForFunction(() => window.__NADOC_DBG__?.store.getState().assemblyActive)
  await expect(page.locator('#welcome-screen')).not.toBeVisible()

  const assemblyTab = page.locator('.right-tab-btn[data-tab="assembly"]')
  await expect(assemblyTab).toBeVisible()
  await expect(assemblyTab).toHaveClass(/active/)
  await expect(page.locator('#right-tab-content-assembly')).toBeVisible()
  await expect(page.locator('#right-tab-content-properties')).toBeHidden()

  await expect(page.locator('#assembly-panel-name')).toHaveText(TEST_NAME)
  await expect(page.locator('#assembly-instance-list [data-instance-id]')).toHaveCount(1)
  await expect(page.locator('#assembly-instance-list')).toContainText('BigO')
  await expect(page.locator('#polymerize-panel')).toBeVisible()
  await expect(page.locator('#polymerize-panel-body')).toBeHidden()
  await expect(page.locator('#assembly-overhang-panel')).toBeHidden()
  await expect(page.locator('#assembly-oconn-panel')).toBeHidden()

  await page.locator('.right-tab-btn[data-tab="visualization"]').click()
  await expect(page.locator('#coloring-options-section')).toBeVisible()
  await expect(page.locator('#repr-color-strand')).toBeEnabled()
  await expect(page.locator('#repr-color-overhang-only')).toBeEnabled()
  await expect(page.locator('#repr-color-base')).toBeDisabled()
  await page.locator('#repr-color-overhang-only').click()
  await expect.poll(() => page.evaluate(
    () => window.__NADOC_DBG__.store.getState().coloringMode,
  )).toBe('overhang-only')

  await page.locator('.right-tab-btn[data-tab="overhangs"]').click()
  await expect(page.locator('#assembly-panel')).toBeHidden()
  await expect(page.locator('#assembly-overhang-panel')).toBeVisible()
  await expect(page.locator('#assembly-oconn-panel')).toBeVisible()

  await page.waitForFunction(() => {
    const box = window.__NADOC_DBG__?.assemblyRenderer?.getBoundingBox?.()
    return box && !box.isEmpty() && Number.isFinite(box.min.x) && Number.isFinite(box.max.x)
  }, null, { timeout: 45_000 })

  // Exercise the user's real entry point while Overhangs is active: right-click
  // the rendered part, choose Polymerize, and confirm both the panel handoff and
  // the periodic-chain mutation work end to end.
  const candidates = await assemblyInstanceCandidates(page)
  expect(candidates.length).toBeGreaterThan(0)
  await page.mouse.click(candidates[0].x, candidates[0].y, { button: 'right' })
  await page.getByText('Polymerize…', { exact: true }).click()

  await expect(assemblyTab).toHaveClass(/active/)
  await expect(page.locator('#polymerize-panel')).toBeVisible()
  await expect(page.locator('#poly-selection')).toContainText('Periodic: BigO')
  await expect(page.locator('#poly-go-btn')).toBeEnabled()
  await page.locator('#poly-go-btn').click()
  await expect.poll(async () => page.evaluate(
    () => window.__NADOC_DBG__.store.getState().currentAssembly?.instances?.length,
  ), { timeout: 45_000 }).toBe(3)
  await expect(page.locator('#poly-status')).toContainText('Chain extended to 3')

  // Autosave must serialize both the result and its snapshot-bearing feature
  // entry. Poll the workspace file through the real API before reloading.
  await expect.poll(() => page.evaluate(async file => {
    const api = await import('/src/api/client.js')
    const saved = await api.getLibraryFileContent(file)
    const assembly = JSON.parse(saved.content)
    return {
      count: assembly.instances_v2?.length ?? assembly.instances?.length,
      op: assembly.feature_log?.at(-1)?.op_kind,
      hasPost: !!assembly.feature_log?.at(-1)?.post_state_gz_b64,
    }
  }, TEST_FILE), { timeout: 15_000 }).toEqual({
    count: 3, op: 'assembly-polymerize-periodic', hasPost: true,
  })

  await page.goto(assemblyUrl)
  await page.waitForFunction(() => window.__NADOC_DBG__?.store.getState().assemblyActive)
  await expect(page.locator('#assembly-instance-list [data-instance-id]')).toHaveCount(3)
  await expect.poll(() => page.evaluate(() => {
    const assembly = window.__NADOC_DBG__.store.getState().currentAssembly
    return [assembly?.feature_log?.at(-1)?.op_kind, assembly?.feature_log_cursor]
  })).toEqual(['assembly-polymerize-periodic', -1])

  // Reload cleared the in-memory undo deque. Calling the same client actions
  // used by Ctrl-Z/Ctrl-Y proves durable undo/redo is reconstructed from the
  // persisted feature entry without depending on browser focus.
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    await api.undoAssembly()
  })
  await expect(page.locator('#assembly-instance-list [data-instance-id]')).toHaveCount(1)
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    await api.redoAssembly()
  })
  await expect(page.locator('#assembly-instance-list [data-instance-id]')).toHaveCount(3)

  await page.locator('#polymerize-panel-heading').click()
  await expect(page.locator('#polymerize-panel')).toBeVisible()
  await expect(page.locator('#polymerize-panel-body')).toBeHidden()
  await expect.poll(() => page.evaluate(() => {
    const state = JSON.parse(localStorage.getItem('nadoc.leftSidebar.sections.v1') || '{}')
    return state.right?.['polymerize-panel']
  })).toBe(true)

  expect(errors).toEqual([])
})
