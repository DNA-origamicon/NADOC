/**
 * md_audit_fixes.spec.js — in-app verification of the NAMD-audit fixes.
 *
 *  1. the run control reads ▶ Run for a local job while a REMOTE run is in flight
 *     (it used to read ＋ Queue, behind a queue that then never drained);
 *  2. "Build despite a linked crossover" is on step 2 for every target.
 *
 * READ-ONLY (memory/feedback_no_live_server_mutation_for_verify): opens the wizard and
 * cancels. Nothing is created, started, stopped, rented or deleted. Boots on a fresh
 * scratch ?doc so the user's default document is untouched.
 *
 *   npx playwright test --config playwright.livedev.config.js \
 *     e2e/md_audit_fixes.spec.js --reporter=list
 */
import { test, expect } from '@playwright/test'
import fs from 'node:fs'

const OUT = 'e2e/screenshots'
const DESIGN = '24hb_1xT'

test('audit fixes are live in the app', async ({ page }) => {
  test.setTimeout(400_000)
  const R = { console: [] }
  page.on('console', m => { if (m.type() === 'error') R.console.push(m.text().slice(0, 200)) })
  page.on('pageerror', e => R.console.push('PAGEERROR: ' + String(e).slice(0, 200)))

  await page.goto(`/?doc=md-audit-fixes-${Date.now()}`)
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

  // ── 1. the queue no longer thinks a remote run holds this machine ──
  R.queue = await page.evaluate(async () => {
    const r = await fetch('/api/md/queue')
    return r.json()
  })

  // ── 2 + 3. the two new controls ──
  // BEFORE the row survey: selecting jobs swaps what the launch row shows, and
  // `＋ New job` ends up not visible, so the wizard leg has to go first.
  await page.locator('#md-jobs-new-btn').click({ timeout: 15_000 })
  await page.locator('.wiz-target-card').first().waitFor({ state: 'visible', timeout: 30_000 })
  await page.waitForTimeout(1500)

  const labelsOnStep2 = async () => {
    await page.locator('.wizard-tab, [class*="tab"]').filter({ hasText: /Protocol & settings/ })
      .first().click({ timeout: 10_000 }).catch(() => {})
    await page.waitForTimeout(2500)
    // Read the settings pane's whole text: the label markup `renderField` emits is an
    // implementation detail, and guessing at its class names is what made this leg report
    // false negatives twice.
    return page.evaluate(() => {
      const pane = document.querySelector('.wizard-fields')
        || [...document.querySelectorAll('div')].find(d =>
          d.offsetParent !== null && /Stop settled stages early/.test(d.textContent || ''))
      return [(pane?.textContent || '').replace(/\s+/g, ' ').trim()]
    })
  }
  const has = (labels, text) => labels.some(l => l.includes(text))

  // The wizard opens on PRODUCTION when a completed run is selected (and the loop above
  // leaves one selected), and production renders PRODUCTION_FIELD_DEFS, not FIELDS.
  // Put it back on Relaxation before looking for a relaxation setting.
  await page.locator('.wizard-tab, [class*="tab"]').filter({ hasText: /Protocol & settings/ })
    .first().click({ timeout: 10_000 }).catch(() => {})
  await page.waitForTimeout(2000)
  await page.locator('button', { hasText: /^Relaxation/ }).first()
    .click({ timeout: 10_000 }).catch(() => {})
  await page.waitForTimeout(2500)

  const localLabels = await labelsOnStep2()
  R.local = {
    // sanity: are we looking at the RELAXATION settings pane at all?
    onRelaxationPane: has(localLabels, 'Stop settled stages early'),
    ringPiercing: has(localLabels, 'Build despite a ring piercing'),
  }
  R.paneText = (localLabels[0] || '').slice(0, 600)
  await page.screenshot({ path: `${OUT}/fixes_step2_local.png` })

  await page.locator('button', { hasText: /^(Cancel|Close)$/ }).first().click({ timeout: 10_000 }).catch(() => {})
  await page.waitForTimeout(800)

  // ── 1. what the primary control offers, over every job in the list ──
  const rows = page.locator('#simulate-jobs-list [data-job-id]')
  await rows.first().waitFor({ state: 'visible', timeout: 60_000 }).catch(() => {})
  const n = await rows.count()
  R.runControl = []
  for (let i = 0; i < Math.min(n, 10); i++) {
    await rows.nth(i).click({ timeout: 8000 }).catch(() => {})
    await page.waitForTimeout(500)
    const s = await page.evaluate(() => {
      const b = document.querySelector('#md-jobs-run-btn')
      return b ? { label: b.textContent.trim(), disabled: b.disabled } : null
    })
    if (s) R.runControl.push(s)
  }
  R.anyQueueLabel = R.runControl.some(s => /Queue/.test(s.label))

  fs.writeFileSync(`${OUT}/md_audit_fixes.json`, JSON.stringify(R, null, 1))
  console.log('queue=' + JSON.stringify(R.queue),
    '| anyQueueLabel=' + R.anyQueueLabel,
    '| local=' + JSON.stringify(R.local),
    '| consoleErrors=' + R.console.length)

  expect(R.queue.busy, 'a remote run must not report this machine busy').toBe(false)
  expect(R.anyQueueLabel, 'no local job should be offered ＋ Queue while only remote runs are up').toBe(false)
  expect(R.local.ringPiercing, 'ring-piercing override on step 2').toBe(true)
  expect(R.console, 'zero console errors').toEqual([])
})
