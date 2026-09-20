import { test, expect } from '@playwright/test'
import { readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { createHash } from 'node:crypto'
import { loadScaffoldedPart } from './helpers/scene_harness.js'
import { cleanupProjectArtifacts } from './project_artifact_cleanup.js'

// Explicit opt-in, read-only source. The imported copy gets a test-only identity
// and name; history is omitted so old project identities cannot enter recovery.
// Persistence: prefixed workspace autosaves + their project stores are removed by
// existing global-teardown even on failure. Optional metrics output is a deliberate
// retained review artifact at NADOC_VIEWER_BENCH_OUTPUT, not a disposable screenshot.
const source = process.env.NADOC_VIEWER_BENCH_FIXTURE
let bootProjectId = null
test.skip(!source, 'Set NADOC_VIEWER_BENCH_FIXTURE to opt into a copied real-design benchmark')
test.setTimeout(180000)
test.afterEach(async ({ page }) => {
  await page.close()
  // Replacing the harness part changes document identity. Its old project store
  // may no longer be discoverable through the final autosave filename.
  if (bootProjectId) await cleanupProjectArtifacts(path.resolve(process.cwd(), '../workspace'), [bootProjectId])
  bootProjectId = null
})

test('records a real-design baseline without modifying its source or running simulations', async ({ page, request }) => {
  page.on('pageerror', error => console.log(`[viewer benchmark page error] ${error.message}`))
  const original = await readFile(source)
  const sourceHash = createHash('sha256').update(original).digest('hex')
  const design = JSON.parse(original)
  design.id = '__e2e__viewer_benchmark'
  design.metadata = { ...design.metadata, name: '__e2e__viewer_benchmark', identity_last_known_path: '__e2e__viewer_benchmark.nadoc' }
  design.feature_log = []
  const doc = '__e2e__viewer_benchmark'
  const api = process.env.NADOC_E2E_API_BASE
  expect(api, 'Use the isolated Playwright config').toBeTruthy()
  await loadScaffoldedPart(page, { doc, name: 'viewer_benchmark_boot' })
  bootProjectId = await page.evaluate(() => window.__nadocTest.viewerDiagnostic().designId)
  const response = await request.post(`${api}/api/design/import`, {
    headers: { 'X-NADOC-Doc': doc }, data: { content: JSON.stringify(design) }, timeout: 90000,
  })
  expect(response.ok()).toBe(true)
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    await api.getDesign()
    await api.getGeometry()
  })
  console.log('[viewer benchmark ready]', await page.evaluate(() => window.__nadocTest.viewerDiagnostic()))
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  await expect.poll(() => page.evaluate(() => window.__nadocTest?.getDesignRenderer?.()?.getBackboneEntries?.().length ?? 0), { timeout: 60000 }).toBeGreaterThan(100)
  await page.evaluate(() => {
    const testApi = window.__nadocTest
    const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity]
    for (const entry of testApi.getDesignRenderer().getBackboneEntries()) {
      const p = entry.nuc?.backbone_position
      if (p) for (let axis = 0; axis < 3; axis++) { lo[axis] = Math.min(lo[axis], p[axis]); hi[axis] = Math.max(hi[axis], p[axis]) }
    }
    if (![...lo, ...hi].every(Number.isFinite)) throw new Error('No geometry bounds for benchmark')
    const center = lo.map((value, axis) => (value + hi[axis]) / 2)
    const distance = Math.max(...lo.map((value, axis) => hi[axis] - value)) * 2 + 10
    testApi.applyCameraPoseForTest({ position: [center[0] + distance, center[1] + distance * 0.4, center[2] + distance],
      target: center, up: [0, 1, 0], fov: 55 })
  })
  await expect.poll(() => page.evaluate(() => window.__nadocTest.getBackboneBeadScreenPositions(20).length)).toBeGreaterThan(0)
  // Let asynchronous representations and initial shader compilation settle.
  await page.waitForTimeout(3000)
  const variant = process.env.NADOC_VIEWER_BENCH_VARIANT ?? 'A'
  const records = []
  const output = process.env.NADOC_VIEWER_BENCH_OUTPUT
  async function saveEvidence() {
    if (output) await writeFile(output, JSON.stringify({ source_filename: path.basename(source), source_sha256: sourceHash,
      scope: 'Headless local probe; 3-second orbit segments, history omitted; not user-GPU acceptance', records }, null, 2) + '\n')
  }
  for (let run = 0; run < 6; run++) {
    await page.evaluate(async variant => {
      const api = (await import('/src/perf/viewer_performance.js')).getViewerPerformance()
      await api.start({ variant, durationMs: 3000 })
    }, variant)
    await expect.poll(() => page.evaluate(async () =>
      (await import('/src/perf/viewer_performance.js')).getViewerPerformance().busy), { timeout: 15000 }).toBe(false)
    const record = await page.evaluate(async () =>
      (await import('/src/perf/viewer_performance.js')).getViewerPerformance().latest)
    if (run || !record.valid) records.push({ ...record, warmup: run === 0 })
    await saveEvidence()
    console.log(`[viewer benchmark run] ${JSON.stringify({ run, valid: record.valid, reason: record.invalid_reason,
      samples: record.frame_intervals.samples, p95_ms: record.frame_intervals.p95_ms, gpu: record.environment.gpu })}`)
    expect(record.valid, record.invalid_reason).toBe(true)
  }
  console.log(`[viewer benchmark] ${JSON.stringify(records.map(r => ({ variant, p95_ms: r.frame_intervals.p95_ms, samples: r.frame_intervals.samples })))}`)
  expect(createHash('sha256').update(await readFile(source)).digest('hex')).toBe(sourceHash)
})
