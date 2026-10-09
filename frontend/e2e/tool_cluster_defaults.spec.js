import { test, expect } from '@playwright/test'
import { loadScaffoldedPart, trackConsoleErrors } from './helpers/scene_harness.js'

for (const tool of ['bend', 'twist', 'translate-rotate']) {
  test(`${tool} starts with cluster picking and returns to default after a viewport pick`, async ({ page }) => {
    test.setTimeout(60_000)
    const errors = trackConsoleErrors(page)
    await loadScaffoldedPart(page, { doc: `e2e-cluster-default-${tool}`, name: `cluster-default-${tool}` })
    await page.evaluate(async () => {
      const api = await import('/src/api/client.js')
      const { store } = await import('/src/state/store.js')
      const strand = store.getState().currentDesign.strands.find(s => s.domains.length)
      await api.createCluster({ name: 'Pick target', helix_ids: [strand.domains[0].helix_id],
        domain_ids: [{ strand_id: strand.id, domain_index: 0 }] })
      const { createSelectionController } = await import('/src/scene/selection_controller.js')
      createSelectionController({ store }).clear()
      window.__nadocTest.applyCameraPoseForTest({ target: [0, 0, 33], position: [100, 20, 33] })
    })
    const level = () => page.evaluate(() => window.__nadocTest.getSelectionLevel())
    await page.locator('#canvas').focus()
    await page.keyboard.press('e')
    await expect.poll(level).toBe('cluster')
    await page.keyboard.press('e')
    await expect.poll(level).toBe('strand')
    await page.keyboard.press('q')
    await expect.poll(level).toBe('cluster')
    await page.keyboard.press('q')
    await expect.poll(level).toBe('default')

    await page.getByRole('button', { name: 'Tools', exact: true }).hover()
    await page.locator(`#menu-tools-${tool}`).click()
    await expect.poll(level).toBe('cluster')
    await expect(page.locator('#select-filter-trigger')).toContainText('clust')
    const points = await page.evaluate(() => {
      const rects = ['.tool-popup', '#left-panel', '#right-panel', '#menu-bar'].flatMap(selector =>
        [...document.querySelectorAll(selector)].map(node => node.getBoundingClientRect()))
      return window.__nadocTest.getClusterBeadScreenPositions().filter(point =>
        !rects.some(r => point.x >= r.left && point.x <= r.right && point.y >= r.top && point.y <= r.bottom))
    })
    expect(points.length).toBeGreaterThan(0)
    await page.mouse.click(points[0].x, points[0].y)
    await expect.poll(level).toBe('default')
    await expect(page.locator('#select-filter-trigger')).toContainText('default')
    expect(await page.evaluate(() => window.__nadocTest.getCanonicalSelection().primary?.kind)).toBe('cluster')
    if (tool === 'translate-rotate') {
      await page.locator('#mr-cancel-btn').click()
    } else {
      await expect(page.locator('#def-apply-btn')).toBeEnabled()
      await expect(page.locator('#def-plane-a-bp')).toHaveValue('0')
      await expect(page.locator('#def-plane-b-bp')).toHaveValue('199')
      expect(await page.evaluate(() => ({
        corners: window.__nadocTest.scene.getObjectByName('clusterSelectionCorners')?.visible ?? false,
        glow: window.__nadocTest.scene.getObjectByName('selectionGlow')?.count ?? 0,
      }))).toEqual({ corners: false, glow: 0 })
      await page.locator('#def-clear-selection').click()
      await expect.poll(level).toBe('cluster')
      await page.keyboard.press('Escape')
    }
    await expect.poll(level).toBe('default')
    expect(errors, errors.join('\n')).toEqual([])
  })
}
