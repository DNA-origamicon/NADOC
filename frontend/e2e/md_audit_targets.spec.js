/**
 * md_audit_targets.spec.js — AUDIT part 2: the wizard's step-1 target panes, the RunPod
 * billing dead-end, and the run-dir listener leak.
 *
 * READ-ONLY (memory/feedback_no_live_server_mutation_for_verify): opens the wizard, clicks
 * target CARDS, and cancels. Nothing is created, rented, submitted or deleted. A RunPod pod
 * is billing on this machine right now — this spec must not touch it, only observe that the
 * UI reports it.
 *
 *   npx playwright test --config playwright.livedev.config.js \
 *     e2e/md_audit_targets.spec.js --reporter=list
 */
import { test, expect } from '@playwright/test'
import fs from 'node:fs'

const OUT = 'e2e/screenshots'
const DESIGN = '24hb_1xT'
const errors = []

async function boot(page) {
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text().slice(0, 240)) })
  page.on('pageerror', e => errors.push('PAGEERROR: ' + String(e).slice(0, 240)))
  await page.goto('/?doc=md-audit-scratch2')
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
}

const cards = (page) => page.locator('.wiz-target-card')

/** How many `nadoc:run-dir-change` listeners are attached to window right now. */
async function runDirListeners(page) {
  const cdp = await page.context().newCDPSession(page)
  const { result } = await cdp.send('Runtime.evaluate', { expression: 'window' })
  const { listeners } = await cdp.send('DOMDebugger.getEventListeners', { objectId: result.objectId })
  await cdp.detach()
  return listeners.filter(l => l.type === 'nadoc:run-dir-change').length
}

test('wizard step-1 target panes + RunPod billing dead-end + run-dir listener leak', async ({ page }) => {
  test.setTimeout(400_000)
  const R = { panes: {}, leak: {}, terminateAffordance: null }

  await boot(page)
  R.leak.beforeAnyWizard = await runDirListeners(page)

  // ── open the wizard on a FRESH relaxation: clear the selection first ──
  await page.locator('#md-jobs-new-btn').click({ timeout: 15_000 })
  await page.waitForTimeout(2500)
  R.cardCount = await cards(page).count()
  R.cardLabels = await cards(page).evaluateAll(
    els => els.map(e => (e.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 70)))

  for (const [idx, name] of [[0, 'local'], [1, 'alpine'], [2, 'runpod']]) {
    if (idx >= R.cardCount) continue
    await cards(page).nth(idx).click({ timeout: 10_000 }).catch(() => {})
    await page.waitForTimeout(idx === 0 ? 1500 : 6000)   // remote panes fetch
    R.panes[name] = await page.evaluate(() => {
      const sel = document.querySelector('.wiz-target-card.selected, .wiz-target-card[aria-selected="true"]')
        || [...document.querySelectorAll('.wiz-target-card')].find(e => /rgb\(\s*88/.test(getComputedStyle(e).borderColor))
      const body = sel || document.querySelector('.wiz-target-card')
      const next = [...document.querySelectorAll('button')].find(b => /Next/.test(b.textContent))
      const hint = document.querySelector('#wiz-target-hint')
      return {
        selectedText: (body?.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 700),
        nextDisabled: next ? next.disabled : null,
        hint: (hint?.textContent || '').trim().slice(0, 200),
      }
    })
    await page.screenshot({ path: `${OUT}/audit2_target_${name}.png` })
  }

  // ── the whole document: is there ANY control that could kill a billing pod? ──
  R.terminateAffordance = await page.evaluate(() => {
    const hits = []
    for (const e of document.querySelectorAll('button,a,[role="button"],input[type="button"]')) {
      const t = ((e.textContent || '') + ' ' + (e.title || '') + ' ' + (e.id || '')).toLowerCase()
      if (/terminate|kill pod|destroy pod|stop pod|shut ?down pod/.test(t)) {
        hits.push({ id: e.id, text: (e.textContent || '').trim().slice(0, 40), visible: e.offsetParent !== null })
      }
    }
    return hits
  })
  // and what the billing warning actually says
  R.billingText = await page.evaluate(() => {
    const n = [...document.querySelectorAll('div')].find(d =>
      /pod(s)? already billing/.test(d.textContent || '') && d.childElementCount === 0)
    return n ? n.textContent.replace(/\s+/g, ' ').trim() : null
  })

  await page.locator('button', { hasText: /^(Cancel|Close)$/ }).first().click({ timeout: 10_000 }).catch(() => {})
  await page.waitForTimeout(800)
  R.leak.afterOneWizard = await runDirListeners(page)

  // open + cancel four more times
  for (let i = 0; i < 4; i++) {
    await page.locator('#md-jobs-new-btn').click({ timeout: 15_000 }).catch(() => {})
    await page.waitForTimeout(1800)
    await page.locator('button', { hasText: /^(Cancel|Close)$/ }).first().click({ timeout: 10_000 }).catch(() => {})
    await page.waitForTimeout(500)
  }
  R.leak.afterFiveWizards = await runDirListeners(page)

  R.errors = errors
  fs.writeFileSync(`${OUT}/md_audit_targets.json`, JSON.stringify(R, null, 1))
  console.log(JSON.stringify(R.leak), 'terminateControls=' + R.terminateAffordance.length,
    'billing=' + R.billingText)
})
