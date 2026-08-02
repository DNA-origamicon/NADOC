/**
 * Occupancy clouds for NAMD — the MD twin of occupancy_clouds.spec.js.
 *
 * Proves the MD half end to end in the real app: the radio exists in the md-viz group,
 * the route answers with the SAME payload shape the oxDNA overlay already draws, and the
 * ENM restraint ramp is excluded from the ensemble by default.
 *
 * A NAMD analysis has no shared frame cache and re-reads the whole trajectory in a
 * spawned subprocess (~36 s measured on a 6.7 k-nucleotide, 120-frame run), so the
 * timeouts here are deliberately generous.
 *
 * Skips unless an MD job with written frames is present. Override with NADOC_E2E_MD_JOB.
 */

import { expect, test } from '@playwright/test'

const API = `${process.env.NADOC_E2E_API_BASE || 'http://127.0.0.1:8002'}/api`
const JOB_ID = process.env.NADOC_E2E_MD_JOB || '383f7dcc4a5d'   // 24hb_0xT, 4 stages

test('NAMD occupancy clusters the free-sampling ensemble only', async ({ page, request }) => {
  test.setTimeout(900_000)

  const jr = await request.get(`${API}/md/jobs/${JOB_ID}`).catch(() => null)
  test.skip(!jr?.ok(), `MD job ${JOB_ID} not present on ${API}`)
  const job = await jr.json()

  await page.goto('/', { timeout: 120_000 })
  await page.waitForSelector('#canvas', { timeout: 120_000 })
  await page.evaluate(() => {
    for (const id of ['splash-screen', 'welcome-screen']) {
      document.getElementById(id)?.style.setProperty('display', 'none')
    }
  })

  // The MD analysis routes resolve the design from the session when the job carries no
  // snapshot, so a design must be loaded — and through the PAGE, or the store stays empty.
  await page.evaluate(async (fp) => {
    const client = await import('/src/api/client.js')
    const { store } = await import('/src/state/store.js')
    for (const cand of [fp, `workspace/${fp}`]) {
      try { await client.loadDesign(cand) } catch { /* try the next candidate */ }
      if (store.getState().currentDesign) break
    }
  }, job.design_source_path)

  // The radio must exist in the md-viz group — a missing id is silent (every listener is
  // skipped with ?. and the feature simply never appears).
  const toggle = page.locator('#md-jobs-occupancy-toggle')
  await expect(toggle).toHaveCount(1)
  expect(await toggle.getAttribute('name')).toBe('md-viz')
  await expect(page.locator('#md-jobs-occupancy-all-stages')).toHaveCount(1)
  await expect(page.locator('#md-occupancy-scope-list')).toHaveCount(1)

  // Drive the route directly: it is the payload contract that matters here, and the
  // subprocess read is far too slow to sit behind a UI toggle in a test.
  const info = await page.evaluate(async (jobId) => {
    const client = await import('/src/api/client.js')
    const resp = await client.getMdOccupancy(jobId, undefined, {})
    if (!resp?.ready) return { ready: false, reason: resp?.reason }
    return {
      ready: true,
      verdict: resp.verdict,
      nKeys: resp.keys.length,
      frameLen: resp.clusters[0].frame.length,
      nFrames: resp.n_frames,
      nFramesTotal: resp.n_frames_total,
      stages: resp.sampling_stages,
      allStages: resp.all_stages,
      hasConfidence: !!resp.confidence,
    }
  }, JOB_ID)

  test.skip(!info.ready, `MD occupancy not ready: ${info.reason}`)

  // Same wire shape as oxDNA, so the same overlay draws it unchanged.
  expect(info.frameLen, 'xyz+normal per key').toBe(info.nKeys * 6)
  expect(['switching', 'drift', 'unimodal']).toContain(info.verdict)
  expect(info.hasConfidence).toBe(true)

  // The ENM restraint ramp is a one-way relaxation; clustering across it would report the
  // ramp itself rather than the structure. Only unrestrained stages form the ensemble.
  if (!info.allStages) {
    expect(info.stages.every((s) => !/enm|fixed|minim/i.test(s)),
      `sampling stages were ${JSON.stringify(info.stages)}`).toBe(true)
    expect(info.nFrames, 'a subset of the run').toBeLessThan(info.nFramesTotal)
  }
})
