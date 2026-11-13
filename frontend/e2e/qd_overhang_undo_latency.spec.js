import { test, expect } from '@playwright/test'
import path from 'node:path'
import { readFile } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { createHash } from 'node:crypto'

test.use({ launchOptions: { args: ['--enable-webgl', '--ignore-gpu-blocklist', '--use-angle=gl'] } })

const fixture = path.resolve('../workspace/VoltronCoreArmV2.nadoc')
test.skip(!existsSync(fixture), 'Requires the local VoltronCoreArmV2 diagnostic fixture')
let sourceHash
const hash = async () => createHash('sha256').update(await readFile(fixture)).digest('hex')
test.beforeEach(async ({ page }) => {
  page.on('console', msg => { if (msg.text().includes('operation') || msg.text().includes('QD')) console.log(msg.text()) })
  page.on('pageerror', error => console.log('PAGE_ERROR', error.message))
  await page.route('**/src/state/store.js', async route => {
    const response = await route.fetch()
    const body = (await response.text()).replace('timingLabel ?? `store-subscriber:${++_nextListener}`',
      'timingLabel ?? new Error().stack.split("\\n")[2]')
    await route.fulfill({ response, body })
  })
  sourceHash = await hash()
  // Diagnosis of a legacy user file is read-only on disk. Block persistence;
  // localStorage belongs to Playwright's disposable browser context.
  await page.route('**/api/design/save**', route => route.fulfill({ status: 200,
    contentType: 'application/json', body: JSON.stringify({ identity_disposition: 'confirmed' }) }))
})
test.afterEach(async () => { expect(await hash()).toBe(sourceHash) })

for (const operation of ['undo', 'redo']) {
test(`QD_OH1 ${operation} presents the restored free end in less than one second`, async ({ page }, testInfo) => {
  test.setTimeout(180_000)
  await page.goto(`/?doc=__e2e__qd-${operation}-latency`)
  await page.waitForSelector('#canvas')
  await page.evaluate(async fixture => {
    const api = await import('/src/api/client.js')
    await api.loadDesign(fixture)
    console.log("QD loaded")
    document.getElementById('welcome-screen')?.classList.add('hidden')
    window.__qdTimings = []
    window.__nadocOperationTraceAll = true
    addEventListener('nadoc:operation-timing', e => window.__qdTimings.push(e.detail))
  }, fixture)
  const results = await page.evaluate(async operation => {
    const api = await import('/src/api/client.js')
    const { store } = await import('/src/state/store.js')
    const { whenOperationIdle } = await import('/src/perf/operation_timing.js')
    await whenOperationIdle()
    const target = store.getState().currentDesign.overhangs.find(o => o.label === 'QD_OH1')
    const expectedEnd = operation === 'undo' ? 1209 : 1214
    const results = []
    for (let i = 0; i < 3; i++) {
      if (operation === 'undo' || i === 0) await api.patchOverhang(target.id, { sequence: target.sequence.slice(0, 10) })
      if (operation === 'redo') await api.undo()
      await whenOperationIdle()
      await new Promise(resolve => setTimeout(resolve, 2200))
      const history = store.getState().currentDesign.feature_log
      console.log('QD history', JSON.stringify({ count: history.length,
        bytes: history.reduce((sum, e) => sum + (e.post_state_gz_b64?.length ?? 0) + (e.pre_state_gz_b64?.length ?? 0) + (e.design_snapshot_gz_b64?.length ?? 0), 0) }))
      const start = performance.now()
      let response
      if (i < 2) response = await api[operation]()
      else await new Promise((resolve, reject) => {
        const timeout = setTimeout(() => { unsubscribe(); reject(new Error(`Menu ${operation} did not restore QD_OH1`)) }, 15000)
        const unsubscribe = store.subscribe(next => {
          const domain = next.currentDesign?.strands.flatMap(s => s.domains).find(d => d.overhang_id === target.id)
          if (domain?.end_bp === expectedEnd && next.currentGeometry?.some(n => n.helix_id === target.helix_id && n.bp_index === expectedEnd && n.is_three_prime)) {
            clearTimeout(timeout); unsubscribe(); resolve()
          }
        })
        document.getElementById(`menu-edit-${operation}`).click()
      })
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
      const duration = performance.now() - start
      const d = store.getState().currentDesign.strands.flatMap(s => s.domains).find(d => d.overhang_id === target.id)
      results.push({ duration, start: d.start_bp, end: d.end_bp, partial: response?.partial_geometry, changed: response?.changed_helix_ids, trace: window.__qdTimings.filter(t => t.label.toLowerCase() === operation).at(-1) })
    }
    return results
  }, operation)
  console.log(`QD_${operation.toUpperCase()}_LATENCY`, JSON.stringify(results))
  // Review framing is outside the measured interaction interval.
  const pixels = await page.evaluate(() => {
    const app = window.__nadocTest, state = app.store.getState()
    const target = state.currentDesign.overhangs.find(o => o.label === 'QD_OH1')
    const root = state.currentGeometry.find(n => n.helix_id === target.helix_id && n.bp_index === 1223 && n.direction === 'REVERSE')
    const [x, y, z] = root.backbone_position
    app.applyCameraPoseForTest({ position: [x + 18, y - 25, z + 4], target: [x, y, z], up: [0, 0, 1], fov: 35 })
    return app.renderedPixelCensus()
  })
  console.log('QD_REVIEW_PIXELS', JSON.stringify(pixels))
  const review = testInfo.outputPath(`qd-${operation}-review.png`)
  await page.screenshot({ path: review })
  console.log('QD_REVIEW_IMAGE', review)
  await page.waitForTimeout(60000)

  for (const result of results) {
    expect([result.start, result.end]).toEqual([1223, operation === 'undo' ? 1209 : 1214])
    expect(result.duration).toBeLessThan(1000)
  }
})
}
