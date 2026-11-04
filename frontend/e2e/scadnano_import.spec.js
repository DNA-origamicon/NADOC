import { test, expect } from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'
import { trackConsoleErrors } from './helpers/scene_harness.js'

// All saves use __e2e__ names inside the launcher's private workspace. Browser
// profiles/localStorage, Vite cache and reports also live under its owned root;
// its finally closes processes and deletes that root on every outcome.
test('scadnano pinned import: menu, downstream edit, undo and saved cold replay', async ({ page, request }) => {
  const root = process.env.NADOC_HISTORY_E2E_ROOT
  if (!root) throw new Error('Use the isolated history launcher')
  const doc = '__e2e__history-bend'
  const name = '__e2e__scadnano-pinned'
  const file = path.join(root, 'workspace', `${name}.nadoc`)
  const headers = { 'X-NADOC-Doc': doc }
  const errors = trackConsoleErrors(page)
  const content = JSON.stringify({ version: '0.19.0', grid: 'square', name,
    helices: [{ grid_position: [0, 0], max_offset: 16 }, { grid_position: [1, 0], max_offset: 16 }],
    strands: [
      { is_scaffold: true, domains: [{ helix: 0, forward: true, start: 0, end: 8 },
        { helix: 1, forward: false, start: 0, end: 8 }] },
      { color: '#ff0000', domains: [{ helix: 0, forward: false, start: 0, end: 8 },
        { helix: 1, forward: true, start: 0, end: 8 }] },
    ] })
  let primary = false
  try {
    await page.goto(`/?doc=${doc}`)
    await page.waitForFunction(() => Boolean(window.__nadocTest?.store))
    await page.locator('#menu-item-import > button').click()
    const picker = page.waitForEvent('filechooser')
    await page.locator('#menu-file-import-scadnano').click()
    const imported = page.waitForResponse(r => new URL(r.url()).pathname === '/api/design/import/scadnano')
    await (await picker).setFiles({ name: `${name}.sc`, mimeType: 'application/json', buffer: Buffer.from(content) })
    await page.locator('.origami-import-options').getByRole('button', { name: 'Import design', exact: true }).click()
    const response = await imported
    expect(response.ok(), await response.text()).toBe(true)
    expect((await response.json()).import_history.status).toBe('reproduced_import')
    await expect(page.getByText('Save Part As', { exact: true })).toBeVisible()
    await expect(page.getByPlaceholder('filename', { exact: true })).toHaveValue(name)
    await page.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(page.getByText('Save Part As', { exact: true })).not.toBeVisible()
    await expect.poll(async () => fs.access(file).then(() => true, () => false)).toBe(true)
    await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentGeometry?.length)).toBe(32)
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    await expect(page.getByText(/F1: Import 1/).first()).toBeVisible()

    const before = await page.evaluate(() => {
      const s = window.__nadocTest.store.getState()
      return { design: s.currentDesign, geometry: s.currentGeometry }
    })
    const changed = await page.evaluate(async () => {
      const api = await import('/src/api/client.js')
      const s = window.__nadocTest.store.getState()
      const nick = await api.addNick({ helixId: s.currentDesign.helices[0].id, bpIndex: 3, direction: 'FORWARD' })
      if (!nick) throw new Error('Native downstream nick failed')
      const result = await api.editFeature(0, { name_override: '__e2e__scadnano-edited' })
      if (!result) throw new Error('Import input edit failed')
      return window.__nadocTest.store.getState().currentDesign
    })
    expect(changed.metadata.name).toBe('__e2e__scadnano-edited')
    expect(changed.helices).toEqual(before.design.helices)
    expect(changed.feature_log).toHaveLength(2)
    const proof = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers })
    expect(proof.ok(), await proof.text()).toBe(true)
    expect((await proof.json()).status).toBe('reproduced_import')
    await page.evaluate(async () => {
      const api = await import('/src/api/client.js')
      if (!await api.undo()) throw new Error('Undo failed')
    })
    await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentDesign.metadata.name)).toBe(name)
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      if (!await api.redo()) throw new Error('Redo failed')
      if (!await api.saveDesignAs(file, true)) throw new Error('Save failed')
      if (!await api.loadDesign(file)) throw new Error('Reopen failed')
    }, file)
    const saved = JSON.parse(await fs.readFile(file, 'utf8'))
    expect(saved.feature_log[0].op_kind).toBe('scadnano-import')
    expect(saved.feature_log[0].params.loss_policy).toBe('existing-importer-v1')
    const after = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers })
    expect(after.ok(), await after.text()).toBe(true)
    expect((await after.json()).status).toBe('reproduced_import')
    expect(errors, errors.join('\n')).toEqual([])
  } catch (error) { primary = true; throw error }
  finally {
    await page.close()
    const response = await request.delete(`http://127.0.0.1:8004/api/documents/${doc}`)
    if (!response.ok() && !primary) throw new Error(`Cleanup HTTP ${response.status()}`)
  }
})


test('scadnano optional relaxation retains recorded poses and cold replay', async ({ page, request }) => {
  const root = process.env.NADOC_HISTORY_E2E_ROOT
  if (!root) throw new Error('Use the isolated history launcher')
  const doc = '__e2e__history-bend'
  const name = '__e2e__relaxed-import'
  const file = path.join(root, 'workspace', `${name}.nadoc`)
  const headers = { 'X-NADOC-Doc': doc }
  const errors = trackConsoleErrors(page)
  const content = JSON.stringify({ version: '0.19.0', grid: 'square', name,
    helices: [{ grid_position: [0, 0], max_offset: 32 }, { grid_position: [9, 0], max_offset: 32 }],
    strands: [{ is_scaffold: true, domains: [
      { helix: 0, forward: true, start: 0, end: 32 },
      { helix: 1, forward: false, start: 0, end: 32 },
    ] }] })
  try {
    await page.goto(`/?doc=${doc}`)
    await page.waitForFunction(() => Boolean(window.__nadocTest?.store))
    await page.locator('#menu-item-import > button').click()
    const picker = page.waitForEvent('filechooser')
    await page.locator('#menu-file-import-scadnano').click()
    await (await picker).setFiles({ name: `${name}.sc`, mimeType: 'application/json', buffer: Buffer.from(content) })
    const options = page.locator('.origami-import-options')
    await expect(options.locator('input')).not.toBeChecked()
    await options.locator('input').check()
    const imported = page.waitForResponse(r => new URL(r.url()).pathname === '/api/design/import/scadnano')
    await options.getByRole('button', { name: 'Import design', exact: true }).click()
    const response = await imported
    expect(response.ok(), await response.text()).toBe(true)
    const result = await response.json()
    expect(result.relaxation.status).toBe('applied')
    expect(result.import_history.status).toBe('reproduced_import')
    expect(result.design.feature_log.length).toBeGreaterThan(1)
    await expect(page.getByText('Save Part As', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(page.getByText('Save Part As', { exact: true })).not.toBeVisible()
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      if (!await api.saveDesignAs(file, true)) throw new Error('Save failed')
      if (!await api.loadDesign(file)) throw new Error('Reopen failed')
    }, file)
    const saved = JSON.parse(await fs.readFile(file, 'utf8'))
    expect(saved.feature_log).toEqual(result.design.feature_log)
    const proof = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers })
    expect(proof.ok(), await proof.text()).toBe(true)
    expect((await proof.json()).status).toBe('reproduced_import')
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    if (process.env.NADOC_FINAL_REVIEW_IMAGE) await page.screenshot({ path: process.env.NADOC_FINAL_REVIEW_IMAGE })
    expect(errors, errors.join('\n')).toEqual([])
  } finally {
    await page.close()
    await request.delete(`http://127.0.0.1:8004/api/documents/${doc}`)
  }
})
