/**
 * Occupancy clouds — crossover extra bases and extension tails must appear in the drawn
 * states, at their SIMULATED positions.
 *
 * Extra bases have no (helix, bp, direction) key: `buildHelixObjects` emits no geometry
 * for them and `applyFemPositions` drops their `__xb__` updates, so a ghost that only
 * calls the helix builder is missing them entirely. This drives the REAL renderer with a
 * REAL payload and checks the beads land on the coordinates the backend sent.
 *
 * It calls `setClusters` directly rather than going through the radio, because no job on
 * this machine is both "switching" (the verdict that draws ghosts) AND has extra bases —
 * the 1xT runs report drift/unimodal. The renderer is what is under test here; the verdict
 * gate is covered by occupancy_clouds.spec.js.
 *
 * Skips unless a job with extra bases is present. Override with NADOC_E2E_XB_JOB.
 */

import { expect, test } from '@playwright/test'

const API = `${process.env.NADOC_E2E_API_BASE || 'http://127.0.0.1:8002'}/api`
// 6hbx100_1xT production — 60 __xb__ inserts (one T per crossover).
const JOB_ID = process.env.NADOC_E2E_XB_JOB || '012a0fbe2de2'

test('extra bases are drawn in each occupancy state, at their simulated positions',
  async ({ page, request }) => {
    test.setTimeout(600_000)

    const jr = await request.get(`${API}/oxdna/jobs/${JOB_ID}`).catch(() => null)
    test.skip(!jr?.ok(), `oxDNA job ${JOB_ID} not present on ${API}`)
    const job = await jr.json()

    await page.goto('/', { timeout: 120_000 })
    await page.waitForSelector('#canvas', { timeout: 120_000 })
    await page.evaluate(() => {
      for (const id of ['splash-screen', 'welcome-screen']) {
        document.getElementById(id)?.style.setProperty('display', 'none')
      }
    })

    // Load through the page's own client so the store — and therefore the ghost's
    // geometry/design — actually populates.
    // A job records design_source_path as a BARE FILENAME, which the backend resolves
    // against the repo root — designs actually live in workspace/. Try both.
    const loadInfo = await page.evaluate(async (fp) => {
      const client = await import('/src/api/client.js')
      const { store } = await import('/src/state/store.js')
      const tried = []
      for (const cand of [fp, `workspace/${fp}`]) {
        tried.push(cand)
        try { await client.loadDesign(cand) } catch { /* try the next candidate */ }
        if (store.getState().currentDesign) break
      }
      const st = store.getState()
      return {
        tried,
        hasOverlay: !!window.__nadocOccupancy,
        nGeom: st.currentGeometry?.length ?? null,
        hasDesign: !!st.currentDesign,
        lastError: st.lastError ?? null,
      }
    }, job.design_source_path)
    expect(loadInfo, `design load diagnostics: ${JSON.stringify(loadInfo)}`)
      .toMatchObject({ hasOverlay: true, hasDesign: true })
    await expect
      .poll(async () => page.evaluate(() => !!window.__nadocOccupancy?.stats?.().hasGeometry),
        { timeout: 120_000 })
      .toBe(true)

    // Watch for console errors only from here on: probing the two candidate design paths
    // above deliberately provokes a 400 for whichever one does not exist.
    const errors = []
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })
    page.on('pageerror', (e) => errors.push(String(e)))

    // Fetch the real payload and hand it straight to the overlay.
    const info = await page.evaluate(async (jobId) => {
      const client = await import('/src/api/client.js')
      const resp = await client.getOxdnaOccupancy(jobId, {})
      if (!resp?.ready) return { ready: false, reason: resp?.reason }

      const xbIdx = resp.keys.findIndex((k) => k[0] === '__xb__')
      await window.__nadocOccupancy.setClusters(resp)

      let beads = null
      let group = null
      window.__nadocScene.traverse((o) => {
        if (o.name === 'occupancyGhost0') group = o
      })
      group?.traverse((o) => { if (o.name === 'xoverExtraBeads') beads = o })

      // Compare SETS, not index-for-index: bead instances are ordered by the design's
      // crossover iteration (beadStartIdx), while payload keys follow the strand walk, so
      // instance i and key i are different inserts.
      // Read the instance matrices directly — a bare `import('three')` is not resolvable
      // at runtime in the page; a column-major 4x4's translation is elements 12,13,14.
      const drawn = []
      if (beads?.instanceMatrix?.array) {
        const a = beads.instanceMatrix.array
        for (let i = 0; i < beads.count; i++) {
          drawn.push([a[i * 16 + 12], a[i * 16 + 13], a[i * 16 + 14]])
        }
      }
      const wanted = []
      resp.keys.forEach((k, i) => {
        if (k[0] === '__xb__') wanted.push(resp.clusters[0].frame.slice(i * 6, i * 6 + 3))
      })
      const near = (p, q) => Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2]) < 0.05
      const matched = wanted.filter((w) => drawn.some((d) => near(d, w))).length
      return {
        ready: true,
        nXb: resp.keys.filter((k) => k[0] === '__xb__').length,
        nExt: resp.keys.filter((k) => String(k[0]).startsWith('__ext_')).length,
        expectedFirstXb: xbIdx >= 0
          ? resp.clusters[0].frame.slice(xbIdx * 6, xbIdx * 6 + 3) : null,
        hasBeadsMesh: !!beads,
        beadCount: beads?.count ?? 0,
        nDrawn: drawn.length,
        nWanted: wanted.length,
        matched,
        sampleDrawn: drawn.slice(0, 2),
        sampleWanted: wanted.slice(0, 2),
        states: window.__nadocOccupancy.stats().states,
      }
    }, JOB_ID)

    test.skip(!info.ready, `occupancy not ready: ${info.reason}`)
    test.skip(!info.nXb, 'this job has no crossover extra bases')

    expect(info.states, 'a state was drawn').toBeGreaterThan(0)
    expect(info.hasBeadsMesh, 'the ghost carries an extra-base mesh').toBe(true)
    expect(info.beadCount, 'one instance per insert').toBeGreaterThanOrEqual(info.nXb)

    // Every insert the backend sent must be drawn where the simulation put it — not on
    // the design-pose Bezier.
    expect(info.matched, `inserts placed at simulated positions: ${JSON.stringify(info)}`)
      .toBe(info.nWanted)

    expect(errors, `console errors: ${errors.join('\n')}`).toEqual([])
  })
