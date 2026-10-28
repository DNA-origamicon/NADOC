import { test, expect } from '@playwright/test'
import { withHistoryFixture } from './helpers/deformation_history.js'
import { installRetentionProbe } from './helpers/retention_probe.js'

// All persisted files, caches and browser profiles are beneath the shared
// launcher's disposable root; document cleanup runs even after assertion errors.
const geometry = records => records.map(n => ({
  key: [n.helix_id, n.bp_index, n.direction, n.copy_k ?? 0, n.strand_id, n.domain_index].join(':'),
  backbone: n.backbone_position, base: n.base_position, normal: n.base_normal,
  tangent: n.axis_tangent, slab: n.slab_position, quaternion: n.slab_quaternion,
})).sort((a, b) => a.key.localeCompare(b.key))

const invoke = (page, method, ...args) => page.evaluate(async ({ method, args }) => {
  const api = await import('/src/api/client.js')
  const result = await api[method](...args)
  if (!result) throw new Error(`${method} failed`)
}, { method, args })

async function openConnections(page, family) {
  await page.setViewportSize({ width: 1920, height: 1080 })
  const close = page.getByRole('button', { name: 'Close Simulations sidebar', exact: true })
  if (await close.isVisible()) await close.click()
  if (!await page.locator('#oconn-heading').isVisible())
    await page.locator('.right-tab-btn[data-tab="overhangs"]').click()
  if (!await page.locator('#oconn-body').isVisible()) await page.locator('#oconn-heading').click()
  const options = await page.locator('#oconn-select-a option').evaluateAll(items => items.map(item => item.value).filter(Boolean))
  await page.locator('#oconn-select-a').selectOption(options[0])
  await page.locator('#oconn-select-b').selectOption(options[1])
  await page.locator('#oconn-button-box').click()
  await page.locator(`#oconn-popover [data-variant="${family}"]`).click()
  if (await page.locator('#oconn-length').isVisible()) await page.locator('#oconn-length').fill('7')
  await expect(page.locator('#oconn-generate')).toBeEnabled()
}

const sameEnd = new Set(['end-to-root', 'root-to-root-dsdna-linker', 'end-to-end-dsdna-linker',
  'end-to-root-ssdna-linker', 'root-to-end-ssdna-linker'])
const families = ['root-to-root', 'end-to-root', ...['root-to-root', 'root-to-end', 'end-to-root', 'end-to-end']
  .flatMap(attach => ['ss', 'ds'].map(material => `${attach}-${material}dna-linker`)),
  'root-to-root-indirect', 'end-to-end-indirect']

for (const family of families) {
  test(`connection lifecycle ${family}`, async ({ page, request }) => {
    await withHistoryFixture({ page, request }, 'bend', async ({ browser, checkpoint, headers, file }) => {
      await openConnections(page, family)
      const before = await checkpoint()
      const created = page.waitForResponse(r => r.url().endsWith('/connection-versions/connect'))
      await page.locator('#oconn-generate').click()
      const response = await created
      expect(response.status(), await response.text()).toBe(201)
      await expect.poll(async () => (await browser()).design.connection_versions.length).toBe(1)
      const connected = (await browser()).design
      expect(connected.feature_log.length).toBe(before.design.feature_log.length + 1)
      expect(connected.feature_log.at(-1).params.action).toMatch(/^connection-version-connect-/)
      expect((await checkpoint()).history.length).toBe(before.history.length + 1)
      await invoke(page, 'undo')
      expect((await browser()).design.connection_versions).toEqual([])
      await invoke(page, 'redo')
      expect((await browser()).design.connection_versions).toEqual(connected.connection_versions)
      await page.locator('#oconn-apply').click()
      await expect.poll(async () => (await browser()).design.connection_versions[0].applied).toBe(false)
      const free = (await browser()).design
      expect(free.duplexes).toEqual([])
      expect(free.overhang_connections).toEqual([])
      expect(free.overhang_bindings).toEqual([])
      await page.locator('#oconn-apply').click()
      await expect.poll(async () => (await browser()).design.connection_versions[0].applied).toBe(true)
      const proof = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers })
      expect((await proof.json()).status).toBe('verified')
      const current = await browser()
      await invoke(page, 'saveDesign', file)
      await invoke(page, 'loadDesign', file)
      expect(geometry((await browser()).geometry)).toEqual(geometry(current.geometry))
      expect((await browser()).design.connection_versions).toEqual(current.design.connection_versions)
      await page.locator('#oconn-list .oconn-version-row').getByTitle('Delete version').click()
      await page.getByRole('dialog').getByRole('button', { name: 'Delete', exact: true }).click()
      await expect.poll(async () => (await browser()).design.connection_versions.length).toBe(0)
      expect((await browser()).design.duplexes).toEqual([])
      expect((await browser()).design.overhang_connections).toEqual([])
      await invoke(page, 'undo')
      expect(geometry((await browser()).geometry)).toEqual(geometry(current.geometry))
    }, sameEnd.has(family) ? 'connection-same' : 'connection-opposite', { pauseRendering: true })
  })
}

test('connection history editor keeps Cancel exact and rebuilds a downstream Apply', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async ({ browser, checkpoint, headers }) => {
    await openConnections(page, 'root-to-root-ssdna-linker')
    await page.locator('#oconn-generate').click()
    await expect.poll(async () => (await browser()).design.connection_versions.length).toBe(1)
    await page.locator('#oconn-apply').click()
    await expect.poll(async () => (await browser()).design.connection_versions[0].applied).toBe(false)
    await page.locator('#oconn-apply').click()
    await expect.poll(async () => (await browser()).design.connection_versions[0].applied).toBe(true)
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    const source = await checkpoint()
    const index = source.design.feature_log.findIndex(row => row.params?.action === 'connection-version-connect-linker')
    const edit = page.locator(`#fl-list [data-fl-row="${index + 1}"] button[title^="Edit "]`)
    await edit.click()
    await page.getByRole('dialog').getByLabel('Bridge length (bp)').fill('11')
    await page.getByRole('dialog').getByRole('button', { name: 'Cancel', exact: true }).click()
    expect(await checkpoint()).toEqual(source)
    await edit.click()
    await page.getByRole('dialog').getByLabel('Bridge length (bp)').fill('5000')
    const refused = page.waitForResponse(response => response.url().endsWith(`/features/${index}/edit`))
    await page.getByRole('dialog').getByRole('button', { name: 'Save', exact: true }).click()
    expect((await refused).status()).toBe(409)
    await expect(page.getByRole('dialog').getByRole('alert')).toBeVisible()
    await expect(page.getByRole('dialog').getByLabel('Bridge length (bp)')).toHaveValue('5000')
    expect(await checkpoint()).toEqual(source)
    await expect(page.locator('#fl-list [data-history-status="error"]')).toHaveCount(1)
    await expect(page.locator('#fl-list [data-history-status="blocked"]')).toHaveCount(2)
    await page.getByRole('dialog').getByLabel('Bridge length (bp)').fill('11')
    await page.getByRole('dialog').getByRole('button', { name: 'Save', exact: true }).click()
    try { await expect(page.getByRole('dialog')).toHaveCount(0) }
    catch (error) { throw new Error(`${error.message}\nEditor: ${await page.getByRole('dialog').innerText()}`) }
    const updated = (await browser()).design
    expect(updated.overhang_connections[0].length_value).toBe(11)
    expect(updated.feature_log.map(row => row.id)).toEqual(source.design.feature_log.map(row => row.id))
    const proof = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers })
    expect((await proof.json()).status).toBe('verified')
    await invoke(page, 'undo')
    expect((await browser()).design.overhang_connections[0].length_value).toBe(7)
    await invoke(page, 'redo')
    expect((await browser()).design.overhang_connections[0].length_value).toBe(11)
    return { expectedConsoleErrors: ['Failed to load resource: the server responded with a status of 409 (Conflict)'] }
  }, 'connection-opposite', { pauseRendering: true })
})

for (const profile of ['a-longer', 'b-longer', 'same-a-longer', 'same-b-longer', 'shared', 'blank']) {
  test(`connection source ${profile} atomic Connect and Add version`, async ({ page, request }) => {
    await withHistoryFixture({ page, request }, 'bend', async ({ browser, checkpoint, headers, file, writes }) => {
      const family = profile.startsWith('same') ? 'end-to-root' : profile === 'shared' ? 'root-to-root-ssdna-linker' : 'root-to-root'
      await openConnections(page, family)
      const before = await checkpoint(), offset = writes.length
      await page.locator('#oconn-generate').click()
      await expect.poll(async () => (await browser()).design.connection_versions.length).toBe(1)
      const first = await browser()
      expect(first.design.feature_log.length).toBe(before.design.feature_log.length + 1)
      expect((await checkpoint()).history.length).toBe(before.history.length + 1)
      expect(writes.slice(offset).filter(write => !write.path.endsWith('/generate-random')).map(write => write.path))
        .toEqual(['/api/design/connection-versions/connect'])
      await expect(page.locator('#oconn-generate')).toHaveText('Add version')
      await page.locator('#oconn-generate').click()
      await expect.poll(async () => (await browser()).design.connection_versions.length).toBe(2)
      const replaced = await browser()
      expect(replaced.design.connection_versions.filter(v => v.applied)).toHaveLength(1)
      expect(replaced.design.feature_log.length).toBe(first.design.feature_log.length + 1)
      expect((await checkpoint()).history.length).toBe(before.history.length + 2)
      await invoke(page, 'undo')
      expect((await browser()).design.connection_versions).toEqual(first.design.connection_versions)
      await invoke(page, 'redo')
      const proof = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers })
      expect((await proof.json()).status).toBe('verified')
      await invoke(page, 'saveDesign', file)
      await invoke(page, 'loadDesign', file)
      expect(geometry((await browser()).geometry)).toEqual(geometry(replaced.geometry))
      expect((await browser()).design.connection_versions).toEqual(replaced.design.connection_versions)
    }, `connection-${profile}`, { pauseRendering: true })
  })
}

for (const profile of ['opposite', 'large']) test(`connection ${profile} request and adopted display latency`, async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async ({ browser, headers }) => {
    await openConnections(page, 'root-to-root-ssdna-linker')
    const result = await page.evaluate(async () => {
      const state = () => window.__nadocTest.store.getState()
      const heapBefore = performance.memory?.usedJSHeapSize
      const samples = [], reads = []
      const started = performance.now()
      document.getElementById('oconn-generate').click()
      while (!state().currentDesign.connection_versions.length) await new Promise(resolve => setTimeout(resolve, 4))
      samples.push(performance.now() - started)
      const id = state().currentDesign.connection_versions[0].id
      const api = await import('/src/api/client.js')
      for (let i = 0; i < 8; i++) {
        const readStart = performance.now()
        const read = fetch('/api/design/revision', { headers: { 'X-NADOC-Doc': '__e2e__history-bend' } })
          .then(response => { if (!response.ok) throw new Error('Scalar read failed'); reads.push(performance.now() - readStart) })
        const start = performance.now()
        if (!await api.applyConnectionVersion(id)) throw new Error('Apply failed')
        samples.push(performance.now() - start)
        await read
      }
      return { samples, reads, nucleotides: state().currentGeometry.length,
        heapBefore, heapAfter: performance.memory?.usedJSHeapSize }
    })
    console.log(`FH25 ${profile} ${JSON.stringify(result)}`)
    expect(Math.max(...result.samples)).toBeLessThan(profile === 'large' ? 10000 : 3000)
    expect(Math.max(...result.reads)).toBeLessThan(500)
    const proof = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers })
    expect((await proof.json()).status).toBe('verified')
    expect((await browser()).design.connection_versions).toHaveLength(1)
  }, `connection-${profile}`, { pauseRendering: true })
})

test('saved connection sequence changes reapply through one ordinary control', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async ({ browser, checkpoint, headers }) => {
    await openConnections(page, 'root-to-root-ssdna-linker')
    await page.locator('#oconn-generate').click()
    await expect.poll(async () => (await browser()).design.connection_versions.length).toBe(1)
    await page.locator('#oconn-list .oconn-version-row').click()
    const before = await browser()
    const input = page.getByLabel('Version bridge sequence', { exact: true })
    await input.fill('ACGTACG'); await input.press('Enter')
    await expect.poll(async () => (await browser()).design.connection_versions[0].bridge_seq).toBe('ACGTACG')
    expect((await browser()).design.overhang_connections).toEqual(before.design.overhang_connections)
    const saved = await checkpoint()
    await page.locator('#oconn-details').getByRole('button', { name: 'Reapply', exact: true }).click()
    await expect.poll(async () => (await browser()).design.overhang_connections[0].bridge_sequence).toBe('ACGTACG')
    expect((await checkpoint()).history.length).toBe(saved.history.length + 1)
    await invoke(page, 'undo')
    expect((await browser()).design.overhang_connections).toEqual(before.design.overhang_connections)
    await invoke(page, 'redo')
    const proof = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers })
    expect((await proof.json()).status).toBe('verified')
  }, 'connection-opposite', { pauseRendering: true })
})

for (const profile of ['opposite', 'large']) test(`connection ${profile} repeated lifecycle retention`, async ({ page, request }) => {
  test.skip(process.env.NADOC_HISTORY_E2E_RETENTION !== '1', 'Explicit GC diagnostic; run separately from latency checks')
  test.setTimeout(180000)
  const retention = await installRetentionProbe(page)
  await withHistoryFixture({ page, request }, 'bend', async f => {
    const original = await f.browser(), samples = []
    for (let cycle = 0; cycle < 12; cycle++) {
      await openConnections(page, 'root-to-root-ssdna-linker')
      await page.locator('#oconn-generate').click()
      await expect.poll(async () => (await f.browser()).design.connection_versions.length).toBe(1)
      const id = (await f.browser()).design.connection_versions[0].id
      await invoke(page, 'applyConnectionVersion', id)
      await invoke(page, 'applyConnectionVersion', id)
      await invoke(page, 'loadDesign', f.file)
      const restored = await f.browser()
      expect(restored.design.connection_versions).toEqual(original.design.connection_versions)
      expect(restored.design.feature_log).toEqual(original.design.feature_log)
      expect(geometry(restored.geometry)).toEqual(geometry(original.geometry))
      const response = await request.get('http://127.0.0.1:8004/api/__e2e__/history/resources', { headers: f.headers })
      expect(response.ok()).toBe(true)
      const backend = await response.json()
      expect(backend.document_sessions).toBe(0)
      samples.push({ cycle, backend, ...await retention.sample() })
      console.log(`FH27 connection ${profile} retained cycle ${cycle + 1}/12`)
    }
    console.log(`FH27 connection retention ${profile}: ${JSON.stringify(samples)}`)
  }, `connection-${profile}`, { pauseRendering: true })
})

test('connection production unequal direct visual review', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async ({ browser, root, file }) => {
    await openConnections(page, 'root-to-root')
    await page.locator('#oconn-generate').click()
    await expect.poll(async () => (await browser()).design.connection_versions.length).toBe(1)
    await invoke(page, 'saveDesign', file)
    await invoke(page, 'loadDesign', file)
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    await page.evaluate(async () => {
      const api = window.__nadocTest
      api.store.setState({ selection: { context: 'design', items: [] } })
      const points = api.store.getState().currentGeometry.map(n => n.backbone_position)
      const lo = [0, 1, 2].map(i => Math.min(...points.map(p => p[i])))
      const hi = [0, 1, 2].map(i => Math.max(...points.map(p => p[i])))
      const target = lo.map((value, i) => (value + hi[i]) / 2)
      const span = Math.max(...hi.map((value, i) => value - lo[i]))
      api.applyCameraPoseForTest({ target, position: target.map((value, i) => value + span * [1.5, .8, 1][i]) })
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
    })
    // Owned launcher root: screenshot is removed in the same failure-safe cleanup.
    await page.screenshot({ path: `${root}/playwright/connection-visual.png` })
    console.log(`FH25 visual review: ${root}/playwright/connection-visual.png`)
    if (process.env.NADOC_HISTORY_E2E_VISUAL === '1') await page.waitForTimeout(20000)
  }, 'connection-a-longer')
})
