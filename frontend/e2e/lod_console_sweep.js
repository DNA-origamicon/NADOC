/* ============================================================================
 * NADOC — LOD FPS sweep on YOUR REAL GPU  (path-to-thousands benchmark)
 * ============================================================================
 * Headless Playwright on this box renders with SwiftShader (software GL), so it
 * can't measure real frame rates. This script runs in YOUR browser, against
 * your actual GPU.
 *
 * HOW TO RUN
 *   1. Start both dev servers (`just dev`, `just frontend`) and open the app
 *      at http://localhost:5173 in Chrome (the shared renderer is the default).
 *   2. Open DevTools → Console.
 *   3. Copy this ENTIRE file and paste it at the console prompt, press Enter.
 *   4. Wait (~5 min for all five fixtures). Watch the [lodbench] log lines.
 *   5. When done it prints a console.table AND a JSON blob — copy the JSON line
 *      and paste it back to me. Results are also in window.__NADOC_LOD_RESULTS__.
 *
 * WHAT IT MEASURES, per fixture (N = 1/20/50/200/500 hinges):
 *   • close  — every instance forced to bp-detail (rep=full, thresholds 0/0)
 *   • ang0.25…ang6.0 — rep=full at DEFAULT thresholds (60/8), camera stepped
 *                      from zoomed-in (0.25× fit) to far-out (6× fit); shows the
 *                      natural close/mid/far bucket split + FPS at each.
 *   • mid    — every instance as one-cylinder-per-helix (rep=cylinders)
 *   • far    — cylinders rep zoomed far out → instances collapse to the hull
 *              solid (the billboard tier was retired; this row exercises the
 *              cylinders→hull demotion path)
 *   • hull   — every instance as a grey hull-prism solid
 * Each row records avgFps, p5Fps (worst-case stutter), draw calls, triangles,
 * and the LOD bucket counts.
 *
 * Tweak NS / DIST_MULTS / SAMPLE_MS below for a quick subset run.
 * ==========================================================================*/
(async () => {
  const D = window.__NADOC_DBG__
  if (!D?.assemblyRenderer?.getBoundingBox) {
    console.error('[lodbench] Shared renderer not active. Open the app normally '
      + '(shared renderer is the default) BEFORE pasting this.')
    return
  }
  const { camera, controls, renderer, assemblyRenderer: ar, store, THREE } = D
  const api = await import('/src/api/client.js')

  // ── config (override any of these by setting window.__LB_* before pasting,
  //    e.g.  window.__LB_NS = [20, 200]  for a quick subset run) ──────────────
  const NS = window.__LB_NS ?? [1, 20, 50, 200, 500]   // fixture sizes to sweep
  const DIST_MULTS = window.__LB_DIST ?? [0.25, 0.6, 1.0, 2.5, 6.0]  // × fit-all distance
  const SAMPLE_MS = window.__LB_SAMPLE_MS ?? 2000      // FPS sample window per data point
  const DIR = window.__LB_DIR ?? 'bench_fixtures'      // workspace subdir of the .nass files
  const VIEW = new THREE.Vector3(1, 0.55, 1).normalize()  // canonical 3/4 view

  const sleep = ms => new Promise(r => setTimeout(r, ms))
  // resolve after a few clean frames (rAF only fires when the main thread is idle)
  const settle = (n = 3) => new Promise(res => {
    let i = 0; const t = () => (++i >= n ? res() : requestAnimationFrame(t)); requestAnimationFrame(t)
  })
  // rebuild-completion counter (the shared renderer fires onRebuildComplete at
  // every rebuild() exit; a rep change / fixture load triggers exactly one).
  if (!window.__lbHook) { window.__lbGen = 0; ar.onRebuildComplete(() => { window.__lbGen++ }); window.__lbHook = true }
  const waitGen = async (g, to = 240000) => {
    const t0 = performance.now()
    while (window.__lbGen <= g && performance.now() - t0 < to) await sleep(100)
    if (window.__lbGen <= g) console.warn('[lodbench] rebuild wait timed out — sample may be stale')
  }

  // real-FPS sampler: collect frame deltas over a wall-clock window
  const sampleFps = ms => new Promise(res => {
    const dts = []; let last = performance.now(), acc = 0
    const tick = () => {
      const now = performance.now(), dt = now - last; last = now; dts.push(dt); acc += dt
      if (acc >= ms && dts.length > 1) {
        const arr = dts.slice(1).map(d => 1000 / d).sort((a, b) => a - b)  // drop 1st (warm-up)
        const q = p => arr[Math.min(arr.length - 1, Math.max(0, Math.floor(p * arr.length)))]
        res({
          frames: arr.length,
          avgFps: +(arr.reduce((s, v) => s + v, 0) / arr.length).toFixed(1),
          p5Fps: +q(0.05).toFixed(1),
          minFps: +arr[0].toFixed(1),
          drawCalls: renderer.info.render.calls,
          triangles: renderer.info.render.triangles,
        })
      } else requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)
  })

  const box = () => ar.getBoundingBox()
  const radius = () => { const b = box(); return (b && !b.isEmpty()) ? b.getBoundingSphere(new THREE.Sphere()).radius : 50 }
  const fitDist = (m = 1.15) => radius() * m / Math.tan(camera.fov * Math.PI / 360)
  const setDist = d => {
    const b = box(); if (!b || b.isEmpty()) return
    const c = b.getCenter(new THREE.Vector3()), r = radius()
    camera.position.copy(c).add(VIEW.clone().multiplyScalar(d))
    controls.target.copy(c)
    camera.near = Math.max(0.1, d - r * 2); camera.far = d + r * 4
    camera.updateProjectionMatrix(); controls.update()
  }
  const setThr = (closePx, farPx) => ar.setLodThresholds({ closePx, farPx })
  const setRep = async rep => {
    const insts = store.getState().currentAssembly?.instances ?? []
    if (!insts.length) return
    const g = window.__lbGen
    await api.batchPatchInstances(insts.map(i => ({ id: i.id, representation: rep })))
    await waitGen(g); await settle()   // reactive rebuild only — do NOT call rebuild() here
  }
  const probe = () => {
    const s = ar.probeLod?.()?.sources?.[0]; const c = s?.counts ?? {}
    return { close: c.close ?? 0, mid: c.mid ?? 0, far: c.far ?? 0, hull: c.hull ?? 0,
             minPx: s?.minPxSize ?? null, maxPx: s?.maxPxSize ?? null }
  }

  const rows = []
  for (const n of NS) {
    const file = `${DIR}/bench_hinge_${String(n).padStart(3, '0')}.nass`
    let res
    try { res = await api.getLibraryFileContent(file) }
    catch (e) { console.warn(`[lodbench] skip ${file}: ${e?.message ?? e}`); continue }
    if (!res?.content) { console.warn(`[lodbench] no content ${file}`); continue }

    console.log(`%c[lodbench] N=${n}: loading + rebuilding…`, 'color:#58a6ff;font-weight:bold')
    const g0 = window.__lbGen, t0 = performance.now()
    await api.importAssembly(res.content)
    store.setState({ assemblyActive: true })   // first load: modeChanged rebuild; later: import already rebuilt
    await waitGen(g0); await settle()
    const loadMs = Math.round(performance.now() - t0)
    console.log(`[lodbench] N=${n}: loaded (${loadMs} ms) — sweeping tiers…`)

    // PART A — close tier (every instance bp-detail)
    await setRep('full'); const fit = fitDist()
    setThr(0, 0); setDist(fit); await sleep(500)
    rows.push({ n, tier: 'close', loadMs, ...(await sampleFps(SAMPLE_MS)), ...probe() })

    // PART B — angular sweep at default thresholds (rep stays full)
    setThr(60, 8)
    for (const m of DIST_MULTS) {
      setDist(fit * m); await sleep(500)
      rows.push({ n, tier: 'ang' + m, ...(await sampleFps(SAMPLE_MS)), ...probe() })
    }

    // PART A cont. — mid (cylinders) then far (cylinders zoomed out → hull) then hull
    await setRep('cylinders')
    setThr(1e9, 0); setDist(fit); await sleep(500)
    rows.push({ n, tier: 'mid', ...(await sampleFps(SAMPLE_MS)), ...probe() })
    // farPx=1e9 forces every cylinders instance below threshold → hull demotion
    // (no billboard tier). The probe's `hull` count picks these up; `far` is 0.
    setThr(1e9, 1e9); setDist(fit); await sleep(500)
    rows.push({ n, tier: 'far', ...(await sampleFps(SAMPLE_MS)), ...probe() })

    await setRep('hull-prism')
    setThr(60, 8); setDist(fit); await sleep(500)
    rows.push({ n, tier: 'hull', ...(await sampleFps(SAMPLE_MS)), ...probe() })

    console.log(`%c[lodbench] N=${n}: done`, 'color:#3fb950')
  }

  window.__NADOC_LOD_RESULTS__ = rows
  console.table(rows.map(r => ({
    N: r.n, tier: r.tier, avgFps: r.avgFps, p5Fps: r.p5Fps,
    draws: r.drawCalls, trisK: r.triangles ? Math.round(r.triangles / 1e3) : '',
    close: r.close, mid: r.mid, far: r.far, hull: r.hull,
  })))
  console.log('%c[lodbench] COPY THE NEXT LINE (JSON) back to share results:', 'color:#d29922;font-weight:bold')
  console.log(JSON.stringify(rows))
  console.log('[lodbench] DONE — ' + rows.length + ' rows; also in window.__NADOC_LOD_RESULTS__')
})()
