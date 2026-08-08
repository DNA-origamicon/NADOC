/**
 * e2e/helpers/md_display_log.js — capture everything the MD Display says, as a log.
 *
 * The MD Display reports itself through four channels that are individually useless and
 * jointly conclusive:
 *
 *   1. `#md-jobs-display-status`  — the status line the user reads (and its spinner)
 *   2. `#md-jobs-display-indicator` — the readiness dot: label + tooltip
 *   3. `nadoc:md-display-state` events — the ONLY definitive "a frame is on screen"
 *      signal (`state: 'frame'`); the status line merely echoes it
 *   4. the browser console
 *
 * Debugging "the display shows nothing" from screenshots is guesswork because the
 * interesting states are transient — a 5 s fetch, a frame that lands and is overwritten,
 * an error that is repainted by the next poll. This records all four on one timeline so
 * the sequence is readable after the fact.
 *
 * Records CHANGES, not samples: a 3-minute run at 500 ms would otherwise be 360 identical
 * rows. Every record carries `t` (ms since attach) so gaps are visible.
 *
 * Usage — attach BEFORE `page.goto`, because the event hook is an init script:
 *
 *   const log = await attachMdDisplayLog(page)
 *   await page.goto('/?doc=…')
 *   …drive the UI…
 *   await log.stop()
 *   log.write('e2e/logs/md_display_<name>')   // → .jsonl + .txt
 *   expect(log.sawFrame()).toBe(true)
 */
import fs from 'node:fs'
import path from 'node:path'

/** Install the recorder. Returns a handle; call `stop()` before `write()`. */
export async function attachMdDisplayLog(page, { intervalMs = 500 } = {}) {
  const t0 = Date.now()
  const records = []
  const at = () => Date.now() - t0
  const push = (kind, data) => records.push({ t: at(), kind, ...data })

  // The event stream has to be hooked before any app code runs, or the 'ready'/'frame'
  // events fired during the first load are lost — exactly the ones that answer "did it
  // ever show anything".
  await page.addInitScript(() => {
    window.__mdDisplayEvents = []
    window.addEventListener('nadoc:md-display-state', (e) => {
      window.__mdDisplayEvents.push({ wall: Date.now(), ...(e.detail || {}) })
    })
  })

  page.on('console', (m) => {
    const type = m.type()
    if (type === 'error' || type === 'warning') {
      push('console', { level: type, text: m.text().slice(0, 300) })
    }
  })
  page.on('pageerror', (e) => push('console', { level: 'pageerror', text: String(e).slice(0, 300) }))

  let lastDom = ''
  let drained = 0
  let timer = null
  let stopped = false

  /** One read of every DOM channel the display paints. */
  const readDom = () => page.evaluate(() => {
    const status = document.getElementById('md-jobs-display-status')
    const ind = document.getElementById('md-jobs-display-indicator')
    const lab = document.getElementById('md-jobs-display-indicator-label')
    const refresh = document.getElementById('md-jobs-live-frame-refresh')
    const toggle = document.getElementById('md-jobs-display-toggle')
    // The job list marks selection with an INLINE background only — no class, no
    // aria-selected (jobs_panel_render.js:25). Selecting on `.selected` silently logged
    // `job=—` for every row, which is worse than not logging it.
    const sel = [...document.querySelectorAll('#simulate-jobs-list [data-job-id]')]
      .find(r => /2a3a4a|rgb\(42,\s*58,\s*74\)/.test(
        r.getAttribute('style') || '') || getComputedStyle(r).backgroundColor === 'rgb(42, 58, 74)')
    return {
      status: (status?.textContent || '').trim(),
      // The spinner is a sibling node, not text — without it "Retrieving…" and a frozen
      // "Retrieving…" look identical in a log.
      spinner: !!status?.querySelector('.nadoc-spinner'),
      dot: (lab?.textContent || '').trim(),
      dotTitle: (ind?.title || '').trim(),
      dotShown: !!ind && ind.style.display !== 'none',
      refreshShown: !!refresh && refresh.style.display !== 'none',
      refreshDisabled: !!refresh?.disabled,
      displayOn: !!toggle?.checked,
      jobId: sel?.dataset?.jobId ?? null,
    }
  }).catch(() => null)

  const tick = async () => {
    if (stopped) return
    const dom = await readDom()
    if (dom) {
      const sig = JSON.stringify(dom)
      if (sig !== lastDom) { lastDom = sig; push('dom', dom) }
    }
    // Drain the in-page event buffer by index so nothing is double-counted.
    const fresh = await page.evaluate(
      (from) => (window.__mdDisplayEvents || []).slice(from), drained,
    ).catch(() => [])
    for (const e of fresh) push('event', e)
    drained += fresh.length
  }

  timer = setInterval(() => { tick().catch(() => {}) }, intervalMs)

  return {
    records,
    /** Force a read now (use around a click, so the log has a row for it). */
    sample: tick,
    note: (text) => push('note', { text }),
    async stop() {
      stopped = true
      clearInterval(timer)
      await tick().catch(() => {})   // final drain: catch events fired during teardown
    },
    /** Did a real MD frame reach the scene? This is the load-bearing question. */
    sawFrame: () => records.some(r => r.kind === 'event' && r.state === 'frame'),
    statusTexts: () => records.filter(r => r.kind === 'dom').map(r => r.status),
    consoleErrors: () => records.filter(r => r.kind === 'console' && r.level !== 'warning'),
    /** `<stem>.jsonl` (machine) + `<stem>.txt` (a readable timeline). */
    write(stem) {
      fs.mkdirSync(path.dirname(stem), { recursive: true })
      fs.writeFileSync(`${stem}.jsonl`, records.map(r => JSON.stringify(r)).join('\n') + '\n')
      fs.writeFileSync(`${stem}.txt`, records.map(fmt).join('\n') + '\n')
      return { jsonl: `${stem}.jsonl`, txt: `${stem}.txt` }
    },
  }
}

function fmt(r) {
  const t = (r.t / 1000).toFixed(1).padStart(7) + 's  '
  if (r.kind === 'dom') {
    const bits = [
      r.displayOn ? 'display=ON' : 'display=off',
      r.jobId ? `job=${r.jobId}` : 'job=—',
      r.dotShown ? `dot=${r.dot || '—'}` : 'dot=hidden',
      r.refreshShown ? (r.refreshDisabled ? 'refresh=busy' : 'refresh=shown') : 'refresh=hidden',
    ]
    return `${t}DOM   [${bits.join(' ')}]\n${' '.repeat(9)}      status: ${r.spinner ? '⟳ ' : ''}${r.status || '(blank)'}`
  }
  if (r.kind === 'event') return `${t}EVENT ${r.state}: ${(r.message || '').slice(0, 160)}`
  if (r.kind === 'console') return `${t}${r.level.toUpperCase()} ${r.text}`
  return `${t}NOTE  ${r.text}`
}
