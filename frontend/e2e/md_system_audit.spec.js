/**
 * md_system_audit.spec.js — AUDIT/TROUBLESHOOTING survey of the NAMD job system.
 *
 * Not part of the routine dev cycle. It answers questions that are only observable in the
 * real app: which of the ~245 `md-*` DOM ids are ever VISIBLE, which controls are
 * permanently disabled, which cards render empty, and whether the Job Wizard's three steps
 * page cleanly for every run target (local / Alpine / RunPod).
 *
 * READ-ONLY (memory/feedback_no_live_server_mutation_for_verify): it opens an existing
 * design through the app's own library, clicks existing jobs, opens the wizard and CANCELS.
 * Nothing is created, submitted, stopped, deleted or archived; no .nadoc is written.
 * Boots on a PINNED ?doc so the user's default document is untouched.
 *
 *   npx playwright test --config playwright.livedev.config.js \
 *     e2e/md_system_audit.spec.js --reporter=list
 */
import { test, expect } from '@playwright/test'
import fs from 'node:fs'

const OUT = 'e2e/screenshots'
const DESIGN = '24hb_1xT'   // widest job mix on this machine: 17 runpod + 2 local

const errors = []

async function openDesign(page, design) {
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text().slice(0, 300)) })
  page.on('pageerror', e => errors.push('PAGEERROR: ' + String(e).slice(0, 300)))
  await page.goto('/?doc=md-audit-scratch')
  await page.waitForSelector('#canvas')
  const welcome = page.locator('#welcome-screen')
  const needsPick = await welcome.evaluate(el => !el.classList.contains('hidden')).catch(() => true)
  if (needsPick) {
    const row = welcome.locator('.lib-row-name', { hasText: new RegExp(`^${design}$`) }).first()
    await row.waitFor({ state: 'visible', timeout: 60_000 })
    await row.click({ timeout: 15_000 })
  }
  await expect(welcome).toHaveClass(/hidden/, { timeout: 90_000 })
  await page.waitForTimeout(2000)
}

async function openNamdPanel(page) {
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click({ timeout: 15_000 })
  await page.locator('.engine-selector-btn[data-engine="namd"]').click({ timeout: 15_000 })
  await page.waitForTimeout(1500)
}

/** Snapshot every md/simulate/runpod/cluster id: does it exist, is it laid out, is it empty? */
const snapshot = (page) => page.evaluate(() => {
  const out = []
  for (const el of document.querySelectorAll('[id]')) {
    if (!/^(md|namd|runpod|cluster|simulate)[-_]/.test(el.id)) continue
    const cs = getComputedStyle(el)
    out.push({
      id: el.id,
      tag: el.tagName.toLowerCase(),
      visible: el.offsetParent !== null || cs.position === 'fixed',
      display: cs.display,
      disabled: el.disabled === true,
      hidden: el.hasAttribute('hidden'),
      text: (el.textContent || '').trim().slice(0, 60),
      kids: el.childElementCount,
    })
  }
  return out
})

test('NAMD job system — DOM + wizard survey', async ({ page }) => {
  test.setTimeout(400_000)
  const report = { errors, phases: {} }

  await openDesign(page, DESIGN)
  await openNamdPanel(page)
  report.phases.panelClosed = await snapshot(page)

  // Expand every collapsible card in the MD panel so "never visible" means never visible,
  // not just "collapsed right now".
  const toggles = await page.locator('#namd-panel [id$="-toggle"], #md-panel [id$="-toggle"]').all()
    .catch(() => [])
  for (const t of toggles) { await t.click({ timeout: 3000 }).catch(() => {}) }
  await page.waitForTimeout(800)
  report.phases.cardsExpanded = await snapshot(page)

  // ---- job rows in the UNIFIED list (the one the user actually clicks) ----
  const rows = page.locator('#simulate-jobs-list [data-job-id]')
  await rows.first().waitFor({ state: 'visible', timeout: 60_000 }).catch(() => {})
  const nRows = await rows.count()
  report.jobRows = nRows
  report.rowSurvey = []

  for (let i = 0; i < Math.min(nRows, 12); i++) {
    const row = rows.nth(i)
    await row.click({ timeout: 10_000 }).catch(() => {})
    await page.waitForTimeout(700)
    const info = await page.evaluate(() => {
      const btn = document.querySelector('#md-jobs-run-btn')
      const sel = document.querySelector('#simulate-jobs-list [data-job-id].selected, #simulate-jobs-list [data-job-id][aria-selected="true"]')
      return {
        jobId: sel?.dataset?.jobId ?? null,
        rowText: (sel?.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 90),
        run: btn ? { text: btn.textContent.trim(), disabled: btn.disabled, title: btn.title, visible: btn.offsetParent !== null } : null,
      }
    })
    report.rowSurvey.push(info)
  }

  // ---- right-click a row: the settings viewer ----
  if (nRows) {
    await rows.first().click({ timeout: 10_000 }).catch(() => {})
    await rows.first().click({ button: 'right', timeout: 10_000 }).catch(() => {})
    await page.waitForTimeout(600)
    report.contextMenu = await page.evaluate(() => {
      const items = [...document.querySelectorAll('.context-menu, [class*="ctx-menu"], [class*="context"]')]
        .filter(e => e.offsetParent !== null)
        .map(e => (e.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 200))
      return items
    })
    await page.keyboard.press('Escape')
    await page.waitForTimeout(300)
  }

  // ---- the wizard: three steps, three targets ----
  const newBtn = page.locator('#md-jobs-new-btn')
  report.newBtn = await newBtn.evaluate(el => ({ visible: el.offsetParent !== null, disabled: el.disabled, text: el.textContent.trim() })).catch(() => null)
  await newBtn.click({ timeout: 15_000 }).catch(e => { report.wizardOpenError = String(e).slice(0, 200) })
  await page.waitForTimeout(2500)

  const wizardState = async (label) => {
    const s = await page.evaluate(() => {
      const modal = [...document.querySelectorAll('div')].find(d =>
        d.offsetParent !== null && /wizard/i.test(d.className || '') && d.querySelector('button'))
      const scope = document.querySelector('.md-wizard, #md-job-wizard') || modal || document.body
      const ctrls = [...scope.querySelectorAll('input,select,textarea,button')]
        .filter(e => e.offsetParent !== null)
      return {
        tabs: [...scope.querySelectorAll('[class*="tab"]')].filter(e => e.offsetParent !== null)
          .map(e => (e.textContent || '').trim().slice(0, 40)).filter(Boolean),
        controls: ctrls.length,
        enabled: ctrls.filter(e => !e.disabled).length,
        buttons: ctrls.filter(e => e.tagName === 'BUTTON').map(e => e.textContent.trim().slice(0, 30)),
        warnText: [...scope.querySelectorAll('*')].filter(e => e.offsetParent !== null &&
          /^(⚠|Cannot|cannot|not available|unavailable)/.test((e.textContent || '').trim()) && e.childElementCount === 0)
          .map(e => e.textContent.trim().slice(0, 120)).slice(0, 12),
      }
    })
    report.phases[label] = s
    return s
  }

  await wizardState('wizard.step1.local')
  await page.screenshot({ path: `${OUT}/audit_wizard_step1_local.png` })

  // Alpine target
  await page.locator('text=Alpine').first().click({ timeout: 8000 }).catch(() => {})
  await page.waitForTimeout(2500)
  await wizardState('wizard.step1.alpine')
  await page.screenshot({ path: `${OUT}/audit_wizard_step1_alpine.png` })

  // RunPod target
  await page.locator('text=RunPod').first().click({ timeout: 8000 }).catch(() => {})
  await page.waitForTimeout(3500)
  await wizardState('wizard.step1.runpod')
  await page.screenshot({ path: `${OUT}/audit_wizard_step1_runpod.png` })

  // back to local and page forward through the steps
  await page.locator('text=Local').first().click({ timeout: 8000 }).catch(() => {})
  await page.waitForTimeout(1200)
  for (const step of ['step2', 'step3']) {
    const next = page.locator('button', { hasText: /Next/ }).first()
    await next.click({ timeout: 10_000 }).catch(e => { report.phases[`nav.${step}.error`] = String(e).slice(0, 160) })
    await page.waitForTimeout(2500)
    await wizardState(`wizard.${step}.local`)
    await page.screenshot({ path: `${OUT}/audit_wizard_${step}.png` })
  }

  // stage table sanity on step 3
  report.stageTable = await page.evaluate(() => {
    const t = [...document.querySelectorAll('table')].filter(e => e.offsetParent !== null)
      .sort((a, b) => b.querySelectorAll('td,th').length - a.querySelectorAll('td,th').length)[0]
    if (!t) return null
    return {
      cols: t.querySelectorAll('thead th').length,
      rows: t.querySelectorAll('tbody tr').length,
      cells: t.querySelectorAll('td').length,
      headers: [...t.querySelectorAll('thead th')].map(e => e.textContent.trim().slice(0, 22)),
    }
  })

  // CANCEL — nothing is created.
  await page.locator('button', { hasText: /^(Cancel|Close)$/ }).first().click({ timeout: 10_000 }).catch(() => {})
  await page.waitForTimeout(1000)
  report.wizardClosed = await page.evaluate(() =>
    !document.querySelector('.md-wizard, #md-job-wizard')?.offsetParent)

  report.phases.afterWizard = await snapshot(page)
  report.errors = errors
  fs.writeFileSync(`${OUT}/md_system_audit.json`, JSON.stringify(report, null, 1))
  console.log('rows=' + nRows, 'errors=' + errors.length)
})
