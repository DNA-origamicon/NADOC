import { test, expect } from '@playwright/test'
import fs from 'node:fs'
import { attachMdDisplayLog } from './helpers/md_display_log.js'

const JOB_ID = '82a3cd08ed4f'
const OUT = 'e2e/logs/md_overhang_alignment'
const CAPTURE_SCENE_SCREENSHOTS = process.env.NADOC_AUDIT_SCENE_SCREENSHOTS === '1'

async function domClick(locator) {
  await locator.waitFor({ state: 'attached', timeout: 30_000 })
  await locator.evaluate(el => el.click())
}

async function domCheck(locator) {
  await locator.waitFor({ state: 'attached', timeout: 30_000 })
  await locator.evaluate(el => {
    el.checked = true
    el.dispatchEvent(new Event('change', { bubbles: true }))
  })
}

test('VoltronCoreArm MD overhangs and rods use the applied active frame', async ({ page }) => {
  test.setTimeout(480_000)
  fs.mkdirSync('e2e/logs', { recursive: true })
  const log = await attachMdDisplayLog(page, { intervalMs: 100 })
  let measurements
  try {
    await page.goto(`/?doc=md-overhang-alignment-${Date.now()}`)
    await expect(page.locator('#welcome-screen')).toBeVisible({ timeout: 15_000 })
    const designRow = page.locator('#welcome-screen .lib-row-name', { hasText: /^VoltronCoreArm$/ }).first()
    await designRow.waitFor({ state: 'visible', timeout: 60_000 })
    await domClick(designRow)
    await expect(page.locator('#welcome-screen')).toHaveClass(/hidden/, { timeout: 120_000 })

    // Software WebGL cannot continuously redraw this system responsively. Render
    // once at the two evidence checkpoints, as in the full Alpine diagnostic.
    await page.evaluate(() => {
      window.__NADOC_DBG__.renderer.setAnimationLoop(null)
      window.__nadocDiagnosticRenderPaused = true
    })
    if (CAPTURE_SCENE_SCREENSHOTS) {
      await page.evaluate(() => window.__NADOC_DBG__.renderer.render(
        window.__NADOC_DBG__.scene, window.__NADOC_DBG__.camera))
      await page.screenshot({ path: `${OUT}_00_equilibrium.png`, timeout: 180_000 })
    } else {
      log.note('scene-screenshot-skipped:equilibrium (requires NADOC_AUDIT_SCENE_SCREENSHOTS=1)')
    }

    await domClick(page.locator('.left-tab-btn[data-tab="dynamics"]'))
    await domClick(page.locator('.engine-selector-btn[data-engine="namd"]'))
    const row = page.locator(`#simulate-jobs-list [data-job-id="${JOB_ID}"]`).first()
    if (!(await row.isVisible().catch(() => false))) await domCheck(page.locator('#md-jobs-show-all'))
    await domClick(row)
    await domCheck(page.locator('#md-jobs-display-toggle'))
    await page.waitForFunction(() => (window.__mdDisplayEvents || []).some(
      e => e.channel === 'process' && e.phase === 'frame-applied'), null, { timeout: 180_000 })

    measurements = await page.evaluate(() => {
      const dbg = window.__NADOC_DBG__
      const ctrl = dbg.designRenderer.getHelixCtrl()
      const updates = dbg.designRenderer.getFemPositions() || []
      const byKey = new Map(updates.map(u => [
        `${u.helix_id}:${u.bp_index}:${u.direction}:${u.copy ?? 0}`,
        u.backbone_position,
      ]))
      const design = dbg.store.getState().currentDesign
      const active = (design.strands || []).filter(s => !s.is_reference)
      const reference = (design.strands || []).filter(s => s.is_reference)
      const referenceIds = new Set(reference.map(s => s.id))
      const THREE = dbg.THREE
      const center = new THREE.Vector3(), quat = new THREE.Quaternion(), scale = new THREE.Vector3()
      const y = new THREE.Vector3(0, 1, 0)
      const rods = []
      const referenceOverhangAlpha = []
      const distances = []
      let expectedOverhangKeys = 0, presentOverhangKeys = 0

      for (const strand of active) for (let di = 0; di < (strand.domains || []).length; di++) {
        const domain = strand.domains[di]
        if (!domain.overhang_id) continue
        const step = domain.direction === 'FORWARD' ? 1 : -1
        const positions = []
        for (let bp = domain.start_bp; ; bp += step) {
          expectedOverhangKeys++
          const p = byKey.get(`${domain.helix_id}:${bp}:${domain.direction}:0`)
          if (p) { presentOverhangKeys++; positions.push(p) }
          if (bp === domain.end_bp) break
        }
        for (let i = 1; i < positions.length; i++) {
          distances.push(Math.hypot(
            positions[i][0] - positions[i - 1][0],
            positions[i][1] - positions[i - 1][1],
            positions[i][2] - positions[i - 1][2]))
        }
        const dom = ctrl.getOverhangCylinderDomainData().find(
          d => d.strandId === strand.id && d.domainIndex === di)
        if (!dom || positions.length < 2) continue
        const mesh = dom.fullCylinder ? ctrl.getOverhangFullCylinderMesh() : ctrl.getOverhangCylinderMesh()
        const matrix = new THREE.Matrix4()
        mesh.getMatrixAt(dom.cylIdx, matrix)
        matrix.decompose(center, quat, scale)
        const rodDir = y.clone().applyQuaternion(quat).normalize()
        const beadDir = new THREE.Vector3(...positions.at(-1)).sub(new THREE.Vector3(...positions[0])).normalize()
        rods.push({
          strandId: strand.id, domainIndex: di,
          angleDeg: THREE.MathUtils.radToDeg(Math.acos(Math.min(1, Math.abs(rodDir.dot(beadDir))))),
          renderedLengthNm: scale.y,
          beadSpanNm: new THREE.Vector3(...positions.at(-1)).distanceTo(new THREE.Vector3(...positions[0])),
        })
      }
      for (const dom of ctrl.getOverhangCylinderDomainData()) {
        if (!referenceIds.has(dom.strandId)) continue
        const mesh = dom.fullCylinder ? ctrl.getOverhangFullCylinderMesh() : ctrl.getOverhangCylinderMesh()
        referenceOverhangAlpha.push(mesh._instanceAlpha?.getX(dom.cylIdx) ?? null)
      }
      const referenceArcs = dbg.unfoldView.getArcMeta().filter(e =>
        referenceIds.has(e.fromNuc?.strand_id) || referenceIds.has(e.toNuc?.strand_id))
      const referenceArcBuffers = dbg.unfoldView.getArcDebugInfo().arcs.filter(e =>
        referenceIds.has(e.fromStrand) || referenceIds.has(e.toStrand))
      const sorted = distances.slice().sort((a, b) => a - b)
      return {
        framePositions: updates.length,
        activeStrands: active.length,
        referenceStrands: reference.length,
        expectedOverhangKeys, presentOverhangKeys,
        overhangNeighbor: {
          count: distances.length,
          medianNm: sorted[Math.floor(sorted.length / 2)] || null,
          maxNm: sorted.at(-1) || null,
          over1Nm: distances.filter(x => x > 1).length,
        },
        rods,
        maxRodAngleDeg: Math.max(0, ...rods.map(r => r.angleDeg)),
        referenceOverhangCount: referenceOverhangAlpha.length,
        visibleReferenceOverhangs: referenceOverhangAlpha.filter(a => a == null || a > 0.001).length,
        referenceCrossoverArcCount: referenceArcs.length,
        visibleReferenceCrossoverArcs: referenceArcs.filter(e => !e.hidden).length,
        renderedReferenceCrossoverArcs: referenceArcBuffers.filter(
          e => (e.renderedSpanNm ?? Infinity) > 1e-6).length,
        maxReferenceCrossoverSpanNm: Math.max(0, ...referenceArcBuffers.map(
          e => e.renderedSpanNm ?? Infinity)),
      }
    })

    if (CAPTURE_SCENE_SCREENSHOTS) {
      await page.evaluate(() => window.__NADOC_DBG__.renderer.render(
        window.__NADOC_DBG__.scene, window.__NADOC_DBG__.camera))
      await page.screenshot({ path: `${OUT}_01_md_applied.png`, timeout: 180_000 })
    } else {
      log.note('scene-screenshot-skipped:md-applied (requires NADOC_AUDIT_SCENE_SCREENSHOTS=1)')
    }
    fs.writeFileSync(`${OUT}_measurements.json`, JSON.stringify(measurements, null, 2))
  } finally {
    await log.stop()
    log.write(OUT)
  }

  expect(measurements.framePositions).toBe(14_179)
  expect(measurements.presentOverhangKeys).toBe(measurements.expectedOverhangKeys)
  expect(measurements.overhangNeighbor.over1Nm).toBe(0)
  expect(measurements.overhangNeighbor.maxNm).toBeLessThan(0.8)
  expect(measurements.rods.length).toBeGreaterThan(0)
  expect(measurements.maxRodAngleDeg).toBeLessThan(12)
  expect(measurements.referenceOverhangCount).toBeGreaterThan(0)
  expect(measurements.visibleReferenceOverhangs).toBe(0)
  expect(measurements.referenceCrossoverArcCount).toBeGreaterThan(0)
  expect(measurements.visibleReferenceCrossoverArcs).toBe(0)
  expect(measurements.renderedReferenceCrossoverArcs).toBe(0)
  expect(measurements.maxReferenceCrossoverSpanNm).toBeLessThan(1e-6)
  expect(log.consoleErrors()).toEqual([])
})
