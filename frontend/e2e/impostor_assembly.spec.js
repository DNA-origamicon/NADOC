/**
 * Sphere impostors — Phase B verification (assembly shared-instancing path).
 *
 * Loads a full-rep assembly (poly_hin.nass — beads render, so the combined
 * impostor+transform shader is actually exercised) on the shared renderer with
 * the impostor flag on, forces close LOD, and confirms:
 *   1. the shared bead InstancedMesh is an impostor (quad geometry, isImpostor)
 *      and is rendering (count > 0),
 *   2. renderer.compile() + a render produce NO shader-compile errors (the
 *      combined center-from-textures → billboard → sphere-paint shader links),
 *   3. a screenshot for visual confirmation.
 */

import { test, expect } from '@playwright/test'
import { readFileSync } from 'fs'
import { resolve } from 'path'

const FIXTURE = resolve(process.cwd(), '..', 'workspace', 'poly_hin.nass')

test.describe('Sphere impostors — Phase B (assembly shared path)', () => {
  test('shared bead mesh renders as impostors with no shader errors', async ({ page }) => {
    const errors = []
    page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
    page.on('pageerror', e => errors.push(String(e)))

    await page.addInitScript(() => {
      localStorage.setItem('NADOC_SHARED_RENDERER', 'true')
      localStorage.setItem('NADOC_IMPOSTORS', 'true')
    })
    await page.goto('/')
    await page.waitForFunction(() => !!window.__NADOC_DBG__, null, { timeout: 15_000 })

    const nass = readFileSync(FIXTURE, 'utf-8')
    await page.evaluate(async (content) => {
      const api = await import('/src/api/client.js')
      const ok = await api.importAssembly(content)
      if (!ok) throw new Error('importAssembly returned falsy')
      const assembly = window.__NADOC_DBG__.store.getState().currentAssembly
      await window.__NADOC_DBG__.assemblyRenderer.rebuild(assembly)
    }, nass)
    await page.waitForFunction(
      () => (window.__NADOC_DBG__?.store?.getState?.()?.currentAssembly?.instances?.length ?? 0) > 0,
      null, { timeout: 30_000 })

    await page.evaluate(() => {
      document.getElementById('welcome-screen')?.style.setProperty('display', 'none')
      window.__NADOC_DBG__.store.setState({ assemblyActive: true })
    })
    await page.waitForTimeout(1500)

    const info = await page.evaluate(() => {
      const dbg = window.__NADOC_DBG__
      const { scene, renderer, camera } = dbg
      // Keep full-rep instances at the close (bp/impostor) bucket, not hull.
      dbg.setLodThresholds?.({ farPx: 0.001 })
      dbg.assemblyRenderer._updateLod?.(camera, renderer)
      renderer.compile(scene, camera)   // force every material's program to link
      renderer.render(scene, camera)
      let meshes = 0, rendering = 0, sampleVerts = -1
      scene.traverse(o => {
        if (o.isInstancedMesh && o.material?.userData?.isImpostor) {
          meshes++
          const pa = o.geometry.getAttribute('position')
          if (pa) sampleVerts = pa.count
          if (o.count > 0 && o.visible) rendering++
        }
      })
      return { meshes, rendering, sampleVerts, instances: dbg.store.getState().currentAssembly?.instances?.length ?? 0 }
    })

    // Settle, frame the camera on the assembly bbox, hide the busy overlay, and
    // re-render for a clean visual (rules out a collapsed-to-origin shader bug).
    await page.waitForTimeout(3500)
    await page.evaluate(() => {
      const dbg = window.__NADOC_DBG__
      const { scene, renderer, camera, controls, THREE } = dbg
      // Frame on instance translations (row-major transform.values[3,7,11]).
      const insts = dbg.store.getState().currentAssembly?.instances ?? []
      const box = new THREE.Box3()
      for (const inst of insts) {
        const v = inst.transform?.values
        if (v && v.length >= 12) box.expandByPoint(new THREE.Vector3(v[3], v[7], v[11]))
      }
      if (!box.isEmpty()) {
        const c = box.getCenter(new THREE.Vector3())
        const r = Math.max(box.getSize(new THREE.Vector3()).length(), 60) * 1.6
        camera.position.set(c.x + r * 0.7, c.y + r * 0.4, c.z + r * 0.7)
        camera.near = 0.1; camera.far = r * 80; camera.updateProjectionMatrix()
        controls.target.copy(c); controls.update()
      }
      document.getElementById('op-progress')?.style.setProperty('display', 'none')
      dbg.assemblyRenderer._updateLod?.(camera, renderer)
      renderer.render(scene, camera)
    })
    await page.waitForTimeout(300)
    await page.screenshot({ path: 'e2e/screenshots/impostor_assembly.png', fullPage: true })

    expect(info.instances).toBeGreaterThan(0)
    expect(info.meshes, 'no impostor bead InstancedMesh in the shared scene').toBeGreaterThan(0)
    expect(info.sampleVerts).toBe(4)            // PlaneGeometry(2,2) quad
    expect(info.rendering, 'impostor bead mesh not rendering (count 0 / hidden)').toBeGreaterThan(0)

    const shaderErrors = errors.filter(t =>
      /Shader Error|WebGLProgram|getProgramInfoLog|VALIDATE_STATUS|getShaderInfoLog/i.test(t))
    expect(shaderErrors, shaderErrors.join('\n')).toHaveLength(0)
  })

  test('atomistic (VDW) renders atom impostors on the shared path — no hull, no shader errors', async ({ page }) => {
    test.setTimeout(300_000)   // backend build_atomistic_model (~15s) + 300k-atom batch build
    const errors = []
    page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
    page.on('pageerror', e => errors.push(String(e)))

    await page.addInitScript(() => {
      localStorage.setItem('NADOC_SHARED_RENDERER', 'true')
      localStorage.setItem('NADOC_IMPOSTORS', 'true')
    })
    await page.goto('/')
    await page.waitForFunction(() => !!window.__NADOC_DBG__, null, { timeout: 15_000 })

    const nass = readFileSync(FIXTURE, 'utf-8')
    await page.evaluate(async (content) => {
      const api = await import('/src/api/client.js')
      await api.importAssembly(content)
      await window.__NADOC_DBG__.assemblyRenderer.rebuild(window.__NADOC_DBG__.store.getState().currentAssembly)
    }, nass)
    await page.waitForFunction(
      () => (window.__NADOC_DBG__?.store?.getState?.()?.currentAssembly?.instances?.length ?? 0) > 0,
      null, { timeout: 30_000 })
    await page.evaluate(() => {
      document.getElementById('welcome-screen')?.style.setProperty('display', 'none')
      window.__NADOC_DBG__.store.setState({ assemblyActive: true })
    })

    // Switch every instance to VDW, then rebuild → atom-impostor batch.
    await page.evaluate(async () => {
      const dbg = window.__NADOC_DBG__
      const api = await import('/src/api/client.js')
      const insts = dbg.store.getState().currentAssembly.instances
      await api.batchPatchInstances(insts.map(i => ({ id: i.id, representation: 'vdw' })))
      await dbg.assemblyRenderer.rebuild(dbg.store.getState().currentAssembly)
    })
    await page.waitForFunction(() => {
      const scene = window.__NADOC_DBG__?.scene
      if (!scene) return false
      let ok = false
      scene.traverse(o => { if (o.isInstancedMesh && o.material?.userData?.isAtomImpostor && o.count > 0) ok = true })
      return ok
    }, null, { timeout: 30_000 })
    await page.waitForTimeout(500)

    const info = await page.evaluate(() => {
      const { scene, renderer, camera, controls, THREE } = window.__NADOC_DBG__
      renderer.compile(scene, camera)
      // Frame on instance translations + hide busy overlay (see bead test).
      const insts = window.__NADOC_DBG__.store.getState().currentAssembly?.instances ?? []
      const box = new THREE.Box3()
      for (const inst of insts) {
        const v = inst.transform?.values
        if (v && v.length >= 12) box.expandByPoint(new THREE.Vector3(v[3], v[7], v[11]))
      }
      if (!box.isEmpty()) {
        const c = box.getCenter(new THREE.Vector3())
        const r = Math.max(box.getSize(new THREE.Vector3()).length(), 60) * 1.6
        camera.position.set(c.x + r * 0.7, c.y + r * 0.4, c.z + r * 0.7)
        camera.near = 0.1; camera.far = r * 80; camera.updateProjectionMatrix()
        controls.target.copy(c); controls.update()
      }
      document.getElementById('op-progress')?.style.setProperty('display', 'none')
      renderer.render(scene, camera)

      let atomMeshes = 0, atomRendering = 0, sampleVerts = -1, elements = []
      scene.traverse(o => {
        if (o.isInstancedMesh && o.material?.userData?.isAtomImpostor) {
          atomMeshes++
          const pa = o.geometry.getAttribute('position')
          if (pa) sampleVerts = pa.count
          if (o.count > 0 && o.visible) atomRendering++
          elements.push(o.name)
        }
      })
      return { atomMeshes, atomRendering, sampleVerts, elements }
    })
    await page.waitForTimeout(300)
    await page.screenshot({ path: 'e2e/screenshots/impostor_atomistic.png', fullPage: true })

    expect(info.atomMeshes, 'no atom-impostor meshes built (atomistic still hull?)').toBeGreaterThan(0)
    expect(info.sampleVerts).toBe(4)                 // impostor quad
    expect(info.atomRendering).toBeGreaterThan(0)
    const shaderErrors = errors.filter(t =>
      /Shader Error|WebGLProgram|getProgramInfoLog|VALIDATE_STATUS|getShaderInfoLog/i.test(t))
    expect(shaderErrors, shaderErrors.join('\n')).toHaveLength(0)
  })
})
