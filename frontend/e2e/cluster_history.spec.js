import { test, expect } from '@playwright/test'
import { withHistoryFixture } from './helpers/deformation_history.js'

// The shared launcher owns saved files, browser storage, caches and processes
// beneath its disposable root; withHistoryFixture closes the document on failure.
test('cluster membership survives dissolution and history scrubbing', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async ({ browser, file, headers }) => {
    const invoke = (method, ...args) => page.evaluate(async ({ method, args }) => {
      const api = await import('/src/api/client.js')
      if (!await api[method](...args)) throw new Error(`${method} failed`)
    }, { method, args })
    const initial = await browser()
    const helices = initial.design.helices.map(h => h.id)
    await invoke('createCluster', { name: 'First arm', helix_ids: [helices[0]] })
    const first = (await browser()).design.cluster_transforms.find(c => c.name === 'First arm')
    await invoke('deleteCluster', first.id)
    const dissolved = (await browser()).design
    await invoke('createCluster', { name: 'Remaining arm', helix_ids: [helices[1]] })
    const created = (await browser()).design
    expect(created.cluster_transforms.find(c => c.is_default).helix_ids).toEqual([])
    await invoke('undo')
    expect((await browser()).design.cluster_transforms).toEqual(dissolved.cluster_transforms)
    await invoke('redo')
    expect((await browser()).design.cluster_transforms).toEqual(created.cluster_transforms)
    await invoke('saveDesign', file)
    await invoke('loadDesign', file)
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    for (const expected of [dissolved, created, dissolved, created]) {
      const index = expected.feature_log.length
      const notch = page.locator(`.fl-notch[data-notch-index="${index}"]`)
      await expect(notch).toBeVisible()
      const box = await notch.boundingBox()
      const thumb = await page.locator('#fl-rail > div').filter({
        has: page.locator('.feature-seek-readiness'),
      }).boundingBox()
      await page.mouse.move(thumb.x + thumb.width / 2, thumb.y + thumb.height / 2)
      await page.mouse.down()
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 4 })
      await page.mouse.up()
      await expect.poll(async () => (await browser()).design.cluster_transforms)
        .toEqual(expected.cluster_transforms)
    }
    const proof = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers })
    expect(proof.ok()).toBe(true)
    expect((await proof.json()).status).toBe('verified')
  }, 'unpair')
})

const sameGeometry = (actual, expected) => expect(JSON.parse(JSON.stringify(actual))).toEqual(JSON.parse(JSON.stringify(expected)))

const invoke = (page, method, ...args) => page.evaluate(async ({ method, args }) => {
  const api = await import('/src/api/client.js')
  if (!await api[method](...args)) throw new Error(`${method} failed`)
}, { method, args })

async function openClusters(page) {
  await page.setViewportSize({ width: 1920, height: 1080 })
  for (const name of ['Close Simulations sidebar']) {
    const close = page.getByRole('button', { name, exact: true })
    if (await close.isVisible()) await close.click()
  }
  await page.locator('.right-tab-btn[data-tab="clustering"]').click()
  if (!await page.locator('#cluster-new-btn').isVisible()) await page.locator('#cluster-panel-heading').click()
}

async function selectStrands(page, helix = null) {
  await page.evaluate(async helix => {
    const { store } = await import('/src/state/store.js')
    const items = store.getState().currentDesign.strands.filter(s => !helix || s.domains.some(d => d.helix_id === helix))
      .map(s => ({ kind: 'strand', id: s.id }))
    store.setState({ selection: { context: 'design', level: 'strand', items, primary: items[0] } })
  }, helix)
}

// Real sidebar controls, ordinary HTTP paths, native cold replay and persistence.
test('cluster sidebar create rename style dissolve and repair are recorded', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async ({ browser, file, headers }) => {
    await openClusters(page)
    const initial = await browser()
    await selectStrands(page, initial.design.helices[0].id)
    await page.locator('#cluster-new-btn').click()
    await expect.poll(async () => (await browser()).design.cluster_transforms.length).toBe(2)
    const made = await browser()
    sameGeometry(made.geometry, initial.geometry)
    expect(made.design.feature_log.length).toBe(initial.design.feature_log.length + 1)
    const id = made.design.cluster_transforms.at(-1).id
    const row = page.locator(`#cluster-list [data-cluster-id="${id}"]`)
    await row.getByTitle('Rename cluster', { exact: true }).click()
    await row.locator('input[type=text]').fill('Sidebar arm')
    await row.getByTitle('Save name', { exact: true }).click()
    await expect.poll(async () => (await browser()).design.cluster_transforms.at(-1).name).toBe('Sidebar arm')
    await row.getByTitle('Colour & opacity', { exact: true }).click()
    const popover = page.locator('.cluster-style-popover')
    await popover.locator('input[type=range]').fill('0.45')
    await expect.poll(async () => (await browser()).design.cluster_transforms.at(-1).opacity).toBe(.45)
    await page.keyboard.press('Escape')
    const styled = (await browser()).design
    expect(styled.feature_log.length).toBe(made.design.feature_log.length + 2)
    await invoke(page, 'undo')
    expect((await browser()).design.cluster_transforms.at(-1).opacity).toBe(1)
    await invoke(page, 'redo')
    await invoke(page, 'saveDesign', file)
    await invoke(page, 'loadDesign', file)
    expect((await browser()).design.cluster_transforms).toEqual(styled.cluster_transforms)
    await row.getByRole('button', { name: 'Dissolve group', exact: true }).click()
    await expect.poll(async () => (await browser()).design.cluster_transforms.length).toBe(1)
    sameGeometry((await browser()).geometry, initial.geometry)
    await page.locator('#cluster-repair-btn').click()
    await expect.poll(async () => (await browser()).design.cluster_transforms.length).toBe(2)
    const repaired = (await browser()).design
    await invoke(page, 'undo')
    expect((await browser()).design.cluster_transforms.length).toBe(1)
    await invoke(page, 'redo')
    expect((await browser()).design.cluster_transforms).toEqual(repaired.cluster_transforms)
    const proof = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers })
    expect(proof.ok()).toBe(true)
    expect((await proof.json()).status).toBe('verified')
  }, 'unpair')
})

test('cluster sidebar dissolution lists every incoming owner without mutation', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async ({ checkpoint, browser }) => {
    await openClusters(page)
    const before = await checkpoint(), display = await browser()
    const response = page.waitForResponse(r => r.request().method() === 'DELETE' && r.url().includes('/cluster/group-a'))
    await page.locator('#cluster-list [data-cluster-id="group-a"]').getByRole('button', { name: 'Dissolve group', exact: true }).click()
    const refused = await response
    expect(refused.status()).toBe(409)
    const issue = (await refused.json()).detail
    expect(new Set(issue.references.map(r => r.owner.kind))).toEqual(new Set(['lattice_frame', 'cluster', 'joint', 'deformation']))
    for (const owner of ['frame', 'Second', 'joint', 'bend']) expect(issue.detail).toContain(owner)
    await expect(page.locator('.toast').filter({ hasText: 'Remove or reassign these references first' })).toBeVisible()
    expect(await checkpoint()).toEqual(before)
    sameGeometry((await browser()).geometry, display.geometry)
    return { expectedConsoleErrors: ['Failed to load resource: the server responded with a status of 409 (Conflict)'] }
  }, 'cluster-incoming', { pauseRendering: true })
})

async function contextClusters(page) {
  await page.locator('#canvas').click({ button: 'right', position: { x: 30, y: 30 } })
  const select = page.locator('select').filter({ has: page.locator('option[value="__new__"]', { hasText: 'New cluster' }) })
  await expect(select).toBeVisible()
  return select
}

test('cluster context creation and membership preserve geometry and history', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async ({ browser, headers }) => {
    await openClusters(page)
    const initial = await browser()
    await selectStrands(page, initial.design.helices[0].id)
    await (await contextClusters(page)).selectOption('__new__')
    await expect.poll(async () => (await browser()).design.cluster_transforms.length).toBe(2)
    const created = (await browser()).design
    const id = created.cluster_transforms.at(-1).id
    sameGeometry((await browser()).geometry, initial.geometry)
    await selectStrands(page, initial.design.helices[1].id)
    await (await contextClusters(page)).selectOption(id)
    await expect.poll(async () => (await browser()).design.cluster_transforms.at(-1).helix_ids.length).toBe(2)
    const edited = (await browser()).design
    expect(edited.feature_log.length).toBe(created.feature_log.length + 1)
    sameGeometry((await browser()).geometry, initial.geometry)
    await invoke(page, 'undo')
    expect((await browser()).design.cluster_transforms).toEqual(created.cluster_transforms)
    await invoke(page, 'redo')
    expect((await browser()).design.cluster_transforms).toEqual(edited.cluster_transforms)
    const proof = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers })
    expect((await proof.json()).status).toBe('verified')
  }, 'unpair')
})

test('cluster visual inspection of placed six-helix bundle after reopen', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async ({ browser, file, root }) => {
    await openClusters(page)
    await selectStrands(page)
    const before = await browser()
    await page.locator('#cluster-new-btn').click()
    await expect.poll(async () => (await browser()).design.cluster_transforms.length).toBe(2)
    sameGeometry((await browser()).geometry, before.geometry)
    await invoke(page, 'saveDesign', file)
    await invoke(page, 'loadDesign', file)
    await page.evaluate(() => {
      const api = window.__nadocTest
      api.store.setState({ selection: { context: 'design', items: [] } })
      const points = api.store.getState().currentGeometry.map(n => n.backbone_position)
      const lo = [0, 1, 2].map(i => Math.min(...points.map(p => p[i])))
      const hi = [0, 1, 2].map(i => Math.max(...points.map(p => p[i])))
      const target = lo.map((v, i) => (v + hi[i]) / 2)
      const span = Math.max(...hi.map((v, i) => v - lo[i]))
      api.applyCameraPoseForTest({ target, position: target.map((v, i) => v + span * [1.5, .8, 1][i]) })
    })
    await page.screenshot({ path: `${root}/playwright/cluster-visual.png` })
    console.log(`FH18 visual review: ${root}/playwright/cluster-visual.png`)
  }, 'cluster-small')
})

for (const size of ['small', 'large']) test(`cluster placed ${size} bundle preserves geometry and measures sidebar latency`, async ({ page, request }) => {
  test.setTimeout(120_000)
  await withHistoryFixture({ page, request }, 'bend', async ({ browser, file, headers }) => {
    await openClusters(page)
    await selectStrands(page)
    const before = await browser()
    const start = Date.now()
    await page.locator('#cluster-new-btn').click()
    await expect.poll(async () => await page.evaluate(() => window.__nadocTest.store.getState().currentDesign.cluster_transforms.length), { timeout: 20_000 }).toBe(before.design.cluster_transforms.length + 1)
    const applyMs = Date.now() - start
    const made = await browser()
    sameGeometry(made.geometry, before.geometry)
    const id = made.design.cluster_transforms.at(-1).id
    const row = page.locator(`#cluster-list [data-cluster-id="${id}"]`)
    await row.getByTitle('Rename cluster', { exact: true }).click()
    await row.locator('input[type=text]').fill('Cancelled name')
    const cancelStart = Date.now()
    await row.locator('input[type=text]').press('Escape')
    const cancelMs = Date.now() - cancelStart
    expect((await browser()).design).toEqual(made.design)
    await row.getByTitle('Colour & opacity', { exact: true }).click()
    const samples = await page.evaluate(async () => {
      const input = document.querySelector('.cluster-style-popover input[type=range]')
      const values = []
      for (let i = 0; i < 40; i++) {
        const start = performance.now()
        input.value = i % 2 ? '.8' : '.6'
        input.dispatchEvent(new Event('input', { bubbles: true }))
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
        values.push(performance.now() - start)
      }
      return values
    })
    expect((await browser()).design).toEqual(made.design)
    const styleStart = Date.now()
    await page.keyboard.press('Escape')
    await expect.poll(async () => await page.evaluate(() => window.__nadocTest.store.getState().currentDesign.cluster_transforms.at(-1).opacity), { timeout: 20000 }).toBe(.8)
    const styleMs = Date.now() - styleStart
    const p95 = samples.sort((a, b) => a - b)[37]
    console.log(`FH18 ${size} helices=${made.design.helices.length} nucleotides=${made.geometry.length} make_ms=${applyMs} style_preview_p95_ms=${Math.round(p95)} rename_cancel_ms=${cancelMs} style_apply_ms=${styleMs}`)
    expect(applyMs).toBeLessThan(size === 'small' ? 3000 : 10000)
    expect(styleMs).toBeLessThan(size === 'small' ? 3000 : 10000)
    expect(p95).toBeLessThan(500)
    expect(cancelMs).toBeLessThan(200)
    await invoke(page, 'saveDesign', file)
    await invoke(page, 'loadDesign', file)
    const proof = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers, timeout: 30000 })
    expect((await proof.json()).status).toBe('verified')
  }, `cluster-${size}`, { pauseRendering: true })
})

test('cluster historical sidebar refusals restore controls and canonical state', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async ({ browser, checkpoint }) => {
    await openClusters(page)
    const initial = await browser()
    await invoke(page, 'createCluster', { name: 'Arm', helix_ids: [initial.design.helices[0].id] })
    const created = (await browser()).design, id = created.cluster_transforms.at(-1).id
    await invoke(page, 'patchCluster', id, { name: 'Later name' })
    await invoke(page, 'seekFeatures', created.feature_log.length - 1)
    const before = await checkpoint()
    const row = page.locator(`#cluster-list [data-cluster-id="${id}"]`)
    await row.getByTitle('Colour & opacity', { exact: true }).click()
    const opacity = page.locator('.cluster-style-popover input[type=range]')
    const refused = page.waitForResponse(r => r.request().method() === 'PATCH' && r.url().includes(`/cluster/${id}`))
    await opacity.fill('0.3')
    expect((await refused).status()).toBe(409)
    await expect(opacity).toHaveValue('1')
    await expect(page.getByRole('alert').filter({ hasText: 'Return to the latest history position' })).toBeVisible()
    await page.keyboard.press('Escape')
    await row.getByTitle('Rename cluster', { exact: true }).click()
    await row.locator('input[type=text]').fill('Refused name')
    await row.getByTitle('Save name', { exact: true }).click()
    await expect(page.getByRole('alert').filter({ hasText: 'Could not rename cluster' })).toBeVisible()
    await expect(row).toContainText('Arm')
    await expect(row).not.toContainText('Refused name')
    await selectStrands(page)
    await page.locator('#cluster-new-btn').click()
    await expect(page.getByRole('alert').filter({ hasText: 'Could not create cluster' })).toBeVisible()
    expect(await checkpoint()).toEqual(before)
    await invoke(page, 'seekFeatures', -1)
    return { expectedConsoleErrors: Array(3).fill('Failed to load resource: the server responded with a status of 409 (Conflict)') }
  }, 'cluster-straight')
})

test('cluster evicted recovery refuses seeking without a server error or mutation', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async ({ browser, checkpoint }) => {
    const initial = await browser()
    await invoke(page, 'createCluster', { name: 'Arm', helix_ids: [initial.design.helices[0].id] })
    const before = await checkpoint()
    const response = page.waitForResponse(r => r.url().includes('/features/seek'))
    await page.evaluate(async () => { await (await import('/src/api/client.js')).seekFeatures(1) })
    const refused = await response
    expect(refused.status()).toBe(410)
    expect((await refused.json()).detail.code).toBe('group_recovery_unavailable')
    expect(await checkpoint()).toEqual(before)
    return { expectedConsoleErrors: ['Failed to load resource: the server responded with a status of 410 (Gone)'] }
  }, 'unpair')
})
