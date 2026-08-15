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
  const pushWall = (kind, data) => records.push({
    t: Math.max(0, Number(data?.wall || Date.now()) - t0), kind, ...data,
  })

  // The event stream has to be hooked before any app code runs, or the 'ready'/'frame'
  // events fired during the first load are lost — exactly the ones that answer "did it
  // ever show anything".
  await page.addInitScript(() => {
    window.__mdDisplayEvents = []
    const capture = (channel) => (e) => window.__mdDisplayEvents.push({
      wall: Date.now(), channel, ...(e.detail || {}),
    })
    window.addEventListener('nadoc:md-display-state', capture('display'))
    window.addEventListener('nadoc:md-display-process', capture('process'))
    window.addEventListener('nadoc:op-progress', capture('popup'))
    window.addEventListener('nadoc:api-request', capture('api'))
    window.__nadocApiTraceAll = true
  })

  page.on('console', (m) => {
    const type = m.type()
    push('console', { level: type, text: m.text().slice(0, 1000) })
  })
  page.on('pageerror', (e) => push('console', { level: 'pageerror', text: String(e).slice(0, 300) }))
  page.on('request', req => {
    const url = req.url()
    if (/\/api\/|\/ws\//.test(url)) push('network', {
      phase: 'request', method: req.method(), url,
    })
  })
  page.on('response', res => {
    const url = res.url()
    if (/\/api\//.test(url)) push('network', {
      phase: 'response', status: res.status(), method: res.request().method(), url,
    })
  })
  page.on('requestfailed', req => {
    const url = req.url()
    if (/\/api\//.test(url)) push('network', {
      phase: 'failed', method: req.method(), url, error: req.failure()?.errorText || '',
    })
  })
  page.on('websocket', ws => {
    push('websocket', { phase: 'created', url: ws.url() })
    ws.on('framesent', e => push('websocket', {
      phase: 'sent', url: ws.url(), payload: String(e.payload).slice(0, 500),
    }))
    ws.on('framereceived', e => push('websocket', {
      phase: 'received', url: ws.url(), payload: String(e.payload).slice(0, 500),
    }))
    ws.on('socketerror', e => push('websocket', { phase: 'error', url: ws.url(), error: String(e) }))
    ws.on('close', () => push('websocket', { phase: 'closed', url: ws.url() }))
  })

  let lastDom = ''
  let drained = 0
  let timer = null
  let stopped = false
  let ticking = false

  /** One read of every DOM channel the display paints. */
  const readDom = () => page.evaluate(() => {
    const status = document.getElementById('md-jobs-display-status')
    const ind = document.getElementById('md-jobs-display-indicator')
    const lab = document.getElementById('md-jobs-display-indicator-label')
    const refresh = document.getElementById('md-jobs-live-frame-refresh')
    const toggle = document.getElementById('md-jobs-display-toggle')
    const popup = document.getElementById('op-progress')
    const popupHeader = document.getElementById('op-progress-header')
    const popupLabel = document.getElementById('op-progress-label')
    const popupFill = document.getElementById('op-progress-fill')
    const frameProgress = document.getElementById('md-jobs-live-frame-progress')
    const frameProgressLabel = document.getElementById('md-jobs-live-frame-progress-label')
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
      popupVisible: !!popup?.classList.contains('visible'),
      popupHeader: (popupHeader?.textContent || '').trim(),
      popupLabel: (popupLabel?.textContent || '').trim(),
      popupFraction: popupFill?.style?.width || '',
      frameProgressVisible: !!frameProgress && frameProgress.style.display !== 'none',
      frameProgress: (frameProgressLabel?.textContent || '').trim(),
    }
  }).catch(() => null)

  const tick = async (force = false) => {
    if ((!force && stopped) || ticking) return
    ticking = true
    try {
      const dom = await readDom()
      if (dom) {
        const sig = JSON.stringify(dom)
        if (sig !== lastDom) { lastDom = sig; push('dom', dom) }
      }
      // Drain the in-page event buffer by index so nothing is double-counted.
      const fresh = await page.evaluate(
        (from) => (window.__mdDisplayEvents || []).slice(from), drained,
      ).catch(() => [])
      for (const e of fresh) pushWall(e.channel || 'event', e)
      drained += fresh.length
    } finally {
      ticking = false
    }
  }

  timer = setInterval(() => { tick().catch(() => {}) }, intervalMs)

  return {
    records,
    /** Force a read now (use around a click, so the log has a row for it). */
    sample: tick,
    note: (text) => push('note', { text }),
    flush: (stem) => writeRecords(stem, records),
    async stop() {
      stopped = true
      clearInterval(timer)
      while (ticking) await new Promise(resolve => setTimeout(resolve, 10))
      await tick(true).catch(() => {})
    },
    /** Did a real MD frame reach the scene? This is the load-bearing question. */
    sawFrame: () => records.some(r => r.kind === 'event' && r.state === 'frame'),
    statusTexts: () => records.filter(r => r.kind === 'dom').map(r => r.status),
    consoleErrors: () => records.filter(
      r => r.kind === 'console' && (r.level === 'error' || r.level === 'pageerror'),
    ),
    /** Compare observed milestones with an explicit expected/forbidden process plan. */
    compare(predictions) {
      const byName = new Map()
      const results = []
      for (const p of predictions) {
        const dependency = p.after ? byName.get(p.after) : null
        const anchor = dependency?.observed ?? null
        const dependencyMissing = !!p.after && !anchor
        const candidates = records.filter(r =>
          recordMatches(r, p.match || {}) && !!anchor && r.t >= anchor.t)
        const observed = dependencyMissing ? null
          : (p.after ? candidates[0] : records.find(r => recordMatches(r, p.match || {}))) ?? null
        const elapsedMs = observed ? observed.t - (anchor?.t ?? 0) : null
        const forbidden = p.should === 'not-happen'
        const pass = dependencyMissing ? false : forbidden
          ? !observed
          : !!observed && (p.minMs == null || elapsedMs >= p.minMs)
            && (p.maxMs == null || elapsedMs <= p.maxMs)
        const result = { ...p, observed, elapsedMs, pass, dependencyMissing }
        byName.set(p.name, result)
        results.push(result)
        push('prediction', {
          name: p.name, should: p.should || 'happen', pass, elapsedMs,
          expected: [p.minMs ?? 0, p.maxMs ?? null],
          observedKind: observed?.kind ?? null,
        })
      }
      return results
    },
    /** `<stem>.jsonl` (machine) + `<stem>.txt` (a readable timeline). */
    write(stem) {
      return writeRecords(stem, records)
    },
  }
}

function writeRecords(stem, records) {
  fs.mkdirSync(path.dirname(stem), { recursive: true })
  fs.writeFileSync(`${stem}.jsonl`, records.map(r => JSON.stringify(r)).join('\n') + '\n')
  fs.writeFileSync(`${stem}.txt`, records.map(fmt).join('\n') + '\n')
  return { jsonl: `${stem}.jsonl`, txt: `${stem}.txt` }
}

function fmt(r) {
  const t = (r.t / 1000).toFixed(1).padStart(7) + 's  '
  if (r.kind === 'dom') {
    const bits = [
      r.displayOn ? 'display=ON' : 'display=off',
      r.jobId ? `job=${r.jobId}` : 'job=—',
      r.dotShown ? `dot=${r.dot || '—'}` : 'dot=hidden',
      r.refreshShown ? (r.refreshDisabled ? 'refresh=busy' : 'refresh=shown') : 'refresh=hidden',
      r.popupVisible ? `popup=${r.popupHeader || 'Working…'}` : 'popup=off',
      r.frameProgressVisible ? `progress=${r.frameProgress || '—'}` : 'progress=off',
    ]
    return `${t}DOM   [${bits.join(' ')}]\n${' '.repeat(9)}      status: ${r.spinner ? '⟳ ' : ''}${r.status || '(blank)'}`
  }
  if (r.kind === 'display') return `${t}DISPLAY ${r.state}: ${(r.message || '').slice(0, 160)}`
  if (r.kind === 'process') return `${t}PROCESS ${r.phase}: ${compact(r)}`
  if (r.kind === 'api') return `${t}API ${r.phase} #${r.id} ${r.method} ${r.path}${r.durationMs == null ? '' : ` ${Math.round(r.durationMs)}ms`}`
  if (r.kind === 'popup') return `${t}POPUP ${r.action} depth=${r.depth} visible=${r.visible} “${r.header || ''}” ${r.label || ''}`
  if (r.kind === 'network') return `${t}NET ${r.phase} ${r.status || ''} ${r.method || ''} ${r.url}`
  if (r.kind === 'websocket') return `${t}WS ${r.phase} ${r.url} ${(r.payload || r.error || '').slice(0, 180)}`
  if (r.kind === 'prediction') return `${t}EXPECT ${r.pass ? 'PASS' : 'FAIL'} ${r.name} observed=${r.elapsedMs == null ? '—' : `${Math.round(r.elapsedMs)}ms`}`
  if (r.kind === 'console') return `${t}${r.level.toUpperCase()} ${r.text}`
  return `${t}NOTE  ${r.text}`
}

function recordMatches(record, match) {
  return Object.entries(match).every(([key, expected]) => {
    const actual = record[key]
    if (expected instanceof RegExp) return expected.test(String(actual ?? ''))
    if (Array.isArray(expected)) return expected.includes(actual)
    return actual === expected
  })
}

function compact(record) {
  return Object.entries(record)
    .filter(([k, v]) => !['t', 'kind', 'wall', 'channel', 'phase', 'at'].includes(k) && v != null)
    .map(([k, v]) => `${k}=${typeof v === 'number' ? Math.round(v * 100) / 100 : String(v).slice(0, 100)}`)
    .join(' ')
}
