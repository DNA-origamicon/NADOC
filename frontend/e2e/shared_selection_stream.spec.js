import { test, expect } from '@playwright/test'
import path from 'node:path'
import { createPreparedHost } from '../../scripts/prepared_view_host.mjs'

// In-memory room and screenshots only; no designs or sharing credentials saved.
test('selection changes, deselection and late joins keep guest scenes and Follow intact', async ({ page, browser }) => {
  test.setTimeout(90000)
  await page.goto('/viewer.html?test=1')
  const bytes = await page.evaluate(async () => {
    const THREE = await import('/node_modules/.vite/deps/three.js')
    const { prepareScene } = await import('/src/viewer/prepared_scene.js')
    const { createClusterSelection, installSelectionTint } = await import('/src/scene/selection_tint.js')
    const scene = new THREE.Scene(), mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(2,2,2), new THREE.MeshBasicMaterial({ color: 0x777777 }), 3)
    for (let i = 0; i < 3; i++) mesh.setMatrixAt(i, new THREE.Matrix4().makeTranslation(i * 4, 0, 0))
    installSelectionTint(mesh); scene.add(mesh)
    const cloud = new THREE.Points(new THREE.BufferGeometry().setAttribute('position', new THREE.Float32BufferAttribute([0,0,0], 3)), new THREE.PointsMaterial())
    cloud.userData.presentationSelection = 'points'; cloud.visible = false; scene.add(cloud)
    const view = { selection: null }, layer = createClusterSelection(scene)
    const camera = { position: [4,0,20], target: [4,0,0], up: [0,1,0], fov: 55, near: .1, far: 1000, orbitMode: 'orbit' }
    window.selectionFixture = { scene, mesh, cloud, view, layer, camera }
    return Array.from(new Uint8Array(prepareScene({ scene, view, camera })))
  })
  const host = await createPreparedHost({ dist: path.resolve(import.meta.dirname, '../dist') }), guests = [], failures = []
  try {
    await new Promise(resolve => host.server.listen(0, '127.0.0.1', resolve))
    const base = `http://127.0.0.1:${host.server.address().port}`; host.setPublicBase(base)
    const share = host.createShare(Buffer.from(bytes)), headers = { Authorization: `Bearer ${host.controlToken}` }
    const post = async (action, value) => {
      const response = await fetch(`${base}/host/shares/${share.id}/broadcast/${action}`, { method: 'POST', headers, body: JSON.stringify(value) })
      expect(response.ok, await response.clone().text()).toBe(true); return response.json()
    }
    const started = await post('start', {}); headers['X-NADOC-Broadcast'] = started.lease
    await post('camera', { revision: share.revision, camera: await page.evaluate(() => window.selectionFixture.camera) })
    const sceneRequests = []
    const join = async name => {
      const guest = await browser.newPage(); guests.push(guest)
      let joined = false
      guest.on('pageerror', error => failures.push(error.message))
      guest.on('console', msg => { if (msg.type() === 'error' && (joined || !msg.text().includes('401 (Unauthorized)'))) failures.push(msg.text()) })
      guest.on('request', request => { if (/\/scene(?:\?|$)/.test(request.url())) sceneRequests.push(request.url()) })
      await guest.goto(share.url); await guest.locator('#guest-name').fill(name); await guest.locator('#join-submit').click()
      await expect(guest.locator('#status')).toContainText('Static snapshot'); joined = true
      return guest
    }
    for (let i = 0; i < 3; i++) await join(`Guest ${i}`)
    const first = guests[0]; await first.locator('[data-follow]').click()
    await expect(first.locator('[data-follow]')).toHaveAttribute('aria-pressed', 'true')
    const baselineRequests = sceneRequests.length, before = await first.locator('canvas').first().screenshot()
    const change = async selected => {
      const payload = await page.evaluate(async selected => {
        const { captureSelectionUpdate } = await import('/src/viewer/selection_update.js')
        const f = window.selectionFixture
        f.cloud.visible = selected
        f.view.selection = selected ? { target: f.cloud.uuid, revision: 1, label: 'Cluster one', ping: null } : null
        if (selected) f.layer.setGroups([[{ instMesh: f.mesh, id: 0 }]])
        else f.layer.clear()
        return captureSelectionUpdate(f).payload
      }, selected)
      await post('selection', { ...payload, revision: share.revision, id: selected ? 'select-one' : 'clear-one' })
    }
    await change(true)
    for (const guest of guests) await expect(guest.locator('.shared-selection-label')).toContainText('Cluster one')
    expect((await first.locator('canvas').first().screenshot()).equals(before)).toBe(false)
    expect(sceneRequests.length).toBe(baselineRequests)
    await expect(first.locator('[data-follow]')).toHaveAttribute('aria-pressed', 'true')
    const late = await join('Late guest'); await expect(late.locator('.shared-selection-label')).toContainText('Cluster one')
    const target = await page.evaluate(() => window.selectionFixture.cloud.uuid)
    await post('selection-ping', { revision: share.revision, target, selectionRevision: 1, ping: { id: 'ping-one', createdAt: Date.now() } })
    for (const guest of guests) await expect(guest.locator('main > .selection-ping')).toBeVisible()
    await change(false)
    for (const guest of guests) await expect(guest.locator('.shared-selection-label')).toBeHidden()
    expect(sceneRequests.length).toBe(baselineRequests + 1)
    await expect(first.locator('[data-follow]')).toHaveAttribute('aria-pressed', 'true')
    expect(failures).toEqual([])
  } finally { for (const guest of guests) await guest.close(); host.stop() }
})
