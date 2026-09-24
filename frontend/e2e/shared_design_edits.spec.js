import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { trackConsoleErrors } from './helpers/scene_harness.js'

// Only a __e2e__ imported copy can autosave; global teardown removes its file
// and revision store. Transport is intercepted, so no public room is created.
const design = JSON.parse(readFileSync(new URL('../../Examples/2hb_xover_atoms_test.nadoc', import.meta.url)))
design.id = 'e2e-shared-edits'; design.metadata.name = '__e2e__shared-edits'

test('publishes design edits on the same invitation and preserves the guest camera', async ({ page, context }) => {
  test.setTimeout(180000)
  const errors = trackConsoleErrors(page), packets = []
  const room = { id: 'test-room', title: 'Editable design', url: 'http://example.invalid/view', expiresAt: Date.now() + 3600000 }
  await page.route('**/__nadoc_share/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/create') || path.endsWith('/content')) {
      packets.push(route.request().postDataBuffer()); await route.fulfill({ json: room })
    } else await route.fulfill({ json: { running: true, shares: packets.length ? [room] : [],
      capabilities: ['share-content-v1', 'editor-broadcast-v1', 'view-tools-v1', 'annotations-v1', 'selection-ping-v1', 'sphere-impostors-v1', 'multi-overlay-v1', 'hull-cutouts-v1'] } })
  })
  await page.goto('/?doc=e2e-shared-edits')
  await page.waitForFunction(() => !!window.__nadocTest)
  await page.evaluate(async design => {
    const api = await import('/src/api/client.js')
    await api.importDesign(JSON.stringify(design)); await api.getGeometry()
    document.getElementById('welcome-screen')?.classList.add('hidden')
  }, design)
  await page.evaluate(() => document.getElementById('menu-file-sharing').click())
  await expect(page.locator('#share-link-dialog [data-status]')).toContainText('Host ready')
  await page.locator('#share-link-dialog [data-create]').click()
  await expect(page.locator('#share-link-dialog [data-status]')).toContainText('Invitation ready')
  await page.locator('#share-link-dialog [data-close]').click()
  // Several sharing polls must not republish an idle renderer's GPU uploads.
  await page.waitForTimeout(2200)
  const idlePackets = packets.length
  await page.waitForTimeout(4200)
  expect(packets.length).toBe(idlePackets)
  const guest = await context.newPage(), guestErrors = trackConsoleErrors(guest)
  await guest.goto('/viewer.html?test=1')
  async function receive() {
    return guest.evaluate(async bytes => {
      const v = window.__preparedViewer
      if (!await v.loadFile(new File([new Uint8Array(bytes)], 'Shared.nadocview'), { preserveCamera: true })) throw new Error('Guest load failed')
      let instances = 0
      v.current.scene.traverse(o => { if (o.isInstancedMesh) instances += o.count })
      return { hash: v.current.data.sourceHash, package: v.current.packageHash, instances, overlay: v.current.data.view.overlay?.length }
    }, [...packets.at(-1)])
  }
  let previous = await receive()
  const guestCamera = await guest.evaluate(() => {
    const v = window.__preparedViewer, pose = v.captureCamera()
    pose.position[0] += 10; v.applyCamera(pose); return v.captureCamera()
  })
  async function checkEdit(edit) {
    const before = packets.length
    await page.evaluate(edit)
    const currentHash = () => page.evaluate(async () => {
      const bytes = new TextEncoder().encode(JSON.stringify(window.__nadocTest.store.getState().currentDesign))
      return [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(v => v.toString(16).padStart(2, '0')).join('')
    })
    await expect.poll(() => packets.length, { timeout: 30000 }).toBeGreaterThan(before)
    let next
    await expect.poll(async () => { next = await receive(); return next.hash === await currentHash() }, { timeout: 30000 }).toBe(true)
    expect(next.package).not.toBe(previous.package)
    expect(next.instances).toBeGreaterThan(previous.instances)
    expect(await guest.evaluate(() => window.__preparedViewer.captureCamera())).toEqual(guestCamera)
    previous = next
  }
  await checkEdit(async () => {
    const api = await import('/src/api/client.js')
    await api.extrudeOverhang({ helixId: 'h_XY_0_-1', bpIndex: 7, direction: 'FORWARD', isFivePrime: true, neighborRow: 0, neighborCol: -2, lengthBp: 8 })
  })
  await checkEdit(async () => {
    const api = await import('/src/api/client.js'), d = window.__nadocTest.store.getState().currentDesign
    const strand = d.strands.find(s => s.domains?.some(dom => dom.overhang_id))
    const domain = strand.domains.find(dom => dom.overhang_id)
    const end = strand.domains[0] === domain ? '5p' : '3p'
    await api.resizeOverhangFreeEnd(domain.overhang_id, { end, deltaBp: domain.direction === 'FORWARD' ? (end === '5p' ? -4 : 4) : (end === '5p' ? 4 : -4) })
  })
  await checkEdit(async () => {
    const api = await import('/src/api/client.js')
    await api.addBundleSegment({ cells: [[4, 4]], lengthBp: 16 })
  })
  // The same edits must invalidate frozen comparison layers too.
  await page.evaluate(() => window.__nadocTest.configureMultiOverlay({ count: 2, representations: ['full', 'cylinders'] }))
  await expect.poll(async () => (await receive()).overlay, { timeout: 30000 }).toBe(2)
  previous = await receive()
  await checkEdit(async () => {
    const api = await import('/src/api/client.js')
    await api.addBundleSegment({ cells: [[6, 4]], lengthBp: 16 })
  })
  expect(previous.overlay).toBe(2)
  expect(errors).toEqual([]); expect(guestErrors).toEqual([])
})
