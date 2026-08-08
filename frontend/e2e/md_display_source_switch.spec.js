/**
 * md_display_source_switch.spec.js — the MD display readiness dot must describe the job
 * you are looking at, not the one you just left.
 *
 * Reported symptom: select a RunPod job, then click an Alpine job, and the display keeps
 * showing a RunPod message until it errors out. Three causes, all pinned here:
 *   • `mdReadinessIndicator` hardcoded "on the pod" for EVERY remote target;
 *   • `_selectJob` cleared `_displayMeta` but never reset the dot, so the previous job's
 *     state + tooltip stayed on screen for the whole round trip;
 *   • `_refreshMdPrewarm` / `_fetchDisplayMeta` awaited without re-checking the selection,
 *     so a slow answer for the old job painted over the new one.
 *
 * READ-ONLY (memory/feedback_no_live_server_mutation_for_verify): clicks existing job rows
 * and reads the DOM. Nothing is created, started, stopped, fetched or deleted. Boots on a
 * fresh scratch ?doc.
 *
 *   npx playwright test --config playwright.livedev.config.js \
 *     e2e/md_display_source_switch.spec.js --reporter=list
 */
import { test, expect } from '@playwright/test'
import fs from 'node:fs'

const OUT = 'e2e/screenshots'
const DESIGN = '24hb_0xT'   // has runpod + alpine + local NAMD jobs on this machine

/** The dot's label + tooltip, and which row is selected. */
const dot = (page) => page.evaluate(() => {
  const el = document.getElementById('md-jobs-display-indicator')
  const lab = document.getElementById('md-jobs-display-indicator-label')
  const sel = document.querySelector('#simulate-jobs-list [data-job-id].selected')
    || document.querySelector('#simulate-jobs-list [data-job-id][aria-selected="true"]')
  return {
    shown: !!el && el.style.display !== 'none',
    text: (lab?.textContent || '').trim(),
    title: (el?.title || '').trim(),
    jobId: sel?.dataset?.jobId ?? null,
  }
})

test('the display dot follows the selected job, not the previous one', async ({ page }) => {
  test.setTimeout(400_000)
  const R = { console: [], samples: [] }
  page.on('console', m => { if (m.type() === 'error') R.console.push(m.text().slice(0, 200)) })
  page.on('pageerror', e => R.console.push('PAGEERROR: ' + String(e).slice(0, 200)))

  await page.goto(`/?doc=md-display-src-${Date.now()}`)
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

  const rows = page.locator('#simulate-jobs-list [data-job-id]')
  await rows.first().waitFor({ state: 'visible', timeout: 60_000 })

  // Which row is which target — the list is the only handle the user has.
  const jobs = await page.evaluate(async () => {
    const r = await fetch('/api/md/jobs')
    const all = await r.json()
    const ids = [...document.querySelectorAll('#simulate-jobs-list [data-job-id]')]
      .map(e => e.dataset.jobId)
    return ids.map(id => {
      const j = (Array.isArray(all) ? all : all.jobs).find(x => x.job_id === id)
      return { id, target: j?.execution_target ?? null, status: j?.status ?? null }
    })
  })
  R.jobs = jobs
  const idxOf = t => jobs.findIndex(j => j.target === t)
  const iPod = idxOf('runpod')
  const iAlp = idxOf('alpine')
  R.have = { runpod: iPod, alpine: iAlp }
  test.skip(iPod < 0 || iAlp < 0, 'needs both a RunPod and an Alpine job on this design')

  // Every NAMD job on this design happens to be `ready` today, so the live server cannot
  // produce the state that leaks. Stub the two display answers instead — the bug is
  // entirely in how the panel SEQUENCES them, and stubbing makes the test deterministic
  // rather than dependent on which runs happen to be un-fetched on the day:
  //   • the RunPod job answers `remote` (the message that used to leak), instantly;
  //   • the Alpine job answers SLOWLY, which is the window the old code left the previous
  //     job's dot on screen — and, before the guard, let the pod answer land on top.
  const podId = jobs[iPod].id
  const alpId = jobs[iAlp].id
  await page.route('**/api/md/jobs/*/display', async route => {
    const id = route.request().url().match(/\/md\/jobs\/([^/]+)\/display/)?.[1]
    if (id === podId) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
        job_id: podId, status: 'failed', ready: false,
        not_ready_code: 'remote',
        not_ready_reason: "Nothing fetched from the pod yet. Fetch this run's results to display it.",
        config_path: null, trajectory_path: null, live_frame: null,
      }) })
    }
    if (id === alpId) {
      await new Promise(r => setTimeout(r, 3500))    // the settling window
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
        job_id: alpId, status: 'running', ready: false,
        not_ready_code: 'remote',
        not_ready_reason: 'Nothing fetched from the cluster yet. Fetch this run’s results to display it.',
        config_path: null, trajectory_path: null, live_frame: null,
      }) })
    }
    return route.continue()
  })

  // 1. the RunPod job — this is the state that used to leak
  await rows.nth(iPod).click({ timeout: 10_000 })
  await page.waitForTimeout(4000)
  R.podDot = await dot(page)
  await page.screenshot({ path: `${OUT}/display_src_runpod.png` })

  // 2. click the Alpine job and watch the dot for the whole settling window
  await rows.nth(iAlp).click({ timeout: 10_000 })
  for (let i = 0; i < 14; i++) {
    R.samples.push({ atMs: i * 500, ...(await dot(page)) })
    await page.waitForTimeout(500)
  }
  R.alpineDot = await dot(page)
  await page.screenshot({ path: `${OUT}/display_src_alpine.png` })

  R.leaked = R.samples.filter(s => /on the pod/i.test(s.text) || /\bthe pod\b/i.test(s.title))
  // The stub must actually have produced the leaky state, or `leaked: []` proves nothing.
  R.podStateReached = /on the pod/i.test(R.podDot.text) || /\bthe pod\b/i.test(R.podDot.title)
  fs.writeFileSync(`${OUT}/md_display_source_switch.json`, JSON.stringify(R, null, 1))
  console.log('pod=' + JSON.stringify(R.podDot),
    '| alpine=' + JSON.stringify(R.alpineDot),
    '| leaked=' + R.leaked.length,
    '| consoleErrors=' + R.console.length)

  // Guard the guard: without this a green run could just mean the pod state never happened.
  expect(R.podStateReached, 'the RunPod job must actually show the pod message first')
    .toBe(true)
  // THE ASSERTION: at no point after selecting Alpine does the dot mention the pod.
  expect(R.leaked, 'a RunPod message must never appear while an Alpine job is selected')
    .toEqual([])
  // …and once the Alpine answer lands it is worded for the CLUSTER, not the pod.
  expect(R.alpineDot.text).toBe('on the cluster')
  expect(R.console, 'zero console errors').toEqual([])
})
