import { test, expect } from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'
import { execFileSync } from 'node:child_process'
import { trackConsoleErrors } from './helpers/scene_harness.js'

// Source fixture, saves, browser profiles, caches and reports all belong to
// the existing launcher's disposable root; its finally removes every artifact.
test('DNA PDB pinned import: ordinary menu, downstream edit and portable replay', async ({ page, request }) => {
  const root = process.env.NADOC_HISTORY_E2E_ROOT
  if (!root) throw new Error('Use the isolated history launcher')
  const source = path.join(root, 'tmp', '__e2e__dna-source.pdb')
  execFileSync('uv', ['run', '--no-sync', 'python', '-c',
    'import sys; from tests.test_pdb_to_design import _write_synthetic_duplex_pdb; _write_synthetic_duplex_pdb(sys.argv[1])', source],
  { cwd: path.resolve(process.cwd(), '..'), timeout: 15000 })
  const content = await fs.readFile(source)
  const doc = '__e2e__history-bend', headers = { 'X-NADOC-Doc': doc }
  const file = path.join(root, 'workspace', '__e2e__dna-pdb-pinned.nadoc')
  const errors = trackConsoleErrors(page)
  let primary = false
  try {
    await page.goto(`/?doc=${doc}`)
    await page.waitForFunction(() => Boolean(window.__nadocTest?.store))
    await page.locator('#menu-item-import > button').click()
    await page.locator('#menu-file-import-pdb').click()
    const picker = page.waitForEvent('filechooser')
    await page.getByRole('button', { name: 'Import from File…', exact: true }).click()
    const imported = page.waitForResponse(r => new URL(r.url()).pathname === '/api/design/import/pdb-auto')
    await (await picker).setFiles({ name: '__e2e__dna-source.pdb', mimeType: 'chemical/x-pdb', buffer: content })
    const response = await imported
    expect(response.ok(), await response.text()).toBe(true)
    expect((await response.json()).import_history.status).toBe('reproduced_import')
    await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentGeometry?.length)).toBe(8)
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    await expect(page.getByText(/F1: Import 1/).first()).toBeVisible()
    const changed = await page.evaluate(async () => {
      const api = await import('/src/api/client.js')
      const state = () => window.__nadocTest.store.getState()
      const before = state().currentDesign
      if (!await api.addNick({ helixId: before.helices[0].id, bpIndex: 2, direction: 'FORWARD' })) throw new Error('Nick failed')
      if (!await api.editFeature(0, { name_override: '__e2e__DNA edited' })) throw new Error('Input edit failed')
      return { design: state().currentDesign, geometry: state().currentGeometry }
    })
    expect(changed.design.metadata.name).toBe('__e2e__DNA edited')
    expect(changed.design.feature_log).toHaveLength(2)
    const proof = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers })
    expect((await proof.json()).status).toBe('reproduced_import')
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      if (!await api.undo()) throw new Error('Undo failed')
      if (!await api.redo()) throw new Error('Redo failed')
      if (!await api.saveDesignAs(file, true)) throw new Error('Save failed')
      if (!await api.loadDesign(file)) throw new Error('Reopen failed')
    }, file)
    const saved = JSON.parse(await fs.readFile(file, 'utf8'))
    const params = saved.feature_log[0].params
    expect(params.loss_policy).toBe('existing-duplex-projection-v1')
    expect(Buffer.from(saved.input_sources[params.source.sha256].data_b64, 'base64')).toEqual(content)
    expect(await page.evaluate(() => window.__nadocTest.store.getState().currentDesign.helices)).toEqual(changed.design.helices)
    const after = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers })
    expect((await after.json()).status).toBe('reproduced_import')
    expect(errors).toEqual([])
  } catch (error) { primary = true; throw error }
  finally {
    await page.close()
    const response = await request.delete(`http://127.0.0.1:8004/api/documents/${doc}`)
    if (!response.ok() && !primary) throw new Error(`Cleanup HTTP ${response.status()}`)
  }
})
