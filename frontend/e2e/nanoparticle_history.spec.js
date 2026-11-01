import { test, expect } from '@playwright/test'
import { withHistoryFixture } from './helpers/deformation_history.js'

// The existing launcher owns workspace saves, browser profiles, caches and
// reports beneath its disposable root and removes them even after failure.
const versions = state => state.design.nanoparticle_connection_versions
const geometry = records => records.map(n => ({
  key: [n.helix_id, n.bp_index, n.direction, n.copy_k ?? 0, n.strand_id, n.domain_index].join(':'),
  backbone: n.backbone_position, base: n.base_position, normal: n.base_normal,
  tangent: n.axis_tangent, slab: n.slab_position, quaternion: n.slab_quaternion,
})).sort((a, b) => a.key.localeCompare(b.key))
const invoke = (page, method, ...args) => page.evaluate(async ({ method, args }) => {
  const api = await import('/src/api/client.js')
  if (!await api[method](...args)) throw new Error(`${method} failed`)
}, { method, args })

async function openConnections(page, design) {
  await page.setViewportSize({ width: 1920, height: 1080 })
  const close = page.getByRole('button', { name: 'Close Simulations sidebar', exact: true })
  if (await close.isVisible()) await close.click()
  await page.locator('.right-tab-btn[data-tab="overhangs"]').click()
  if (!await page.locator('#oconn-body').isVisible()) await page.locator('#oconn-heading').click()
  await page.locator('#oconn-endpoint-mode').selectOption('nanoparticle')
  await page.locator('#oconn-select-a').selectOption(design.nanoparticle_conjugations[0].surface_strands[0].strand_id)
  await page.locator('#oconn-select-b').selectOption(design.overhangs.find(o => !o.auxiliary_endpoint).id)
  await page.locator('#oconn-button-box').click()
  await page.locator('#oconn-popover [data-variant="end-to-root"]').click()
  await expect(page.locator('#oconn-np-add')).toBeEnabled()
}

test('nanoparticle ordinary lifecycle, pending context and historical editor', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async ({ browser, checkpoint, headers, file }) => {
    await openConnections(page, (await browser()).design)
    const before = await checkpoint()
    await page.locator('#oconn-np-add').click()
    await expect.poll(async () => versions(await browser()).length).toBe(1)
    const primary = versions(await browser())[0].id
    await page.locator('#oconn-np-apply').click()
    await expect.poll(async () => versions(await browser())[0].applied).toBe(true)
    const applied = await browser()
    expect(applied.design.feature_log.at(-1).params.nanoparticle_application_version).toBe(1)
    await page.locator('#oconn-np-add').click()
    await expect.poll(async () => versions(await browser()).length).toBe(2)
    const alternative = versions(await browser()).find(v => v.id !== primary).id
    const context = await browser(), index = context.design.feature_log.length - 1
    expect(context.design.feature_log[index].params.nanoparticle_pending_context_version).toBe(1)
    expect(geometry(context.geometry)).toEqual(geometry(applied.geometry))
    expect((await checkpoint()).history.length).toBe(before.history.length + 3)
    await page.locator('#oconn-np-apply').click()
    await expect.poll(async () => versions(await browser()).find(v => v.id === alternative)?.applied).toBe(true)
    const downstream = await browser()
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    const edit = page.locator(`#fl-list [data-fl-row="${index + 1}"] button[title^="Edit "]`)
    const unchanged = await checkpoint()
    await edit.click()
    await page.getByRole('dialog').getByLabel('Name', { exact: true }).fill('Cancelled alternative')
    await page.getByRole('dialog').getByRole('button', { name: 'Cancel', exact: true }).evaluate(cancel => {
      const dialog = cancel.closest('[role="dialog"]')
      window.__npCancelTiming = null
      cancel.addEventListener('click', () => {
        const started = performance.now()
        requestAnimationFrame(() => requestAnimationFrame(() => {
          window.__npCancelTiming = { ms: performance.now() - started,
            closed: !dialog.isConnected || dialog.getClientRects().length === 0 }
        }))
      }, { capture: true, once: true })
    })
    const cancelWrites = []
    const trackCancel = request => {
      if (request.method() !== 'GET' && new URL(request.url()).pathname.startsWith('/api/design'))
        cancelWrites.push(request.url())
    }
    page.on('request', trackCancel)
    await page.getByRole('dialog').getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect.poll(() => page.evaluate(() => window.__npCancelTiming)).not.toBeNull()
    const cancelTiming = await page.evaluate(() => window.__npCancelTiming)
    page.off('request', trackCancel)
    console.log(`FH30 Cancel click through repaint ${cancelTiming.ms} ms`)
    expect(cancelTiming.closed).toBe(true)
    expect(cancelTiming.ms).toBeLessThanOrEqual(400)
    expect(cancelWrites).toEqual([])
    expect(await checkpoint()).toEqual(unchanged)
    await edit.click()
    await page.getByRole('dialog').getByLabel('Connection type', { exact: true }).selectOption('root-to-root')
    const refused = page.waitForResponse(r => r.url().endsWith(`/features/${index}/edit`))
    await page.getByRole('dialog').getByRole('button', { name: 'Save', exact: true }).click()
    expect((await refused).status()).toBe(409)
    await expect(page.getByRole('dialog').getByRole('alert')).toBeVisible()
    expect(await checkpoint()).toEqual(unchanged)
    await expect(page.locator('#fl-list [data-history-status="error"]')).toHaveCount(1)
    await expect(page.locator('#fl-list [data-history-status="blocked"]')).toHaveCount(1)
    await page.getByRole('dialog').getByLabel('Connection type', { exact: true }).selectOption('end-to-root')
    await page.getByRole('dialog').getByLabel('Name', { exact: true }).fill('Earlier alternative')
    await page.getByRole('dialog').getByRole('button', { name: 'Save', exact: true }).click()
    try { await expect(page.getByRole('dialog')).toHaveCount(0) }
    catch (error) { throw new Error(`${error.message}\nEditor: ${await page.getByRole('dialog').innerText()}`) }
    expect((await browser()).design.feature_log[index].params.name).toBe('Earlier alternative')
    // The later Apply has its own explicit name input. Edit that field to
    // change the final label while preserving the earlier authored choice.
    await page.locator(`#fl-list [data-fl-row="${index + 2}"] button[title^="Edit "]`).click()
    await page.getByRole('dialog').getByLabel('Name', { exact: true }).fill('Chosen alternative')
    await page.getByRole('dialog').getByRole('button', { name: 'Save', exact: true }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect.poll(async () => versions(await browser()).find(v => v.id === alternative)?.name).toBe('Chosen alternative')
    expect(geometry((await browser()).geometry)).toEqual(geometry(downstream.geometry))
    await page.locator('#oconn-np-list .oconn-version-row').filter({ hasNotText: 'Chosen alternative' }).click()
    await page.locator('#oconn-np-apply').click()
    await expect.poll(async () => versions(await browser()).find(v => v.id === primary)?.applied).toBe(true)
    await page.locator('#oconn-np-list .oconn-version-row').filter({ hasText: 'Chosen alternative' }).click()
    await page.locator('#oconn-np-apply').click()
    await expect.poll(async () => versions(await browser()).find(v => v.id === alternative)?.applied).toBe(true)
    expect(versions(await browser()).filter(v => v.applied)).toHaveLength(1)
    await invoke(page, 'undo')
    expect(versions(await browser()).find(v => v.id === primary).applied).toBe(true)
    await invoke(page, 'redo')
    await page.locator('#oconn-np-list .oconn-version-row').filter({ hasText: 'Chosen alternative' }).click()
    await page.locator('#oconn-np-apply').click()
    await expect.poll(async () => versions(await browser()).some(v => v.applied)).toBe(false)
    await page.locator('#oconn-np-apply').click()
    await expect.poll(async () => versions(await browser()).find(v => v.id === alternative)?.applied).toBe(true)
    const final = await browser()
    await invoke(page, 'saveDesign', file)
    await invoke(page, 'loadDesign', file)
    expect(versions(await browser())).toEqual(versions(final))
    expect(geometry((await browser()).geometry)).toEqual(geometry(final.geometry))
    const proof = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers })
    expect((await proof.json()).status).toBe('verified')
    await page.locator('#oconn-np-list .oconn-version-row').filter({ hasText: 'Chosen alternative' }).locator('.oconn-row-del').click()
    await expect.poll(async () => versions(await browser()).length).toBe(1)
    expect((await browser()).design.duplexes).toEqual([])
    await invoke(page, 'undo')
    expect(geometry((await browser()).geometry)).toEqual(geometry(final.geometry))
    return { expectedConsoleErrors: ['Failed to load resource: the server responded with a status of 409 (Conflict)'] }
  }, 'connection-np-small', { pauseRendering: true })
})

for (const profile of ['small', 'large']) test(`nanoparticle ${profile} adopted display latency`, async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async ({ browser, headers }) => {
    await openConnections(page, (await browser()).design)
    await page.locator('#oconn-np-add').click()
    const count = profile === 'small' ? 1 : 3
    await expect.poll(async () => versions(await browser()).length).toBe(count)
    const result = await page.evaluate(async () => {
      const state = () => window.__nadocTest.store.getState()
      const api = await import('/src/api/client.js')
      const id = state().currentDesign.nanoparticle_connection_versions.at(-1).id
      const samples = [], reads = [], heapBefore = performance.memory?.usedJSHeapSize
      for (let i = 0; i < 9; i++) {
        const applied = i % 2 === 0, start = performance.now()
        const read = fetch('/api/design/revision', { headers: { 'X-NADOC-Doc': '__e2e__history-bend' } })
          .then(r => { if (!r.ok) throw new Error('Scalar read failed'); reads.push(performance.now() - start) })
        if (!await api.patchNanoparticleConnectionVersion('gold', id, { applied })) throw new Error('Apply failed')
        samples.push(performance.now() - start)
        if (state().currentDesign.nanoparticle_connection_versions.find(v => v.id === id).applied !== applied
          || !state().currentGeometry.length) throw new Error('Display was not adopted')
        await read
      }
      return { samples, reads, nucleotides: state().currentGeometry.length,
        heapBefore, heapAfter: performance.memory?.usedJSHeapSize }
    })
    console.log(`FH30 ${profile} ${JSON.stringify(result)}`)
    expect(Math.max(...result.samples)).toBeLessThan(profile === 'large' ? 10000 : 3000)
    expect(Math.max(...result.reads)).toBeLessThan(500)
    const proof = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers })
    expect((await proof.json()).status).toBe('verified')
  }, `connection-np-${profile}`, { pauseRendering: true })
})

test('nanoparticle ordinary applied geometry visual review', async ({ page, request }) => {
  if (process.env.NADOC_HISTORY_E2E_VISUAL === '1') test.setTimeout(90000)
  await withHistoryFixture({ page, request }, 'bend', async ({ browser, root, file }) => {
    await openConnections(page, (await browser()).design)
    await page.locator('#oconn-np-add').click()
    await expect.poll(async () => versions(await browser()).length).toBe(1)
    await page.locator('#oconn-np-apply').click()
    await expect.poll(async () => versions(await browser())[0].applied).toBe(true)
    await invoke(page, 'saveDesign', file)
    await invoke(page, 'loadDesign', file)
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
    await page.screenshot({ path: `${root}/playwright/nanoparticle-visual.png` })
    console.log(`FH30 visual review: ${root}/playwright/nanoparticle-visual.png`)
    if (process.env.NADOC_HISTORY_E2E_VISUAL === '1') await page.waitForTimeout(20000)
  }, 'connection-np-small')
})
