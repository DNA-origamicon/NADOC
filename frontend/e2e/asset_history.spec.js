import { test, expect } from '@playwright/test'
import path from 'node:path'
import { trackConsoleErrors } from './helpers/scene_harness.js'

// Uses only the history launcher's owned workspace/profile/cache/output root.
const JOBS = 'http://127.0.0.1:8004/api/design/features/evaluation/jobs'
const state = page => page.evaluate(() => window.__nadocTest.store.getState().currentDesign)
const invoke = (page, method, ...args) => page.evaluate(async ({ method, args }) => {
  const api = await import('/src/api/client.js')
  const changes = []
  const record = () => {
    const context = api.assetOperationAPI.capture()
    const row = JSON.stringify({ id: context.designId, loadout: context.loadoutId, rev: context.revision,
      generation: context.generation, cursor: context.source?.feature_log_cursor,
      assembly: window.__nadocTest.store.getState().assemblyActive })
    if (changes.at(-1) !== row) changes.push(row)
  }
  record()
  const unsubscribe = window.__nadocTest.store.subscribe(record)
  try { return await api[method](...args) }
  catch (error) { throw new Error(`${error.message}; contexts: ${changes.join(' -> ')}`) }
  finally { unsubscribe() }
}, { method, args })

for (const kind of ['fit', 'biotin']) test(`native asset ${kind} ordinary flow and historical edit`, async ({ page, request }) => {
  test.setTimeout(120000)
  page.setDefaultTimeout(15000)
  const root = process.env.NADOC_HISTORY_E2E_ROOT
  const doc = '__e2e__history-bend', headers = { 'X-NADOC-Doc': doc }
  const errors = trackConsoleErrors(page)
  let primary = false
  page.on('response', response => { if (response.status() >= 400) console.log('Asset HTTP failure', response.status(), new URL(response.url()).pathname) })
  page.on('response', async response => {
    const route = new URL(response.url()).pathname
    if ((route.startsWith('/api/design') || route === '/api/library/upload') && response.request().method() !== 'GET') {
      const body = await response.json().catch(() => ({}))
      console.log('Asset write', response.request().method(), route, response.status(), body.revision, body.source_revision, body.job_id)
    }
  })
  try {
    const seeded = await request.post(`http://127.0.0.1:8004/api/__e2e__/history/seed/asset-${kind === 'fit' ? 'fit' : 'empty'}`, { headers })
    expect(seeded.ok(), await seeded.text()).toBe(true)
    console.log('Asset fixture seeded', kind)
    await page.goto(`/?doc=${doc}${kind === 'fit' ? '&readiness=simulation' : ''}`, { waitUntil: 'domcontentloaded' })
    await page.waitForFunction(() => window.__nadocTest?.store)
    if (process.env.NADOC_HISTORY_E2E_VISUAL !== '1')
      await page.evaluate(() => window.__nadocTest.pauseViewerRenderingForTest())
    if (kind === 'biotin') {
      await page.locator('#menu-bar > .menu-item').filter({ has: page.locator(':scope > button').filter({ hasText: /^File$/ }) }).hover()
      await page.locator('#menu-file-new').click()
      await page.locator('#new-design-name').fill('__e2e__asset-biotin')
      await page.locator('.modal').filter({ has: page.locator('#new-design-name') }).getByRole('button', { name: 'Create', exact: true }).click()
      await expect(page.locator('#new-design-name')).toHaveCount(0)
      await expect.poll(async () => (await state(page))?.metadata?.name).toBe('__e2e__asset-biotin')
    }
    await invoke(page, 'getDesign')
    await page.waitForFunction(() => window.__nadocTest.store.getState().currentDesign?.animations?.length > 0)
    if (kind === 'biotin') await page.waitForFunction(() => window.__nadocTest.store.getState().currentDesign?.active_loadout_id === 'main')
    console.log('Asset app loaded', kind)
    let index, before, particle
    if (kind === 'fit') {
      before = await state(page)
      const target = before.overhangs.find(o => !o.auxiliary_endpoint).id
      particle = 'gold'; index = before.feature_log.length
      expect(await invoke(page, 'attachNanoparticleToOverhang', particle, target)).toBeTruthy()
      expect((await state(page)).feature_log.at(-1).params.np_fitting_version).toBe(1)
      await page.evaluate(id => window.__nadocTest.nanoparticles.select(id), particle)
      await expect.poll(() => page.evaluate(() => window.__nadocTest.nanoparticles.gizmoAttached())).toBe(true)
      const originalPosition = await page.evaluate(() => window.__nadocTest.nanoparticles.rendered()[0].position)
      expect(await page.evaluate(() => window.__nadocTest.nanoparticles.gizmoSetTransform([.1, .1, 0], [0, 0, 0, 1]))).toBe(true)
      await page.locator('#mr-cancel-btn').click()
      expect((await state(page)).feature_log).toHaveLength(index + 1)
      await expect.poll(() => page.evaluate(() => window.__nadocTest.nanoparticles.rendered()[0].position)).toEqual(originalPosition)
      await page.evaluate(id => window.__nadocTest.nanoparticles.select(id), particle)
      expect(await page.evaluate(() => window.__nadocTest.nanoparticles.gizmoSetTransform([.1, .1, 0], [0, 0, 0, 1]))).toBe(true)
      const previewPosition = await page.evaluate(() => window.__nadocTest.nanoparticles.rendered()[0].position)
      expect(await page.evaluate(() => window.__nadocTest.nanoparticles.gizmoApply())).toBe(true)
      await expect.poll(async () => {
        const actual = await page.evaluate(() => window.__nadocTest.nanoparticles.rendered()[0].position)
        return Math.max(...actual.map((value, i) => Math.abs(value - previewPosition[i])))
      }).toBeLessThan(1e-6)
      index += 1
      expect(await invoke(page, 'relaxNanoparticleConnectionVersions', particle)).toBeTruthy()
    } else {
      const cancelled = invoke(page, 'createGoldNanosphere', 10, { count_override: 1 })
        .then(() => 'unexpected publication', error => error.message)
      await page.getByRole('dialog', { name: 'Create coated nanoparticle' }).getByRole('button', { name: 'Cancel', exact: true }).click()
      expect(await cancelled).toContain('cancelled')
      expect((await state(page)).nanoparticles).toHaveLength(0)
      const result = await invoke(page, 'createGoldNanosphere', 10, { count_override: 1 })
      expect(result).toBeTruthy(); particle = result.nanoparticle_id
      await page.evaluate(async pid => {
        const { openStreptavidinDialog } = await import('/src/ui/streptavidin_dialog.js')
        openStreptavidinDialog(window.__nadocTest.store.getState().currentDesign.nanoparticles.find(p => p.id === pid))
      }, particle)
      await page.locator('#strep-dna-sequence').fill('ACGTACGT')
      await page.locator('#strep-dna-linker').fill('2')
      const biotinStarted = Date.now()
      await page.locator('#strep-dna-create').click()
      await expect.poll(async () => (await state(page)).nanoparticles[0].biotin_dna.length,
        { timeout: 30000 }).toBe(1)
      console.log('Biotin worker through display adoption ms', Date.now() - biotinStarted)
      await page.locator('#strep-cancel').click()
      index = 2
    }
    console.log('Asset ordinary actions complete', kind)
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    const row = page.locator(`#fl-list [data-fl-row="${index + 1}"]`)
    await row.locator('button[title^="Edit "]').click()
    const dialog = page.locator('.modal').filter({ has: page.locator('input') })
    if (kind === 'fit') await dialog.getByLabel('Translation (nm) X', { exact: true }).fill('0.2')
    else await dialog.getByLabel('DNA sequence', { exact: true }).fill('ACGTACGA')
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(dialog).toHaveCount(0, { timeout: 30000 })
    if (kind === 'biotin') {
      await page.locator('#fl-list [data-fl-row="2"]').locator('button[title^="Edit "]').click()
      const beforeFailure = (await state(page)).feature_log.map(entry => entry.params)
      await dialog.getByLabel('Tetramer count (0 uses coverage)', { exact: true }).fill('2')
      await dialog.getByRole('button', { name: 'Save', exact: true }).click()
      await expect(dialog.locator('[role=alert]')).not.toHaveText('', { timeout: 30000 })
      await expect(page.locator('#fl-list [data-fl-row="3"] [data-history-status="error"]')).toHaveCount(1)
      expect((await state(page)).feature_log.map(entry => entry.params)).toEqual(beforeFailure)
      await dialog.getByLabel('Tetramer count (0 uses coverage)', { exact: true }).fill('1')
      await dialog.getByLabel('Placement seed', { exact: true }).fill('2')
      await dialog.getByRole('button', { name: 'Save', exact: true }).click()
      await expect(dialog).toHaveCount(0, { timeout: 30000 })
      expect((await state(page)).feature_log[1].params.seed).toBe(2)
    }
    const edited = await state(page)
    if (kind === 'fit') expect(edited.feature_log[index].params.gizmo_move.translation[0]).toBe(.2)
    else expect(edited.strands[0].sequence).toBe('ACGTACGA')
    expect(await invoke(page, 'undo')).toBeTruthy()
    expect(await invoke(page, 'redo')).toBeTruthy()
    // File → New already establishes this part's autosave target. Save there;
    // directly calling Save As would leave the desktop path on the old file.
    const file = kind === 'biotin' ? edited.metadata.identity_last_known_path
      : path.join(root, 'workspace', `__e2e__asset-${kind}.nadoc`)
    expect(file).toContain('__e2e__')
    expect(await invoke(page, 'saveDesignAs', file, true)).toBeTruthy()
    const reopenedSave = kind === 'biotin'
      ? page.waitForResponse(response => new URL(response.url()).pathname === '/api/design/save-workspace')
      : Promise.resolve()
    expect(await invoke(page, kind === 'biotin' ? 'openLibraryPart' : 'loadDesign', file)).toBeTruthy()
    await reopenedSave
    const saved = await state(page)
    expect(saved.input_sources).toEqual(edited.input_sources)
    expect(saved.feature_log.map(r => r.params)).toEqual(edited.feature_log.map(r => r.params))
    if (process.env.NADOC_HISTORY_E2E_VISUAL === '1') {
      const screenshot = path.join(root, 'output', `asset-${kind}.png`)
      await page.screenshot({ path: screenshot })
      console.log('Visual inspection ready', screenshot)
      await page.waitForTimeout(15000)
    }
    const started = await request.post(JOBS, { headers, data: { operation: 'verify',
      expected_revision: await page.evaluate(async () => (await import('/src/api/client.js')).currentRevisionWatermark()) } })
    expect(started.ok(), await started.text()).toBe(true)
    const id = (await started.json()).job_id
    let result
    await expect.poll(async () => {
      result = await (await request.get(`${JOBS}/${id}`, { headers })).json()
      return result.status
    }, { timeout: 30000 }).not.toBe('running')
    expect(result.result.status, JSON.stringify(result)).toBe(kind === 'fit' ? 'verified' : 'reproduced_import')
    if (kind === 'biotin') {
      expect(await invoke(page, 'removeNanoparticleBiotinDNA', particle)).toBeTruthy()
      expect((await state(page)).strands).toEqual([])
    }
    expect(errors).toEqual([])
  } catch (error) { primary = true; console.log('Asset flow failure', kind, error.message); throw error }
  finally {
    try {
      await page.close()
      const cleanup = await request.delete(`http://127.0.0.1:8004/api/documents/${doc}`, { timeout: 5000 })
      expect(cleanup.ok()).toBe(true)
    } catch (error) { if (!primary) throw error }
  }
})

test('generated assets use ordinary worker, editable history and cold save/reopen', async ({ page, request }) => {
  test.setTimeout(240000)
  page.setDefaultTimeout(15000)
  const root = process.env.NADOC_HISTORY_E2E_ROOT
  const doc = '__e2e__history-bend', headers = { 'X-NADOC-Doc': doc }
  const errors = trackConsoleErrors(page)
  page.on('response', async response => {
    if (!new URL(response.url()).pathname.includes('/api/design/')) return
    const body = await response.json().catch(() => ({}))
    if (response.status() >= 400 || body.result && body.result.status !== 'ready')
      console.log('Generated response', response.status(), new URL(response.url()).pathname,
        JSON.stringify(body).slice(0, 2400))
  })
  try {
    const seeded = await request.post('http://127.0.0.1:8004/api/__e2e__/history/seed/asset-generated', { headers })
    expect(seeded.ok(), await seeded.text()).toBe(true)
    await page.goto(`/?doc=${doc}&readiness=simulation`, { waitUntil: 'domcontentloaded' })
    await page.waitForFunction(() => window.__nadocTest?.store)
    await page.evaluate(() => window.__nadocTest.pauseViewerRenderingForTest())
    await invoke(page, 'getDesign')
    await page.waitForFunction(() => window.__nadocTest.store.getState().currentDesign?.animations?.length > 0)
    const original = await state(page)
    await page.evaluate(async () => {
      const { showGenerateDesign } = await import('/src/ui/generate_design.js')
      const api = await import('/src/api/client.js')
      showGenerateDesign({ api, store: window.__nadocTest.store })
    })
    await page.getByRole('button', { name: 'Calculate design', exact: true }).click()
    await expect(page.getByRole('button', { name: 'Generate in current loadout', exact: true })).toBeEnabled({ timeout: 30000 })
    await page.getByRole('button', { name: 'Generate in current loadout', exact: true }).click()
    await expect.poll(async () => (await state(page))?.duplexes?.length, { timeout: 100000 }).toBe(2)
    const generated = await state(page)
    expect(generated.nanoparticles.map(p => p.id)).toEqual(original.nanoparticles.map(p => p.id))
    await page.getByRole('button', { name: 'Close', exact: true }).click()
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    const index = generated.feature_log.findIndex(e => e.op_kind === 'nanoparticle-conjugate')
    await page.locator(`#fl-list [data-fl-row="${index + 1}"]`).locator('button[title^="Edit "]').click()
    const editor = page.locator('.modal').filter({ has: page.locator('input') })
    await editor.getByRole('spinbutton').fill('0.8')
    await editor.getByRole('button', { name: 'Save', exact: true }).click()
    await expect.poll(async () => {
      const error = await editor.locator('[role=alert]').textContent().catch(() => '')
      if (error) throw new Error(error)
      return (await state(page)).feature_log[index].params.spacer_nm
    }, { timeout: 100000 }).toBe(.8)
    expect(await invoke(page, 'undo')).toBeTruthy()
    expect(await invoke(page, 'redo')).toBeTruthy()
    const file = path.join(root, 'workspace', '__e2e__generated-assets.nadoc')
    expect(await invoke(page, 'saveDesignAs', file, true)).toBeTruthy()
    expect(await invoke(page, 'loadDesign', file)).toBeTruthy()
    const started = await request.post(JOBS, { headers, data: { operation: 'verify',
      expected_revision: await page.evaluate(async () => (await import('/src/api/client.js')).currentRevisionWatermark()) } })
    expect(started.ok(), await started.text()).toBe(true)
    const id = (await started.json()).job_id
    let result
    await expect.poll(async () => {
      result = await (await request.get(`${JOBS}/${id}`, { headers })).json()
      return result.status
    }, { timeout: 60000 }).not.toBe('running')
    expect(result.result.status, JSON.stringify(result)).toBe('verified')
    expect(errors).toEqual([])
  } finally {
    await page.close()
    await request.delete(`http://127.0.0.1:8004/api/documents/${doc}`, { timeout: 5000 })
  }
})
