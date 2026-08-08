/**
 * md_audit_gpukey.spec.js — AUDIT part 3: does the GPU the wizard makes you pick actually
 * reach `POST /api/md/jobs`?
 *
 * `md_jobs_panel._launchRelax` sets `runpod_gpu_key` from its OWN Clusters-card picker
 * (`_selectedRunpodGpu`) AFTER spreading the wizard's payload, and the wizard never writes
 * that variable. This spec measures the request body that would be sent.
 *
 * READ-ONLY AND THEN SOME: `POST /api/md/jobs` is INTERCEPTED AND ABORTED, so no job is
 * ever created. `/api/runpod/job-preview` is stubbed client-side (the real RunPod session
 * is disconnected on this machine and a live one must not be touched) — the stub never
 * reaches the server. Nothing is rented, submitted, stopped or deleted.
 *
 *   npx playwright test --config playwright.livedev.config.js \
 *     e2e/md_audit_gpukey.spec.js --reporter=list
 */
import { test, expect } from '@playwright/test'
import fs from 'node:fs'

const OUT = 'e2e/screenshots'
const DESIGN = '24hb_1xT'
const PICK = 'NVIDIA H100 80GB HBM3'      // the row this spec selects
const PICK_KEY = 'NVIDIA H100 80GB HBM3'

const previewStub = {
  sized: true, connected: true, n_atoms: 250000, n_atoms_source: 'stub',
  relax_ns: 20, production_ns: 100,
  gpus: [
    // Key names match backend/core/runpod_select.py (vram_gb / available), so the rows
    // render the way real ones do rather than as "undefined GB · ● unknown".
    { key: PICK_KEY, label: 'H100 80GB', vram_gb: 80, available: true, usd_per_hour: 2.39,
      ns_per_day: 220, hours: 12, total_cost: 28.7, usd_per_ns: 0.13 },
    { key: 'NVIDIA GeForce RTX 4090', label: 'RTX 4090', vram_gb: 24, available: true,
      usd_per_hour: 0.34, ns_per_day: 60, hours: 44, total_cost: 15.0, usd_per_ns: 0.15 },
  ],
  storage: { staging: { usd: 0.1, gb: 2 }, trajectory: { gb: 40 }, fits: true },
  volume: { id: 'stubvol1', name: 'nadoc', size_gb: 200 },
  balance: { available: true, usd: 500 },
  live_pods: [{ id: 'stub-pod-1', status: 'RUNNING', cost_per_hr: 0.34 }],
  preflight: {
    ok: true,
    checks: [{ key: 'connected', ok: true, label: 'Connected', detail: 'stub' }],
  },
  budget: { budget_usd: 50, estimated_usd: 28.8, over_budget: false },
  note: null,
}

test('the wizard’s chosen RunPod GPU reaches POST /md/jobs', async ({ page }) => {
  test.setTimeout(400_000)
  const R = { console: [] }

  await page.route('**/api/runpod/job-preview', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(previewStub) }))
  await page.route('**/api/runpod/volumes', route =>
    route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ volumes: [{ id: 'stubvol1', name: 'nadoc', size_gb: 200 }] }) }))
  await page.route('**/api/runpod/volume', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true}' }))

  // THE MEASUREMENT. Two halves, deliberately:
  //  • a PASSIVE observer of every MD POST — routing the whole /api/md/ surface to inspect
  //    it starved the wizard's own plan requests and timed the run out, and interception is
  //    not needed to READ a body;
  //  • one narrow route on the create URL, which aborts so no job is ever created.
  const posts = []
  R.posts = posts
  page.on('request', req => {
    if (req.method() !== 'POST' || !/\/api\/md\//.test(req.url())) return
    let body = null
    try { body = req.postDataJSON() } catch { body = null }
    posts.push({ url: req.url().replace(/^https?:\/\/[^/]+/, ''), body })
  })

  let created = null
  await page.route(/\/api\/md\/jobs(\?|$)/, async route => {
    if (route.request().method() !== 'POST') return route.continue()
    try { created = route.request().postDataJSON() } catch { created = { _raw: route.request().postData() } }
    await route.abort()
  })

  page.on('console', m => { if (m.type() === 'error') R.console.push(m.text().slice(0, 200)) })
  page.on('response', r => {
    if (r.status() >= 400) R.console.push(`HTTP ${r.status()} ${r.request().method()} ${r.url().replace(/^https?:\/\/[^/]+/, '')}`)
  })

  // A FRESH scratch doc each run: a reused one restores the previous run's (empty) session,
  // so no part is loaded, ＋ New job has nothing to build for, and the wizard never opens.
  await page.goto(`/?doc=md-audit-gpukey-${Date.now()}`)
  await page.waitForSelector('#canvas')
  const welcome = page.locator('#welcome-screen')
  if (await welcome.evaluate(el => !el.classList.contains('hidden')).catch(() => true)) {
    const row = welcome.locator('.lib-row-name', { hasText: new RegExp(`^${DESIGN}$`) }).first()
    await row.waitFor({ state: 'visible', timeout: 60_000 })
    await row.click({ timeout: 15_000 })
  }
  await expect(welcome).toHaveClass(/hidden/, { timeout: 90_000 })
  await page.waitForTimeout(2000)
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click({ timeout: 15_000 })
  await page.locator('.engine-selector-btn[data-engine="namd"]').click({ timeout: 15_000 })
  await page.waitForTimeout(1500)

  await page.locator('#md-jobs-new-btn').click({ timeout: 15_000 })
  // Assert the wizard is actually up — a silently-unopened modal made every later
  // measurement read as null and looked like a product bug rather than a spec one.
  await page.locator('.wiz-target-card').first().waitFor({ state: 'visible', timeout: 30_000 })
  await page.waitForTimeout(1500)

  // RunPod card
  await page.locator('.wiz-target-card').nth(2).click({ timeout: 10_000 })
  await page.waitForTimeout(8000)
  R.billingText = await page.evaluate(() => {
    const n = [...document.querySelectorAll('div')].find(d =>
      /pod(s)? already billing/.test(d.textContent || '') && d.childElementCount === 0)
    return n ? n.textContent.replace(/\s+/g, ' ').trim() : null
  })

  // pick the H100 row
  const rows = page.locator('.wiz-runpod-row, [data-gpu-key]')
  R.gpuRowCount = await rows.count()
  if (R.gpuRowCount) {
    await rows.first().click({ timeout: 8000 }).catch(() => {})
  } else {
    await page.locator(`text=${PICK}`).first().click({ timeout: 8000 }).catch(() => {})
  }
  await page.waitForTimeout(2500)

  R.step1 = await page.evaluate(() => {
    const next = [...document.querySelectorAll('button')].find(b => /Next/.test(b.textContent))
    const hint = document.querySelector('#wiz-target-hint')
    return { nextDisabled: next ? next.disabled : null, hint: (hint?.textContent || '').trim() }
  })
  await page.screenshot({ path: `${OUT}/audit3_runpod_picked.png` })

  // page to the end and press Create job
  for (let i = 0; i < 2; i++) {
    await page.locator('button', { hasText: /Next/ }).first().click({ timeout: 10_000 }).catch(() => {})
    await page.waitForTimeout(3000)
  }
  // Scope to the modal's own footer — a bare /^Create/ over the page matches a dropdown
  // button in the panel behind the overlay and hangs waiting for it to be clickable.
  const createBtn = page.locator('.md-modal, .modal, [class*="wizard"]')
    .locator('button', { hasText: /^Create job$/ }).last()
  R.createVisible = await createBtn.isVisible().catch(() => false)
  await createBtn.click({ timeout: 15_000 }).catch(e => {
    R.createClickError = String(e).slice(0, 200)
  })
  await page.waitForTimeout(4000)

  R.created = created
  R.postUrls = posts.map(p => p.url)
  R.verdict = created
    ? { sent_runpod_gpu_key: created.runpod_gpu_key ?? null,
        execution_target: created.execution_target ?? null,
        runpod_budget_usd: created.runpod_budget_usd ?? null,
        runpod_volume_id: created.runpod_volume_id ?? null,
        expected: PICK_KEY }
    : 'no POST /md/jobs was captured'
  fs.writeFileSync(`${OUT}/md_audit_gpukey.json`, JSON.stringify(R, null, 1))
  console.log('VERDICT', JSON.stringify(R.verdict), '| billing:', R.billingText, '| step1:', JSON.stringify(R.step1))
})
