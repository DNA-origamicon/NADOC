import { test, expect } from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'
import { gunzipSync } from 'node:zlib'
import { trackConsoleErrors } from './helpers/scene_harness.js'

// Persistent inventory: __e2e__ import save/project history and optional caches
// live only in the config's temporary workspace (removed on runner exit).
// Session autosave is disabled; global teardown removes the isolated bridge key.
// Screenshots/traces live in testInfo.outputPath and are removed after inspection.
test('Pointer original-byte upload, feature history and saved part visualization', async ({ page }, testInfo) => {
  const errors = trackConsoleErrors(page)
  const root = path.resolve(import.meta.dirname, '..', '..')
  const raw = gunzipSync(await fs.readFile(path.join(root, 'tests/fixtures/cadnano_dietz_pointer.json.gz')))
  await page.goto('/?doc=__e2e__dietz-pointer')
  await page.waitForFunction(() => Boolean(window.__nadocTest?.store))
  await page.locator('#menu-item-import > button').click()
  const picker = page.waitForEvent('filechooser')
  await page.locator('#menu-file-import-cadnano').click()
  await (await picker).setFiles({ name: '__e2e__dietz-pointer.json', mimeType: 'application/json', buffer: raw })
  const imported = page.waitForResponse(r => new URL(r.url()).pathname === '/api/design/import/cadnano')
  await page.locator('.origami-import-options').getByRole('button', { name: 'Import design', exact: true }).click()
  const response = await imported
  expect(response.ok(), await response.text()).toBe(true)
  const result = await response.json()
  expect(result.import_history.status).toBe('reproduced_import')
  expect(result.design.helices).toHaveLength(82)
  expect(result.design.strands).toHaveLength(162)
  await expect(page.getByText('Save Part As', { exact: true })).toBeVisible()
  await page.getByPlaceholder('filename', { exact: true }).fill('__e2e__dietz-pointer')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByText('Save Part As', { exact: true })).not.toBeVisible()
  // Copy complete provenance into the isolated workspace: even read-only opening
  // can autosave document metadata, so never give the app the user's file path.
  let reviewPath = path.join(process.env.NADOC_WORKSPACE, '__e2e__dietz-pointer.nadoc')
  if (process.env.NADOC_POINTER_REVIEW_PATH) {
    reviewPath = path.join(process.env.NADOC_WORKSPACE, '__e2e__published-pointer.nadoc')
    await fs.copyFile(process.env.NADOC_POINTER_REVIEW_PATH, reviewPath)
  }
  await page.evaluate(async file => {
    const api = await import('/src/api/client.js')
    if (!await api.loadDesign(file)) throw new Error('Published Pointer load failed')
  }, reviewPath)
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentGeometry?.length)).toBe(15238)
  const history = await page.evaluate(() => window.__nadocTest.store.getState().currentDesign.feature_log)
  expect(history[0].op_kind).toBe('cadnano-import')
  await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
  await page.setViewportSize({ width: 1800, height: 1000 })
  // View changes only: frame the complete object after loading and panel layout.
  await page.evaluate(() => {
    const { camera, controls } = window.__nadocTest
    camera.position.set(100, 80, 130)
    controls.target.set(0, 0, 35)
    controls.update()
    document.activeElement?.blur()
  })
  await page.keyboard.press('f')
  await page.waitForTimeout(1200)
  await page.screenshot({ path: testInfo.outputPath('pointer-perspective.png') })
  expect(errors, errors.join('\n')).toEqual([])
})

test('Pointer scaffold target fits the dialog and M13 assignment uses the recorded operation', async ({ page }, testInfo) => {
  const errors = trackConsoleErrors(page)
  const source = process.env.NADOC_POINTER_REVIEW_PATH
  if (!source) throw new Error('Set NADOC_POINTER_REVIEW_PATH to the published Pointer')
  const isolated = path.join(process.env.NADOC_WORKSPACE, '__e2e__pointer-sequence.nadoc')
  await fs.copyFile(source, isolated)
  await page.goto('/?doc=__e2e__pointer-sequence')
  await page.waitForFunction(() => Boolean(window.__nadocTest?.store))
  await page.evaluate(async file => {
    const api = await import('/src/api/client.js')
    if (!await api.loadDesign(file)) throw new Error('Pointer load failed')
  }, isolated)
  await page.locator('#menu-seq-assign-scaffold').evaluate(el => el.click())
  const target = page.getByRole('combobox', { name: 'Scaffold sequence target' })
  const dialog = page.getByRole('dialog').filter({ has: target })
  await expect(target).toBeVisible()
  const value = await target.locator('option').last().getAttribute('value')
  await target.selectOption(value)
  // Reproduce the former intrinsic-width layout as a negative control.
  const formerOverflow = await target.evaluate(el => {
    const wrapper = el.closest('.scaffold-sequence-target'), body = el.closest('.modal__body')
    wrapper.classList.remove('scaffold-sequence-target')
    const overflow = body.scrollWidth - body.clientWidth
    wrapper.classList.add('scaffold-sequence-target')
    return overflow
  })
  expect(formerOverflow).toBeGreaterThan(1)
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 900 })
    const bounds = await target.evaluate(el => {
      const box = el.closest('.modal__body'), r = el.getBoundingClientRect(), b = box.getBoundingClientRect()
      return { left: r.left, right: r.right, bodyLeft: b.left, bodyRight: b.right,
        overflow: box.scrollWidth - box.clientWidth }
    })
    expect(bounds.left).toBeGreaterThanOrEqual(bounds.bodyLeft)
    expect(bounds.right).toBeLessThanOrEqual(bounds.bodyRight)
    expect(bounds.overflow).toBeLessThanOrEqual(1)
    await page.screenshot({ path: testInfo.outputPath(`scaffold-target-${width}.png`) })
  }
  await page.setViewportSize({ width: 1280, height: 900 })
  const assigned = page.waitForResponse(r => new URL(r.url()).pathname === '/api/design/assign-scaffold-sequence')
  await dialog.getByRole('button', { name: 'Apply', exact: true }).click()
  const response = await assigned
  expect(response.ok(), await response.text()).toBe(true)
  const result = await response.json()
  expect(result.padded_nt).toBe(0)
  expect(result.total_nt).toBe(7249)
  const scaffold = result.design.strands.find(s => s.strand_type === 'scaffold')
  const expected = (await fs.readFile(path.resolve(import.meta.dirname, '../../backend/core/m13mp18.txt'), 'utf8')).trim().toUpperCase()
  expect(scaffold.sequence).toBe(expected)
  expect(result.design.feature_log.at(-1).op_kind).toBe('assign-scaffold-sequence')
  expect(errors, errors.join('\n')).toEqual([])
})
