/**
 * LOD FPS sweep — path-to-thousands benchmark.
 *
 * ⚠️ HEADLESS = SOFTWARE GL. Playwright's chromium on this box renders with
 * ANGLE/SwiftShader (CPU rasterizer), so the avgFps/p5Fps numbers here are NOT
 * representative of a real GPU — use them only for relative shape / sanity.
 * For REAL frame rates run e2e/lod_console_sweep.js in your own browser.
 * What IS reliable headless: draw calls, triangle counts, bucket distributions.
 * NOTE: setRepSettle calls rebuild() explicitly AND a store subscriber rebuilds
 * on the rep change (main.js:9032) → this spec double-builds (buildMs inflated).
 * The console sweep relies on the reactive rebuild only (accurate buildMs).
 *
 * Answers four questions for the shared assembly renderer:
 *   1. Which LOD tiers earn their keep (close/mid/far/hull)?
 *   2. Where should the angular pixel thresholds (closePx/farPx) sit?
 *   3. What instance count N still holds 60 / 30 FPS, per tier?
 *   4. Frontend cold-open (rebuild) time per N.
 *
 * Method: for each N-hinge fixture in workspace/bench_fixtures/, reload the
 * page (clean GPU state), then:
 *   PART A — force every instance into ONE tier and sample FPS at a fit-all
 *            framing (isolates per-tier cost → "max N per tier").
 *   PART B — rep='full', DEFAULT thresholds, sweep camera distance fit×{...}
 *            and record the natural close/mid/far bucket split + FPS at each
 *            (→ where the thresholds should sit).
 *
 * Writes e2e/bench_results/lod_fps.{json,md} and per-(N,distance) screenshots
 * for the human visual-acceptability pass.
 *
 * Run: cd frontend && npx playwright test e2e/lod_fps_sweep.spec.js --reporter=list
 * Subset: NADOC_BENCH_N=20,200 npx playwright test e2e/lod_fps_sweep.spec.js
 */
import { test, expect } from '@playwright/test'
import { existsSync, readFileSync, readdirSync, writeFileSync, mkdirSync, appendFileSync } from 'node:fs'
import { resolve as resolvePath, join } from 'node:path'

const FIXTURE_DIR = resolvePath(process.cwd(), '..', 'workspace', 'bench_fixtures')
const RESULTS_DIR = resolvePath(process.cwd(), 'e2e', 'bench_results')
const SHOTS_DIR = resolvePath(process.cwd(), 'e2e', 'screenshots')
const PROG = join(RESULTS_DIR, 'progress.log')

/** Append a timestamped breadcrumb straight to a file — bypasses Playwright's
 *  per-worker stdout buffering so a hung/killed run is still diagnosable. */
function logp(msg) {
  const line = `${new Date().toISOString().slice(11, 19)}  ${msg}`
  console.log(line)
  try { appendFileSync(PROG, line + '\n') } catch { /* dir may not exist yet */ }
}

const SAMPLE_MS = Number(process.env.NADOC_BENCH_SAMPLE_MS ?? 1800)
// Camera distance multipliers of the fit-all distance (1.0 = whole assembly
// fills the viewport height). <1 zooms in; >1 zooms out.
const DIST_MULTS = [0.25, 0.6, 1.0, 2.5, 6.0]
const VIEW_DIR = [1, 0.55, 1] // canonical 3/4 view for every sample

function fixtures() {
  if (!existsSync(FIXTURE_DIR)) return []
  const want = process.env.NADOC_BENCH_N
    ? new Set(process.env.NADOC_BENCH_N.split(',').map(s => parseInt(s, 10)))
    : null
  return readdirSync(FIXTURE_DIR)
    .filter(f => /^bench_hinge_\d+\.nass$/.test(f))
    .map(f => ({ n: parseInt(f.match(/(\d+)/)[1], 10), file: join(FIXTURE_DIR, f) }))
    .filter(x => !want || want.has(x.n))
    .sort((a, b) => a.n - b.n)
}

test.setTimeout(30 * 60_000)
test.skip(fixtures().length === 0, `no fixtures in ${FIXTURE_DIR} (run scripts/gen_hinge_fixture.py)`)

/** Resolve only once the render loop is running freely (rAF fires only when the
 *  main thread is idle — so this naturally waits out a synchronous rebuild that
 *  blocks JS). Then `frames` clean frames confirm steady state. */
async function settleFrames(page, frames = 6) {
  await page.evaluate(n => new Promise(res => {
    let i = 0
    const tick = () => (++i >= n ? res() : requestAnimationFrame(tick))
    requestAnimationFrame(tick)
  }), frames)
}

async function loadFixture(page, content) {
  await page.addInitScript(() => localStorage.setItem('NADOC_SHARED_RENDERER', 'true'))
  await page.goto('/')
  await page.waitForFunction(() => !!window.__NADOC_DBG__, null, { timeout: 30_000 })
  logp('  page loaded, __NADOC_DBG__ ready; importing fixture')
  const buildMs = await page.evaluate(async (nass) => {
    const api = await import('/src/api/client.js')
    const ok = await api.importAssembly(nass)
    if (!ok) throw new Error('importAssembly returned falsy')
    const assembly = window.__NADOC_DBG__.store.getState().currentAssembly
    const t0 = performance.now()
    try { await window.__NADOC_DBG__.assemblyRenderer.rebuild(assembly) } catch (e) { /* explicit; reactive may also fire */ }
    return performance.now() - t0
  }, content)
  await page.waitForFunction(
    () => (window.__NADOC_DBG__?.store?.getState?.()?.currentAssembly?.instances?.length ?? 0) > 0,
    null, { timeout: 60_000 },
  )
  await page.evaluate(() => {
    document.getElementById('welcome-screen')?.style.setProperty('display', 'none')
    document.getElementById('welcome')?.style.setProperty('display', 'none')
    window.__NADOC_DBG__.store.setState({ assemblyActive: true })
  })
  await settleFrames(page)
  logp(`  fixture loaded + rebuilt (${Math.round(buildMs)} ms)`)
  return buildMs
}

/** Patch all instances to `rep`, trigger an explicit rebuild, await it, and
 *  settle. Returns the rebuild wall-time (ms). Robust to whether a reactive
 *  store subscriber also rebuilds — rebuild() is safe to call directly (mirrors
 *  the hull_prism_assembly spec). */
async function setRepSettle(page, rep) {
  const t0 = Date.now()
  await page.evaluate(async (rep) => {
    await window.__NADOC_DBG__.setAllRep(rep)
    const a = window.__NADOC_DBG__.store.getState().currentAssembly
    try { await window.__NADOC_DBG__.assemblyRenderer.rebuild(a) } catch (e) { /* see above */ }
  }, rep)
  await settleFrames(page)
  return Date.now() - t0
}

async function setThresholds(page, closePx, farPx) {
  await page.evaluate(({ c, f }) => window.__NADOC_DBG__.setLodThresholds({ closePx: c, farPx: f }),
    { c: closePx, f: farPx })
}

async function setDist(page, d) {
  await page.evaluate(({ d, dir }) => window.__NADOC_DBG__.setCameraDist(d, dir), { d, dir: VIEW_DIR })
  await page.waitForTimeout(450) // let per-frame LOD bucketing settle
}

async function sample(page) {
  const stats = await page.evaluate(async (ms) => await window.__NADOC_DBG__.sampleFps(ms), SAMPLE_MS)
  const lod = await page.evaluate(() => {
    const snap = window.__NADOC_DBG__.assemblyRenderer.probeLod?.()
    const s = snap?.sources?.[0]
    return s ? { counts: s.counts, minPx: s.minPxSize, maxPx: s.maxPxSize } : null
  })
  return { ...stats, lod }
}

test('LOD FPS sweep across the hinge progression', async ({ page }) => {
  page.on('pageerror', err => logp(`[browser error] ${err.message}`))
  page.on('console', msg => {
    if (msg.type() === 'error') logp(`[browser console.error] ${msg.text().slice(0, 200)}`)
  })

  const rows = []
  mkdirSync(RESULTS_DIR, { recursive: true })
  writeFileSync(PROG, '')
  logp(`sweep start; fixtures=${fixtures().map(f => f.n).join(',')}`)

  for (const { n, file } of fixtures()) {
    if (!existsSync(file)) continue
    logp(`========== N=${n} ==========`)
    const content = readFileSync(file, 'utf-8')
    const loadBuildMs = await loadFixture(page, content)

    // ── PART A — per-tier isolation at fit-all framing ──────────────────────
    // close: rep full, thresholds 0/0 → every instance bp-detail
    const fullBuildMs = await setRepSettle(page, 'full')
    logp(`  rep=full rebuilt (${Math.round(fullBuildMs)} ms)`)
    const fit = await page.evaluate(() => window.__NADOC_DBG__.fitDist(1.15))
    await setThresholds(page, 0, 0)
    await setDist(page, fit)
    rows.push({ n, phase: 'tier', tier: 'close', rep: 'full', distMult: 1.0, buildMs: Math.round(fullBuildMs), ...(await sample(page)) })
    logp(`  [close]  fps=${rows.at(-1).avgFps} p5=${rows.at(-1).p5Fps} draws=${rows.at(-1).drawCalls} tris(k)=${Math.round((rows.at(-1).triangles ?? 0) / 1e3)}`)

    // ── PART B — angular sweep at DEFAULT thresholds, rep full ──────────────
    await setThresholds(page, 60, 8)
    for (const m of DIST_MULTS) {
      await setDist(page, fit * m)
      const s = await sample(page)
      rows.push({ n, phase: 'angular', tier: 'auto', rep: 'full', distMult: m, ...s })
      logp(`  [angular x${m}] fps=${s.avgFps} p5=${s.p5Fps} draws=${s.drawCalls} buckets=${JSON.stringify(s.lod?.counts)}`)
      // screenshots: fit-all + far, for the human visual-acceptability pass
      if (m === 1.0 || m === 6.0) {
        await page.screenshot({ path: join(SHOTS_DIR, `lod_N${String(n).padStart(3, '0')}_full_x${m}.png`) })
      }
    }

    // mid: rep cylinders, force-mid via thresholds (huge close, zero far)
    const cylBuildMs = await setRepSettle(page, 'cylinders')
    await setThresholds(page, 1e9, 0)
    await setDist(page, fit)
    rows.push({ n, phase: 'tier', tier: 'mid', rep: 'cylinders', distMult: 1.0, buildMs: Math.round(cylBuildMs), ...(await sample(page)) })
    logp(`  [mid]    fps=${rows.at(-1).avgFps} p5=${rows.at(-1).p5Fps} draws=${rows.at(-1).drawCalls}`)

    // far: same rep, force-far via thresholds (huge close + huge far) → no rebuild
    await setThresholds(page, 1e9, 1e9)
    await setDist(page, fit)
    rows.push({ n, phase: 'tier', tier: 'far', rep: 'cylinders', distMult: 1.0, buildMs: 0, ...(await sample(page)) })
    logp(`  [far]    fps=${rows.at(-1).avgFps} p5=${rows.at(-1).p5Fps} draws=${rows.at(-1).drawCalls}`)

    // hull: rep hull-prism (distance-independent)
    const hullBuildMs = await setRepSettle(page, 'hull-prism')
    await setThresholds(page, 60, 8)
    await setDist(page, fit)
    rows.push({ n, phase: 'tier', tier: 'hull', rep: 'hull-prism', distMult: 1.0, buildMs: Math.round(hullBuildMs), ...(await sample(page)) })
    logp(`  [hull]   fps=${rows.at(-1).avgFps} p5=${rows.at(-1).p5Fps} draws=${rows.at(-1).drawCalls}`)
  }

  // ── Emit results ──────────────────────────────────────────────────────────
  writeFileSync(join(RESULTS_DIR, 'lod_fps.json'), JSON.stringify(rows, null, 2))

  const md = []
  md.push('# LOD FPS sweep results\n')
  md.push(`Sample window: ${SAMPLE_MS} ms. avg/p5/min in FPS. draws = draw calls, tris in thousands.\n`)
  md.push('## Per-tier isolation (fit-all framing)\n')
  md.push('| N | tier | rep | buildMs | avgFps | p5Fps | minFps | draws | tris(k) |')
  md.push('|--:|------|-----|--------:|-------:|------:|-------:|------:|--------:|')
  for (const r of rows.filter(r => r.phase === 'tier')) {
    md.push(`| ${r.n} | ${r.tier} | ${r.rep} | ${r.buildMs ?? ''} | ${r.avgFps ?? '-'} | ${r.p5Fps ?? '-'} | ${r.minFps ?? '-'} | ${r.drawCalls ?? '-'} | ${r.triangles != null ? Math.round(r.triangles / 1e3) : '-'} |`)
  }
  md.push('\n## Angular sweep (rep=full, thresholds 60/8)\n')
  md.push('| N | distMult | avgFps | p5Fps | draws | tris(k) | close | mid | far | pxRange |')
  md.push('|--:|---------:|-------:|------:|------:|--------:|------:|----:|----:|--------|')
  for (const r of rows.filter(r => r.phase === 'angular')) {
    const c = r.lod?.counts ?? {}
    const px = r.lod ? `${(r.lod.minPx ?? 0).toFixed(0)}…${(r.lod.maxPx ?? 0).toFixed(0)}` : '-'
    md.push(`| ${r.n} | ${r.distMult} | ${r.avgFps ?? '-'} | ${r.p5Fps ?? '-'} | ${r.drawCalls ?? '-'} | ${r.triangles != null ? Math.round(r.triangles / 1e3) : '-'} | ${c.close ?? '-'} | ${c.mid ?? '-'} | ${c.far ?? '-'} | ${px} |`)
  }
  writeFileSync(join(RESULTS_DIR, 'lod_fps.md'), md.join('\n') + '\n')
  console.log(`\n=== wrote ${join(RESULTS_DIR, 'lod_fps.json')} + lod_fps.md (${rows.length} rows) ===`)

  expect(rows.length).toBeGreaterThan(0)
})
