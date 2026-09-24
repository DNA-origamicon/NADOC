import { test, expect } from '@playwright/test'

test('exports sequence and overhang canvas labels into self-contained guest textures', async ({ page }) => {
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
  await page.goto('/viewer.html?test=1')
  const result = await page.evaluate(async () => {
    const THREE = await import('/node_modules/.vite/deps/three.js')
    const { initSequenceOverlay } = await import('/src/scene/sequence_overlay.js')
    const { initOverhangNameOverlay } = await import('/src/scene/overhang_name_overlay.js')
    const { prepareScene, loadPreparedScene } = await import('/src/viewer/prepared_scene.js')
    const { decodeContainer } = await import('/src/viewer/package_container.js')
    const listeners = []
    const scene = new THREE.Scene(), store = { getState: () => ({ showSequences: true }), subscribe(fn) { listeners.push(fn) } }
    const sequences = initSequenceOverlay(scene, store), overhangs = initOverhangNameOverlay(scene, store)
    const geometry = [...'ATGC'].map((letter, i) => ({ helix_id: 'h1', bp_index: i, direction: 'FORWARD', strand_id: 's1', overhang_id: 'oh1', backbone_position: [0, 0, i], base_normal: [1, 0, 0] }))
    const design = { strands: [{ id: 's1', strand_type: 'staple', sequence: 'ATGC', domains: [{ helix_id: 'h1', start_bp: 0, end_bp: 4, direction: 'FORWARD' }] }], overhangs: [{ id: 'oh1', label: 'Capture A' }] }
    listeners.forEach(fn => fn({ currentGeometry: geometry, currentDesign: design, currentHelixAxes: {}, showSequences: true }, {}))
    overhangs.rebuild(geometry, design); overhangs.setVisible(true)
    const camera = { position: [10, 0, 2], target: [0, 0, 2], up: [0, 1, 0], fov: 55, orbitMode: 'orbit' }
    const bytes = prepareScene({ scene, camera }), data = decodeContainer(bytes), guest = await loadPreparedScene(bytes)
    const labels = [], images = []
    guest.scene.traverse(o => {
      if (o.name.startsWith('seqLabel_')) labels.push(o.name)
      if (o.material?.map) images.push([o.material.map.image.width, o.material.map.image.height])
    })
    await window.__preparedViewer.loadFile(new File([bytes], 'labels.nadocview'))
    // Verify shader compilation and canvas texture decoding in the actual guest renderer.
    window.__preparedViewer.runtime.renderer.render(window.__preparedViewer.runtime.scene, window.__preparedViewer.runtime.camera)
    sequences.setVisible(false); overhangs.setVisible(false)
    const hidden = decodeContainer(prepareScene({ scene, camera }))
    guest.dispose(); sequences.dispose(); overhangs.dispose()
    return { labels, images, embedded: data.images.every(i => i.url.startsWith('data:image/png;base64,')), hiddenImages: hidden.images.length }
  })
  expect(result.labels.sort()).toEqual(['seqLabel_A', 'seqLabel_C', 'seqLabel_G', 'seqLabel_T'])
  expect(result.images).toHaveLength(5)
  expect(result.images.every(([w, h]) => w > 0 && h > 0)).toBe(true)
  expect(result.embedded).toBe(true)
  expect(result.hiddenImages).toBe(0)
  expect(errors).toEqual([])
})

test('guest cube and roll controls navigate independently while view labels persist', async ({ page }) => {
  await page.goto('/viewer.html?test=1')
  await page.evaluate(async () => {
    const THREE = await import('/node_modules/.vite/deps/three.js')
    const { prepareScene } = await import('/src/viewer/prepared_scene.js')
    const { captureViewTools } = await import('/src/viewer/shared_view_tools.js')
    const scene = new THREE.Scene(); scene.add(new THREE.Mesh(new THREE.BoxGeometry(5, 5, 5), new THREE.MeshBasicMaterial()))
    const camera = { position: [10,8,20], target: [0,0,0], up: [0,1,0], fov: 55, orbitMode: 'trackball' }
    const view = { viewTools: { ...captureViewTools(document), sequences: true, lengthHeatmap: true }, visualization: {
      engine: 'oxdna', jobId: 'run-1', jobName: 'PEG trial', runDate: '2026-09-20T12:34:00.000Z', mode: 'Flexibility map (RMSF)',
    } }
    await window.__preparedViewer.loadFile(new File([prepareScene({ scene, camera, view })], 'labels.nadocview'))
  })
  await expect(page.locator('#vc-wrap')).toBeVisible()
  await expect(page.locator('#vc-roll')).toBeVisible()
  const label = page.locator('.shared-view-tools')
  await expect(label).toContainText('PEG trial'); await expect(label).toContainText('2026')
  await expect(label).toContainText('Flexibility map (RMSF)'); await expect(label).toContainText('Sequences')
  await page.locator('.vc-r').evaluate(el => el.click())
  await expect.poll(() => page.evaluate(() => {
    const p = window.__preparedViewer.captureCamera().position
    return p[0] > 5 && Math.abs(p[1]) < .01 && Math.abs(p[2]) < .01
  })).toBe(true)
  const before = await page.evaluate(() => window.__preparedViewer.captureCamera().up)
  await page.locator('.vc-roll-btn').first().click()
  await expect.poll(() => page.evaluate(before => {
    const up = window.__preparedViewer.captureCamera().up
    return up.reduce((n, x, i) => n + Math.abs(x - before[i]), 0) > 1
  }, before)).toBe(true)
  await expect(label).toContainText('PEG trial')
  await page.evaluate(() => window.__preparedViewer.clear())
  await expect(page.locator('#vc-wrap')).toBeHidden(); await expect(label).toBeHidden()
})
