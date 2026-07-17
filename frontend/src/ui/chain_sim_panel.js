/**
 * chain_sim_panel.js — the "Chain Simulations" left-sidebar section.
 *
 * Sits above the Simulate section. Owns a named-project queue of oxDNA/NAMD relax→
 * production stages that Launch turns into unattended `MdPipeline` chains. When "chain
 * mode" is enabled, the oxDNA/NAMD Relax/Production buttons flip to "Queue …" and feed
 * this queue instead of launching immediately.
 *
 * Projects persist on the design (like DesignAnimations) via the `chain_sim_endpoints`
 * API, so a plan travels with the `.nadoc`. All pure decisions (preflight ✓/⚠/✕, ETA,
 * grouping into chains) live in the unit-tested `chain_sim_model.js`; this module is the
 * stateful DOM/store glue.
 *
 * Factory: initChainSimPanel({ store, api, engines, selectEngine, getBaseCount,
 *   getCompletedJobs, getThroughput }) → { isEnabled, refresh }.
 */

import { getSectionCollapsed, setSectionCollapsed } from './section_collapse_state.js'
import { showConfirm } from './primitives/confirm.js'
import { showToast } from './toast.js'
import {
  newChainStage, stagePreflight, queuePreflightLevel,
  estimateStageSeconds, estimateTotalSeconds, formatDuration,
  chainGroups, toChainStagePayload, liveStageBadge, latestHealthSample,
} from './chain_sim_model.js'
import { chainStatusSummary } from './stage_planner_model.js'

const _ENABLE_KEY = 'nadoc.chainSim.enabled.v1'
const _C = { ok: '#3fb950', warn: '#e0a800', err: '#d9534f', dim: '#8b949e', accent: '#4a9eff', text: '#c9d1d9' }
const _GLYPH = { ok: '✓', warn: '⚠', error: '✕' }
const _GLYPH_COLOR = { ok: _C.ok, warn: _C.warn, error: _C.err }

function _el(tag, props = {}, kids = []) {
  const e = document.createElement(tag)
  for (const [k, v] of Object.entries(props)) {
    if (k === 'style') Object.assign(e.style, v)
    else if (k === 'text') e.textContent = v
    else if (k.startsWith('on') && typeof v === 'function') e.addEventListener(k.slice(2).toLowerCase(), v)
    else if (v != null) e.setAttribute(k, String(v))
  }
  for (const c of [].concat(kids)) if (c) e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c)
  return e
}

export function initChainSimPanel({
  store, api,
  engines = {},
  selectEngine = null,
  getBaseCount = () => 0,
  getCompletedJobs = () => [],
  getThroughput = () => ({}),
  getDesignSourcePath = () => null,
} = {}) {
  const heading   = document.getElementById('chain-sim-heading')
  const arrow     = document.getElementById('chain-sim-arrow')
  const body      = document.getElementById('chain-sim-body')
  const enableEl  = document.getElementById('chain-sim-enable')
  const selectEl  = document.getElementById('chain-sim-project-select')
  const renameEl  = document.getElementById('chain-sim-rename-input')
  const newBtn    = document.getElementById('chain-sim-new-btn')
  const dupBtn    = document.getElementById('chain-sim-dup-btn')
  const delBtn    = document.getElementById('chain-sim-del-btn')
  const queueEl   = document.getElementById('chain-sim-queue')
  const totalEl   = document.getElementById('chain-sim-total')
  const launchBtn = document.getElementById('chain-sim-launch-btn')
  const statusEl  = document.getElementById('chain-sim-status')
  if (!heading || !queueEl) return { isEnabled: () => false, refresh: () => {} }

  let _enabled   = localStorage.getItem(_ENABLE_KEY) === '1'
  let _activeId  = null
  let _stages    = []          // local authoritative copy while editing
  let _selRow    = -1          // highlighted queue row
  let _busy      = false
  let _launched  = []          // [{ chainId, stageIds }] launched this session
  let _liveStatus = {}         // stageId -> { status, jobId, engine, health }
  let _seenJobIds = new Set()  // realised stage job ids already pushed to the engine lists
  let _pollTimer = null

  // ── collapse ──────────────────────────────────────────────────────────────────
  let _collapsed = getSectionCollapsed('dynamics', 'chain-sim-panel', false)
  body.style.display = _collapsed ? 'none' : ''
  if (arrow) arrow.classList.toggle('is-collapsed', _collapsed)
  heading.addEventListener('click', () => {
    _collapsed = !_collapsed
    body.style.display = _collapsed ? 'none' : ''
    arrow.classList.toggle('is-collapsed', _collapsed)
    setSectionCollapsed('dynamics', 'chain-sim-panel', _collapsed)
  })

  // ── enable toggle ───────────────────────────────────────────────────────────--
  enableEl.checked = _enabled
  enableEl.addEventListener('change', () => {
    _enabled = enableEl.checked
    localStorage.setItem(_ENABLE_KEY, _enabled ? '1' : '0')
    // Tell the engine panels to repaint their Relax/Production button labels.
    window.dispatchEvent(new CustomEvent('nadoc:chain-mode-change', { detail: { enabled: _enabled } }))
  })

  // ── project list from the design ───────────────────────────────────────────────
  function _projects() {
    return store.getState().currentDesign?.chain_sim_projects ?? []
  }

  function _rebuildSelect() {
    const projects = _projects()
    selectEl.replaceChildren()
    if (!projects.length) {
      selectEl.appendChild(_el('option', { text: '— No chain projects —', disabled: '' }))
      _activeId = null
      _stages = []
      _renderQueue()
      return
    }
    for (const p of projects) selectEl.appendChild(_el('option', { value: p.id, text: p.name }))
    if (!projects.some((p) => p.id === _activeId)) _activeId = projects[0].id
    selectEl.value = _activeId
    _loadActiveStages()
  }

  function _loadActiveStages() {
    const proj = _projects().find((p) => p.id === _activeId)
    _stages = (proj?.stages ?? []).map((s) => ({ ...s }))
    _selRow = -1
    // Live run-status belongs to the previously-viewed project's launch — drop it so a
    // switched-to project shows its own preflight, not stale statuses.
    _stopPolling(); _launched = []; _liveStatus = {}; _seenJobIds = new Set(); statusEl.textContent = ''
    _renderQueue()
  }

  selectEl.addEventListener('change', () => { _activeId = selectEl.value; _loadActiveStages() })

  // rename on double-click (inline input, like Animations)
  selectEl.addEventListener('dblclick', () => {
    if (!_activeId) return
    const proj = _projects().find((p) => p.id === _activeId)
    renameEl.value = proj?.name ?? ''
    selectEl.style.display = 'none'
    renameEl.style.display = ''
    renameEl.focus(); renameEl.select()
  })
  function _commitRename() {
    const name = renameEl.value.trim()
    selectEl.style.display = ''
    renameEl.style.display = 'none'
    if (name && _activeId) api.updateChainSimProject(_activeId, { name }).catch(() => showToast('Rename failed', 'err'))
  }
  renameEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); _commitRename() }
    if (e.key === 'Escape') { selectEl.style.display = ''; renameEl.style.display = 'none' }
  })
  renameEl.addEventListener('blur', _commitRename)

  // ── New / Duplicate / Delete ────────────────────────────────────────────────---
  // Select the most-recently-added project after a create/duplicate (the store is the
  // source of truth once the await resolves — _syncFromDesignResponse has updated it).
  function _selectLastProject() {
    const projs = _projects()
    _activeId = projs[projs.length - 1]?.id ?? _activeId
    _rebuildSelect()
  }

  newBtn.addEventListener('click', async () => {
    const n = _projects().length + 1
    const ok = await api.createChainSimProject(`Chain ${n}`).catch(() => null)
    if (ok === null) return showToast('Could not create project', 'err')
    _selectLastProject()
  })
  dupBtn.addEventListener('click', async () => {
    const proj = _projects().find((p) => p.id === _activeId)
    if (!proj) return
    const ok = await api.createChainSimProject(`${proj.name} copy`, proj.stages.map((s) => ({ ...s }))).catch(() => null)
    if (ok === null) return showToast('Could not duplicate project', 'err')
    _selectLastProject()
  })
  delBtn.addEventListener('click', async () => {
    if (!_activeId) return
    const proj = _projects().find((p) => p.id === _activeId)
    const ok = await showConfirm({
      title: 'Delete chain project',
      message: `Delete “${proj?.name ?? 'this project'}” and its ${_stages.length} queued stage(s)? This cannot be undone.`,
      confirmLabel: 'Delete',
    })
    if (!ok) return
    await api.deleteChainSimProject(_activeId).catch(() => showToast('Delete failed', 'err'))
    _activeId = null
    _rebuildSelect()
  })

  // ── enqueue (called by the engine buttons) ──────────────────────────────────---
  async function _ensureProject() {
    if (_activeId && _projects().some((p) => p.id === _activeId)) return true
    const ok = await api.createChainSimProject('Chain 1').catch(() => null)
    if (ok === null) { showToast('Could not create a chain project', 'err'); return false }
    _selectLastProject()
    return !!_activeId
  }

  function _buildStage(engine, protocol) {
    const eng = engines[engine] || {}
    const runEl = eng.getRunElements?.() || {}
    const adv = eng.getAdvanced?.() || {}
    const allowField = protocol === 'production' || engine === 'namd'  // oxDNA relax excludes field
    const field = (allowField && runEl.field?.enabled && Number(runEl.field.field_pN) > 0)
      ? { field_pN: runEl.field.field_pN, dir: runEl.field.dir } : null
    const surface = runEl.surface?.enabled
      ? {
          dir: runEl.surface.dir,
          offset_nm: runEl.surface.offsetNm ?? runEl.surface.offset_nm,
          position_nm: runEl.surface.positionNm ?? runEl.surface.position_nm,
          stiff: runEl.surface.stiff,
        }
      : null
    const anchors = runEl.anchors?.length ? runEl.anchors : null
    // A production may seed off an ALREADY-COMPLETED job the user has selected (the
    // "already ran a relax, now queue productions" case). Captured here; an in-queue
    // relax before this stage still takes precedence at preflight/launch time.
    let seed_job_id = null, seed_job_name = null, seed_engine = null
    if (protocol === 'production') {
      const sel = eng.getSelectedJob?.()
      if (sel && sel.status === 'completed') {
        seed_job_id = sel.job_id
        seed_job_name = sel.name || sel.design_name || sel.job_id
        seed_engine = engine
      }
    }
    return newChainStage({
      id: (crypto.randomUUID?.() || `s${Date.now()}${Math.round(performance.now())}`),
      engine, protocol, field, surface, anchors,
      run_target: adv.run_target || 'local',
      cluster_name: adv.cluster_name || null,
      steps: adv.steps ?? null,
      length_ns: adv.length_ns ?? null,
      label: adv.label || `${engine.toUpperCase()} ${protocol}`,
      seed_job_id, seed_job_name, seed_engine,
    })
  }

  async function enqueue(engine, protocol) {
    if (!(await _ensureProject())) return
    _stages = [..._stages, _buildStage(engine, protocol)]
    _selRow = _stages.length - 1
    _renderQueue()
    await _persistStages()
    showToast(`Queued ${engine.toUpperCase()} ${protocol}`, 'ok')
  }

  async function _persistStages() {
    if (!_activeId) return
    await api.setChainSimStages(_activeId, _stages).catch(() => showToast('Could not save queue', 'err'))
  }

  // ── queue render ────────────────────────────────────────────────────────────--
  function _etaCtx() {
    const t = getThroughput() || {}
    return { baseCount: getBaseCount() || 0, oxdnaStepsPerSec: t.oxdnaStepsPerSec ?? null, namdNsPerDay: t.namdNsPerDay ?? null }
  }

  function _stageSummary(st) {
    const bits = [st.label || `${st.engine} ${st.protocol}`]
    if (st.field && Number(st.field.field_pN) > 0) bits.push(`E ${(+st.field.field_pN).toPrecision(2)}pN`)
    if (st.surface) bits.push('surf')
    if (st.anchors?.length) bits.push(`⚓${st.anchors.length}`)
    if (st.run_target === 'alpine') bits.push('alpine')
    return bits.join(' · ')
  }

  function _iconBtn(glyph, title, onClick) {
    return _el('button', {
      title, onclick: onClick,
      style: { background: 'none', border: 'none', color: _C.dim, cursor: 'pointer', padding: '0 2px', fontSize: '12px' },
    }, glyph)
  }

  function _renderQueue() {
    queueEl.replaceChildren()
    if (!_activeId) {
      queueEl.appendChild(_el('div', { style: { color: _C.dim, fontSize: '11px', padding: '4px' } },
        'No chain project. Click + to create one, then Queue a run from an engine.'))
      _renderTotal(); _renderLaunch(); return
    }
    if (!_stages.length) {
      queueEl.appendChild(_el('div', { style: { color: _C.dim, fontSize: '11px', padding: '4px' } },
        _enabled ? 'Queue empty — press “Queue Relax” / “Queue Production” in an engine.'
                 : 'Queue empty — enable chain simulations, then Queue a run from an engine.'))
      _renderTotal(); _renderLaunch(); return
    }
    const completedJobs = getCompletedJobs() || []
    const ctx = _etaCtx()
    _stages.forEach((st, i) => {
      const pf = stagePreflight(_stages, i, { completedJobs })
      const live = _liveStatus[st.id]   // set once the chain is launched
      const active = i === _selRow
      // Lead glyph: the LIVE run status once launched (queued/running/done/failed),
      // else the plan preflight (✓/⚠/✕).
      const lead = live
        ? _el('span', { title: `${liveStageBadge(live.status).label}`, style: { color: liveStageBadge(live.status).color, fontWeight: '700', width: '12px', flexShrink: '0' } }, liveStageBadge(live.status).symbol)
        : _el('span', { title: pf.reasons.join('; ') || 'ready', style: { color: _GLYPH_COLOR[pf.level], fontWeight: '700', width: '12px', flexShrink: '0' } }, _GLYPH[pf.level])
      // Trailing: once launched show the status label + a health dot; else the ETA.
      const trailing = live
        ? _el('span', { style: { display: 'flex', gap: '4px', alignItems: 'center', flexShrink: '0' } }, [
            _el('span', { style: { color: liveStageBadge(live.status).color } }, liveStageBadge(live.status).label),
            _healthDot(live.health),
          ])
        : _el('span', { style: { color: _C.dim, flexShrink: '0' } }, formatDuration(estimateStageSeconds(st, ctx)))
      const row = _el('div', {
        style: {
          display: 'flex', alignItems: 'center', gap: '5px', padding: '3px 4px',
          borderRadius: '3px', cursor: 'pointer', fontSize: '11px',
          background: active ? 'rgba(74,158,255,0.12)' : 'transparent',
          border: `1px solid ${active ? _C.accent : 'transparent'}`,
        },
        onclick: () => _selectRow(i),
      }, [
        lead,
        _el('span', { style: { color: _C.dim, fontVariantNumeric: 'tabular-nums', flexShrink: '0' } }, `${i + 1}.`),
        _el('span', { style: { flex: '1', minWidth: '0', color: pf.level === 'error' && !live ? _C.err : _C.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } },
          _stageSummary(st) + (pf.seedFrom ? ` — ${pf.seedFrom.label}` : '')),
        trailing,
        _iconBtn('✎', 'update this stage to the engine’s current settings', (e) => { e.stopPropagation(); _updateStageFromCurrent(i) }),
        _iconBtn('↑', 'move up', (e) => { e.stopPropagation(); _reorder(i, i - 1) }),
        _iconBtn('↓', 'move down', (e) => { e.stopPropagation(); _reorder(i, i + 1) }),
        _iconBtn('✕', 'remove', (e) => { e.stopPropagation(); _remove(i) }),
      ])
      queueEl.appendChild(row)
    })
    _renderTotal(); _renderLaunch()
  }

  /** A pass/warn health dot for a launched stage's latest health sample (null = none yet). */
  function _healthDot(health) {
    if (!health) return null
    const ok = health.passed !== false
    return _el('span', {
      title: health.reason || (ok ? 'health OK' : 'health warning'),
      style: { color: ok ? _C.ok : _C.err, flexShrink: '0' },
    }, '●')
  }

  function _renderTotal() {
    if (!_stages.length) { totalEl.textContent = ''; return }
    const total = estimateTotalSeconds(_stages, _etaCtx())
    totalEl.textContent = `Total: ${formatDuration(total)} · ${_stages.length} stage${_stages.length === 1 ? '' : 's'}`
  }

  function _renderLaunch() {
    launchBtn.disabled = _busy || !_stages.length
  }

  function _selectRow(i) {
    _selRow = i
    const st = _stages[i]
    selectEngine?.(st.engine)
    const live = _liveStatus[st.id]
    const eng = engines[st.engine] || {}
    if (live?.jobId && eng.selectJob) {
      // A LAUNCHED stage → select its REAL job in the engine's standard list, exactly like
      // clicking that job's row there (highlights it + populates every card from the job's
      // actual run config + follows the display). This is a superset of the plan echo below.
      eng.selectJob(live.jobId)
    } else {
      // An un-launched (planned) stage → echo the queued run's conditions into the cards.
      eng.applyRunConfig?.({ field: st.field, surface: st.surface, anchors: st.anchors })
    }
    _renderQueue()
  }

  // Overwrite a queued stage's tunable settings (field / surface / anchors + advanced
  // knobs) with whatever the engine currently has configured — keeping the stage's engine,
  // protocol, id and queue position. Lets the user FIX a stage in place (e.g. re-aim a field
  // that pointed the wrong way) instead of removing + re-queuing. Reuses the same
  // `_buildStage` capture the engine "Queue …" buttons use, so an updated stage is identical
  // to a freshly-queued one. The revised plan is what the NEXT Launch uses (a Resume re-runs
  // the already-launched chain's frozen plan, so re-Launch to apply changed settings).
  function _updateStageFromCurrent(i) {
    const st = _stages[i]
    const fresh = _buildStage(st.engine, st.protocol)   // reads this engine's current cards
    _stages[i] = { ...fresh, id: st.id }
    _selRow = i
    _renderQueue()
    _persistStages()
    showToast(`Updated stage ${i + 1} to current ${st.engine.toUpperCase()} settings`, 'ok')
  }

  function _reorder(from, to) {
    if (to < 0 || to >= _stages.length) return
    const arr = _stages.slice()
    const [s] = arr.splice(from, 1)
    arr.splice(to, 0, s)
    _stages = arr
    _selRow = to
    _renderQueue()
    _persistStages()
  }

  function _remove(i) {
    _stages = _stages.filter((_, j) => j !== i)
    if (_selRow >= _stages.length) _selRow = _stages.length - 1
    _renderQueue()
    _persistStages()
  }

  // ── Launch ────────────────────────────────────────────────────────────────────
  launchBtn.addEventListener('click', _launch)
  async function _launch() {
    if (_busy || !_stages.length) return
    const completedJobs = getCompletedJobs() || []
    const level = queuePreflightLevel(_stages, { completedJobs })
    if (level === 'error') {
      const bad = _stages.map((st, i) => ({ st, i, pf: stagePreflight(_stages, i, { completedJobs }) }))
        .filter((x) => x.pf.level === 'error')
        .map((x) => `• Stage ${x.i + 1} (${x.st.label}): ${x.pf.reasons.join('; ')}`)
      await showConfirm({
        title: 'Cannot launch — fix these stages',
        message: `Some queued stages can’t run:\n\n${bad.join('\n')}\n\nRemove or fix them, then launch again.`,
        confirmLabel: 'OK', cancelLabel: null,
      })
      return
    }
    if (level === 'warn') {
      const warns = _stages.map((st, i) => ({ st, i, pf: stagePreflight(_stages, i, { completedJobs }) }))
        .filter((x) => x.pf.level === 'warn')
        .map((x) => `• Stage ${x.i + 1} (${x.st.label}): ${x.pf.reasons.join('; ')}`)
      const ok = await showConfirm({
        title: 'Launch with warnings?',
        message: `These stages have warnings:\n\n${warns.join('\n')}\n\nLaunch anyway?`,
        confirmLabel: 'Launch anyway',
      })
      if (!ok) return
    }
    const groups = chainGroups(_stages, { completedJobs })
    if (!groups.length) { showToast('Nothing launchable in the queue', 'warn'); return }
    const designSourcePath = getDesignSourcePath?.() ?? null
    // Engines whose job list needs an immediate refresh (a chain spawns stage 0 before
    // createChain returns, but the engine panels don't know to poll until they see it).
    const launchedEngines = new Set()
    _busy = true; _renderLaunch()
    _launched = []; _seenJobIds = new Set()
    for (const g of groups) {
      // stamp design_source_path so every spawned job lands in the per-design engine
      // job list (with its standard status + health + trajectory viz).
      const payload = {
        root_job_id: g.root_job_id,
        root_engine: g.root_engine,
        design_source_path: designSourcePath,
        stages: g.stages.map(toChainStagePayload),
      }
      const res = await api.createChain(payload).catch(() => null)
      if (res?.chain?.chain_id) {
        _launched.push({ chainId: res.chain.chain_id, stageIds: g.stages.map((s) => s.id) })
        g.stages.forEach((s) => launchedEngines.add(s.engine))
      }
    }
    _busy = false; _renderLaunch()
    if (!_launched.length) {
      statusEl.style.color = _C.err
      statusEl.textContent = `Launch failed: ${api.lastErrorMessage?.() || 'unknown error'}`
      return
    }
    // Immediately populate the engine job list(s) so the freshly-spawned stage-0 run shows
    // up at once (and each panel re-arms its own status/health poll from there).
    launchedEngines.forEach((eng) => engines[eng]?.refreshJobs?.())
    showToast(`Launched ${_launched.length} chain${_launched.length === 1 ? '' : 's'}`, 'ok')
    _startPolling()
  }

  // Poll each launched chain: map its per-stage {status, job_id} back onto the queue rows
  // (by the stage ids captured at launch), and pull each realised job's latest health
  // sample — so a queue row tracks its stage's live status + health like the engine list.
  function _startPolling() {
    _stopPolling()
    if (!_launched.length) return
    const tick = async () => {
      const live = {}
      const summaries = []
      const errors = []           // actionable failure messages to surface on halt
      let allDone = true
      for (const { chainId, stageIds } of _launched) {
        const res = await api.getMdChain(chainId).catch(() => null)
        const chain = res?.chain
        if (!chain) { allDone = false; continue }
        const summary = chainStatusSummary(chain)
        summaries.push(summary.headline)
        if (summary.error) errors.push(summary.error)
        if (chain.status !== 'completed' && chain.status !== 'failed') allDone = false
        ;(chain.stages || []).forEach((cs, i) => {
          const sid = stageIds[i]
          if (sid) live[sid] = { status: cs.status, jobId: cs.job_id, engine: cs.engine }
        })
      }
      // As soon as a stage is REALISED (its job_id first appears — i.e. the stage has
      // STARTED, not completed), push it into the matching engine's standard job list so
      // the running job shows there immediately (the engine panel wouldn't otherwise know
      // to poll for a mid-chain stage the supervisor just spawned). One refresh per engine.
      const enginesToRefresh = new Set()
      for (const v of Object.values(live)) {
        if (v.jobId && !_seenJobIds.has(v.jobId)) { _seenJobIds.add(v.jobId); enginesToRefresh.add(v.engine) }
      }
      enginesToRefresh.forEach((eng) => engines[eng]?.refreshJobs?.())
      // Health for each realised job (running/done/failed carry a job_id).
      await Promise.all(Object.values(live).filter((v) => v.jobId).map(async (v) => {
        const job = v.engine === 'oxdna'
          ? await api.getOxdnaJob?.(v.jobId).catch(() => null)
          : await api.getMdJob?.(v.jobId).catch(() => null)
        v.health = latestHealthSample(job)
      }))
      _liveStatus = live
      // On a halt, lead with the backend's actionable reason (e.g. "Open 'X' to continue
      // this run") instead of only the generic "halted at stage N" headline.
      if (errors.length) {
        statusEl.style.color = _C.err
        statusEl.textContent = `${summaries.join('  |  ')} — ${errors.join('  ')}`
      } else {
        statusEl.style.color = _C.accent
        statusEl.textContent = summaries.join('  |  ')
      }
      _renderQueue()
      if (allDone) _stopPolling()
    }
    tick()
    _pollTimer = setInterval(tick, 4000)
  }
  function _stopPolling() { if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null } }

  // ── store sync ──────────────────────────────────────────────────────────────--
  // Rebuild when the design (and thus its chain_sim_projects) changes, unless a rename
  // input is focused. Keep the active project + local queue if still present.
  store.subscribeSlice('design', () => {
    if (document.activeElement === renameEl) return
    const projects = _projects()
    if (_activeId && projects.some((p) => p.id === _activeId)) {
      // Refresh dropdown labels but keep local stage edits authoritative.
      const cur = selectEl.value
      selectEl.replaceChildren()
      for (const p of projects) selectEl.appendChild(_el('option', { value: p.id, text: p.name }))
      selectEl.value = _activeId || cur
    } else {
      _rebuildSelect()
    }
  })

  _rebuildSelect()

  return {
    isEnabled: () => _enabled,
    enqueue,
    refresh: _rebuildSelect,
  }
}
