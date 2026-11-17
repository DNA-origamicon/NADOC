import { test, expect } from '@playwright/test'
import { loadScaffoldedPart } from './helpers/scene_harness.js'

// Only persisted designs are __e2e__atomistic-picking; global teardown removes
// those and their project directories. Session caching is disabled by config.
test('non-surface atomistic clicks resolve displayed geometry', async ({ page }) => {
  test.setTimeout(120000)
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  await loadScaffoldedPart(page, { doc: '__e2e__atomistic-picking', name: 'atomistic-picking' })
  await page.locator('#select-filter-trigger').click()
  await page.locator('#select-filter .sf-btn[data-key="base"]').click()
  for (const mode of ['ballstick', 'stick', 'vdw']) {
    await page.evaluate(mode => window.__nadocTest.setRepresentation(mode), mode)
    await page.waitForFunction(mode => {
      const t = window.__nadocTest
      return t.getAtomisticRenderer().getMode() === mode &&
        t.scene.children.some(m => m.name === (mode === 'stick' ? 'atomBonds' : 'atomSpheres'))
    }, mode)
    const target = await page.evaluate(async mode => {
      const THREE = await import('/node_modules/three/build/three.module.js')
      const t = window.__nadocTest, ar = t.getAtomisticRenderer()
      const mesh = t.scene.children.find(m => m.name === (mode === 'vdw' ? 'atomSpheres' : 'atomBonds'))
      const matrix = new THREE.Matrix4()
      mesh.getMatrixAt(Math.floor(mesh.count / 2), matrix)
      const center = new THREE.Vector3().setFromMatrixPosition(matrix)
      t.applyCameraPoseForTest({ position: center.clone().add(new THREE.Vector3(0, 0, 1)).toArray(), target: center.toArray() })
      const hit = ar.raycastPick(new THREE.Raycaster(center.clone().add(new THREE.Vector3(0, 0, 1)), new THREE.Vector3(0, 0, -1)))
      const { atomBaseKey } = await import('/src/scene/base_ref.js')
      const rect = document.getElementById('canvas').getBoundingClientRect()
      return { key: atomBaseKey(hit.atom), x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 }
    }, mode)
    await page.evaluate(() => {
      window.__nadocTest.selectRefsForTest([])
      window.__nadocTest.renderViewerFrameForTest()
    })
    expect(await page.evaluate(() => window.__nadocTest.getSelectionLevel())).toBe('base')
    await page.mouse.click(target.x, target.y)
    await expect.poll(() => page.evaluate(() => window.__nadocTest.getSelectedBaseKeys())).toEqual([target.key])
    // Canonical refs are shared by the filter buttons, sidebar and pointer paths.
    // Recompose each pool: the original defect restored raw Full entries here.
    const checks = await page.evaluate(async key => {
      const t = window.__nadocTest, design = t.store.getState().currentDesign
      const strand = design.strands.find(s => s.domains.length)
      const { baseKey } = await import('/src/scene/base_ref.js')
      const domain = strand.domains[0]
      const end = baseKey({ helix_id: domain.helix_id, bp_index: domain.start_bp, direction: domain.direction })
      const refs = [
        { kind: 'strand', id: strand.id },
        { kind: 'domain', strandId: strand.id, domainIndex: 0 },
        { kind: 'end', key: end }, { kind: 'base', key },
      ]
      t.selectRefsForTest([])
      const originalColors = new Map()
      t.scene.traverseVisible(mesh => {
        if (mesh.name === 'atomSpheres' || mesh.name === 'atomBonds') originalColors.set(mesh, mesh.instanceColor.array.slice())
      })
      return refs.map(ref => {
        t.selectRefsForTest([ref]); t.renderViewerFrameForTest()
        let glow = 0, recolored = 0, ghostPoints = 0
        t.scene.traverseVisible(mesh => {
          if (mesh.name === 'selectionGlow') glow += mesh.count
          if (mesh.name === 'Presenter selection' && mesh.material.colorWrite) ghostPoints += mesh.geometry.drawRange.count
          if (mesh.name !== 'atomSpheres' && mesh.name !== 'atomBonds') return
          const colors = mesh.instanceColor.array
          if (colors.some((v, i) => v !== originalColors.get(mesh)[i])) recolored++
        })
        return { kind: ref.kind, glow, ghostPoints, recolored, highlighted: t.getAtomisticRenderer().selectionHighlightEntries().length }
      })
    }, target.key)
    for (const check of checks) {
      expect(check.glow, `${mode} ${check.kind}: no ghost beads`).toBe(0)
      expect(check.recolored).toBe(0)
      expect(check.ghostPoints).toBe(0)
      expect(check.highlighted, `${mode} ${check.kind}: native highlight`).toBeGreaterThan(0)
    }
    if (mode === 'stick' && process.env.NADOC_PICK_REVIEW_HOLD_MS) {
      await page.screenshot({ path: 'test-results/atomistic-highlight.png' })
      await page.waitForTimeout(Number(process.env.NADOC_PICK_REVIEW_HOLD_MS))
    }
  }
  await page.evaluate(() => window.__nadocTest.setRepresentation('full'))
  await expect.poll(() => page.evaluate(() => {
    let count = 0
    window.__nadocTest.scene.traverseVisible(m => { if (m.name === 'selectionGlow') count += m.count })
    return count
  })).toBeGreaterThan(0)
  expect(errors).toEqual([])
})
