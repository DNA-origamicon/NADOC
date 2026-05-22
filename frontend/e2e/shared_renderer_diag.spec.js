/**
 * Diagnostic harness for the path-to-thousands shared-instancing renderer.
 *
 * Loads a representative .nass (default: `workspace/50 hinge test.nass`),
 * forces the shared path on via `localStorage`, then probes the live
 * Three.js scene through `window.__NADOC_DBG__`.  Emits scene-state JSON +
 * screenshots for three feature gaps that still block the flag-flip:
 *
 *   A. Rep change full ↔ cylinders triggers a per-instance geometry refetch
 *      instead of the legacy `_inPlaceHelixLodRebuild` swap.
 *   B. Store change `coloringMode: 'part'` doesn't propagate to material
 *      colours on the shared path (subscriber wiring missing).
 *   C. Far LOD: distant instances collapse to the grey hull solid
 *      (the billboard tier was retired — see assembly_renderer.js).
 *
 * This is a DIAGNOSTIC, not a regression assertion.  Asserts are limited
 * to "assembly loaded + something rendered" so the spec doesn't fail while
 * the gaps are open.  Re-purpose into a regression test once each fix lands.
 *
 * Skipped automatically when:
 *   - the fixture file isn't present (CI / fresh checkouts),
 *   - or the env var `NADOC_SKIP_DIAG=1` is set.
 *
 * Run manually with:
 *   cd frontend && npx playwright test e2e/shared_renderer_diag.spec.js \
 *                                       --reporter=list > /tmp/diag.log 2>&1
 *
 * Override the fixture via `NADOC_DIAG_FIXTURE=/path/to/some.nass`.
 */
import { test, expect } from '@playwright/test'
import { existsSync, readFileSync } from 'node:fs'
import { resolve as resolvePath } from 'node:path'

const DEFAULT_FIXTURE = resolvePath(
  process.cwd(), '..', 'workspace', '50 hinge test.nass',
)
const FIXTURE = process.env.NADOC_DIAG_FIXTURE ?? DEFAULT_FIXTURE
const SCREENSHOT_DIR = 'e2e/screenshots/shared_renderer_diag'

test.describe.configure({ mode: 'serial' })
test.setTimeout(180_000)

test.skip(
  process.env.NADOC_SKIP_DIAG === '1',
  'NADOC_SKIP_DIAG=1 — diagnostic intentionally skipped.',
)
test.skip(
  !existsSync(FIXTURE),
  `fixture missing: ${FIXTURE} (set NADOC_DIAG_FIXTURE to override)`,
)

/** Pull the shared renderer's per-source state out of the debug hook. */
async function probe(page, label) {
  return await page.evaluate((label) => {
    const dbg = window.__NADOC_DBG__
    if (!dbg) return { error: 'no __NADOC_DBG__ — shared renderer flag may be off' }
    const ar = dbg.assemblyRenderer
    const store = dbg.store?.getState?.() ?? {}
    const cam = dbg.camera
    const scene = dbg.scene
    const renderer = dbg.renderer

    const meshStats = []
    scene.traverse((obj) => {
      if (obj.isInstancedMesh) {
        meshStats.push({
          name: obj.name || obj.userData?.tag || obj.type,
          count: obj.count,
          visible: obj.visible,
          material: obj.material?.name || obj.material?.type,
          color: obj.material?.color ? `#${obj.material.color.getHexString()}` : null,
        })
      }
    })

    const repHist = {}
    for (const inst of (store.currentAssembly?.instances ?? [])) {
      const r = inst.representation ?? 'unset'
      repHist[r] = (repHist[r] ?? 0) + 1
    }

    return {
      label,
      window_NADOC_SHARED_RENDERER: window.NADOC_SHARED_RENDERER,
      store: {
        coloringMode: store.coloringMode,
        assemblyActive: store.assemblyActive,
        currentAssembly_instance_count: store.currentAssembly?.instances?.length,
      },
      camera_dist_to_origin: cam.position.length().toFixed(1),
      assemblyRendererCaps: {
        hasUpdateColoringMode: typeof ar?.updateColoringMode === 'function',
        hasUpdateStrandColor: typeof ar?.updateStrandColor === 'function',
        hasInPlaceLodRebuild: typeof ar?._inPlaceHelixLodRebuild === 'function',
      },
      perInstanceRepHist: repHist,
      instancedMeshes: meshStats,
      renderer_info: {
        calls: renderer.info.render?.calls,
        triangles: renderer.info.render?.triangles,
      },
    }
  }, label)
}

async function snap(page, name) {
  await page.screenshot({ path: `${SCREENSHOT_DIR}/${name}.png`, fullPage: false })
}

test('shared renderer: load fixture + probe state', async ({ page }) => {
  page.on('console', msg => {
    const t = msg.text()
    // Drop the per-instance GET noise that floods the log when rep change
    // fires off 200 design fetches.  We already know the API hammering is
    // happening; we don't need every URL.
    if (t.startsWith('[API') && t.includes('/assembly/instances/')) return
    console.log(`[browser ${msg.type()}] ${t}`)
  })
  page.on('pageerror', err => console.log(`[browser error] ${err.message}`))

  // ── 1. Force the shared path on via localStorage (pre-flag-flip default).
  await page.addInitScript(() => {
    localStorage.setItem('NADOC_SHARED_RENDERER', 'true')
  })

  // ── 2. Open the app first so client.js loads and __NADOC_DBG__ becomes available.
  await page.goto('/')
  await page.waitForFunction(() => !!window.__NADOC_DBG__, null, { timeout: 15_000 })

  // ── 3. Inject the .nass via api.importAssembly + assemblyRenderer.rebuild
  //      (the menu File-Open flow at main.js ~L8140-8200).
  const nassContent = readFileSync(FIXTURE, 'utf-8')
  await page.evaluate(async (content) => {
    const apiModule = await import('/src/api/client.js')
    const ok = await apiModule.importAssembly(content)
    if (!ok) throw new Error('importAssembly returned falsy')
    const assembly = window.__NADOC_DBG__.store.getState().currentAssembly
    await window.__NADOC_DBG__.assemblyRenderer.rebuild(assembly)
  }, nassContent)
  await page.waitForFunction(
    () => (window.__NADOC_DBG__?.store?.getState?.()?.currentAssembly?.instances?.length ?? 0) > 0,
    null,
    { timeout: 30_000 },
  )

  // ── 4. Enter assembly mode (no exposed setter — flip the store + hide
  //      welcome panel to mirror _enterAssemblyMode's user-visible effects).
  await page.evaluate(() => {
    document.getElementById('welcome-screen')?.style.setProperty('display', 'none')
    document.getElementById('welcome')?.style.setProperty('display', 'none')
    window.__NADOC_DBG__.store.setState({ assemblyActive: true })
  })
  await page.waitForTimeout(2000)

  const p0 = await probe(page, 'baseline_after_load')
  console.log('\n=== PROBE: baseline_after_load ===')
  console.log(JSON.stringify(p0, null, 2))
  await snap(page, '01_baseline')

  // ── Bug A — rep change to 'full' via UI click ───────────────────────────────
  // The full-rep button id is `menu-view-detail-full` (see main.js _ALL_REPRS).
  // On the legacy renderer this triggers `_inPlaceHelixLodRebuild`; on the
  // shared renderer it falls back to a full rebuild that re-fetches every
  // instance's geometry serially.
  await page.evaluate(() => {
    const btn = document.getElementById('menu-view-detail-full')
    if (!btn) { console.log('[diag] no menu-view-detail-full button'); return }
    btn.click()
  })
  // batchPatchInstances + rebuild + cluster_panel's per-instance design refetch
  // serialise badly at N=200; wait 60s to let the LOD reflect new rep.
  await page.waitForFunction(
    () => {
      const inst = window.__NADOC_DBG__?.store?.getState?.()?.currentAssembly?.instances ?? []
      return inst.length > 0 && inst.every(i => i.representation === 'full')
    },
    null,
    { timeout: 60_000 },
  )
  // Settle a beat for the renderer rebuild + LOD bucketing to land.
  await page.waitForTimeout(3000)
  const pFull = await probe(page, 'after_rep_full')
  console.log('\n=== PROBE: after_rep_full ===')
  console.log(JSON.stringify(pFull, null, 2))
  await snap(page, '02_rep_full')

  // ── Bug B — coloring mode change via store setState ─────────────────────────
  await page.evaluate(() => {
    window.__NADOC_DBG__.store.setState({ coloringMode: 'part' })
  })
  await page.waitForTimeout(1500)
  const pColor = await probe(page, 'after_coloring_part')
  console.log('\n=== PROBE: after_coloring_part ===')
  console.log(JSON.stringify(pColor, null, 2))
  await snap(page, '03_color_part')

  // ── Zoom out to exercise the far LOD (hull solids — billboard tier retired) ─
  await page.evaluate(() => {
    const cam = window.__NADOC_DBG__.camera
    cam.position.set(0, 0, 8000)
    cam.lookAt(0, 0, 0)
  })
  await page.waitForTimeout(1500)
  const pFar = await probe(page, 'after_zoom_out')
  console.log('\n=== PROBE: after_zoom_out ===')
  console.log(JSON.stringify(pFar, null, 2))
  await snap(page, '04_far_lod')

  // Halfway back for mid-LOD.
  await page.evaluate(() => {
    const cam = window.__NADOC_DBG__.camera
    cam.position.set(0, 0, 1500)
    cam.lookAt(0, 0, 0)
  })
  await page.waitForTimeout(1000)
  const pMid = await probe(page, 'after_zoom_mid')
  console.log('\n=== PROBE: after_zoom_mid ===')
  console.log(JSON.stringify(pMid, null, 2))
  await snap(page, '05_mid_lod')

  // ── Move camera to within closeDist of one specific instance to verify bp
  //      meshes actually draw when within range.  Reads the first instance's
  //      translation column directly from xformData.
  await page.evaluate(() => {
    const dbg = window.__NADOC_DBG__
    const src = dbg.assemblyRenderer._sourcesForTest?.()?.values?.()?.next?.()?.value
    if (!src) { console.log('[diag] no source entry'); return }
    const x = src.xformData[12], y = src.xformData[13], z = src.xformData[14]
    const cam = dbg.camera
    cam.position.set(x + 5, y + 5, z + 5)   // 5 units off the first instance
    cam.lookAt(x, y, z)
    console.log(`[diag] camera moved to (${(x+5).toFixed(1)}, ${(y+5).toFixed(1)}, ${(z+5).toFixed(1)}) targeting instance at (${x.toFixed(1)}, ${y.toFixed(1)}, ${z.toFixed(1)})`)
  })
  await page.waitForTimeout(1500)
  const pCloseup = await probe(page, 'after_zoom_to_instance')
  console.log('\n=== PROBE: after_zoom_to_instance ===')
  console.log(JSON.stringify(pCloseup, null, 2))
  await snap(page, '06_closeup')

  // Sanity asserts — diagnostic still wants to fail if the FIXTURE didn't
  // load at all (e.g. backend down, .nass corrupt).  Does NOT assert on bug
  // states; those are open until the gaps are fixed.
  expect(p0.store.currentAssembly_instance_count).toBeGreaterThan(0)
  expect(p0.renderer_info.triangles ?? 0).toBeGreaterThan(0)
})
