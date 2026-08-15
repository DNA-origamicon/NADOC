/**
 * Real, livedev-only diagnostic for VoltronCoreArm's Alpine Display-MD workflow.
 *
 * Produces a timestamped JSONL/text timeline and screenshots at the predicted
 * checkpoints from welcome screen through local cached-frame display and an
 * explicit Alpine refresh.  It never starts/stops a job or changes the design.
 * Run only against the user's existing :5173/:8000 servers:
 *
 *   npx playwright test --config playwright.livedev.config.js \
 *     e2e/md_alpine_display_diagnostic.spec.js --reporter=list
 */
import { test, expect } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { attachMdDisplayLog } from './helpers/md_display_log.js'

const API = 'http://localhost:8000'
const JOB_ID = '82a3cd08ed4f'
const DESIGN_NAME = 'VoltronCoreArm'
const OUT = 'e2e/logs/md_alpine_display_diagnostic'
const CAPTURE_SCREENSHOTS = process.env.NADOC_AUDIT_SCREENSHOTS !== '0'

async function domClick(locator) {
  await locator.waitFor({ state: 'attached', timeout: 30_000 })
  await locator.evaluate(el => el.click())
}

async function domCheck(locator, checked = true) {
  await locator.waitFor({ state: 'attached', timeout: 30_000 })
  await locator.evaluate((el, value) => {
    el.checked = value
    el.dispatchEvent(new Event('change', { bubbles: true }))
  }, checked)
}

const PREDICTIONS = [
  { name: 'welcome', should: 'happen', maxMs: 15_000,
    match: { kind: 'note', text: 'checkpoint:welcome' } },
  { name: 'design-loaded', after: 'welcome', should: 'happen', maxMs: 120_000,
    match: { kind: 'note', text: 'checkpoint:design-loaded' } },
  { name: 'dynamics-open', after: 'design-loaded', should: 'happen', maxMs: 10_000,
    match: { kind: 'note', text: 'checkpoint:dynamics-open' } },
  { name: 'job-select', after: 'dynamics-open', should: 'happen', maxMs: 10_000,
    match: { kind: 'note', text: 'checkpoint:job-select' } },
  { name: 'warmup-start', after: 'job-select', should: 'happen', maxMs: 5_000,
    match: { kind: 'dom', dot: 'warming…' } },
  { name: 'warmup-frame-cached', after: 'warmup-start', should: 'happen', maxMs: 30_000,
    match: { kind: 'process', phase: 'frame-cached' } },
  { name: 'warmup-finish', after: 'warmup-frame-cached', should: 'happen', maxMs: 3_000,
    match: { kind: 'note', text: 'checkpoint:warmup-finished' } },
  { name: 'display-click', after: 'warmup-finish', should: 'happen', maxMs: 5_000,
    match: { kind: 'note', text: 'checkpoint:display-click' } },
  { name: 'display-request', after: 'display-click', should: 'happen', maxMs: 5_000,
    match: { kind: 'process', phase: 'display-requested' } },
  { name: 'cached-frame-applied', after: 'display-request', should: 'happen', maxMs: 5_000,
    match: { kind: 'process', phase: 'frame-applied' } },
  { name: 'toggle-must-not-poll-alpine', after: 'display-click', should: 'not-happen',
    match: { kind: 'api', phase: 'start', path: /fetch-live-frame(?!\/(?:start|progress))/ } },
  { name: 'refresh-click', after: 'cached-frame-applied', should: 'happen', maxMs: 30_000,
    match: { kind: 'note', text: 'checkpoint:refresh-click' } },
  { name: 'refresh-start-request', after: 'refresh-click', should: 'happen', maxMs: 3_000,
    match: { kind: 'api', phase: 'start', path: /fetch-live-frame\/start/ } },
  { name: 'refresh-transfer-complete', after: 'refresh-start-request', should: 'happen', maxMs: 30_000,
    match: { kind: 'dom', frameProgress: /Preparing to apply frame|Applying frame to the part/ } },
  { name: 'refreshed-frame-applied', after: 'refresh-click', should: 'happen', maxMs: 30_000,
    match: { kind: 'process', phase: 'frame-applied', source: 'socket' } },
  { name: 'refresh-ui-complete', after: 'refreshed-frame-applied', should: 'happen', maxMs: 5_000,
    match: { kind: 'dom', frameProgress: /Display frame applied.*100%/ } },
  { name: 'generic-working-popup', after: 'display-click', should: 'not-happen',
    match: { kind: 'popup', action: 'show', header: 'Working…' } },
]

test('VoltronCoreArm: welcome → Display MD → Alpine refresh diagnostic', async ({ page, request }) => {
  test.setTimeout(900_000)
  fs.mkdirSync(path.dirname(OUT), { recursive: true })

  const jobRes = await request.get(`${API}/api/md/jobs/${JOB_ID}`)
  expect(jobRes.ok(), `job ${JOB_ID} must exist`).toBe(true)
  const job = await jobRes.json()
  expect(job.execution_target).toBe('alpine')

  const log = await attachMdDisplayLog(page, { intervalMs: 100 })
  let evidencePage = null
  const shot = async (name, { scene = false } = {}) => {
    log.note(`screenshot:${name}`)
    if (!CAPTURE_SCREENSHOTS) {
      log.note(`screenshot-skipped:${name} (timing pass)`)
      log.flush(OUT)
      return
    }
    if (scene) {
      // Final scene evidence deliberately pays for one software-WebGL render. It is
      // outside the timing pass and therefore cannot inflate the measured workflow.
      await page.evaluate(() => {
        const dbg = window.__NADOC_DBG__
        if (window.__nadocDiagnosticRenderPaused && dbg?.renderer && dbg?.scene && dbg?.camera) {
          dbg.renderer.render(dbg.scene, dbg.camera)
        }
      })
      await page.screenshot({
        path: `${OUT}_${name}.png`, fullPage: false, animations: 'disabled', timeout: 180_000,
      })
    } else {
      // Even a hidden/detached WebGL canvas makes Chromium's compositor read back the
      // 3D backing surface. Clone the exact live DOM + styles into a lightweight page;
      // this preserves status/progress evidence without touching the timed renderer.
      const snapshot = await page.evaluate((welcomeShot) => {
        const target = document.querySelector(welcomeShot ? '#welcome-screen' : '#left-panel')
        const css = [...document.querySelectorAll('style,link[rel="stylesheet"]')]
          .map(el => el.outerHTML).join('\n')
        return {
          css,
          html: target?.outerHTML || '<div>Evidence target missing</div>',
          rootClass: document.documentElement.className,
          bodyClass: document.body.className,
        }
      }, name === '00_welcome')
      evidencePage ||= await page.context().newPage()
      await evidencePage.setContent(`<!doctype html><html class="${snapshot.rootClass}"><head>`
        + `<base href="http://localhost:5173/">${snapshot.css}</head>`
        + `<body class="${snapshot.bodyClass}" style="margin:0;background:#0d1117">${snapshot.html}</body></html>`,
      { waitUntil: 'domcontentloaded' })
      const target = evidencePage.locator(name === '00_welcome' ? '#welcome-screen' : '#left-panel')
      await target.screenshot({
        path: `${OUT}_${name}.png`, animations: 'disabled', timeout: 30_000,
      })
    }
    log.flush(OUT)
  }

  let diagnosticError = null
  try {
    await page.goto(`/?doc=md-alpine-diagnostic-${Date.now()}`)
    await page.waitForSelector('#canvas')
    await expect(page.locator('#welcome-screen')).toBeVisible({ timeout: 15_000 })
    log.note('checkpoint:welcome')
    await log.sample(); await shot('00_welcome')

    await page.evaluate(() => {
      const dbg = window.__NADOC_DBG__
      if (!dbg?.renderer) throw new Error('NADOC diagnostic renderer is unavailable')
      dbg.renderer.setAnimationLoop(null)
      window.__nadocDiagnosticRenderPaused = true
    })
    log.note('diagnostic-render-loop:paused (manual render at screenshots)')

    const welcome = page.locator('#welcome-screen')
    const row = welcome.locator('.lib-row-name', { hasText: new RegExp(`^${DESIGN_NAME}$`) }).first()
    await row.waitFor({ state: 'visible', timeout: 60_000 })
    await row.click()
    await expect(welcome).toHaveClass(/hidden/, { timeout: 120_000 })
    log.note('checkpoint:design-loaded')
    await log.sample(); await shot('01_design_loaded')

    await domClick(page.locator('.left-tab-btn[data-tab="dynamics"]'))
    await domClick(page.locator('.engine-selector-btn[data-engine="namd"]'))
    await expect(page.locator('#tab-content-dynamics')).toBeVisible()
    await expect(page.locator('#cl-go')).toHaveCount(0)
    await expect(page.getByText(/Cluster:\s*Connecting/i)).toHaveCount(0)
    const clusterStatus = await request.get(`${API}/api/cluster/status`).then(r => r.json())
    expect(clusterStatus.state).toBe('connected')
    log.note(`checkpoint:cluster-connected (${clusterStatus.who || clusterStatus.host || 'connected'})`)
    log.note('checkpoint:dynamics-open')
    await log.sample(); await shot('02_dynamics_open')

    const jobRow = page.locator(`#simulate-jobs-list [data-job-id="${JOB_ID}"]`).first()
    if (!(await jobRow.isVisible().catch(() => false))) {
      // The unified list can arrive well after the engine card while the large design's
      // first geometry/render pass is settling. Keep the current-engine filter intact;
      // toggling the hidden legacy panel's similarly-named checkbox does not help here.
      await domCheck(page.locator('#simulate-jobs-show-all-types'), false)
    }
    await jobRow.waitFor({ state: 'visible', timeout: 120_000 })
    // Auto-selection may already have selected R1 while the design loaded. Do not
    // toggle it off: closing the websocket cannot cancel an in-flight native parse,
    // and selecting it again would start a second parse of this very large system.
    const selected = await jobRow.evaluate(el =>
      /2a3a4a|rgb\(42,\s*58,\s*74\)/.test(el.getAttribute('style') || '')
      || getComputedStyle(el).backgroundColor === 'rgb(42, 58, 74)')
    const warmFramesBefore = await page.evaluate(() =>
      (window.__mdDisplayEvents || []).filter(
        e => e.channel === 'process' && e.phase === 'frame-cached').length)
    log.note('checkpoint:job-select')
    log.note(`job-selection:${selected ? 'already-selected; retained warm-up' : 'clicked'}`)
    if (!selected) await domClick(jobRow)

    const refresh = page.locator('#md-jobs-live-frame-refresh')
    const readyBeforeWait = await page.locator('#md-jobs-display-indicator-label')
      .textContent().then(t => t?.trim() === 'ready').catch(() => false)
    if (!readyBeforeWait) {
      await expect(refresh).toBeDisabled({ timeout: 5_000 })
      await page.waitForFunction((n) =>
        (window.__mdDisplayEvents || []).filter(
          e => e.channel === 'process' && e.phase === 'frame-cached').length > n,
      warmFramesBefore, { timeout: 180_000 })
    }
    await expect(page.locator('#md-jobs-display-indicator-label'))
      .toHaveText('ready', { timeout: 5_000 })
    log.note('checkpoint:warmup-finished')
    await log.sample(); await shot('03_warmup_finished')

    const toggle = page.locator('#md-jobs-display-toggle')
    await expect(toggle).toBeVisible()
    const appliedBeforeDisplay = await page.evaluate(() =>
      (window.__mdDisplayEvents || []).filter(
        e => e.channel === 'process' && e.phase === 'frame-applied').length)
    await domCheck(toggle)
    log.note('checkpoint:display-click')
    await log.sample(); await shot('04_display_clicked_t0')

    await page.waitForFunction((n) =>
      (window.__mdDisplayEvents || []).filter(
        e => e.channel === 'process' && e.phase === 'frame-applied').length > n,
    appliedBeforeDisplay, { timeout: 30_000 })
    log.note('checkpoint:cached-frame-visible')
    await log.sample(); await shot('05_cached_frame_visible', { scene: true })

    await expect(refresh).toBeVisible({ timeout: 15_000 })
    if (await refresh.isDisabled()) {
      const cluster = await request.get(`${API}/api/cluster/status`).then(r => r.json()).catch(() => null)
      log.note(`AUTH_REQUIRED:${JSON.stringify(cluster)}`)
      await shot('06_auth_required')
      throw new Error('ALPINE_AUTH_REQUIRED: reconnect to Alpine in NADOC, then rerun this diagnostic')
    }

    const appliedBefore = await page.evaluate(() =>
      (window.__mdDisplayEvents || []).filter(
        e => e.channel === 'process' && e.phase === 'frame-applied' && e.source === 'socket').length)
    log.note('checkpoint:refresh-click')
    await domClick(refresh)
    await log.sample(); await shot('06_refresh_clicked_t0')
    await page.waitForTimeout(1_000)
    await log.sample(); await shot('07_refresh_predicted_1s')
    await page.waitForTimeout(4_000)
    await log.sample(); await shot('08_refresh_predicted_5s')

    await page.waitForFunction((n) =>
      (window.__mdDisplayEvents || []).filter(
        e => e.channel === 'process' && e.phase === 'frame-applied' && e.source === 'socket').length > n,
    appliedBefore, { timeout: 330_000 })
    await expect(page.locator('#md-jobs-live-frame-progress-label'))
      .toContainText(/Display frame applied.*100%/, { timeout: 10_000 })
    log.note('checkpoint:refreshed-frame-visible')
    await log.sample(); await shot('09_refreshed_frame_visible', { scene: true })
  } catch (err) {
    diagnosticError = err
    log.note(`diagnostic-error:${err?.message || err}`)
    await shot('99_failure').catch(() => {})
  } finally {
    await log.stop()
    const comparison = log.compare(PREDICTIONS)
    const files = log.write(OUT)
    fs.writeFileSync(`${OUT}_predictions.json`, JSON.stringify(comparison, null, 2))
    console.log(`[diagnostic] timeline: ${files.txt}`)
    console.log(`[diagnostic] predictions: ${OUT}_predictions.json`)
    for (const p of comparison) {
      console.log(`[prediction] ${p.pass ? 'PASS' : 'FAIL'} ${p.name} `
        + `(observed=${p.elapsedMs == null ? '—' : `${Math.round(p.elapsedMs)}ms`})`)
    }
  }

  if (diagnosticError) throw diagnosticError
  expect(log.consoleErrors(), 'browser console/page errors').toEqual([])
})
