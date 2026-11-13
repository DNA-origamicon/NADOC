import { test, expect } from '@playwright/test'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

// Read-only legacy diagnosis. No parts, assemblies or jobs are authored/saved.
// Server workspace/session/cache isolation belongs to the config and runner.
// Only Playwright's configured output directory receives screenshots/traces.
const source = fileURLToPath(new URL('../../workspace/duplex.nadoc', import.meta.url))
const hash = () => createHash('sha256').update(readFileSync(source)).digest('hex')

async function positions(page) {
  return page.evaluate(async () => {
    const THREE = await import('/node_modules/three/build/three.module.js')
    return window.__nadocTest.comparisonScenesForTest().overlays.filter(l => l.renderScene).map(layer => {
      const points = [], p = new THREE.Vector3(), m = new THREE.Matrix4()
      layer.renderScene.traverseVisible(obj => {
        const repr = layer.effectiveRepresentation ?? layer.representation
        const selected = ['full','beads'].includes(repr) ? obj.name === 'backboneSpheres'
          : repr === 'surface' ? obj.name === 'dna-surface'
          : repr === 'oxdna' ? obj.userData?.oxdnaPrimitive === 'backbone'
          : repr.startsWith('mrdna-') ? obj.isInstancedMesh && obj.geometry?.type === 'SphereGeometry'
          : obj.name === 'atomSpheres' || (repr === 'stick' && obj.name === 'atomBonds')
        if (!selected) return
        if (obj.isInstancedMesh) for (let i = 0; i < obj.count; i++) {
          obj.getMatrixAt(i, m); p.setFromMatrixPosition(m); points.push(p.toArray())
        }
        else {
          const a = obj.geometry?.attributes.position
          for (let i = 0; i < (a?.count ?? 0); i++) points.push([a.getX(i), a.getY(i), a.getZ(i)])
        }
      })
      const center = [0,1,2].map(axis => points.reduce((sum,p) => sum+p[axis], 0) / points.length)
      return { representation: layer.representation, count: points.length, center }
    })
  })
}
async function ready(page) {
  await expect(page.locator('.mo-layer-row[data-ready="true"]')).toHaveCount(4, { timeout: 90000 })
  await page.waitForTimeout(150)
}
async function moved(page, baseline, dx) {
  await expect.poll(async () => (await positions(page)).map((layer,i) => layer.count > 0 && Math.abs(layer.center[0] - baseline[i].center[0] - dx) < .03), { timeout: 90000 })
    .toEqual([true,true,true,true])
  await ready(page)
}

test('all overlay layers follow oxDNA display, job trajectory, and off at a fixed camera', async ({ page }, info) => {
  const original = hash(), errors = []
  page.on('pageerror', error => errors.push(error.message))
  let frame
  const shifted = dx => frame.map(n => ({ ...n, backbone_position: [n.backbone_position[0]+dx, ...n.backbone_position.slice(1)] }))
    // Display MD uses its real WebSocket controller with in-memory frame replies.
    // No manifest, trajectory file or simulation process is created.
    let mdOffset = 4
    await page.routeWebSocket(/\/ws\/md-run(?:\?|$)/, ws => {
      ws.onMessage(raw => {
        const message = JSON.parse(raw)
        if (message.action === 'load') ws.send(JSON.stringify({ type: 'ready', n_frames: 2, n_p_atoms: frame.length }))
        else if (['get_latest','seek'].includes(message.action)) ws.send(JSON.stringify({
          type: 'frame', frame_idx: mdOffset === 4 ? 0 : 1, n_frames: 2,
          positions: shifted(mdOffset).map(n => ({ ...n, x: n.backbone_position[0], y: n.backbone_position[1], z: n.backbone_position[2] })),
        }))
      })
    })
  try {
    await page.goto('/?test=1&doc=__e2e__multi-overlay-simulation')
    await page.evaluate(async source => {
      await (await import('/src/api/client.js')).loadDesign(source)
      document.getElementById('welcome-screen')?.classList.add('hidden')
    }, source)
    await expect.poll(() => page.evaluate(() => window.__nadocTest?.store.getState().currentGeometry?.length ?? 0)).toBeGreaterThan(0)
    await page.evaluate(() => window.__nadocTest.configureMultiOverlay({
      count: 4, representations: ['beads','surface','oxdna','mrdna-fine'], opacities: [1,.6,1,1], separation: .7,
    }))
    await ready(page)
    await page.evaluate(() => window.__nadocTest.applyCameraPoseForTest({ position: [28,34,65], target: [0,0,7] }))
    const baseline = await positions(page)
    expect(baseline.every(l => l.count > 0)).toBe(true)
    const native = await page.locator('#canvas').screenshot({ path: info.outputPath('off.png') })
    frame = await page.evaluate(() => window.__nadocTest.store.getState().currentGeometry.map(n => ({
      helix_id: n.helix_id, bp_index: n.bp_index, direction: n.direction, copy: n.copy ?? 0,
      backbone_position: n.backbone_position, nx: n.base_normal[0], ny: n.base_normal[1], nz: n.base_normal[2],
      tx: n.axis_tangent[0], ty: n.axis_tangent[1], tz: n.axis_tangent[2],
    })))
    await page.evaluate(p => window.__nadocOxdnaDisplay.displayLiveFrame(p), shifted(4))
    await moved(page, baseline, 4)
    const on = await page.locator('#canvas').screenshot({ path: info.outputPath('oxdna-live-on.png') })
    expect(on.equals(native)).toBe(false)
    await page.evaluate(p => window.__nadocOxdnaDisplay.displayLiveFrame(p), shifted(-3))
    await moved(page, baseline, -3)
    await page.locator('#canvas').screenshot({ path: info.outputPath('oxdna-next-frame.png') })
    await page.evaluate(() => window.__nadocOxdnaDisplay.stopAndRestore())
    await moved(page, baseline, 0)

    // Real job controller and asynchronous surface transport, intercepted solely
    // to avoid submitting a simulation or creating persisted job artifacts.
    const surface = await page.evaluate(async () => {
      const { docHeaders } = await import('/src/shared/doc_id.js')
      return (await fetch('/api/design/surface?detail=coarse&probe_radius=0.06', { headers: docHeaders() })).json()
    })
    const meshAt = dx => ({ ...surface, vertices: surface.vertices.map((v,i) => i%3 === 0 ? v+dx : v) })
    const frames = [4,-3].map(dx => shifted(dx).flatMap(n => [...n.backbone_position,n.nx,n.ny,n.nz,n.tx,n.ty,n.tz]))
    await page.route('**/api/oxdna/jobs/__e2e__overlay/**', async route => {
      const url = new URL(route.request().url()), endpoint = url.pathname.split('/').at(-1)
      let json
      if (endpoint === 'display') json = { ready: true, positions: shifted(4) }
      else if (endpoint === 'display-surface') { await new Promise(resolve => setTimeout(resolve, 100)); json = { ready: true, surface: meshAt(4) } }
      else if (endpoint === 'trajectory-meta') json = { n_frames: 2, stages: [], markers: [] }
      else if (endpoint === 'trajectory') {
        const header = Buffer.from(JSON.stringify({ ready: true, n_frames: 2, n_nucleotides: frame.length,
          keys: frame.map(n => [n.helix_id,n.bp_index,n.direction,n.copy]), stages: [], markers: [] }))
        const offset = (12 + header.length + 3) & ~3
        const body = Buffer.alloc(offset + frames.flat().length * 4)
        body.write('NADOTR1\0'); body.writeUInt32LE(header.length, 8); header.copy(body, 12)
        frames.flat().forEach((value,i) => body.writeFloatLE(value, offset + i*4))
        return route.fulfill({ contentType: 'application/octet-stream', body })
      }
      else if (endpoint === 'frames-surface') {
        json = Object.fromEntries(route.request().postDataJSON().frame_indices.map(i => [String(i),meshAt(i ? -3 : 4)]))
      } else if (endpoint.endsWith('progress')) json = { active: false }
      else return route.fulfill({ status: 404, json: { detail: 'No binary fixture' } })
      await route.fulfill({ json })
    })
    await page.evaluate(() => window.__nadocOxdnaDisplay.displayJob('__e2e__overlay'))
    await moved(page, baseline, 4)
    await page.locator('#canvas').screenshot({ path: info.outputPath('oxdna-job-on.png') })
    expect(await page.evaluate(() => window.__nadocOxdnaDisplay.loadTrajectory('__e2e__overlay', true, 'job', 1, null, { frameStart: 0, frameEnd: 1 }))).toMatchObject({ ok: true })
    await moved(page, baseline, 4)
    await page.evaluate(() => window.__nadocOxdnaDisplay.showFrame(1))
    await moved(page, baseline, -3)
    await page.locator('#canvas').screenshot({ path: info.outputPath('job-trajectory-frame-2.png') })
    await page.evaluate(() => window.__nadocOxdnaDisplay.stopAndRestore())
    await moved(page, baseline, 0)
    await page.locator('#canvas').screenshot({ path: info.outputPath('restored-off.png') })
    await page.evaluate(() => window.__nadocMdDisplay.displayLatest('__e2e__in-memory.json', { jobId: '__e2e__md-overlay', live: false }))
    await moved(page, baseline, 4)
    await page.locator('#canvas').screenshot({ path: info.outputPath('display-md-on.png') })
    mdOffset = -3
    await page.evaluate(() => window.__nadocMdDisplay.applyTrajectoryCommand({ action: 'seek', frameIdx: 1 }))
    await moved(page, baseline, -3)
    await page.evaluate(() => window.__nadocMdDisplay.stopDisplayKeepWarm())
    await moved(page, baseline, 0)

    // The remaining supported styles use the same layer-refresh path.
    await page.evaluate(() => window.__nadocTest.configureMultiOverlay({
      count: 4, representations: ['full','vdw','ballstick','stick'], separation: .7,
    }))
    await ready(page)
    await page.evaluate(() => window.__nadocTest.applyCameraPoseForTest({ position: [28,34,65], target: [0,0,7] }))
    const atomicBaseline = await positions(page)
    expect(atomicBaseline.every(l => l.count > 0)).toBe(true)
    await page.evaluate(p => window.__nadocOxdnaDisplay.displayLiveFrame(p), shifted(4))
    await moved(page, atomicBaseline, 4)
    await page.locator('#canvas').screenshot({ path: info.outputPath('full-and-atomic-on.png') })
    await page.evaluate(() => window.__nadocOxdnaDisplay.stopAndRestore())
    await moved(page, atomicBaseline, 0)
    await page.evaluate(() => window.__nadocTest.configureMultiOverlay({
      count: 4, representations: ['beads','mrdna-coarse','mrdna-fine','oxdna'], separation: .7,
    }))
    await ready(page)
    await page.evaluate(() => window.__nadocTest.applyCameraPoseForTest({ position: [28,34,65], target: [0,0,7] }))
    const coarseBaseline = await positions(page)
    await page.evaluate(p => window.__nadocOxdnaDisplay.displayLiveFrame(p), shifted(4))
    await moved(page, coarseBaseline, 4)
    await page.locator('#canvas').screenshot({ path: info.outputPath('all-coarse-on.png') })
    await page.evaluate(() => window.__nadocOxdnaDisplay.stopAndRestore())
    await moved(page, coarseBaseline, 0)
    expect(errors).toEqual([])
  } finally { expect(hash()).toBe(original) }
})
