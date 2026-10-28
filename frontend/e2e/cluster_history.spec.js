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
