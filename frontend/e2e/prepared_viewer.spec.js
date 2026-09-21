import { test, expect } from '@playwright/test'
import { readFile, writeFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import path from 'node:path'
import { cleanupProjectArtifacts } from './project_artifact_cleanup.js'
import { loadScaffoldedPart, trackConsoleErrors } from './helpers/scene_harness.js'

// Persistence: __e2e__prepared_viewer part + project store cleaned by existing global
// teardown, even on failure. Download only in testInfo.outputPath (runner-owned).
let bootProjectId
test.afterEach(async ({ page }) => {
  await page.close()
  if (bootProjectId) await cleanupProjectArtifacts(path.resolve(import.meta.dirname, '../../workspace'), [bootProjectId])
  bootProjectId = null
})

test(process.env.NADOC_PREPARED_FIXTURE ? 'round-trips the large Full scene with identical pixels and no editor API' : 'exports native Full geometry and opens it without any editor API in the standalone viewer', async ({ page, context }, testInfo) => {
  test.setTimeout(240000)
  const errors = trackConsoleErrors(page)
  await loadScaffoldedPart(page, { doc: '__e2e__prepared_viewer', name: process.env.NADOC_PREPARED_FIXTURE ? 'prepared_viewer_boot' : 'prepared_viewer' })
  if (process.env.NADOC_PREPARED_FIXTURE) {
    const source = await readFile(process.env.NADOC_PREPARED_FIXTURE)
    const hash = createHash('sha256').update(source).digest('hex')
    bootProjectId = await page.evaluate(() => window.__nadocTest.viewerDiagnostic().designId)
    const design = JSON.parse(source)
    design.id = '__e2e__prepared_viewer'; design.feature_log = []
    design.metadata = { ...design.metadata, name: '__e2e__prepared_viewer', identity_last_known_path: '__e2e__prepared_viewer.nadoc' }
    const response = await page.request.post(`${process.env.NADOC_E2E_API_BASE}/api/design/import`, { headers: { 'X-NADOC-Doc': '__e2e__prepared_viewer' }, data: { content: JSON.stringify(design) }, timeout: 90000 })
    expect(response.ok()).toBe(true)
    await page.evaluate(async () => { const api = await import('/src/api/client.js'); await api.getDesign(); await api.getGeometry() })
    await page.waitForFunction(() => window.__nadocTest.scene.getObjectByName('proteinTraceRoot')?.children.length > 0 && window.__nadocTest.scene.getObjectByName('nanoparticles')?.children.length > 0, null, { timeout: 60000 })
    expect(createHash('sha256').update(await readFile(process.env.NADOC_PREPARED_FIXTURE)).digest('hex')).toBe(hash)
  }
  await page.evaluate(() => {
    const entries = window.__nadocTest.getDesignRenderer().getBackboneEntries()
    const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity]
    for (const entry of entries) for (let i = 0; i < 3; i++) { lo[i] = Math.min(lo[i], entry.nuc.backbone_position[i]); hi[i] = Math.max(hi[i], entry.nuc.backbone_position[i]) }
    const center = lo.map((v, i) => (v + hi[i]) / 2), size = Math.max(...hi.map((v, i) => v - lo[i])) + 10
    window.__nadocTest.applyCameraPoseForTest({ position: [center[0] + size, center[1] + size * .4, center[2] + size], target: center, up: [0, 1, 0], fov: 55 })
    document.querySelector('#canvas').parentElement.style.cssText = 'flex:none;width:800px;height:600px;position:relative'
  })
  await page.waitForTimeout(1000)
  const sourceImage = await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => resolve(document.querySelector('#canvas').toDataURL()))))
  await writeFile(testInfo.outputPath('editor.png'), Buffer.from(sourceImage.split(',')[1], 'base64'))
  if (process.env.NADOC_PREPARED_FIXTURE) await page.evaluate(() => window.__nadocTest.pauseViewerRenderingForTest())
  // Fail immediately with the export diagnostic rather than timing out on download.
  const diagnostic = await page.evaluate(async () => {
    const { prepareScene } = await import('/src/viewer/prepared_scene.js')
    try { prepareScene({ scene: window.__nadocTest.scene, camera: { position: [10, 4, 20], target: [0, 0, 0], up: [0, 1, 0], fov: 55, orbitMode: 'multiscale' } }); return null }
    catch (error) {
      const materials = new Set()
      window.__nadocTest.scene.traverseVisible(o => { if (o.material) for (const m of Array.isArray(o.material) ? o.material : [o.material]) materials.add(`${o.name}:${o.type}:${m.type}`) })
      return `${error.message}\n${[...materials].join('\n')}`
    }
  })
  expect(diagnostic).toBeNull()
  await page.locator('#menu-item-export').hover()
  const download = page.waitForEvent('download', { timeout: 15000 })
  if (process.env.NADOC_PREPARED_FIXTURE) await page.locator('#menu-file-export-viewer').evaluate(el => el.click())
  else await page.locator('#menu-file-export-viewer').click()
  const file = await download
  const path = testInfo.outputPath('scene.nadocview'); await file.saveAs(path)
  const buffer = await readFile(path)
  console.log('[prepared package]', JSON.stringify({ bytes: buffer.length, source: process.env.NADOC_PREPARED_FIXTURE ?? 'small Full fixture' }))
  expect(buffer.length).toBeGreaterThan(1000)
  await page.goto('about:blank') // Only one renderer active during the package check.
  const viewer = await context.newPage(), requests = []
  viewer.on('request', request => { if (/\/api\/|\/ws\b/.test(request.url())) requests.push(request.url()) })
  const viewerErrors = trackConsoleErrors(viewer)
  await viewer.route('**/api/**', route => route.abort())
  await viewer.goto('/viewer.html?test=1')
  await viewer.locator('main').evaluate(el => { el.style.cssText = 'flex:none;width:800px;height:600px;position:relative' })
  await viewer.locator('#file').setInputFiles({ name: 'scene.nadocview', mimeType: 'application/octet-stream', buffer })
  await expect(viewer.locator('#status')).toContainText('Static snapshot')
  await expect(viewer.locator('#title')).toContainText('__e2e__prepared_viewer')
  if (process.env.NADOC_PREPARED_FIXTURE) {
    expect(await viewer.evaluate(() => window.__preparedViewer.current.scene.getObjectByName('proteinTraceRoot')?.children.length)).toBeGreaterThan(0)
    expect(await viewer.evaluate(() => window.__preparedViewer.current.scene.getObjectByName('nanoparticles')?.children.length)).toBeGreaterThan(0)
  }
  await viewer.waitForTimeout(1000)
  const packageImage = await viewer.evaluate(() => new Promise(resolve => requestAnimationFrame(() => resolve(document.querySelector('#canvas').toDataURL()))))
  await writeFile(testInfo.outputPath('viewer.png'), Buffer.from(packageImage.split(',')[1], 'base64'))
  console.log('[prepared pixels]', JSON.stringify({ identical: sourceImage === packageImage }))
  expect(createHash('sha256').update(packageImage).digest('hex')).toBe(createHash('sha256').update(sourceImage).digest('hex'))
  if (process.env.NADOC_PREPARED_FIXTURE) {
    // SwiftShader cannot provide meaningful interactive performance for 6M triangles.
    // This opt-in probe owns static visual parity only; the small test below owns
    // real pointer gestures. Large-design interactive acceptance belongs on the GPU.
    expect(requests).toEqual([]); expect(errors).toEqual([]); expect(viewerErrors).toEqual([])
    await viewer.evaluate(() => window.__preparedViewer.dispose())
    await viewer.close()
    return
  }
  const before = await viewer.evaluate(() => {
    const v = window.__preparedViewer
    let instances = 0; v.current.scene.traverse(o => { if (o.isInstancedMesh) instances += o.count })
    return { instances, position: v.runtime.camera.position.toArray() }
  })
  expect(before.instances).toBeGreaterThan(100)
  const canvas = viewer.locator('#canvas'), box = await canvas.boundingBox()
  await viewer.mouse.move(box.x + box.width * .5, box.y + box.height * .5)
  await viewer.mouse.down(); await viewer.mouse.move(box.x + box.width * .7, box.y + box.height * .6, { steps: 12 }); await viewer.mouse.up()
  const after = await viewer.evaluate(() => window.__preparedViewer.runtime.camera.position.toArray())
  expect(after).not.toEqual(before.position)
  await viewer.locator('#reset').click()
  expect(await viewer.evaluate(() => window.__preparedViewer.runtime.camera.position.toArray())).toEqual(before.position)
  await viewer.locator('#file').setInputFiles({ name: 'broken.nadocview', mimeType: 'application/octet-stream', buffer: Buffer.from('invalid') })
  await expect(viewer.locator('#status')).toContainText('Could not open')
  expect(await viewer.evaluate(() => !!window.__preparedViewer.current)).toBe(true)
  expect(requests).toEqual([]); expect(errors).toEqual([]); expect(viewerErrors).toEqual([])
  await viewer.close()
})
