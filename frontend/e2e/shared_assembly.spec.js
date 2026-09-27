import { readFileSync } from 'node:fs'
import { test, expect } from '@playwright/test'
import { trackConsoleErrors } from './helpers/scene_harness.js'

// Files/history use __e2e__; global teardown removes them even on failure.
// Transport is intercepted, so no public host or room is created.
test('assembly invitation mirrors transforms, visibility, selection and deletion with an independent guest camera', async ({ page, context }) => {
  test.setTimeout(180000)
  const errors = trackConsoleErrors(page), packets = []
  const room = { id: 'assembly-room', title: 'Assembly', url: 'http://example.invalid/view', expiresAt: Date.now() + 3600000 }
  await page.route('**/__nadoc_share/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/create') || path.endsWith('/content')) {
      packets.push(route.request().postDataBuffer()); await route.fulfill({ json: room })
    } else await route.fulfill({ json: { running: true, shares: packets.length ? [room] : [],
      capabilities: ['share-content-v1', 'editor-broadcast-v1', 'view-tools-v1', 'annotations-v1', 'selection-ping-v1', 'sphere-impostors-v1', 'multi-overlay-v1', 'hull-cutouts-v1', 'guest-visualizations-v1'] } })
  })
  const design = JSON.parse(readFileSync(new URL('../../Examples/2hb_xover_atoms_test.nadoc', import.meta.url)))
  design.id = '__e2e__shared_assembly_part'; design.metadata.name = '__e2e__shared_assembly_part'
  await page.goto('/?doc=__e2e__shared_assembly')
  await page.waitForFunction(() => !!window.__nadocTest)
  const ids = await page.evaluate(async design => {
    const api = await import('/src/api/client.js')
    await api.importDesign(JSON.stringify(design)); await api.getGeometry()
    await api.saveDesign('workspace/__e2e__shared_assembly_part.nadoc')
    await api.createAssembly('__e2e__shared_assembly')
    for (let i = 0; i < 2; i++) await api.addInstance({ source: { type: 'file', path: '__e2e__shared_assembly_part.nadoc' }, representation: 'full',
      transform: { values: [1,0,0,i*25, 0,1,0,0, 0,0,1,0, 0,0,0,1] } })
    document.getElementById('welcome-screen')?.classList.add('hidden')
    await window.__nadocTest.enterAssemblyMode()
    return window.__nadocTest.store.getState().currentAssembly.instances.map(i => i.id)
  }, design)
  await page.waitForFunction(() => {
    let found = false
    window.__nadocTest.scene.traverseVisible(o => { if (o.userData.sharedInstanced && o.count > 0) found = true })
    return found
  }, null, { timeout: 30000 })
  await page.evaluate(() => document.getElementById('menu-file-sharing').click())
  await expect(page.locator('#share-link-dialog [data-create]')).toBeEnabled()
  await page.locator('#share-link-dialog [data-create]').click()
  await expect(page.locator('#share-link-dialog [data-copy-link]')).toBeVisible().catch(async error => { throw new Error(`${error.message}\n${await page.locator('#share-link-dialog').innerText()}`) })
  await page.locator('#share-link-dialog [data-close]').click()
  const guest = await context.newPage(), guestErrors = trackConsoleErrors(guest)
  await guest.goto('/viewer.html?test=1')
  async function receive() {
    return guest.evaluate(async bytes => {
      const v = window.__preparedViewer
      if (!await v.loadFile(new File([new Uint8Array(bytes)], 'Assembly.nadocview'), { preserveCamera: true })) throw new Error(document.getElementById('status').textContent)
      const matrices = []
      v.current.scene.updateMatrixWorld(true)
      v.current.scene.traverseVisible(o => { if (o.isInstancedMesh && o.count > 0) matrices.push([o.name, o.count, [...o.instanceMatrix.array], o.matrixWorld.toArray()]) })
      return { hash: v.current.data.sourceHash, package: v.current.packageHash, view: v.current.data.view, matrices }
    }, [...packets.at(-1)])
  }
  let previous = await receive()
  expect(previous.view.assembly).toBe(true)
  expect(previous.matrices.length).toBeGreaterThan(0)
  const camera = await guest.evaluate(() => {
    const v = window.__preparedViewer, pose = v.captureCamera(); pose.position[0] += 10; v.applyCamera(pose); return v.captureCamera()
  })
  async function edit(action, arg) {
    const count = packets.length
    await page.evaluate(action, arg)
    await expect.poll(() => packets.length, { timeout: 30000 }).toBeGreaterThan(count).catch(async error => { throw new Error(`${error.message}\n${await page.locator('#share-link-dialog').textContent()}`) })
    const next = await receive()
    expect(next.package).not.toBe(previous.package)
    const currentCamera = await guest.evaluate(() => window.__preparedViewer.captureCamera())
    for (const key of ['position', 'target', 'up']) camera[key].forEach((value, i) => expect(currentCamera[key][i]).toBeCloseTo(value, 10))
    expect(currentCamera.fov).toBe(camera.fov)
    previous = next
    return next
  }
  const initialMatrices = previous.matrices
  await edit(async id => {
    const api = await import('/src/api/client.js')
    await api.patchInstance(id, { transform: { values: [1,0,0,60, 0,1,0,0, 0,0,1,0, 0,0,0,1] } })
  }, ids[1])
  expect(previous.matrices).not.toEqual(initialMatrices)
  await edit(id => window.__nadocTest.store.setState({ activeInstanceId: id }), ids[1])
  expect(previous.view.selection?.label).toContain('part')
  await edit(() => document.querySelector('[data-selection-ping]').click())
  expect(previous.view.selection.ping).toBeTruthy()
  await edit(() => window.__nadocTest.store.setState({ activeInstanceId: null, multiSelectedInstanceIds: [] }))
  expect(previous.view.selection).toBeNull()
  await edit(async id => { const api = await import('/src/api/client.js'); await api.patchInstance(id, { visible: false }) }, ids[1])
  const hidden = previous.matrices
  await edit(async id => { const api = await import('/src/api/client.js'); await api.patchInstance(id, { visible: true }) }, ids[1])
  expect(previous.matrices).not.toEqual(hidden)
  for (const representation of ['cylinders', 'hull-prism', 'full']) {
    await edit(async representation => {
      const api = await import('/src/api/client.js')
      const instances = window.__nadocTest.store.getState().currentAssembly.instances
      await api.batchPatchInstances(instances.map(i => ({ id: i.id, representation })))
    }, representation)
    expect(previous.matrices.length).toBeGreaterThan(0)
  }
  await edit(async id => { const api = await import('/src/api/client.js'); await api.duplicateInstance(id, { offset: [0, 30, 0] }) }, ids[0])
  await edit(async id => { const api = await import('/src/api/client.js'); await api.deleteInstance(id) }, ids[1])
  expect(previous.view.assembly).toBe(true)
  expect(errors).toEqual([]); expect(guestErrors).toEqual([])
})
