import { test, expect } from '@playwright/test'

test.use({ viewport: { width: 1920, height: 1100 }, launchOptions: { args: ['--enable-webgl', '--ignore-gpu-blocklist'] } })

const state = page => page.evaluate(() => window.__nadocTest.clusterJoin.getState())
const design = page => page.evaluate(async () => (await import('/src/state/store.js')).store.getState().currentDesign)

async function openJoin(page) {
  await page.getByRole('button', { name: 'Tools', exact: true }).hover()
  await page.locator('#menu-tools-join').click()
  await expect.poll(async () => (await state(page)).loading).toBe(false)
  await expect(page.locator('#cluster-join-panel')).toBeVisible()
}

async function pickVisibleSite(page, clusterId, kind) {
  const points = await page.evaluate(({ clusterId, kind }) => {
    const occluders = ['.tool-popup', '#left-panel', '#right-panel', '#menu-bar'].flatMap(selector =>
      [...document.querySelectorAll(selector)].filter(node => getComputedStyle(node).display !== 'none').map(node => node.getBoundingClientRect()))
    return window.__nadocTest.clusterJoin.getSiteScreenPositions()
      .filter(p => p.cluster_id === clusterId && p.kind === kind)
      .filter(p => !occluders.some(r => p.x >= r.left && p.x <= r.right && p.y >= r.top && p.y <= r.bottom))
      .sort((a, b) => Math.abs(a.from.bp_index - 36) - Math.abs(b.from.bp_index - 36))
  }, { clusterId, kind })
  for (const point of points) {
    await page.mouse.move(point.x, point.y)
    const current = await state(page)
    const hover = current.sites.find(site => site.id === current.hoveredSiteId)
    if (hover?.cluster_id !== clusterId || hover.kind !== kind) continue
    expect(current.visibleSiteIds).toContain(hover.id)
    const markers = await page.evaluate(() => window.__nadocTest.scene.getObjectByName('cluster-join-markers')?.children.length)
    expect(markers).toBeGreaterThan(0)
    await page.mouse.click(point.x, point.y)
    return hover
  }
  throw new Error(`No visible, correctly hit-tested ${kind} port on ${clusterId}; considered ${points.length} points`)
}

test('Join uses native hover picks, previews and commits one undoable routing and pose edit', async ({ page }, testInfo) => {
  test.setTimeout(120_000)
  const errors = [], applyRequests = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route(/\/api\/(oxdna|md|mrdna|lammps|cando|snupi|blade)\/jobs(?:\?.*)?$/, route => route.request().method() === 'GET' ? route.fulfill({ json: [] }) : route.continue())
  await page.addInitScript(() => localStorage.setItem('nadoc.hint.selModifiers.v1', '1'))
  await page.goto('/?doc=e2e-cluster-join')
  await page.waitForFunction(() => !!window.__nadocTest?.clusterJoin)
  await page.getByRole('button', { name: 'File', exact: true }).hover()
  await page.locator('#menu-file-new').click()
  await page.locator('#new-design-name').fill('__e2e__cluster-join')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  const ids = await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const { store } = await import('/src/state/store.js')
    await api.createBundle({ cells: [[0, 0], [0, 1], [8, 0], [8, 1]], lengthBp: 63, name: '__e2e__cluster-join' })
    const helices = store.getState().currentDesign.helices
    // Keep the native frame's placement owner; the new cluster takes the
    // branch helices out of that default body through the normal grouping API.
    await api.patchCluster(store.getState().currentDesign.cluster_transforms[0].id, { name: 'Body' })
    await api.createCluster({ name: 'Branch', helix_ids: helices.filter(h => h.grid_pos[0] === 8).map(h => h.id), log: true })
    await api.autoScaffoldSeamless()
    window.__nadocTest.applyCameraPoseForTest({ position: [65, 65, 38], target: [0, 12, 9], up: [0, 0, 1] })
    return Object.fromEntries(store.getState().currentDesign.cluster_transforms.map(c => [c.name, c.id]))
  })
  const before = await design(page)
  expect(before.strands.filter(s => s.strand_type === 'scaffold')).toHaveLength(2)
  page.on('request', request => { if (request.url().endsWith('/design/cluster-join/apply')) applyRequests.push(request.postDataJSON()) })

  await openJoin(page)
  const panel = page.locator('.tool-popup[data-tool-panel="cluster-join-panel"]')
  await expect(panel).toHaveCSS('backdrop-filter', 'blur(18px) saturate(1.25)')
  await expect(panel.locator('[data-join-apply]')).toBeDisabled()
  await expect.poll(async () => (await state(page)).sites.length).toBeGreaterThan(0)
  const first = await pickVisibleSite(page, ids.Body, 'side')
  await expect.poll(async () => (await state(page)).first?.id).toBe(first.id)
  // Escape from the first pick resets the gesture without editing the design.
  await page.keyboard.press('Escape')
  expect((await state(page)).first).toBeNull()
  expect((await design(page)).strands).toEqual(before.strands)
  await pickVisibleSite(page, ids.Body, 'side')
  await pickVisibleSite(page, ids.Branch, 'end')
  await expect.poll(async () => (await state(page)).previewLoading).toBe(false)
  // This actual port pair has a 0.24 nm connector overlap at the default gap.
  // Reject it without changing DNA, then resolve it through the visible control.
  expect((await state(page)).preview?.valid).toBe(false)
  expect((await state(page)).status).toContain('Connector placement clashes')
  await expect(panel.locator('[data-join-apply]')).toBeDisabled()
  expect((await design(page)).cluster_transforms).toEqual(before.cluster_transforms)
  expect((await design(page)).strands).toEqual(before.strands)
  await panel.getByLabel('Join gap (nm)').fill('1.2')
  await expect(panel.locator('[data-join-apply]')).toBeEnabled()
  const prepared = await state(page)
  expect(prepared.preview?.valid, prepared.status).toBe(true)
  expect(prepared.preview.scaffold_count_after).toBe(1)
  expect((await design(page)).cluster_transforms).toEqual(before.cluster_transforms)
  expect((await design(page)).strands).toEqual(before.strands)
  const ghostCount = await page.evaluate(() => window.__nadocTest.scene.getObjectByName('cluster-join-ghost')?.children.length)
  expect(ghostCount).toBe(2)
  await page.screenshot({ path: testInfo.outputPath('join-preview.png') })
  // Optional human review hold; evidence stays under the cleanup reporter.
  if (process.env.NADOC_JOIN_REVIEW_HOLD) {
    // Observation-only close view of the attachment; the picks and pose are unchanged.
    await page.evaluate(() => {
      const p = window.__nadocTest.clusterJoin.getState().first.position
      window.__nadocTest.applyCameraPoseForTest({ position: [p[0] + 22, p[1] + 15, p[2] + 12], target: [p[0], p[1], p[2]], up: [0, 0, 1] })
    })
    await page.screenshot({ path: testInfo.outputPath('join-preview-close.png') })
    await page.waitForTimeout(20_000)
  }

  await panel.getByLabel('Join gap (nm)').fill('')
  await expect(panel.locator('[data-join-apply]')).toBeDisabled()
  await panel.getByLabel('Join gap (nm)').fill('1.2')
  await expect(panel.locator('[data-join-apply]')).toBeEnabled()
  await panel.locator('[data-join-apply]').click()
  await expect(panel).toBeHidden()
  const after = await design(page)
  expect(applyRequests).toHaveLength(1)
  expect(after.strands.filter(s => s.strand_type === 'scaffold')).toHaveLength(1)
  expect(after.cluster_transforms.find(c => c.id === ids.Body)).toEqual(before.cluster_transforms.find(c => c.id === ids.Body))
  expect(after.cluster_transforms.find(c => c.id === ids.Branch).translation).not.toEqual(before.cluster_transforms.find(c => c.id === ids.Branch).translation)
  expect(after.feature_log.at(-1).op_kind).toBe('cluster-join')
  expect(after.strands.filter(s => s.strand_type === 'staple')).toEqual(before.strands.filter(s => s.strand_type === 'staple'))
  const previewVisible = await page.evaluate(() => window.__nadocTest.scene.getObjectByName('cluster-join-preview')?.visible)
  expect(previewVisible).toBe(false)
  if (process.env.NADOC_JOIN_REVIEW_HOLD) {
    await page.screenshot({ path: testInfo.outputPath('joined-native.png') })
    await page.waitForTimeout(20_000)
  }

  await page.evaluate(async () => (await import('/src/api/client.js')).undo())
  const undone = await design(page)
  expect(undone.strands).toEqual(before.strands)
  expect(undone.cluster_transforms).toEqual(before.cluster_transforms)
  await page.evaluate(async () => (await import('/src/api/client.js')).redo())
  const redone = await design(page)
  expect(redone.strands).toEqual(after.strands)
  expect(redone.cluster_transforms).toEqual(after.cluster_transforms)

  await page.locator('#view-tools [data-key="join"]').click()
  await expect(panel).toBeVisible()
  await page.getByRole('button', { name: 'Close Join clusters', exact: true }).click()
  await expect(panel).toBeHidden()
  expect(errors).toEqual([])
})
