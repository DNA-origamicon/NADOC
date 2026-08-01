/**
 * repr_switch_with_md_viz.spec.js — TROUBLESHOOTING spec for the 2026-08-01
 * representation-switch audit. Not part of the routine dev cycle; it exists because the
 * audit's central claims are about WHAT THE APP FETCHES and WHAT IS ON SCREEN during a
 * switch, and neither is observable from a unit test.
 *
 * What each test answers:
 *   R1  CG → atomistic while a NAMD TRAJECTORY is displayed must not fetch and build the
 *       DESIGN's all-atom model first — that is seconds of work rendering the wrong,
 *       un-simulated structure before the real one replaces it ("native flash").
 *   R2  the same for the live "Display MD" stream, which drives the atomistic renderer
 *       itself and was likewise absent from the defer decision.
 *   R7  a vdw ↔ ballstick flip must not re-download a payload whose coordinates are
 *       identical — only the renderer's geometry changes.
 *   indicator  every wait longer than a blink is announced, in BOTH directions, and the
 *       announcement always clears.
 *
 * Read-only: opens an existing design through the app's own library and an existing
 * finished job. Writes nothing.
 *
 * Runs against the USER'S dev servers (playwright.livedev.config.js) — a throwaway backend
 * cannot serve this: it would have to redo the archived job's multi-minute MDAnalysis work
 * on a single worker and wedges its own event loop doing it. Boots on a PINNED ?doc so the
 * user's default document is untouched, and never submits/stops/deletes a job.
 *
 *   npx playwright test --config playwright.livedev.config.js \
 *     e2e/repr_switch_with_md_viz.spec.js --reporter=list
 */
import { test, expect } from '@playwright/test'
import { trackConsoleErrors } from './helpers/scene_harness.js'

const API = process.env.NADOC_E2E_API_BASE || 'http://localhost:8000'

// A real finished NAMD job: 2hb_1xT, 200 composite frames, one production stage.
const JOB = '29c5b267380f'
const DESIGN = '2hb_1xT'
const SHOTS = 'e2e/screenshots'

/** Open the design through the welcome-screen library — the app's own load flow, which is
 *  what hides the welcome overlay and re-enables the side panels. An API load leaves the
 *  overlay up and every panel click then lands on it instead. */
async function openDesign(page, doc) {
  await page.goto(`/?doc=${doc}`)
  await page.waitForSelector('#canvas')
  const welcome = page.locator('#welcome-screen')
  // A doc whose design the backend already has open boots straight past the welcome
  // screen (session restore), so only click the library row when it is actually showing.
  const needsPick = await welcome.evaluate(el => !el.classList.contains('hidden'))
    .catch(() => true)
  if (needsPick) {
    const row = welcome.locator('.lib-row-name', { hasText: new RegExp(`^${DESIGN}$`) }).first()
    await row.waitFor({ state: 'visible', timeout: 60_000 })
    await row.click({ timeout: 15_000 })
  }
  await expect(welcome).toHaveClass(/hidden/, { timeout: 60_000 })
  await page.waitForFunction(() => {
    let n = 0
    window.__nadocTest?.scene?.traverse(o => {
      if (o.isInstancedMesh && o.name === 'backboneSpheres') n += o.count
    })
    return n > 0
  }, null, { timeout: 60_000 })
  await page.waitForTimeout(500)
}

/** Simulations tab → NAMD engine → select the job. */
async function selectMdJob(page) {
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click({ timeout: 15_000 })
  await page.locator('.engine-selector-btn[data-engine="namd"]').click({ timeout: 15_000 })
  await page.waitForTimeout(800)
  const row = page.locator(`#md-jobs-list [data-job-id="${JOB}"]`)
  await row.waitFor({ state: 'attached', timeout: 30_000 })
  // This job is a CHILD row (a production run branched off a relaxed parent) and its
  // group is collapsed, so the element is in the DOM but not visible. Dispatch the click
  // directly rather than driving the tree expander — the job-tree UI is not under test
  // here, and its collapse state is incidental to the representation switch.
  await row.evaluate((el) => el.click())
  // Selection is confirmed by the viz radios going live — they enable only for a selected
  // job with a written trajectory, which is exactly the precondition these tests need.
  // (The row itself carries no class to assert on; selection is an inline background.)
  await expect(page.locator('#md-jobs-traj-toggle')).toBeEnabled({ timeout: 30_000 })
}

/**
 * Record, in the page, everything that happens during a switch:
 *   • heavy-status events (the progress signal), and
 *   • every appearance of the persistent toast, via MutationObserver.
 * Event-driven rather than polled — a fast switch can raise and clear the toast between
 * two polls, and "I didn't catch it" is not evidence that it never showed.
 */
async function startRecorder(page) {
  await page.evaluate(() => {
    const rec = { status: [], toasts: [] }
    window.__reprRec = rec
    const onStatus = (e) => rec.status.push({ ...e.detail })
    for (const n of ['nadoc:oxdna-heavy-status', 'nadoc:md-heavy-status']) {
      window.addEventListener(n, onStatus)
    }
    const seen = new Set()
    const scan = () => {
      for (const el of document.querySelectorAll('.toast--visible .toast-message')) {
        const t = el.textContent.trim()
        if (t && !seen.has(t)) { seen.add(t); rec.toasts.push(t) }
      }
    }
    new MutationObserver(scan).observe(document.body, {
      subtree: true, childList: true, attributes: true, attributeFilter: ['class'],
    })
    scan()
  })
}
const recorded = (page) => page.evaluate(() => window.__reprRec)
const resetRec = (page) => page.evaluate(() => {
  window.__reprRec.status.length = 0
  window.__reprRec.toasts.length = 0
})

/** What is actually drawn. `cg` counts VISIBLE backbone bead instances — the renderer keeps
 *  the mesh and flips an ancestor's `.visible`, so `count` alone would say beads are up
 *  when they are hidden under the atoms. */
async function sceneState(page) {
  return page.evaluate(() => {
    const vis = (o) => { for (let n = o; n; n = n.parent) if (n.visible === false) return false; return true }
    let cg = 0, atoms = 0
    window.__nadocTest?.scene?.traverse(o => {
      if (!o.isInstancedMesh || !o.count || !vis(o)) return
      if (o.name === 'backboneSpheres') cg += o.count
      else if (/atom|vdw|ballstick|bond/i.test(o.name || '')) atoms += o.count
    })
    return { cg, atoms }
  })
}

async function pressRepr(page, key) {
  await page.locator('#canvas').click({ position: { x: 400, y: 600 }, timeout: 10_000 }).catch(() => {})
  await page.keyboard.press(key)
}

test.describe('representation switch while an MD visualization is displayed', () => {
  test.setTimeout(300_000)

  test('R1 + R7 + indicator: NAMD trajectory, CG ⇄ atomistic', async ({ page }) => {
    const errors = trackConsoleErrors(page)

    // Which heavy routes the app asks for — the decisive evidence. Narrow pattern so the
    // interception doesn't proxy megabytes of unrelated traffic through the test process.
    const calls = []
    await page.route(/\/api\/(design\/(atomistic|surface)|md\/jobs\/[^/]+\/(atomistic-model|frames-atomistic|frames-surface|rmsf))/,
      (route) => {
        const rq = route.request()
        let body = ''
        try { body = (rq.postData() || '').slice(0, 120) } catch { /* GET */ }
        calls.push(rq.url().replace(/^https?:\/\/[^/]+/, '') + (body ? ` ${body}` : ''))
        route.continue()
      })

    await openDesign(page, 'reprR1')
    await selectMdJob(page)
    await startRecorder(page)

    // 200 frames, not the default 1000: this test is about the SWITCH, and a lighter
    // trajectory keeps the throwaway backend's single worker responsive.
    const interval = page.locator('#md-jobs-traj-interval')
    await interval.fill('100')
    await interval.dispatchEvent('change')
    // Warm the route before the UI asks, so the first UI fetch isn't racing the live
    // prewarm's PSF parse for the same event loop.
    await page.request.get(`${API}/api/md/jobs/${JOB}/trajectory?stride=100`, { timeout: 300_000 })

    const traj = page.locator('#md-jobs-traj-toggle')
    await expect(traj).toBeEnabled({ timeout: 30_000 })
    page.on('dialog', d => d.accept())       // frame-count + "prepare atoms?" prompts
    await traj.check({ force: true })
    await expect.poll(
      () => page.locator('#md-jobs-traj-status').textContent(),
      { timeout: 180_000, message: 'trajectory never loaded' },
    ).toMatch(/frame|ready|atoms/i)
    await page.waitForTimeout(1500)
    await page.screenshot({ path: `${SHOTS}/repr-r1-1-traj-cg.png` })

    expect((await sceneState(page)).cg, 'CG beads show the trajectory frame').toBeGreaterThan(0)

    // ── CG → ball-and-stick ──────────────────────────────────────────────────
    calls.length = 0
    await resetRec(page)
    await pressRepr(page, 'F7')

    await expect.poll(async () => (await sceneState(page)).atoms,
      { timeout: 180_000, message: 'atoms never appeared' }).toBeGreaterThan(0)
    await page.waitForTimeout(1200)
    await page.screenshot({ path: `${SHOTS}/repr-r1-2-ballstick.png` })

    const rec = await recorded(page)
    const designBuilds = calls.filter(u => /design\/(atomistic|surface)/.test(u))
    const jobBuilds = calls.filter(u => /md\/jobs\//.test(u))

    // R1: the design's own all-atom model is never built — the SIMULATED one is.
    expect(designBuilds, `design heavy build leaked in: ${designBuilds.join(', ')}`).toEqual([])
    expect(jobBuilds.length, 'the job atoms were fetched instead').toBeGreaterThan(0)

    // Indicator: announced, and cleared.
    expect(rec.status.some(s => s.building), `no progress signal: ${JSON.stringify(rec.status)}`).toBe(true)
    expect(rec.status.at(-1)?.building, 'progress signal never cleared').toBe(false)
    expect(rec.toasts, 'no visible loading toast').not.toEqual([])

    const after = await sceneState(page)
    expect(after.atoms).toBeGreaterThan(0)
    expect(after.cg, 'CG must be hidden under the atoms').toBe(0)

    // ── R7: ballstick → vdw is the same coordinates, different geometry ──────
    // Wait for the initial prebuild to FINISH first. Asserting mid-prebuild proves
    // nothing: the chunks it is still fetching (32-63, 64-95, …) are the first fill, not
    // a refetch, and reading them as one is how this test first mis-accused the budget
    // code. The claim is about the STEADY state — nothing already in hand is re-fetched.
    await expect.poll(
      () => page.locator('#md-jobs-traj-status').textContent(),
      { timeout: 300_000, message: 'atom prebuild never finished' },
    ).toMatch(/atoms ready|atoms: \d+ of|atoms not prepared/i)

    calls.length = 0
    await resetRec(page)
    await pressRepr(page, 'F6')
    await page.waitForTimeout(6000)
    await page.screenshot({ path: `${SHOTS}/repr-r1-3-vdw.png` })
    const frameRefetch = calls.filter(u => /frames-atomistic/.test(u))
    expect(frameRefetch, `re-downloaded frames on a vdw flip: ${frameRefetch.join(', ')}`).toEqual([])
    expect((await sceneState(page)).atoms, 'still atomistic after the flip').toBeGreaterThan(0)

    // ── back to CG ───────────────────────────────────────────────────────────
    await resetRec(page)
    await pressRepr(page, 'F4')
    await expect.poll(async () => (await sceneState(page)).cg, { timeout: 60_000 }).toBeGreaterThan(0)
    await page.waitForTimeout(800)
    await page.screenshot({ path: `${SHOTS}/repr-r1-4-back-to-cg.png` })
    expect((await recorded(page)).status.at(-1)?.building ?? false,
      'progress signal stranded after returning to CG').toBe(false)

    expect(errors.filter(e => !/favicon|ResizeObserver/i.test(e)), 'console errors').toEqual([])
  })

  // The indicator exists for the systems where the reload is SLOW (a VoltronCore-class PSF
  // parse is tens of seconds). 2hb_1xT is small and fast, so on this fixture the toast can
  // come and go between two video frames — which proves the wiring but shows nothing. Hold
  // the heavy response open to make the slow case reproducible, and photograph it.
  test('indicator is VISIBLE while a slow switch is in flight', async ({ page }) => {
    // Delay the ONE-SHOT topology fetch — that is the real slow step on a big system (the
    // PSF parse + model build), and it is fetched once per job on the first atomistic
    // need. Do NOT stall the per-frame route instead: every prebuild chunk goes through it
    // too, and holding those long enough supersedes the in-flight heavy build, which
    // correctly falls back to leaving the CG up — a different behaviour from a slow one.
    let hold = true
    await page.route(/\/api\/md\/jobs\/[^/]+\/atomistic-model/, async (route) => {
      if (hold) { hold = false; await new Promise(r => setTimeout(r, 6000)) }
      await route.continue()
    })

    await openDesign(page, 'reprSlow')
    await selectMdJob(page)
    await startRecorder(page)

    const interval = page.locator('#md-jobs-traj-interval')
    await interval.fill('100')
    await interval.dispatchEvent('change')
    const traj = page.locator('#md-jobs-traj-toggle')
    await expect(traj).toBeEnabled({ timeout: 30_000 })
    page.on('dialog', d => d.accept())
    await traj.check({ force: true })
    await expect.poll(() => page.locator('#md-jobs-traj-status').textContent(),
      { timeout: 300_000 }).toMatch(/atoms ready|atoms: \d+ of|atoms not prepared|frame/i)

    await resetRec(page)
    await pressRepr(page, 'F7')

    // Photograph the app mid-switch: the progress toast must be on screen and readable.
    // Matched by TEXT, not `.first()` — the canvas also carries an unrelated always-on
    // "Selection: Alt-click = …" hint toast, and picking that one would pass or fail for
    // reasons that have nothing to do with the switch.
    const busy = page.locator('.toast--visible .toast-message', { hasText: /loading|computing/i })
    await busy.first().waitFor({ state: 'visible', timeout: 60_000 })
    await page.waitForTimeout(300)
    const text = (await busy.first().textContent()).trim()
    await page.screenshot({ path: `${SHOTS}/repr-indicator-visible.png` })
    expect(text, 'the indicator must say what it is doing').toMatch(/loading|computing/i)

    // …and it must go away on its own once the atoms land.
    await expect.poll(async () => (await sceneState(page)).atoms, { timeout: 180_000 }).toBeGreaterThan(0)
    await expect.poll(() => busy.count(),
      { timeout: 60_000, message: 'the indicator never cleared' }).toBe(0)
    await page.screenshot({ path: `${SHOTS}/repr-indicator-cleared.png` })
  })

  test('R2 + indicator: live Display MD, CG ⇄ atomistic', async ({ page }) => {
    const errors = trackConsoleErrors(page)
    const calls = []
    await page.route(/\/api\/design\/(atomistic|surface)/,
      (route) => {
        const rq = route.request()
        let body = ''
        try { body = (rq.postData() || '').slice(0, 120) } catch { /* GET */ }
        calls.push(rq.url().replace(/^https?:\/\/[^/]+/, '') + (body ? ` ${body}` : ''))
        route.continue()
      })

    await openDesign(page, 'reprR2')
    await selectMdJob(page)
    await startRecorder(page)

    const display = page.locator('#md-jobs-display-toggle')
    await expect(display).toBeEnabled({ timeout: 30_000 })
    await display.check({ force: true })
    await expect.poll(
      () => page.locator('#md-jobs-display-status').textContent(),
      { timeout: 180_000, message: 'live display never showed a frame' },
    ).toMatch(/Displaying frame/i)
    await page.waitForTimeout(1000)
    await page.screenshot({ path: `${SHOTS}/repr-r2-1-live-cg.png` })

    calls.length = 0
    await resetRec(page)
    await pressRepr(page, 'F7')

    await expect.poll(async () => (await sceneState(page)).atoms,
      { timeout: 180_000, message: 'MD atoms never appeared' }).toBeGreaterThan(0)
    await page.waitForTimeout(1200)
    await page.screenshot({ path: `${SHOTS}/repr-r2-2-live-ballstick.png` })

    const rec = await recorded(page)
    // R2: the live stream supplies the atoms, so the design model is never built.
    expect(calls, `design heavy build leaked in: ${calls.join(', ')}`).toEqual([])
    // The reload + PSF parse is announced — before this, the CG simply sat there.
    expect(rec.status.some(s => s.building && s.kind === 'atomistic'),
      `no progress signal: ${JSON.stringify(rec.status)}`).toBe(true)
    expect(rec.toasts, 'no visible loading toast').not.toEqual([])
    await expect.poll(async () => (await recorded(page)).status.at(-1)?.building,
      { timeout: 60_000, message: 'progress signal never cleared' }).toBe(false)

    // The reverse direction reloads too, and shows the design at NATIVE positions
    // meanwhile — so it is announced as well.
    await resetRec(page)
    await pressRepr(page, 'F4')
    await expect.poll(async () => (await sceneState(page)).cg, { timeout: 120_000 }).toBeGreaterThan(0)
    const back = await recorded(page)
    expect(back.status.some(s => s.building && s.kind === 'cg'),
      `atomistic→CG was silent: ${JSON.stringify(back.status)}`).toBe(true)
    await page.screenshot({ path: `${SHOTS}/repr-r2-3-live-back-to-cg.png` })

    expect(errors.filter(e => !/favicon|ResizeObserver/i.test(e)), 'console errors').toEqual([])
  })
})
