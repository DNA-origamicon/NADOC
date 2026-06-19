// benchmark_panel.js — "Benchmark" collapsible card for the oxDNA and NAMD
// subsections of the Dynamics panel.  Running a benchmark fires a short array of
// trial simulations (sized like the open design, on a synthetic proxy the backend
// generates + deletes) across this machine's CPU/GPU configs, keeps the fastest,
// and writes it into the design's per-machine defaults (keyed by hostname) so the
// panel pre-fills it.
//
// Factory (Feathers' Sprout Method): initBenchmarkPanel({api, getWorkspacePath})
// → {mountOxdna(el), mountNamd(el)}.  main.js only imports + inits + mounts.
//
// While a sweep runs: a spinner sits on the button, a loading bar + ETA show
// progress, every other control in BOTH Dynamics panels is disabled (a concurrent
// job would corrupt the timing), and a Cancel button kills the run (keeping the
// existing defaults).  Dummy-proof: if this machine has only ONE possible config
// (no GPU → CPU-only), it warns first that benchmarking can't improve anything.

const FIELD_IDS = {
  oxdna: { backend: 'oxdna-jobs-backend', device: 'oxdna-jobs-device' },
  namd: { threads: 'md-jobs-threads', devices: 'md-jobs-devices' },
}

// The two Dynamics panel sections to lock while a benchmark runs.
const PANEL_IDS = ['oxdna-jobs-panel', 'md-jobs-panel']

function _set(id, value) {
  const el = document.getElementById(id)
  if (el != null && value != null) el.value = String(value)
}

function _fmt(n, digits = 1) {
  return typeof n === 'number' && isFinite(n) ? n.toFixed(digits) : '—'
}

function _fmtEta(s) {
  if (s == null) return 'estimating…'
  if (s < 90) return `~${Math.ceil(s)}s left`
  return `~${Math.ceil(s / 60)} min left`
}

// Spinner keyframes — injected once, shared by both cards.
function _ensureStyle() {
  if (document.getElementById('bench-spin-style')) return
  const st = document.createElement('style')
  st.id = 'bench-spin-style'
  st.textContent =
    '@keyframes bench-spin{to{transform:rotate(360deg)}}' +
    '.bench-spinner{width:11px;height:11px;border:2px solid currentColor;' +
    'border-top-color:transparent;border-radius:50%;display:inline-block;' +
    'vertical-align:middle;margin-right:5px;animation:bench-spin .7s linear infinite}'
  document.head.appendChild(st)
}

export function initBenchmarkPanel({ api, getWorkspacePath = () => null, sleep, confirm } = {}) {
  const _sleep = sleep || ((ms) => new Promise((r) => setTimeout(r, ms)))
  const _confirm = confirm || ((m) => window.confirm(m))

  // Panel-lock state (one benchmark at a time → a single saved snapshot is enough).
  let _locked = null

  function _lockPanels(activeCancelBtn) {
    if (_locked) return
    _locked = new Map()
    for (const pid of PANEL_IDS) {
      const sec = document.getElementById(pid)
      if (!sec) continue
      for (const el of sec.querySelectorAll('button, input, select, textarea')) {
        _locked.set(el, el.disabled)
        el.disabled = true
      }
    }
    if (activeCancelBtn) activeCancelBtn.disabled = false // Cancel stays clickable
  }

  function _unlockPanels() {
    if (!_locked) return
    for (const [el, prev] of _locked) el.disabled = prev
    _locked = null
  }

  function _resultLine(engine, r) {
    if (engine === 'oxdna') {
      const m = r.steps_per_s != null ? `${_fmt(r.steps_per_s, 0)} steps/s` : (r.error || '—')
      return `${r.label}: ${m}`
    }
    const m = r.ns_per_day != null ? `${_fmt(r.ns_per_day, 2)} ns/day` : (r.error || '—')
    return `${r.label}: ${m}`
  }

  function _recLine(engine, rec) {
    if (!rec) return ''
    if (engine === 'oxdna') {
      return `Best: ${rec.backend}${rec.backend === 'CUDA' ? ` device ${rec.device}` : ''}` +
             ` (${_fmt(rec.steps_per_s, 0)} steps/s)`
    }
    return `Best: +p${rec.threads} ${rec.devices ? `GPU ${rec.devices}` : 'CPU-only'}` +
           ` (${_fmt(rec.ns_per_day, 2)} ns/day)`
  }

  function _applyToInputs(engine, rec) {
    if (engine === 'oxdna') {
      _set(FIELD_IDS.oxdna.backend, rec.backend)
      _set(FIELD_IDS.oxdna.device, rec.device)
    } else {
      _set(FIELD_IDS.namd.threads, rec.threads)
      _set(FIELD_IDS.namd.devices, rec.devices)
    }
  }

  // One mount = one engine's collapsible card.
  function _mount(el, engine) {
    if (!el) return
    _ensureStyle()
    el.innerHTML = `
      <div class="bench-card" style="border:1px solid #30363d;border-radius:4px;background:#0d1117">
        <div class="bench-card__header" role="button" tabindex="0"
          style="display:flex;align-items:center;gap:6px;cursor:pointer;user-select:none;padding:5px 7px;color:#c9d1d9;font-size:var(--text-xs);font-weight:600">
          <span class="bench-card__chevron" style="display:inline-block;transition:transform .15s">▸</span>
          <span>Benchmark</span>
        </div>
        <div class="bench-card__body" style="display:none;padding:0 7px 7px">
          <button type="button" class="bench-run-btn"
            style="width:100%;font-size:var(--text-xs);padding:5px;background:#2a223a;border:1px solid #a371f7;color:#a371f7;border-radius:3px;cursor:pointer;font-weight:600">
            <span class="bench-spinner" style="display:none"></span><span class="bench-run-label">⏱ Benchmark this machine</span>
          </button>
          <div class="bench-progress" style="display:none;margin-top:6px">
            <div style="height:6px;background:#21262d;border-radius:3px;overflow:hidden">
              <div class="bench-bar-fill" style="height:100%;width:0%;background:#a371f7;transition:width .3s"></div>
            </div>
            <div class="bench-eta" style="font-size:10px;color:#8b949e;margin-top:3px"></div>
          </div>
          <button type="button" class="bench-cancel-btn"
            style="display:none;width:100%;font-size:var(--text-xs);padding:4px;margin-top:5px;background:#3a1a1a;border:1px solid #f85149;color:#f85149;border-radius:3px;cursor:pointer;font-weight:600">
            Cancel (keep current defaults)
          </button>
          <div class="bench-status" style="font-size:var(--text-xs);color:#8b949e;margin-top:5px;min-height:14px"></div>
          <div class="bench-results" style="font-size:10px;color:#8b949e;font-family:var(--font-mono);margin-top:4px;white-space:pre-line"></div>
          <div class="bench-note" style="font-size:10px;color:#8b949e;margin-top:4px;font-style:italic"></div>
          <button type="button" class="bench-apply-btn"
            style="display:none;width:100%;font-size:var(--text-xs);padding:5px;margin-top:5px;background:#1a3a1a;border:1px solid #3fb950;color:#3fb950;border-radius:3px;cursor:pointer;font-weight:600">
            Apply &amp; save as default
          </button>
        </div>
      </div>`

    const header = el.querySelector('.bench-card__header')
    const chevron = el.querySelector('.bench-card__chevron')
    const body = el.querySelector('.bench-card__body')
    const runBtn = el.querySelector('.bench-run-btn')
    const spinner = el.querySelector('.bench-spinner')
    const progress = el.querySelector('.bench-progress')
    const barFill = el.querySelector('.bench-bar-fill')
    const etaEl = el.querySelector('.bench-eta')
    const cancelBtn = el.querySelector('.bench-cancel-btn')
    const statusEl = el.querySelector('.bench-status')
    const resultsEl = el.querySelector('.bench-results')
    const noteEl = el.querySelector('.bench-note')
    const applyBtn = el.querySelector('.bench-apply-btn')

    const toggle = () => {
      const open = body.style.display !== 'none'
      body.style.display = open ? 'none' : ''
      chevron.style.transform = open ? '' : 'rotate(90deg)'
    }
    header.addEventListener('click', toggle)
    header.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle() } })

    let _lastId = null
    let _lastRec = null
    let _cancelId = null

    runBtn.addEventListener('click', () => { runSweep(engine, el).catch(() => {}) })
    cancelBtn.addEventListener('click', async () => {
      if (!_cancelId) return
      cancelBtn.disabled = true
      statusEl.textContent = 'Cancelling…'
      await api.cancelBenchmark(_cancelId)
      // The poll loop sees state → cancelled and tears down.
    })
    applyBtn.addEventListener('click', async () => {
      if (!_lastId) return
      applyBtn.disabled = true
      const res = await api.applyBenchmark(_lastId, { design_source_path: getWorkspacePath() })
      if (res) {
        _applyToInputs(engine, _lastRec)
        statusEl.textContent = res.saved_to
          ? `Applied — saved to ${res.saved_to.split('/').pop()}`
          : 'Applied to panel (save the design to persist).'
      } else {
        statusEl.textContent = 'Apply failed.'
      }
      applyBtn.disabled = false
    })

    el._bench = {
      runBtn, spinner, progress, barFill, etaEl, cancelBtn,
      statusEl, resultsEl, noteEl, applyBtn,
      setId: (id) => { _lastId = id }, setRec: (r) => { _lastRec = r },
      setCancelId: (id) => { _cancelId = id },
    }
  }

  async function runSweep(engine, el) {
    const ctx = el && el._bench
    if (!ctx) return null
    const { runBtn, spinner, progress, barFill, etaEl, cancelBtn,
            statusEl, resultsEl, noteEl, applyBtn } = ctx

    // Dummy-proof: if this machine has only one possible config (no GPU → CPU-only),
    // there's nothing to compare — warn before wasting a run.
    let hw = null
    try { hw = await api.benchmarkHardware() } catch { hw = null }
    const grid = hw && (engine === 'oxdna' ? hw.oxdna_grid : hw.namd_grid)
    if (grid && grid.length <= 1) {
      const ok = _confirm(
        `Only one ${engine === 'oxdna' ? 'oxDNA' : 'NAMD'} configuration is available on ` +
        `this machine (no GPU detected). The benchmark has nothing to compare, so it ` +
        `won't change or improve your settings.\n\nRun it anyway?`)
      if (!ok) { statusEl.textContent = 'Benchmark cancelled — nothing to compare.'; return null }
    }

    // Reset UI + lock both Dynamics panels for the duration.
    applyBtn.style.display = 'none'
    resultsEl.textContent = ''
    noteEl.textContent = ''
    spinner.style.display = ''
    progress.style.display = ''
    barFill.style.width = '0%'
    etaEl.textContent = ''
    statusEl.textContent = 'Building synthetic system…'
    _lockPanels(cancelBtn)

    const finish = () => {
      spinner.style.display = 'none'
      progress.style.display = 'none'
      cancelBtn.style.display = 'none'
      _unlockPanels()
    }

    const path = getWorkspacePath()
    let start
    try {
      start = engine === 'oxdna'
        ? await api.startOxdnaBenchmark({ design_source_path: path })
        : await api.startNamdBenchmark({ design_source_path: path })
    } catch { start = null }
    if (!start || !start.benchmark_id) {
      statusEl.textContent = 'Could not start benchmark (is the engine installed?).'
      finish()
      return null
    }
    const id = start.benchmark_id
    ctx.setId(id)
    ctx.setCancelId(id)
    cancelBtn.disabled = false
    cancelBtn.style.display = ''

    let state = null
    for (;;) {
      state = await api.getBenchmark(id)
      if (!state) break
      const done = state.trials_done ?? 0
      const total = state.trials_total ?? start.trials_total ?? 0
      barFill.style.width = `${Math.round((state.fraction ?? 0) * 100)}%`
      etaEl.textContent = `Trial ${done}/${total} · ${_fmtEta(state.eta_seconds)}`
      statusEl.textContent = state.state === 'running'
        ? `Running${state.current_label ? ` — ${state.current_label}` : ''}…`
        : ''
      if (state.results && state.results.length) {
        resultsEl.textContent = state.results.map((r) => _resultLine(engine, r)).join('\n')
      }
      if (state.state !== 'running') break
      await _sleep(1500)
    }

    finish()
    if (!state || state.state === 'failed') {
      statusEl.textContent = `Benchmark failed: ${(state && state.error) || 'unknown error'}`
      return state
    }
    if (state.state === 'cancelled') {
      statusEl.textContent = 'Benchmark cancelled — kept existing defaults.'
      return state
    }
    statusEl.textContent = _recLine(engine, state.recommendation)
    noteEl.textContent = state.note || ''
    ctx.setRec(state.recommendation)
    applyBtn.style.display = ''
    return state
  }

  return {
    mountOxdna: (el) => _mount(el, 'oxdna'),
    mountNamd: (el) => _mount(el, 'namd'),
    runSweep, // exposed for tests
  }
}
