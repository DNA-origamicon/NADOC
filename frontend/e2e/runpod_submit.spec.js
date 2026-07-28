/**
 * REAL end-to-end: submit a NAMD relaxation to RunPod through the app's own path
 * (connect → preflight → create+prepare job → start → rent a real pod → NAMD runs → teardown).
 *
 * ⚠️ THIS RENTS A REAL RUNPOD GPU (~$0.50). It is deliberately NOT in the `just smoke` allowlist.
 * Run explicitly:
 *   NADOC_E2E_RUNPOD=1 npx playwright test --config frontend/playwright.config.js \
 *     e2e/runpod_submit.spec.js
 *
 * Uses a SMALL full-box design (10hb) — the release NAMD build on the volume runs it fine.
 * VoltronCore's sparse water-shell box dies at step 0 on that build (see RUNPOD_RUNBOOK §7), so
 * it is intentionally NOT used here. The relax ladder has no minutes-scale mode, so the test
 * asserts the PIPELINE — pod actually rented, NAMD actually running (not step-0-failed), pod
 * actually destroyed — not a completed relaxation.
 */
import { expect, test } from '@playwright/test'
import { existsSync, readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import path from 'node:path'

const API = process.env.NADOC_E2E_API_BASE || 'http://127.0.0.1:8002'
const KEY_FILE = path.join(homedir(), '.runpod_key')
const VOLUME = '77pnhye88p'
const DESIGN = '/home/jojo/Work/NADOC/workspace/10hb.nadoc'

// Opt-in + key-gated: this test spends money, so it no-ops unless explicitly enabled.
const ENABLED = process.env.NADOC_E2E_RUNPOD === '1' && existsSync(KEY_FILE)

async function jobStatus(request, jobId) {
  const r = await request.get(`${API}/api/md/jobs`)
  const body = await r.json()
  const j = (body.jobs || body).find(x => x.job_id === jobId)
  return j || {}
}
async function livePods(request) {
  const r = await request.get(`${API}/api/runpod/pods`).catch(() => null)
  if (!r) return []
  const body = await r.json().catch(() => ({ pods: [] }))
  return body.pods || []
}

test.describe('RunPod relax submission (REAL pod)', () => {
  test.skip(!ENABLED, 'set NADOC_E2E_RUNPOD=1 and provide ~/.runpod_key to run (rents a GPU)')
  test.setTimeout(15 * 60 * 1000) // prep + rent + run + teardown

  test('submit a small relax to RunPod: rent → NAMD runs → teardown', async ({ request }) => {
    const apiKey = readFileSync(KEY_FILE, 'utf8').trim()
    let jobId = null

    try {
      // 1 ── connect the in-memory RunPod session
      const conn = await request.post(`${API}/api/runpod/connect`, {
        data: { api_key: apiKey, network_volume_id: VOLUME },
      })
      expect(conn.status(), 'connect').toBe(200)
      expect((await conn.json()).connected, 'connected').toBe(true)

      // 2 ── $0 preflight GATE: no pod is rented if this fails
      const pre = await (await request.post(`${API}/api/runpod/preflight`, { data: {} })).json()
      expect(pre.ok, `preflight failed: ${JSON.stringify(pre.checks)}`).toBe(true)

      // 3 ── load a SMALL full-box design (runs on the release build, unlike sparse VoltronCore)
      const load = await request.post(`${API}/api/design/load`, { data: { path: DESIGN } })
      expect(load.status(), 'load 10hb').toBe(200)

      // 4 ── create + prepare a relax job targeting RunPod (solvation runs async → 'preparing')
      const create = await request.post(`${API}/api/md/jobs`, {
        data: { execution_target: 'runpod', autostart: false },
      })
      expect(create.status(), 'create job').toBe(200)
      jobId = (await create.json()).job_id
      expect(jobId, 'job_id').toBeTruthy()

      // 5 ── wait for preparation to finish (→ queued); surface a prep failure clearly
      await expect
        .poll(async () => (await jobStatus(request, jobId)).status,
          { timeout: 300000, intervals: [3000] })
        .not.toBe('preparing')
      const prepared = await jobStatus(request, jobId)
      expect(prepared.status, `prep ended ${prepared.status}: ${prepared.error || ''}`).toBe('queued')

      // 6 ── START → the app's RunPod submission path → status running
      const start = await request.post(`${API}/api/md/jobs/${jobId}/start`)
      expect(start.status(), 'start').toBe(200)
      expect((await start.json()).status, 'runpod start status').toBe('running')

      // 7 ── a REAL pod appears (anything in /runpod/pods is billing == proof of rental)
      await expect
        .poll(async () => (await livePods(request)).length,
          { timeout: 300000, intervals: [5000] })
        .toBeGreaterThan(0)

      // 8 ── NAMD genuinely runs: the job STAYS running past boot + first steps.
      //      A sparse-box step-0 failure would flip it to 'failed' within ~1 min.
      await new Promise(r => setTimeout(r, 150000)) // 2.5 min: pod boot + NAMD start + steps
      const mid = await jobStatus(request, jobId)
      expect(['running', 'completed'], `job went ${mid.status}: ${mid.error || ''}`)
        .toContain(mid.status)

      // 9 ── teardown: stop the job (destroys the pod), then prove the pod is gone
      const stop = await request.post(`${API}/api/md/jobs/${jobId}/stop`)
      expect(stop.status(), 'stop').toBe(200)
      await expect
        .poll(async () => (await livePods(request)).length,
          { timeout: 180000, intervals: [5000] })
        .toBe(0)
    } finally {
      // belt-and-braces cleanup — best-effort, never masks the real assertion
      try {
        if (jobId) await request.post(`${API}/api/md/jobs/${jobId}/stop`).catch(() => {})
        for (const p of await livePods(request)) {
          await request.post(`${API}/api/runpod/pods/${p.id}/terminate`).catch(() => {})
        }
      } catch {
        /* the external reap.py backstop is the final guarantee */
      }
    }
  })
})
