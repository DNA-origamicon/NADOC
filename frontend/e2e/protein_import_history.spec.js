import { test, expect } from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'
import { execFileSync } from 'node:child_process'
import { trackConsoleErrors } from './helpers/scene_harness.js'

// The history launcher owns and removes saves, profiles, caches and reports.
// Original PDB bytes are generated in memory; no user workspace is touched.
for (const placement of ['free', 'library']) test(`protein original-input ${placement} import and portable placement`, async ({ page, request }) => {
  const root = process.env.NADOC_HISTORY_E2E_ROOT
  if (!root) throw new Error('Use the isolated history launcher')
  const content = execFileSync('uv', ['run', '--no-sync', 'python', '-c',
    'from tests.test_protein import _SYNTH_PDB; print(_SYNTH_PDB, end="")'],
  { cwd: path.resolve(process.cwd(), '..'), timeout: 15000 })
  const doc = '__e2e__history-bend', headers = { 'X-NADOC-Doc': doc }
  const file = path.join(root, 'workspace', `__e2e__protein-${placement}.nadoc`)
  const state = () => page.evaluate(() => window.__nadocTest.store.getState().currentDesign)
  const errors = trackConsoleErrors(page)
  let primary = false
  try {
    if (placement === 'library') {
      const seed = await request.post('http://127.0.0.1:8004/api/__e2e__/history/seed/connection-np-small', { headers })
      expect(seed.ok(), await seed.text()).toBe(true)
      // Reuse the history harness's exact unrelated startup-request boundary.
      const readiness = await request.get('http://127.0.0.1:8004/api/design/readiness', { headers })
      expect(readiness.ok()).toBe(true)
      const report = await readiness.text()
      await page.route(url => url.pathname === '/api/design/readiness', route =>
        route.fulfill({ status: 200, contentType: 'application/json', body: report }))
      await page.route(url => url.pathname === '/api/jobs/active', route =>
        route.fulfill({ status: 200, json: { jobs: [], count: 0, any_running: false } }))
    }
    await page.goto(`/?doc=${doc}${placement === 'library' ? '&readiness=simulation' : ''}`)
    await page.waitForFunction(() => Boolean(window.__nadocTest?.store))
    if (placement === 'library') {
      await page.evaluate(() => window.__nadocTest.pauseViewerRenderingForTest())
      await page.waitForFunction(() => window.__nadocTest.store.getState().currentGeometry?.length > 0, null, { timeout: 15000 })
      await page.waitForFunction(() => !new URL(location.href).searchParams.has('readiness'), null, { timeout: 15000 })
      console.log('FH33 library fixture loaded')
    }
    const prefix = (await state())?.feature_log?.length ?? 0
    await page.locator('#menu-item-import > button').click()
    await page.locator('#menu-file-import-pdb').click()
    await page.locator('#pdb-protein-placement').selectOption(placement)
    const picker = page.waitForEvent('filechooser')
    await page.getByRole('button', { name: 'Import from File…', exact: true }).click()
    const imported = page.waitForResponse(r => new URL(r.url()).pathname === '/api/design/import/pdb-auto')
    const started = Date.now()
    await (await picker).setFiles({ name: '__e2e__protein-source.pdb', mimeType: 'chemical/x-pdb', buffer: content })
    const response = await imported
    expect(response.ok(), await response.text()).toBe(true)
    const payload = await response.json()
    await expect(page.locator('#pdb-protein-placement')).toHaveCount(0)
    if (placement === 'library') {
      expect((await state()).feature_log).toHaveLength(prefix)
      await page.locator('#menu-item-tools > button').click()
      await page.locator('#menu-item-tools .submenu-item').filter({ hasText: /^Proteins/ }).hover()
      await page.locator('#menu-file-attach-protein').click()
      const modal = page.locator('h3', { hasText: 'Attach Protein to Overhang' }).locator('../..')
      await modal.locator('select').first().selectOption(payload.protein.id)
      await modal.getByRole('button', { name: 'Attach', exact: true }).click()
      await expect.poll(async () => (await state()).protein_attachments.length).toBe(1)
      await modal.getByRole('button', { name: '✕', exact: true }).click()
    }
    await expect.poll(async () => (await state())?.protein_attachments.length).toBe(1)
    console.log(`FH33 ${placement} import/placement through display ${Date.now() - started} ms`)
    const placed = await state()
    expect(placed.feature_log.slice(prefix).map(r => r.op_kind)).toEqual(['protein-import', 'protein-attach'])
    expect(placed.feature_log.slice(prefix).every(r => r.params.protein_version === 1)).toBe(true)
    const edited = await page.evaluate(async index => {
      const api = await import('/src/api/client.js')
      if (!await api.editFeature(index, { name: '__e2e__protein edited' })) throw new Error('Protein input edit failed')
      return window.__nadocTest.store.getState().currentDesign
    }, prefix)
    expect(edited.protein_assets[0].name).toBe('__e2e__protein edited')
    expect(edited.protein_attachments).toEqual(placed.protein_attachments)
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      if (!await api.undo() || !await api.redo()) throw new Error('Undo/redo failed')
      if (!await api.saveDesignAs(file, true) || !await api.loadDesign(file)) throw new Error('Save/reopen failed')
    }, file)
    const saved = JSON.parse(await fs.readFile(file, 'utf8'))
    const params = saved.feature_log[prefix].params
    expect(Buffer.from(saved.input_sources[params.source.sha256].data_b64, 'base64')).toEqual(content)
    expect((await state()).protein_attachments).toEqual(edited.protein_attachments)
    const proof = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers })
    const report = await proof.json()
    expect(report.status, JSON.stringify(report)).toBe('reproduced_import')
    expect(errors).toEqual([])
  } catch (error) {
    primary = true
    console.log('FH33 failure state:', await page.evaluate(() => ({ url: location.href,
      design: window.__nadocTest?.store.getState().currentDesign?.id,
      error: window.__nadocTest?.store.getState().lastError,
      dialogs: document.body.innerText.slice(-2500) })).catch(() => 'browser unavailable'))
    throw error
  }
  finally {
    try {
      await page.close()
      const response = await request.delete(`http://127.0.0.1:8004/api/documents/${doc}`)
      if (!response.ok()) throw new Error(`Cleanup HTTP ${response.status()}`)
    } catch (error) { if (!primary) throw error }
  }
})
