import { test, expect } from '@playwright/test'
import { readFileSync, writeFileSync } from 'node:fs'
import { createHash } from 'node:crypto'

// Read-only specimen published/replayed by scripts.extension_slab_fixture. No app saves.
// Only screenshots/metrics in Playwright's output; isolated server scratch and
// Vite bridge credentials are removed by the runner/global teardown on failure.
const source = process.env.NADOC_EXTENSION_SLAB_FIXTURE
const hash = () => createHash('sha256').update(readFileSync(source)).digest('hex')

test.skip(!source, 'Run with the replay-verified extension slab fixture')

test('extension Full slabs overlay the existing atomic rings', async ({ page }, info) => {
  const original = hash(), errors = []
  page.on('pageerror', e => errors.push(e.message))
  try {
    await page.goto('/?test=1&doc=__e2e__extension-slabs')
    await page.evaluate(async source => {
      await (await import('/src/api/client.js')).loadDesign(source)
      document.getElementById('welcome-screen')?.classList.add('hidden')
    }, source)
    await expect.poll(() => page.evaluate(() => window.__nadocTest?.store.getState().currentGeometry?.length ?? 0)).toBeGreaterThan(0)
    await page.evaluate(() => window.__nadocTest.configureMultiOverlay({
      count: 2, representations: ['full', 'ballstick'], colorings: ['strand', 'cpk'], opacities: [.4, 1], separation: 0,
    }))
    await expect(page.locator('.mo-layer-row[data-ready="true"]')).toHaveCount(2, { timeout: 120000 })
    const result = await page.evaluate(async () => {
      const THREE = await import('/node_modules/three/build/three.module.js')
      const { docHeaders } = await import('/src/shared/doc_id.js')
      const { atoms } = await (await fetch('/api/design/atomistic', { headers: docHeaders() })).json()
      const records = window.__nadocTest.store.getState().currentGeometry.filter(n => n.extension_id && !n.is_modification)
      const layer = window.__nadocTest.comparisonScenesForTest().overlays.find(l => l.representation === 'full')
      const rendered = [], m = new THREE.Matrix4(), p = new THREE.Vector3(), q = new THREE.Quaternion(), s = new THREE.Vector3()
      layer.renderScene.traverseVisible(o => {
        if (o.name !== 'baseSlabs') return
        for (let i = 0; i < o.count; i++) {
          o.getMatrixAt(i, m); m.decompose(p, q, s)
          if (s.lengthSq() > 1e-10) rendered.push({ p: p.clone(), q: q.clone() })
        }
      })
      const metrics = records.map(n => {
        const residue = atoms.filter(a => a.extension_id === n.extension_id && a.ext_k === n.bp_index)
        const names = residue.some(a => a.name === 'N9') ? ['N9','C8','N7','C5','C6','N1','C2','N3','C4'] : ['N1','C2','N3','C4','C5','C6']
        const ring = names.map(name => { const a = residue.find(a => a.name === name); return new THREE.Vector3(a.x,a.y,a.z) })
        const center = ring.reduce((v,a) => v.add(a), new THREE.Vector3()).multiplyScalar(1/ring.length)
        const slab = rendered.reduce((best, x) => !best || x.p.distanceTo(center) < best.p.distanceTo(center) ? x : best, null)
        const normal = new THREE.Vector3(0,1,0).applyQuaternion(slab.q)
        const ringNormal = ring[1].clone().sub(ring[0]).cross(ring[2].clone().sub(ring[0])).normalize()
        return { extension: n.extension_id, center: center.toArray(), distance: slab.p.distanceTo(center),
          angle: Math.acos(Math.min(1,Math.abs(normal.dot(ringNormal)))) * 180/Math.PI,
          normal: normal.toArray(), along: new THREE.Vector3(0,0,1).applyQuaternion(slab.q).toArray() }
      })
      return { metrics, rendered: rendered.length, records: records.length }
    })
    expect(result.records).toBeGreaterThan(0)
    expect(result.metrics.every(m => m.distance < 2e-5 && m.angle < 1)).toBe(true)
    writeFileSync(info.outputPath('alignment.json'), JSON.stringify(result, null, 2))
    await info.attach('alignment', { body: JSON.stringify(result), contentType: 'application/json' })
    for (const [index, target] of result.metrics.slice(0, 2).entries()) {
      // Reversible observation crop: keep real instance poses within 0.65 nm
      // of this ring, removing foreground residues that occlude the close-up.
      await page.evaluate(async center => {
        const THREE = await import('/node_modules/three/build/three.module.js')
        const focus = new THREE.Vector3(...center), m = new THREE.Matrix4(), p = new THREE.Vector3()
        for (const layer of window.__nadocTest.comparisonScenesForTest().overlays) layer.renderScene?.traverse(o => {
          if (!o.isInstancedMesh) { if (o.isMesh || o.isLine) o.visible = false; return }
          o.userData.auditMatrices ??= o.instanceMatrix.array.slice()
          o.instanceMatrix.array.set(o.userData.auditMatrices)
          for (let i = 0; i < o.count; i++) {
            o.getMatrixAt(i, m); p.setFromMatrixPosition(m)
            if (p.distanceTo(focus) > .65) o.setMatrixAt(i, new THREE.Matrix4().makeScale(0,0,0))
          }
          o.instanceMatrix.needsUpdate = true
        })
      }, target.center)
      for (const view of ['face','edge']) {
        const offset = target.normal.map((n,i) => view === 'face' ? 3*n + .7*target.along[i] : .45*n + 3*target.along[i])
        await page.evaluate(({center,offset}) => window.__nadocTest.applyCameraPoseForTest({
          position: center.map((v,i) => v + offset[i]), target: center, fov: 30,
        }), { center: target.center, offset })
        await page.waitForTimeout(300)
        await page.locator('#canvas').screenshot({ path: info.outputPath(`extension-${index}-${view}.png`) })
      }
    }
    expect(errors).toEqual([])
  } finally { expect.soft(hash()).toBe(original) }
})
