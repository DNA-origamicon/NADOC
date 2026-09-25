import { test, expect } from '@playwright/test'
import { loadScaffoldedPart, trackConsoleErrors } from './helpers/scene_harness.js'

// Only __e2e__shared-representations workspace files/history can persist; global
// teardown removes them. Sharing transport is intercepted: no host or public link.
test('shares native representations, view volumes and isolated multi-overlay layers', async ({ page, context }) => {
  test.setTimeout(180_000)
  const errors = trackConsoleErrors(page), packets = []
  const capabilities = ['share-content-v1', 'view-tools-v1', 'annotations-v1', 'selection-ping-v1', 'sphere-impostors-v1', 'guest-visualizations-v1', 'editor-broadcast-v1', 'multi-overlay-v1', 'hull-cutouts-v1']
  const room = { id: 'test-room', title: 'Test view', url: 'http://example.invalid/view', expiresAt: Date.now() + 3600000 }
  await page.route('**/__nadoc_share/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (path.endsWith('/create') || path.endsWith('/content')) {
      packets.push(request.postDataBuffer())
      await route.fulfill({ json: room })
    } else await route.fulfill({ json: { running: true, capabilities, shares: packets.length ? [room] : [] } })
  })
  await loadScaffoldedPart(page, { doc: 'e2e-shared-representations', name: 'shared-representations' })
  const guest = await context.newPage(), guestErrors = trackConsoleErrors(guest)
  await guest.goto('/viewer.html?test=1')
  async function publish() {
    await page.evaluate(() => document.getElementById('menu-file-sharing').click())
    if (!packets.length) {
      await expect(page.locator('#share-link-dialog [data-create]')).toBeEnabled()
      await page.locator('#share-link-dialog [data-create]').click()
    }
    await expect(page.locator('#share-link-dialog [data-copy-link]')).toBeVisible()
    await page.locator('#share-link-dialog [data-close]').click()
    const bytes = [...packets.at(-1)]
    return guest.evaluate(async bytes => {
      const viewer = window.__preparedViewer
      if (!await viewer.loadFile(new File([new Uint8Array(bytes)], 'shared.nadocview'))) throw new Error(document.body.textContent)
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
      const { data, scene } = viewer.current
      let meshes = 0
      scene.traverse(o => { if (o.isMesh) meshes++ })
      return { representation: data.view.representation, overlay: data.view.overlay?.length, meshes, volumes: !!scene.getObjectByName('view-volumes') }
    }, bytes)
  }
  for (const representation of ['hull-prism', 'cylinders', 'mrdna-coarse', 'mrdna-fine', 'oxdna']) {
    const before = packets.length
    await page.evaluate(rep => window.__nadocTest.setRepresentation(rep), representation)
    if (before) await expect.poll(() => packets.length, { timeout: 15000 }).toBeGreaterThan(before)
    const result = await publish()
    expect(result.representation).toBe(representation)
    expect(result.meshes).toBeGreaterThan(0)
  }
  await page.evaluate(() => document.getElementById('view-volume-add-box').click())
  await expect(page.locator('.view-volume-row')).toHaveCount(1)
  await expect(page.locator('#view-volume-busy')).toBeHidden()
  expect((await publish()).volumes).toBe(true)
  await page.evaluate(() => window.__nadocTest.configureMultiOverlay({ count: 3,
    representations: ['hull-prism', 'mrdna-fine', 'oxdna'], opacities: [1, .5, .3], separation: .2 }))
  const overlay = await publish()
  expect(overlay.overlay).toBe(3)
  expect(overlay.meshes).toBeGreaterThan(3)
  // Renderer must also work from the opposite side, where layer order reverses.
  await guest.evaluate(() => {
    const v = window.__preparedViewer, pose = v.captureCamera()
    pose.position[0] *= -1; v.applyCamera(pose)
  })
  await guest.waitForTimeout(100)
  expect(errors).toEqual([]); expect(guestErrors).toEqual([])
})
