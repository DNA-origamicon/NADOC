/**
 * LOD simplification (billboard tier retired): a cylinders-rep assembly
 * collapses to the grey hull solid when zoomed far out (NOT a billboard), and
 * the photo-export suppression flag forces every instance back to its detail
 * bucket (no hull demotion) for uniform high-detail figures.
 *
 * Run: cd frontend && npx playwright test e2e/lod_cylinders_to_hull.spec.js \
 *        --config playwright.bench.config.js --reporter=list
 */
import { test, expect } from '@playwright/test'
import { existsSync } from 'node:fs'
import { resolve as resolvePath } from 'node:path'

const FIX = resolvePath(process.cwd(), '..', 'workspace', 'bench_fixtures', 'bench_hinge_050.nass')
test.skip(!existsSync(FIX), `fixture missing: ${FIX}`)

test('cylinders demote to hull at distance; suppression forces detail everywhere', async ({ page }) => {
  test.setTimeout(120_000)
  page.on('pageerror', e => console.log('[pageerror] ' + e.message))
  await page.addInitScript(() => localStorage.setItem('NADOC_SHARED_RENDERER', 'true'))
  await page.goto('http://localhost:5173/')
  await page.waitForFunction(() => !!window.__NADOC_DBG__?.assemblyRenderer, null, { timeout: 30_000 })

  // Load the 50-instance assembly + enter assembly mode.
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const res = await api.getLibraryFileContent('bench_fixtures/bench_hinge_050.nass')
    await api.importAssembly(res.content)
    window.__NADOC_DBG__.store.setState({ assemblyActive: true })
  })
  await page.waitForFunction(
    () => (window.__NADOC_DBG__.store.getState().currentAssembly?.instances?.length ?? 0) === 50,
    null, { timeout: 30_000 },
  )
  // Force cylinders as the working rep, then settle.
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const insts = window.__NADOC_DBG__.store.getState().currentAssembly.instances
    await api.batchPatchInstances(insts.map(i => ({ id: i.id, representation: 'cylinders' })))
  })
  await page.waitForTimeout(3000)

  // Sum bucket counts across all sources.
  const sumCounts = async () => await page.evaluate(() => {
    const snap = window.__NADOC_DBG__.assemblyRenderer.probeLod?.()
    const acc = { close: 0, mid: 0, hull: 0, n: 0 }
    for (const s of snap?.sources ?? []) {
      acc.close += s.counts?.close ?? 0
      acc.mid   += s.counts?.mid   ?? 0
      acc.hull  += s.counts?.hull  ?? 0
      acc.n     += s.numInstances ?? 0
    }
    return acc
  })

  // ── A. Zoom far out: cylinders fall below farPx → hull bucket, no billboard ──
  // farPx=1e9 forces every instance below the threshold (the "very far away"
  // case) regardless of the actual camera distance.
  await page.evaluate(() => window.__NADOC_DBG__.assemblyRenderer.setLodThresholds({ closePx: 60, farPx: 1e9 }))
  await page.waitForTimeout(800)
  const far = await sumCounts()
  console.log('A (far, cylinders):', JSON.stringify(far))
  expect(far.n, 'fixture loaded 50 instances').toBe(50)
  expect(far.hull, 'all cylinders demoted to hull at distance').toBe(far.n)
  expect(far.mid, 'no cylinders drawn far away').toBe(0)
  // No retired billboard mesh anywhere on the scene.
  const hasFarMesh = await page.evaluate(() => {
    let found = false
    window.__NADOC_DBG__.scene.traverse(o => { if (o.name === 'sharedLodFar') found = true })
    return found
  })
  expect(hasFarMesh, 'billboard tier retired — no sharedLodFar mesh').toBe(false)

  // ── B. Suppression on: every instance back to its detail bucket (mid), no hull ──
  await page.evaluate(() => window.__NADOC_DBG__.assemblyRenderer.setSuppressLodDemotion(true))
  await page.waitForTimeout(800)
  const sup = await sumCounts()
  console.log('B (suppressed):', JSON.stringify(sup))
  expect(sup.mid, 'suppression draws every cylinders instance at mid (no hull demotion)').toBe(sup.n)
  expect(sup.hull, 'suppression leaves nothing in the hull bucket').toBe(0)

  // Restore so we don't leak the flag into other state.
  await page.evaluate(() => window.__NADOC_DBG__.assemblyRenderer.setSuppressLodDemotion(false))
})
