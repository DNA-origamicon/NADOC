/**
 * Animation panel — sidebar UI for building and playing keyframe animations.
 *
 * Lets the user:
 *  - Create / rename / delete DesignAnimations
 *  - Add keyframes (capturing current camera + deform_t)
 *  - Edit per-keyframe timing and deform_t
 *  - Reorder keyframes by drag
 *  - Play / Pause / Stop with a scrub slider
 *  - Export to WebM or GIF
 *
 * @param {object} store
 * @param {object} opts
 * @param {object}   opts.player               — animation player (from initAnimationPlayer)
 * @param {function(): object} opts.captureCurrentCamera
 * @param {object}   opts.api                  — API module
 * @param {function} opts.exportVideo          — from export_video.js
 * @param {object}   opts.renderer             — THREE.WebGLRenderer
 * @param {object}   opts.scene                — THREE.Scene
 * @param {object}   opts.camera               — THREE.PerspectiveCamera
 */
import { openKeyframeTextPopup } from './keyframe_text_popup.js'
import { showOpProgress, hideOpProgress, setOpProgressLabel, setOpProgressFraction } from './op_progress.js'
import { getSectionCollapsed, setSectionCollapsed } from './section_collapse_state.js'
import { filterJobsForPart, makeSpinner, mdChildLabelFor } from './md_jobs_panel.js'
import { jobDisplayName, productionState, relaxIndexMap, relaxRowLabel, runRowLabel } from './oxdna_jobs_panel.js'
import { flattenJobTree } from './job_tree.js'
import { statusBadge, statusKeyFor } from './job_status_symbol.js'
import { initFrameRangeSlider } from './frame_range_slider.js'
import { keyframeTrajSpec, trajectoryJobs } from '../scene/trajectory_keyframes.js'
import { formatJobTime, trajectorySamplingPlan } from '../scene/trajectory_range.js'
import {
  planExportPhases, beginExportSession, endExportSession, activeExportSession,
} from '../scene/export_progress.js'

// Build a one-line label for a feature-log entry as shown in the keyframe
// State dropdown. Mirrors the wording the user sees in the Feature Log tab.
function _featureLogTickLabel(e, idx) {
  let lbl = `F${idx + 1}`
  if (e.feature_type === 'deformation' && e.op_snapshot) {
    const op = e.op_snapshot
    const kind = op.type ? (op.type.charAt(0).toUpperCase() + op.type.slice(1)) : 'Deform'
    lbl += `: ${kind} bp ${op.plane_a_bp}–${op.plane_b_bp}`
  } else if (e.feature_type === 'cluster_op') {
    lbl += ': Cluster transform'
  } else if (e.feature_type === 'overhang_rotation') {
    const ids = e.overhang_ids ?? []
    const lbls = e.labels ?? []
    const detail = ids.length === 1 ? (lbls[0] ? `"${lbls[0]}"` : ids[0]) : `${ids.length} overhangs`
    lbl += `: Orient ${detail}`
  } else if (e.feature_type === 'snapshot') {
    lbl += `: ${e.label || e.op_kind || 'Snapshot'}`
    if (e.evicted) lbl += ' (evicted)'
  } else if (e.feature_type === 'routing-cluster') {
    const n = e.children?.length ?? 0
    lbl += `: Fine routing (${n} step${n === 1 ? '' : 's'})`
  } else if (e.label) {
    lbl += `: ${e.label}`
  }
  return lbl
}

const _SA_MODE_WORD = { unzip: 'Unzip', displacement: 'Toehold displacement' }
const _SA_FORM_WORD = { helical: 'Helical', straight: 'Straight' }

// Human label for a strand-animation keyframe's state, e.g.
// "OH1 (Unzip, Helical) φ=1.00" — one clause per overhang in strand_anim_phi.
// mode/form come from each overhang's saved strand_anim_setup.
function _strandAnimSummary(strandAnimPhi, design) {
  const ohs = design?.overhangs ?? []
  const parts = []
  for (const [ohId, phi] of Object.entries(strandAnimPhi)) {
    const oh = ohs.find(o => o.id === ohId)
    const name = oh?.label ?? ohId
    const s = oh?.strand_anim_setup
    const mode = _SA_MODE_WORD[s?.mode]
    const form = _SA_FORM_WORD[s?.form]
    const desc = (mode || form) ? ` (${[mode, form].filter(Boolean).join(', ')})` : ''
    parts.push(`${name}${desc} φ=${Number(phi).toFixed(2)}`)
  }
  return parts.join(', ')
}

/**
 * Pure: one engine's job list → dropdown entries in the SAME order and with the SAME
 * names the Simulations tab shows — relaxations as "relax N", their derived runs as
 * "Run N [A][H][E]" (oxDNA) / "Production N · seed S" (NAMD), each child right under
 * its parent. The flat list this replaced ran every job through `jobDisplayName`, so a
 * relaxation and all of its production runs rendered as the SAME string (the design-file
 * stem) and only the timestamp told them apart.
 */
function _trajEntriesForEngine(jobs, engine) {
  const relaxNo = relaxIndexMap(jobs)
  const sorted = jobs.slice().sort((a, b) => (b.created_at || 0) - (a.created_at || 0))
  let rootNo = 0
  return flattenJobTree(sorted).map(({ job, depth, index }) => ({
    ...job,
    id: job.job_id,
    engine,
    depth,
    // Roots carry the tab's newest-first [N] position (roots only, as there); a child
    // gets none, exactly as the tab leaves its indexLabel empty.
    listIndex: depth === 0 ? (rootNo += 1) : 0,
    label: depth > 0
      ? (engine === 'namd' ? mdChildLabelFor(job, index) : runRowLabel(job, index))
      : (engine === 'namd' ? (job.design_name || jobDisplayName(job))
                           : relaxRowLabel(job, relaxNo.get(job.job_id))),
  }))
}

/**
 * Pure: oxDNA + MD job lists → one unified list of trajectory-dropdown entries
 * (`{...job, id, engine, depth, label}`), filtered to a part path. BOTH engines key
 * their job id as `job_id` (NOT `id`) — reading `j.id` yields undefined option values,
 * leaving the dropdown unselectable ("no trajectory yet"). Exported for regression testing.
 */
export function normalizeTrajJobs(oxJobs, mdJobs, partPath) {
  const ox = Array.isArray(oxJobs) ? filterJobsForPart(oxJobs, partPath || null, false) : []
  const md = Array.isArray(mdJobs) ? filterJobsForPart(mdJobs, partPath || null, false) : []
  return [..._trajEntriesForEngine(ox, 'oxdna'), ..._trajEntriesForEngine(md, 'namd')]
}

export function initAnimationPanel(store, { player, captureCurrentCamera, api, exportVideo, renderer, scene, camera, pinToFeature, getWorkspacePath, trajectoryKeyframes = null }) {
  const panelEl    = document.getElementById('animation-panel')
  const heading    = document.getElementById('animation-panel-heading')
  const arrow      = document.getElementById('animation-panel-arrow')
  const body       = document.getElementById('animation-panel-body')
  const selectEl      = document.getElementById('animation-select')
  const renameInput   = document.getElementById('animation-rename-input')
  const actionsBtn    = document.getElementById('anim-actions-btn')
  const actionsMenu   = document.getElementById('anim-actions-menu')
  const renameBtn     = document.getElementById('anim-rename-btn')
  const newBtn        = document.getElementById('animation-new-btn')
  const deleteAnimBtn = document.getElementById('animation-delete-btn')
  const kfListEl      = document.getElementById('animation-kf-list')
  const addKfBtn   = document.getElementById('animation-add-kf-btn')
  const addTrajBtn = document.getElementById('animation-add-trajectory-btn')
  const playPauseBtn   = document.getElementById('anim-playpause-btn')
  const skipStartBtn   = document.getElementById('anim-skip-start-btn')
  const skipEndBtn     = document.getElementById('anim-skip-end-btn')
  const loopBtn        = document.getElementById('anim-loop-btn')
  const bounceBtn      = document.getElementById('anim-bounce-btn')
  const disablePosesEl = document.getElementById('anim-disable-poses')
  const scrubEl        = document.getElementById('anim-scrub')
  const timeEl         = document.getElementById('anim-time-display')
  if (!heading || !kfListEl) return

  let _collapsed    = getSectionCollapsed('scene', 'animation-panel', false)
  let _activeAnimId = null   // currently selected animation ID
  let _dragId       = null
  let _dragOver     = null
  let _assemblyMode = false  // true when assembly mode is active

  // Apply persisted collapse state to DOM.
  body.style.display = _collapsed ? 'none' : ''
  if (arrow) arrow.classList.toggle('is-collapsed', _collapsed)

  // ── Part context ──────────────────────────────────────────────────────────────
  let _partMode    = false
  let _partDesign  = null
  let _partPatchFn = null

  // ── Mode-aware helpers ────────────────────────────────────────────────────────────

  function _getAnimations() {
    if (_partMode)     return _partDesign?.animations ?? []
    if (_assemblyMode) return store.getState().currentAssembly?.animations ?? []
    return store.getState().currentDesign?.animations ?? []
  }

  /** Pick the correct API function based on current mode (design/assembly only). */
  function _api(designFn, assemblyFn) {
    return _assemblyMode ? assemblyFn : designFn
  }

  // ── Collapse / expand ────────────────────────────────────────────────────────
  heading.addEventListener('click', () => {
    _collapsed = !_collapsed
    body.style.display = _collapsed ? 'none' : ''
    arrow.classList.toggle('is-collapsed', _collapsed)
    setSectionCollapsed('scene', 'animation-panel', _collapsed)
  })

  // ── Animation selector ───────────────────────────────────────────────────────

  function _rebuildSelect(animations) {
    if (!selectEl) return
    selectEl.innerHTML = ''
    if (!animations?.length) {
      const opt = document.createElement('option')
      opt.textContent = '— No animations —'
      opt.disabled = true
      selectEl.appendChild(opt)
      _activeAnimId = null
      _rebuildKfList([])
      return
    }
    for (const anim of animations) {
      const opt = document.createElement('option')
      opt.value = anim.id
      opt.textContent = anim.name
      selectEl.appendChild(opt)
    }
    // If currently selected ID is still present, keep it; else select first.
    const stillPresent = animations.some(a => a.id === _activeAnimId)
    if (!stillPresent) _activeAnimId = animations[0].id
    selectEl.value = _activeAnimId
    const active = animations.find(a => a.id === _activeAnimId)
    _rebuildKfList(active?.keyframes ?? [])
    _syncFpsLoop(active)
  }

  selectEl?.addEventListener('change', () => {
    _stopPlayback()
    _activeAnimId = selectEl.value
    const anim = _getAnimations().find(a => a.id === _activeAnimId)
    _rebuildKfList(anim?.keyframes ?? [])
    _syncFpsLoop(anim)
  })

  // fps + loop settings (shown below selector)
  const _fpsInput  = document.getElementById('anim-fps')

  function _syncFpsLoop(anim) {
    const loopOn = !!(anim?.loop)
    if (_fpsInput) _fpsInput.value = anim?.fps ?? 30
    if (loopBtn)   loopBtn.classList.toggle('is-active', loopOn)
    player.setLoopMode?.(loopOn)
  }

  _fpsInput?.addEventListener('change', async () => {
    if (!_activeAnimId) return
    if (_partMode) {
      await _partPatchFn(d => {
        const a = d.animations?.find(a => a.id === _activeAnimId)
        if (a) a.fps = parseInt(_fpsInput.value) || 30
      })
    } else {
      await _api(api.updateAnimation, api.updateAssemblyAnimation)(_activeAnimId, { fps: parseInt(_fpsInput.value) || 30 })
    }
  })
  loopBtn?.addEventListener('click', async () => {
    if (!_activeAnimId) return
    const next = !loopBtn.classList.contains('is-active')
    loopBtn.classList.toggle('is-active', next)
    // Update the live player flag synchronously so a toggle made while
    // the animation is playing takes effect at the next boundary —
    // otherwise the player's _animation reference holds the pre-toggle
    // loop value until the API roundtrip lands and the store replaces
    // currentDesign.
    player.setLoopMode?.(next)
    if (_partMode) {
      await _partPatchFn(d => {
        const a = d.animations?.find(a => a.id === _activeAnimId)
        if (a) a.loop = next
      })
    } else {
      await _api(api.updateAnimation, api.updateAssemblyAnimation)(_activeAnimId, { loop: next })
    }
  })

  // ── Actions dropdown (⋯ button) ──────────────────────────────────────────────

  actionsBtn?.addEventListener('click', (e) => {
    e.stopPropagation()
    if (!actionsMenu) return
    actionsMenu.style.display = actionsMenu.style.display === 'none' ? '' : 'none'
  })

  document.addEventListener('click', () => {
    if (actionsMenu) actionsMenu.style.display = 'none'
  })

  actionsMenu?.addEventListener('click', (e) => e.stopPropagation())

  // ── Rename ────────────────────────────────────────────────────────────────────

  function _commitRename() {
    const name = renameInput.value.trim()
    selectEl.style.display = ''
    renameInput.style.display = 'none'
    if (!name || !_activeAnimId) return
    if (_partMode) {
      _partPatchFn(d => {
        const a = d.animations?.find(a => a.id === _activeAnimId)
        if (a) a.name = name
      })
    } else {
      _api(api.updateAnimation, api.updateAssemblyAnimation)(_activeAnimId, { name })
    }
  }

  renameBtn?.addEventListener('click', () => {
    if (!actionsMenu) return
    actionsMenu.style.display = 'none'
    if (!_activeAnimId) return
    const anim = _getAnimations().find(a => a.id === _activeAnimId)
    renameInput.value = anim?.name ?? ''
    selectEl.style.display = 'none'
    renameInput.style.display = ''
    renameInput.focus()
    renameInput.select()
  })

  renameInput?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); _commitRename() }
    if (e.key === 'Escape') { selectEl.style.display = ''; renameInput.style.display = 'none' }
  })

  renameInput?.addEventListener('blur', _commitRename)

  // ── New / Delete animation ────────────────────────────────────────────────────

  newBtn?.addEventListener('click', async () => {
    if (actionsMenu) actionsMenu.style.display = 'none'
    if (_partMode) {
      const n = (_partDesign?.animations?.length ?? 0) + 1
      await _partPatchFn(d => {
        d.animations = [...(d.animations ?? []), {
          id: crypto.randomUUID(), name: `Animation ${n}`,
          keyframes: [], fps: 30, loop: false,
        }]
      })
      return
    }
    const state = store.getState()
    const source = _assemblyMode ? state.currentAssembly : state.currentDesign
    if (!source) return
    const n = (source.animations?.length ?? 0) + 1
    await _api(api.createAnimation, api.createAssemblyAnimation)(`Animation ${n}`)
  })

  deleteAnimBtn?.addEventListener('click', async () => {
    if (actionsMenu) actionsMenu.style.display = 'none'
    if (!_activeAnimId) return
    _stopPlayback()
    if (_partMode) {
      await _partPatchFn(d => {
        d.animations = d.animations?.filter(a => a.id !== _activeAnimId)
      })
    } else {
      await _api(api.deleteAnimation, api.deleteAssemblyAnimation)(_activeAnimId)
    }
  })

  // ── Keyframe list ─────────────────────────────────────────────────────────────

  function _rebuildKfList(keyframes) {
    kfListEl.innerHTML = ''
    // Bind/Unbind pose authoring (design editor only) — shown even with no
    // keyframes so the user can set open/closed angles before building the timeline.
    const posesSection = _makeBindingPosesSection(_bindingsDesign())
    if (posesSection) kfListEl.appendChild(posesSection)
    if (!keyframes?.length) {
      const empty = document.createElement('div')
      empty.style.cssText = 'color:#484f58;font-size:11px;padding:4px 0'
      empty.textContent = 'No keyframes. Navigate to a view and click + Add Keyframe.'
      kfListEl.appendChild(empty)
      return
    }
    keyframes.forEach((kf, i) => {
      kfListEl.appendChild(_makeKfRow(kf, i, keyframes))
    })
  }

  const _delStyle  = 'background:#2d1515;border:1px solid #c93c3c;color:#c93c3c;border-radius:3px;font-size:var(--text-xs);line-height:1.4;cursor:pointer;padding:3px 4px;flex-shrink:0'
  const _editStyle = 'background:#21262d;border:1px solid #30363d;color:#8b949e;border-radius:3px;font-size:var(--text-xs);line-height:1.4;cursor:pointer;padding:3px 4px;flex-shrink:0'
  const _saveStyle = 'background:#162420;border:1px solid #3fb950;color:#3fb950;border-radius:3px;font-size:var(--text-xs);line-height:1.4;cursor:pointer;padding:3px 4px;flex-shrink:0'

  function _truncate(s, n) {
    s = s.replace(/\s+/g, ' ')
    return s.length > n ? s.slice(0, n - 1) + '…' : s
  }

  function _numInput(value, step, min, onChange) {
    const inp = document.createElement('input')
    inp.type = 'number'; inp.step = step; inp.min = min; inp.value = value
    inp.style.cssText = [
      'width:44px;box-sizing:border-box',
      'background:#0d1117;border:1px solid #30363d;border-radius:3px',
      'color:#c9d1d9;padding:2px 3px;font-family:var(--font-ui);font-size:var(--text-xs)',
    ].join(';')
    inp.addEventListener('keydown', e => { e.stopPropagation(); if (e.key === 'Enter') inp.blur() })
    inp.addEventListener('change', () => onChange(parseFloat(inp.value)))
    return inp
  }

  // ── Overhang bind/unbind authoring (design editor only) ──────────────────────
  // Bindings + the relax/topology machinery live on the active design, so these
  // controls are gated to the default design mode (not assembly / part-context).
  function _bindingsDesign() {
    return (!_partMode && !_assemblyMode) ? store.getState().currentDesign : null
  }

  /** All bind/unbind animation drivers: OverhangBindings (WC) + linkers. */
  function _drivers(design) {
    const bindings = (design?.overhang_bindings ?? []).map(b => ({ ...b, _kind: 'binding' }))
    const linkers  = (design?.overhang_connections ?? []).map(c => ({
      ...c, _kind: 'linker', name: c.name || `Linker ${c.id.slice(0, 4)}`,
    }))
    return [...bindings, ...linkers]
  }

  /** Persist authored open/closed angle for a driver (dispatch by kind). */
  function _patchDisplayPose(driver, patch) {
    return driver._kind === 'linker'
      ? api.patchConnectionDisplayPose(driver.id, patch)
      : api.patchBindingDisplayPose(driver.id, patch)
  }

  /** Smallest cluster (by helix count) that owns an overhang's helix. */
  function _owningClusterId(design, overhangId) {
    const oh = design?.overhangs?.find(o => o.id === overhangId)
    if (!oh) return null
    const cands = (design.cluster_transforms ?? [])
      .map((c, i) => ({ c, i }))
      .filter(({ c }) => (c.helix_ids ?? []).includes(oh.helix_id))
    if (!cands.length) return null
    cands.sort((a, b) => (a.c.helix_ids.length - b.c.helix_ids.length) || (b.i - a.i))
    return cands[0].c.id
  }

  /** Resolve a driver's target joint: stored id, else the single spanning joint. */
  function _autoJointForDriver(design, driver) {
    if (driver.target_joint_id) {
      return design.cluster_joints?.find(j => j.id === driver.target_joint_id) ?? null
    }
    const ca = _owningClusterId(design, driver.overhang_a_id)
    const cb = _owningClusterId(design, driver.overhang_b_id)
    const cands = (design.cluster_joints ?? []).filter(j => j.cluster_id === ca || j.cluster_id === cb)
    return cands.length === 1 ? cands[0] : null
  }

  /** Signed twist angle (deg) of a cluster's current rotation about a joint axis. */
  function _currentJointAngleDeg(design, joint) {
    const ct = design?.cluster_transforms?.find(c => c.id === joint.cluster_id)
    const ax = joint?.axis_direction
    if (!ct || !ax) return null
    const n = Math.hypot(ax[0], ax[1], ax[2]) || 1
    const r = ct.rotation
    const dot = (r[0] * ax[0] + r[1] * ax[1] + r[2] * ax[2]) / n
    let a = 2 * Math.atan2(dot, r[3])
    while (a >  Math.PI) a -= 2 * Math.PI
    while (a < -Math.PI) a += 2 * Math.PI
    return a * 180 / Math.PI
  }

  /** Patch one keyframe's binding φ (null removes it). Design mode only. */
  async function _patchKfBindingState(kf, bindingId, phiOrNull) {
    if (_partMode || _assemblyMode || !_activeAnimId) return
    const cur = { ...(kf.binding_states ?? {}) }
    if (phiOrNull == null) delete cur[bindingId]
    else cur[bindingId] = phiOrNull
    await api.updateKeyframe(_activeAnimId, kf.id, { binding_states: cur })
  }

  // ── Trajectory keyframes (simulation trajectory playback) ────────────────────
  // Per-(job, resolution) metadata cache {nFrames, markers} so re-rendering a row
  // doesn't re-download the (potentially large) trajectory each time the store changes.
  const _trajMetaCache = new Map()

  // Authoring PREVIEW state. It lives at panel scope, not inside the keyframe row, for
  // one reason: the row is rebuilt from scratch on every store change, and a preview that
  // died with its DOM would be torn down by any unrelated edit while you were scrubbing.
  // At most one keyframe previews at a time — it holds a display controller, and two
  // would fight over the model's positions.
  let _previewKfId = null
  let _previewJob  = null
  let _previewFrame = 0   // survives the row rebuild the next store change causes
  // The {engine, scope, stride} the preview was loaded at. Needed to RESUME after a tab
  // trip: frame indices only mean the same instant within one resolution, so re-loading
  // at the module's `lineage` fallback would point the needle at a different frame.
  let _previewSpec = null

  /** Stop playback AND any authoring preview. Every place that used to call
   *  `player.stop()` goes through here: both hold the same display controllers, and
   *  leaving a preview alive after the user switched animation / left the design would
   *  keep a trajectory pinned over a model it no longer belongs to. */
  function _stopPlayback() {
    _stopPreview()
    player.stop()
  }

  /**
   * Depth counter for a keyframe patch THIS PANEL just made, whose result is already on
   * screen. While it is non-zero the keyframe list does not rebuild.
   *
   * Every keyframe save replaces `currentDesign`, and the store subscriber answers that by
   * blowing the whole list away (`kfListEl.innerHTML = ''`) and rebuilding every row from
   * scratch — new widgets, re-fetched job dropdowns, and a trajectory bar that has to
   * re-derive its playhead. Harmless for a one-shot edit; visible as a hard reset when it
   * fires on the release of a drag you are still looking at. The widget already shows the
   * new values, so the rebuild has nothing to contribute.
   *
   * Scoped to the patch itself rather than "while previewing": an unrelated edit (a new
   * keyframe, an undo) must still repaint the list immediately. The store is written
   * synchronously inside the awaited call, so the subscriber always fires while the
   * counter is up.
   */
  let _selfKfPatch = 0

  async function _patchKfNoRebuild(kf, patch) {
    _selfKfPatch++
    try { await _patchKf(kf, patch) } finally { _selfKfPatch-- }
  }

  /** Drop any active preview and put the display back the way it was found. Safe to call
   *  when nothing is previewing. */
  function _stopPreview() {
    if (!_previewKfId) return
    _previewKfId = null
    _previewJob  = null
    _previewSpec = null
    _previewFrame = 0
    trajectoryKeyframes?.release()
  }

  /**
   * Put a surviving preview back on screen after a sidebar trip.
   *
   * Leaving the Animations tab no longer releases the preview (the player only releases
   * holds it took, and `_leaveAnimationsTab` skips its design re-seek while one is live),
   * so for Photo and Simulations the model never moved and this only re-asserts the
   * frame. For Feature Log / Plates the display-tab policy DOES turn displays off — but
   * with `keepCache`, so the trajectory and its frame bakes are still resident and
   * `previewLoad` resolves through `resumeTrajectory` without touching the network.
   *
   * Called on arrival at the Animations tab. Safe and cheap when nothing is previewing.
   */
  async function resumePreview() {
    if (!_previewKfId || !_previewJob || !_previewSpec) return false
    if (!trajectoryKeyframes) return false
    if (!trajectoryKeyframes.isPreviewing()) {
      // The hold was dropped (Feature Log / Plates). Re-take it at the SAME resolution.
      const n = await trajectoryKeyframes.previewLoad(_previewJob, _previewSpec).catch(() => 0)
      if (!n) { _stopPreview(); return false }
    }
    // Something else may have moved the model while we were away, and `show()` no-ops on
    // an unchanged (job, frame) pair — so drop the guard before re-asserting the frame.
    trajectoryKeyframes.invalidate?.()
    trajectoryKeyframes.previewShow(_previewJob, _previewSpec.engine, _previewFrame)
    return true
  }

  /** Patch one keyframe (design or part-context mode; assembly unsupported). */
  async function _patchKf(kf, patch) {
    if (!_activeAnimId) return
    if (_partMode) {
      await _partPatchFn(d => {
        const a = d.animations?.find(a => a.id === _activeAnimId)
        if (!a) return
        const k = a.keyframes?.find(k => k.id === kf.id)
        if (k) Object.assign(k, patch)
      })
    } else {
      await _api(api.updateKeyframe, api.updateAssemblyKeyframe)(_activeAnimId, kf.id, patch)
    }
  }

  /** oxDNA + NAMD jobs for the active design (filtered by workspace path),
   *  normalized to {id, engine, design_source_path, created_at, design_name}. */
  async function _trajJobsForDesign() {
    const path = getWorkspacePath ? getWorkspacePath() : null
    const [ox, md] = await Promise.all([
      api.listOxdnaJobs().catch(() => null),
      api.listMdJobs().catch(() => null),
    ])
    return normalizeTrajJobs(ox, md, path)
  }

  /** Fetch {nFrames, markers} for a job's composite trajectory AT ONE RESOLUTION, via
   *  the lightweight META endpoint (no coordinate download — instant). The cache is keyed
   *  by resolution as well as job, because 'job'/stride=N and the sparse lineage view are
   *  different frame spaces of the same trajectory and their counts differ by orders of
   *  magnitude. Caches only SUCCESSES, so a transient failure can retry on the next
   *  selection instead of sticking on "no trajectory yet". The full frame data is fetched
   *  at preview / play / bake. */
  async function _trajMeta(jobId, spec) {
    if (!jobId) return null
    const key = _specKey(jobId, spec)
    if (_trajMetaCache.has(key)) return _trajMetaCache.get(key)
    const resp = await (spec.engine === 'namd'
      ? api.getMdTrajectoryMeta(jobId, { stride: spec.stride })
      : api.getOxdnaTrajectoryMeta(jobId, spec.scope)).catch(() => null)
    if (!resp?.ready || !(resp.n_frames > 0)) return null   // not cached → retryable
    const meta = { nFrames: resp.n_frames, markers: resp.markers || [] }
    _trajMetaCache.set(key, meta)
    return meta
  }

  const _specKey = (jobId, spec) =>
    `${jobId}|${spec?.engine || 'oxdna'}|${spec?.scope || 'lineage'}|${spec?.stride ?? ''}`

  /** Sync: is this (job, resolution) already in the cache? Lets a row rebuild skip the
   *  loading spinner — saving a range rebuilds the row, and a spinner flashing for one
   *  microtask on every drag release reads as the panel reloading under you. */
  const _trajMetaCached = (jobId, spec) => _trajMetaCache.has(_specKey(jobId, spec))

  /** Frames a job's trajectory has at the resolution a keyframe addresses. Prefers the
   *  LOADED count (authoritative — a job still writing can disagree with its meta), then
   *  the meta cache, so the export check works before anything has been downloaded. */
  function _framesForKeyframe(kf) {
    const loaded = trajectoryKeyframes?.frameCount?.(kf.trajectory_job_id) ?? 0
    if (loaded > 0) return loaded
    return _trajMetaCache.get(_specKey(kf.trajectory_job_id, keyframeTrajSpec(kf)))?.nFrames ?? 0
  }

  /** One-line warning when the chosen export fps cannot show every simulated frame,
   *  or '' when it can. See `trajectorySamplingPlan` for the arithmetic. */
  function _samplingWarning(anim, fps) {
    if (!anim) return ''
    const byId = new Map()
    for (const kf of anim.keyframes ?? []) {
      if (kf?.trajectory_job_id) byId.set(kf.trajectory_job_id, _framesForKeyframe(kf))
    }
    const plan = trajectorySamplingPlan(anim, (j) => byId.get(j) ?? 0, fps)
    const parts = []
    if (!plan.ok && plan.worst) {
      const w = plan.worst
      parts.push(`${fps} fps shows only ${w.shown} of ${w.frames} simulated frames `
               + `(${w.dropped} never drawn) — use ${plan.minFps} fps or lengthen the hold`)
    }
    // The OTHER way frames go missing: a heavy rep (surface / atomistic) snaps to the
    // nearest baked cell, so the bake's size — not the trajectory's — caps how many
    // different shapes the video can contain. Only reported once a bake has run.
    for (const jobId of byId.keys()) {
      const bake = trajectoryKeyframes?.heavyBake?.(jobId)
      if (bake?.capped && bake.total > 0) {
        parts.push(`the surface/atomistic bake holds ${bake.frames} of ${bake.total} `
                 + `frames (memory-limited) — switch to a bead representation for all of them`)
      }
    }
    return parts.length ? `⚠ ${parts.join('. ')}.` : ''
  }

  /**
   * Build the trajectory State controls for a trajectory keyframe:
   *
   *   [ job dropdown ..................................... ]
   *   [ resolution ▾ ] [ ▶ preview ]   frames 1200–8400 / 12000 · @3021
   *   [ ◂──█████████▉──────────────▶ ]        ← ONE bar: start, end, playhead
   *
   * The bar is `ui/frame_range_slider.js`: start and end are grips, the previewed frame
   * is a needle, and all three live on the same axis because they address the same thing.
   *
   * RESOLUTION is the other half of this. A composite frame index only means something
   * relative to how the trajectory was sampled, and the animation path used to hard-wire
   * the sparse whole-lineage view — every job flattened to ~200 frames, no matter how
   * many its production runs actually wrote. The picker exposes what each backend really
   * offers: for oxDNA, this job's own stages at every written frame ('job') against the
   * ancestor chain strided to ~200 ('lineage'); for NAMD, a DCD frame interval. New
   * keyframes default to the full per-job view — that is the thing worth animating.
   *
   * Populated asynchronously; returns the container synchronously.
   */
  function _makeTrajectoryControls(kf) {
    const wrap = document.createElement('div')
    wrap.style.cssText = 'display:flex;flex-direction:column;gap:4px;padding-left:18px'

    // Job dropdown row
    const jobRow = document.createElement('div')
    jobRow.style.cssText = 'display:flex;align-items:center;gap:5px'
    const jobLbl = document.createElement('span')
    jobLbl.textContent = 'Traj'
    jobLbl.title = 'Simulation job whose trajectory this keyframe plays'
    jobLbl.style.cssText = 'font-size:var(--text-xs);color:#484f58;flex-shrink:0'
    const jobSel = document.createElement('select')
    jobSel.style.cssText = [
      'flex:1;min-width:0;box-sizing:border-box',
      'background:#0d1117;border:1px solid #30363d;border-radius:3px',
      'color:#c9d1d9;padding:3px 3px;font-size:var(--text-xs)',
    ].join(';')
    jobSel.addEventListener('keydown', e => e.stopPropagation())
    jobRow.append(jobLbl, jobSel)

    // Resolution row: oxDNA scope dropdown OR NAMD stride box, plus the preview toggle.
    const resRow = document.createElement('div')
    resRow.style.cssText = 'display:flex;align-items:center;gap:5px'
    const scopeSel = document.createElement('select')
    scopeSel.title = 'How much of the trajectory this keyframe addresses'
    scopeSel.style.cssText = [
      'flex:1;min-width:0;box-sizing:border-box',
      'background:#0d1117;border:1px solid #30363d;border-radius:3px',
      'color:#c9d1d9;padding:2px 3px;font-size:var(--text-xs)',
    ].join(';')
    for (const [v, t] of [['job', 'This job · every frame'],
                          ['lineage', 'Whole lineage · ~200 frames']]) {
      const o = document.createElement('option'); o.value = v; o.textContent = t
      scopeSel.appendChild(o)
    }
    scopeSel.addEventListener('keydown', e => e.stopPropagation())

    const strideWrap = document.createElement('div')
    strideWrap.style.cssText = 'flex:1;min-width:0;display:none;align-items:center;gap:4px'
    const strideLbl = document.createElement('span')
    strideLbl.textContent = 'every'
    strideLbl.style.cssText = 'font-size:var(--text-xs);color:#484f58;flex-shrink:0'
    const strideIn = document.createElement('input')
    strideIn.type = 'number'; strideIn.min = '1'; strideIn.step = '1'
    strideIn.title = 'DCD frame interval — 1 loads every frame NAMD wrote'
    strideIn.style.cssText = [
      'width:52px;box-sizing:border-box',
      'background:#0d1117;border:1px solid #30363d;border-radius:3px',
      'color:#c9d1d9;padding:2px 3px;font-size:var(--text-xs)',
    ].join(';')
    strideIn.addEventListener('keydown', e => e.stopPropagation())
    const strideSuffix = document.createElement('span')
    strideSuffix.textContent = 'frames'
    strideSuffix.style.cssText = 'font-size:var(--text-xs);color:#484f58;flex-shrink:0'
    strideWrap.append(strideLbl, strideIn, strideSuffix)

    const previewBtn = document.createElement('button')
    previewBtn.textContent = '▶ Preview'
    previewBtn.title = 'Load this trajectory and scrub it with the bar below'
    previewBtn.style.cssText = _editStyle
    resRow.append(scopeSel, strideWrap, previewBtn)

    // The one bar: start grip, end grip, previewed-frame needle, stage ticks.
    const bar = initFrameRangeSlider({
      // Per pointer move: label only. Saving here PATCHed the keyframe on every pixel and
      // each save re-rendered this row, so the bar was rebuilt mid-drag.
      onRangeChange: ({ start, end }) => { _setLabel(start, end, _nFrames) },
      // Once, on release.
      // Saved on release. `NoRebuild` because the bar you just let go of IS the current
      // state — repainting the row from the store would throw the widget away and take
      // the playhead with it.
      onRangeCommit: async ({ start, end }) => {
        kf.trajectory_frame_start = start
        kf.trajectory_frame_end   = end
        await _patchKfNoRebuild(kf, { trajectory_frame_start: start, trajectory_frame_end: end })
      },
      onPlayhead: (i) => {
        _scrubTo(i)
        _setLabel(bar.getRange().start, bar.getRange().end, _nFrames)
      },
    })

    const rangeLbl = document.createElement('div')
    rangeLbl.style.cssText = 'font-size:var(--text-xs);color:#8b949e;text-align:center;display:flex;align-items:center;justify-content:center;gap:5px;min-height:14px'
    rangeLbl.textContent = '—'

    // Heavy-rep notice: atomistic/surface reps re-build each frame → slower.
    const heavyNote = document.createElement('div')
    heavyNote.textContent = 'Atomistic / surface reps re-build each frame — playback + export are slower.'
    heavyNote.style.cssText = 'font-size:var(--text-xs);color:#6e7681;font-style:italic;line-height:1.3'

    wrap.append(jobRow, resRow, bar.el, rangeLbl, heavyNote)

    let _nFrames = 0

    /** The resolution this row is currently editing, read straight off the keyframe so
     *  the widget and every fetch agree with what playback will do. */
    function _spec() { return keyframeTrajSpec(kf) }

    function _setLabel(s, e, n) {
      if (!n) { rangeLbl.textContent = 'no trajectory yet'; return }
      const head = bar.getPlayhead()
      rangeLbl.textContent = `frames ${s}–${e} / ${n}`
        + (head == null ? '' : ` · showing ${head}`)
    }

    // Spinner + message while the (potentially large) trajectory downloads.
    function _setLoading(text) {
      rangeLbl.innerHTML = ''
      rangeLbl.appendChild(makeSpinner('#c050d0', 10))
      const t = document.createElement('span'); t.textContent = text
      rangeLbl.appendChild(t)
    }

    /** Mirror the keyframe's resolution onto whichever control the engine uses. */
    function _syncResolutionControls() {
      const spec = _spec()
      const isMd = spec.engine === 'namd'
      scopeSel.style.display = isMd ? 'none' : ''
      strideWrap.style.display = isMd ? 'flex' : 'none'
      scopeSel.value = spec.scope
      strideIn.value = spec.stride == null ? '' : String(spec.stride)
      strideIn.placeholder = 'auto'
      const noJob = !kf.trajectory_job_id
      scopeSel.disabled = strideIn.disabled = noJob
      previewBtn.disabled = noJob
    }

    // Fetch + apply trajectory metadata with a loading spinner in between.
    async function _loadMeta() {
      if (!kf.trajectory_job_id) { _nFrames = 0; bar.setFrames(0); bar.setEnabled(false); _setLabel(0, 0, 0); return }
      const spec = _spec()
      if (!_trajMetaCached(kf.trajectory_job_id, spec)) _setLoading('Loading trajectory…')
      await _applyMeta(await _trajMeta(kf.trajectory_job_id, spec))
    }

    // Apply trajectory metadata to the bar (enable + set bounds + values).
    async function _applyMeta(meta) {
      _nFrames = meta?.nFrames ?? 0
      if (!meta || meta.nFrames < 2) {
        bar.setFrames(0)
        bar.setEnabled(false)
        _setLabel(0, 0, _nFrames)
        return
      }
      const n = meta.nFrames
      const s0 = Number.isFinite(kf.trajectory_frame_start) ? Math.max(0, Math.min(n - 1, kf.trajectory_frame_start)) : 0
      const e0 = Number.isFinite(kf.trajectory_frame_end)   ? Math.max(0, Math.min(n - 1, kf.trajectory_frame_end))   : n - 1
      bar.setFrames(n, meta.markers)
      bar.setRange(s0, e0)
      bar.setEnabled(true)
      _setLabel(s0, e0, n)
    }

    // ── Preview ────────────────────────────────────────────────────────────────
    // Dragging the needle scrubs the real model, through the SAME display controller
    // the Simulations tab and playback use — so a job already scrubbed over there costs
    // nothing here, and pressing Play afterwards re-uses this download instead of
    // repeating it. Refused while the animation is playing: the player owns the
    // controller then, and two writers would fight over every frame.
    function _previewing() {
      return _previewKfId === kf.id && _previewJob === kf.trajectory_job_id
    }

    function _scrubTo(i) {
      if (!_previewing() || i == null) return
      _previewFrame = i
      trajectoryKeyframes?.previewShow(kf.trajectory_job_id, _spec().engine, i)
    }

    function _renderPreviewBtn() {
      const on = _previewing()
      previewBtn.textContent = on ? '■ Stop' : '▶ Preview'
      previewBtn.title = on
        ? 'Stop previewing and restore the design'
        : 'Load this trajectory and scrub it with the bar below'
      // On a row rebuilt mid-preview, the panel-scope frame is the truth — the widget
      // is brand new and knows nothing.
      bar.setPlayhead(on ? (bar.getPlayhead() ?? _previewFrame) : null)
    }

    previewBtn.addEventListener('click', async () => {
      if (_previewing()) { _stopPreview(); _renderPreviewBtn(); _setLabel(bar.getRange().start, bar.getRange().end, _nFrames); return }
      if (!kf.trajectory_job_id) return
      if (player?.isPlaying?.()) {
        rangeLbl.textContent = 'stop playback first'
        return
      }
      _stopPreview()
      previewBtn.disabled = true
      _setLoading('Loading trajectory…')
      const spec = _spec()
      const n = await (trajectoryKeyframes?.previewLoad(kf.trajectory_job_id, spec, {
        onProgress: (p) => {
          if (p?.phase === 'frames' && p.total) _setLoading(`Preparing frames ${p.done}/${p.total}…`)
        },
      }) ?? 0)
      previewBtn.disabled = false
      if (!n) { _setLabel(bar.getRange().start, bar.getRange().end, _nFrames); return }
      _previewKfId = kf.id
      _previewJob  = kf.trajectory_job_id
      _previewSpec = spec
      _previewFrame = Math.min(bar.getRange().start, Math.max(0, n - 1))
      // The download is authoritative about the frame count — the meta call and it can
      // disagree while a job is still writing.
      if (n !== _nFrames) { _nFrames = n; bar.setFrames(n); bar.setEnabled(true) }
      _renderPreviewBtn()
      _scrubTo(bar.getPlayhead())
      _setLabel(bar.getRange().start, bar.getRange().end, _nFrames)
    })

    // Async populate: jobs dropdown (with timestamps), then meta for the selected job.
    ;(async () => {
      jobSel.innerHTML = ''
      const loadingOpt = document.createElement('option')
      loadingOpt.value = ''; loadingOpt.textContent = 'Loading jobs…'
      jobSel.appendChild(loadingOpt)
      const jobs = await _trajJobsForDesign()
      jobSel.innerHTML = ''
      const none = document.createElement('option')
      none.value = ''; none.textContent = jobs.length ? '— select job —' : '— no oxDNA / NAMD jobs —'
      jobSel.appendChild(none)
      // Option text mirrors a Simulations-tab row: [position] [engine] status-glyph
      // name · time. A derived run is prefixed "↳" instead of indented, because a
      // <select> collapses leading whitespace.
      jobs.forEach((j) => {
        const o = document.createElement('option')
        const when = formatJobTime(j.created_at)
        const tag = j.engine === 'namd' ? 'MD' : 'oxDNA'
        const key = statusKeyFor(j.engine, j.status, j.engine === 'oxdna' ? productionState(j) : null)
        const sym = statusBadge(key).symbol
        const pos = j.depth ? '↳' : `[${j.listIndex}]`
        o.value = j.id
        o.dataset.engine = j.engine
        o.textContent = `${pos} [${tag}] ${sym} ${j.label}${when ? ` · ${when}` : ''}`
        jobSel.appendChild(o)
      })
      jobSel.value = kf.trajectory_job_id ?? ''
      _syncResolutionControls()
      // _loadMeta FIRST: it sizes the bar. Restoring the playhead before the bar knows
      // its frame count is how a rebuilt row used to lose it.
      await _loadMeta()
      _renderPreviewBtn()
    })()

    jobSel.addEventListener('change', async () => {
      const jobId = jobSel.value || null
      const engine = jobSel.selectedOptions[0]?.dataset.engine || 'oxdna'
      _stopPreview()
      // New job → full span at this engine's fullest resolution, and the saved
      // start/end are meaningless in the new frame space, so clear them.
      const patch = {
        trajectory_job_id: jobId, trajectory_engine: engine,
        trajectory_frame_start: null, trajectory_frame_end: null,
        trajectory_scope:  engine === 'namd' ? null : 'job',
        trajectory_stride: engine === 'namd' ? 1 : null,
      }
      Object.assign(kf, patch)
      await _patchKfNoRebuild(kf, patch)
      _syncResolutionControls()
      _renderPreviewBtn()
      await _loadMeta()
    })

    scopeSel.addEventListener('change', async () => {
      _stopPreview(); _renderPreviewBtn()
      // Frame indices do not survive a resolution change — 4000 of 12 000 is a
      // different instant from 4000 of 200 — so re-open on the full span.
      const patch = { trajectory_scope: scopeSel.value === 'job' ? 'job' : 'lineage',
                      trajectory_frame_start: null, trajectory_frame_end: null }
      Object.assign(kf, patch)
      await _patchKfNoRebuild(kf, patch)
      await _loadMeta()
    })

    strideIn.addEventListener('change', async () => {
      _stopPreview(); _renderPreviewBtn()
      const raw = Math.floor(Number(strideIn.value))
      const stride = raw >= 1 ? raw : null
      strideIn.value = stride == null ? '' : String(stride)
      const patch = { trajectory_stride: stride,
                      trajectory_frame_start: null, trajectory_frame_end: null }
      Object.assign(kf, patch)
      await _patchKfNoRebuild(kf, patch)
      await _loadMeta()
    })

    return wrap
  }

  /** One-time "Bind/Unbind poses" section: authored open/closed hinge angles. */
  function _makeBindingPosesSection(design) {
    const drivers = _drivers(design)
    if (!drivers.length) return null
    const wrap = document.createElement('div')
    wrap.style.cssText = 'margin-bottom:6px;padding:5px 6px;border:1px solid #21262d;border-radius:4px'
    const hdr = document.createElement('div')
    hdr.textContent = 'Bind/Unbind poses'
    hdr.style.cssText = 'font-size:var(--text-xs);color:#8b949e;margin-bottom:4px'
    wrap.appendChild(hdr)

    const tiny = (txt) => {
      const s = document.createElement('span')
      s.textContent = txt
      s.style.cssText = 'font-size:var(--text-xs);color:#484f58;flex-shrink:0'
      return s
    }
    const grabBtn = (txt, title, onClick) => {
      const b = document.createElement('button')
      b.textContent = txt; b.title = title; b.style.cssText = _editStyle
      b.addEventListener('click', onClick)
      return b
    }

    for (const b of drivers) {
      const joint = _autoJointForDriver(design, b)
      const row = document.createElement('div')
      row.style.cssText = 'display:flex;align-items:center;gap:4px;margin-bottom:3px;flex-wrap:wrap'
      const lbl = document.createElement('span')
      lbl.textContent = b.name || 'B'
      lbl.title = b._kind === 'linker' ? 'Linker' : 'Overhang binding'
      lbl.style.cssText = 'font-size:var(--text-xs);color:#c9d1d9;max-width:70px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex-shrink:0'
      if (!joint) {
        const warn = document.createElement('span')
        warn.textContent = '(no spanning joint)'
        warn.style.cssText = 'font-size:var(--text-xs);color:#d29922'
        row.append(lbl, warn); wrap.appendChild(row); continue
      }
      const openVal   = Number.isFinite(b.unbound_angle_deg) ? b.unbound_angle_deg.toFixed(1) : ''
      const closedSeed = Number.isFinite(b.bound_angle_deg) ? b.bound_angle_deg
                        : (Number.isFinite(b.locked_angle_deg) ? b.locked_angle_deg : null)
      const closedVal = closedSeed != null ? closedSeed.toFixed(1) : ''

      const openInp = _numInput(openVal, '1', '-360', async v => {
        await _patchDisplayPose(b, { unbound_angle_deg: v })
      })
      openInp.style.width = '50px'; openInp.title = 'Unbound (open) hinge angle (°)'
      const closedInp = _numInput(closedVal, '1', '-360', async v => {
        await _patchDisplayPose(b, { bound_angle_deg: v })
      })
      closedInp.style.width = '50px'; closedInp.title = 'Bound (closed) hinge angle (°)'

      const grabOpen = grabBtn('⟲', 'Set unbound from current hinge angle', async () => {
        const a = _currentJointAngleDeg(design, joint)
        if (a != null) { openInp.value = a.toFixed(1); await _patchDisplayPose(b, { unbound_angle_deg: a }) }
      })
      const grabClosed = grabBtn('⟲', 'Set bound from current hinge angle', async () => {
        const a = _currentJointAngleDeg(design, joint)
        if (a != null) { closedInp.value = a.toFixed(1); await _patchDisplayPose(b, { bound_angle_deg: a }) }
      })
      row.append(lbl, tiny('open'), openInp, grabOpen, tiny('closed'), closedInp, grabClosed)
      wrap.appendChild(row)
    }
    return wrap
  }

  function _makeKfRow(kf, index, allKfs) {
    const poses = _partMode
      ? (_partDesign?.camera_poses ?? [])
      : (_assemblyMode ? (store.getState().currentAssembly?.camera_poses ?? []) : (store.getState().currentDesign?.camera_poses ?? []))
    const featureLog = _partMode
      ? (_partDesign?.feature_log ?? [])
      : (store.getState().currentDesign?.feature_log ?? [])
    const configurations = _assemblyMode ? (store.getState().currentAssembly?.configurations ?? []) : []

    // Strand-animation keyframe (created from the right-sidebar panel): its
    // "State" is the un/hybridization of one or more overhangs, not a feature-log
    // pin or assembly config. Detected by a non-empty strand_anim_phi map.
    const strandAnimPhi = (kf.strand_anim_phi && Object.keys(kf.strand_anim_phi).length > 0)
      ? kf.strand_anim_phi : null
    const isStrandAnim = !!strandAnimPhi
    // Trajectory keyframe: plays an oxDNA trajectory range. Flagged at creation
    // (is_trajectory) so it renders as a trajectory row even before a job is picked.
    const isTrajectory = !isStrandAnim && (!!kf.is_trajectory || kf.trajectory_job_id != null)

    const row = document.createElement('div')
    row.dataset.kfId = kf.id
    row.style.cssText = [
      'display:flex;flex-direction:column;gap:4px',
      'padding:5px 6px;border-radius:4px',
      // Purple accent marks special keyframes (strand-anim + trajectory).
      (isStrandAnim || isTrajectory)
        ? 'border:1px solid #c050d0;border-left:3px solid #c050d0;margin-bottom:3px'
        : 'border:1px solid #21262d;margin-bottom:3px',
    ].join(';')

    // ── Top row: drag handle + index badge + delete ───────────────────────────
    const topRow = document.createElement('div')
    topRow.style.cssText = 'display:flex;align-items:center;gap:5px'

    // Drag handle
    const handle = document.createElement('span')
    handle.textContent = '⠿'
    handle.title = 'Drag to reorder'
    handle.style.cssText = 'color:#484f58;cursor:grab;font-size:11px;flex-shrink:0'
    handle.draggable = true
    handle.addEventListener('dragstart', e => {
      _dragId = kf.id; e.dataTransfer.effectAllowed = 'move'; row.style.opacity = '0.5'
    })
    handle.addEventListener('dragend', () => {
      row.style.opacity = ''
      _dragId = _dragOver = null
      kfListEl.querySelectorAll('[data-kf-id]').forEach(r => { r.style.borderTop = ''; r.style.borderBottom = '' })
    })
    row.addEventListener('dragover', e => {
      if (!_dragId || _dragId === kf.id) return
      e.preventDefault(); e.dataTransfer.dropEffect = 'move'
      const rect = row.getBoundingClientRect()
      const isTop = (e.clientY - rect.top) < rect.height / 2
      kfListEl.querySelectorAll('[data-kf-id]').forEach(r => { r.style.borderTop = ''; r.style.borderBottom = '' })
      if (isTop) row.style.borderTop = '2px solid #58a6ff'
      else       row.style.borderBottom = '2px solid #58a6ff'
      _dragOver = { id: kf.id, before: isTop }
    })
    row.addEventListener('drop', async e => {
      e.preventDefault()
      if (!_dragId || !_dragOver || !_activeAnimId) return
      const anim = _getAnimations().find(a => a.id === _activeAnimId)
      if (!anim) return
      const kfs = [...anim.keyframes]
      const from = kfs.findIndex(k => k.id === _dragId)
      let   to   = kfs.findIndex(k => k.id === _dragOver.id)
      if (from === -1 || to === -1 || from === to) return
      const [moved] = kfs.splice(from, 1)
      if (!_dragOver.before && to >= from) to++
      else if (_dragOver.before && to > from) to--
      kfs.splice(_dragOver.before ? to : to + 1, 0, moved)
      if (_partMode) {
        await _partPatchFn(d => {
          const a = d.animations?.find(a => a.id === _activeAnimId)
          if (a) a.keyframes = kfs
        })
      } else {
        await _api(api.reorderKeyframes, api.reorderAssemblyKeyframes)(_activeAnimId, kfs.map(k => k.id))
      }
    })

    // Index badge
    const badge = document.createElement('span')
    badge.textContent = `${index + 1}`
    badge.style.cssText = 'font-size:var(--text-xs);color:#484f58;flex-shrink:0;width:12px;text-align:right'

    // Spacer
    const spacer = document.createElement('span')
    spacer.style.cssText = 'flex:1'

    // Text button
    const hasText = !!(kf.text && kf.text.trim())
    const textBtnStyle = hasText
      ? 'background:#1a2942;border:1px solid #1f6feb;color:#58a6ff;border-radius:3px;font-size:var(--text-xs);line-height:1.4;cursor:pointer;padding:3px 6px;flex-shrink:0'
      : _editStyle + ';padding:3px 6px'
    const textBtn = document.createElement('button')
    textBtn.textContent = hasText ? `T: ${_truncate(kf.text, 12)}` : 'T'
    textBtn.title = hasText ? 'Edit keyframe text' : 'Add keyframe text'
    textBtn.style.cssText = textBtnStyle
    textBtn.addEventListener('click', async e => {
      e.stopPropagation()
      if (!_activeAnimId) return
      const patch = await openKeyframeTextPopup({
        text:              kf.text ?? '',
        text_font_family:  kf.text_font_family ?? 'sans-serif',
        text_font_size_px: kf.text_font_size_px ?? 24,
        text_color:        kf.text_color ?? '#ffffff',
        text_bold:         !!kf.text_bold,
        text_italic:       !!kf.text_italic,
        text_align:        kf.text_align ?? 'center',
      })
      if (patch == null) return
      if (_partMode) {
        await _partPatchFn(d => {
          const a = d.animations?.find(a => a.id === _activeAnimId)
          if (!a) return
          const k = a.keyframes?.find(k => k.id === kf.id)
          if (k) Object.assign(k, patch)
        })
      } else {
        await _api(api.updateKeyframe, api.updateAssemblyKeyframe)(_activeAnimId, kf.id, patch)
      }
    })

    // Delete button
    const delBtn = document.createElement('button')
    delBtn.textContent = '×'; delBtn.title = 'Delete keyframe'
    delBtn.style.cssText = _delStyle
    delBtn.addEventListener('pointerenter', () => { delBtn.style.background = '#3d1c1c'; delBtn.style.color = '#ff6b6b' })
    delBtn.addEventListener('pointerleave', () => { delBtn.style.cssText = _delStyle })
    delBtn.addEventListener('click', async e => {
      e.stopPropagation()
      if (!_activeAnimId) return
      if (_partMode) {
        await _partPatchFn(d => {
          const a = d.animations?.find(a => a.id === _activeAnimId)
          if (a) a.keyframes = a.keyframes?.filter(k => k.id !== kf.id)
        })
      } else {
        await _api(api.deleteKeyframe, api.deleteAssemblyKeyframe)(_activeAnimId, kf.id)
      }
    })

    // Joints badge — shown in assembly mode when keyframe has joint_values
    const jointCount = Object.keys(kf.joint_values ?? {}).length
    let saBadge = null
    if (isStrandAnim) {
      saBadge = document.createElement('span')
      saBadge.textContent = 'Strand'
      saBadge.title = 'Strand-animation keyframe (un/hybridization φ)'
      saBadge.style.cssText = 'font-size:var(--text-xs);color:#c050d0;background:#1a0a1f;border:1px solid #c050d0;border-radius:3px;padding:0 3px;flex-shrink:0'
    }
    let trajBadge = null
    if (isTrajectory) {
      trajBadge = document.createElement('span')
      trajBadge.textContent = 'Trajectory'
      trajBadge.title = 'Trajectory keyframe (plays an oxDNA trajectory range)'
      trajBadge.style.cssText = 'font-size:var(--text-xs);color:#c050d0;background:#1a0a1f;border:1px solid #c050d0;border-radius:3px;padding:0 3px;flex-shrink:0'
    }
    if (_assemblyMode && jointCount > 0) {
      const jBadge = document.createElement('span')
      jBadge.textContent = `Joints: ${jointCount}`
      jBadge.style.cssText = 'font-size:var(--text-xs);color:#ff8c00;background:#1a1200;border:1px solid #ff8c00;border-radius:3px;padding:0 3px;flex-shrink:0'
      topRow.append(handle, badge, spacer, jBadge, textBtn, delBtn)
    } else if (saBadge) {
      topRow.append(handle, badge, spacer, saBadge, textBtn, delBtn)
    } else if (trajBadge) {
      topRow.append(handle, badge, spacer, trajBadge, textBtn, delBtn)
    } else {
      topRow.append(handle, badge, spacer, textBtn, delBtn)
    }

    // ── Camera pose selector ──────────────────────────────────────────────────
    const poseRow = document.createElement('div')
    poseRow.style.cssText = 'display:flex;align-items:center;gap:5px;padding-left:18px'

    const poseLbl = document.createElement('span')
    poseLbl.textContent = 'Pose'
    poseLbl.style.cssText = 'font-size:var(--text-xs);color:#484f58;flex-shrink:0'

    const poseSelect = document.createElement('select')
    poseSelect.style.cssText = [
      'flex:1;min-width:0;box-sizing:border-box',
      'background:#0d1117;border:1px solid #30363d;border-radius:3px',
      'color:#c9d1d9;padding:3px 3px;font-size:var(--text-xs)',
    ].join(';')

    // Build options: blank "none" + all saved poses + spin (centroid orbit)
    const SPIN_VALUE = '__spin__'
    const noneOpt = document.createElement('option')
    noneOpt.value = ''; noneOpt.textContent = '— no camera move —'
    poseSelect.appendChild(noneOpt)
    for (const p of poses) {
      const opt = document.createElement('option')
      opt.value = p.id; opt.textContent = p.name
      poseSelect.appendChild(opt)
    }
    const spinOpt = document.createElement('option')
    spinOpt.value = SPIN_VALUE; spinOpt.textContent = 'Spin (model centroid)'
    poseSelect.appendChild(spinOpt)
    const _isSpin = (k) => k.spin_axis != null
    poseSelect.value = _isSpin(kf) ? SPIN_VALUE : (kf.camera_pose_id ?? '')

    // ── Spin sub-controls (axis + rotations) — visible only when Spin chosen ─
    const spinRow = document.createElement('div')
    spinRow.style.cssText = 'display:flex;align-items:center;gap:5px;padding-left:18px'
    spinRow.style.display = _isSpin(kf) ? 'flex' : 'none'

    const spinAxisLbl = document.createElement('span')
    spinAxisLbl.textContent = 'Axis'
    spinAxisLbl.style.cssText = 'font-size:var(--text-xs);color:#484f58;flex-shrink:0'

    const axisSel = document.createElement('select')
    axisSel.style.cssText = poseSelect.style.cssText
    for (const a of ['x', 'y', 'z']) {
      const o = document.createElement('option')
      o.value = a; o.textContent = a.toUpperCase()
      axisSel.appendChild(o)
    }
    axisSel.value = kf.spin_axis ?? 'z'
    axisSel.addEventListener('keydown', e => e.stopPropagation())
    axisSel.addEventListener('change', async () => {
      const patch = { spin_axis: axisSel.value }
      if (_partMode) {
        await _partPatchFn(d => {
          const a = d.animations?.find(a => a.id === _activeAnimId)
          if (!a) return
          const k = a.keyframes?.find(k => k.id === kf.id)
          if (k) Object.assign(k, patch)
        })
      } else {
        await _api(api.updateKeyframe, api.updateAssemblyKeyframe)(_activeAnimId, kf.id, patch)
      }
    })

    const spinRotLbl = document.createElement('span')
    spinRotLbl.textContent = 'Rot'
    spinRotLbl.style.cssText = 'font-size:var(--text-xs);color:#484f58;flex-shrink:0'

    const rotsInp = _numInput(
      String(kf.spin_rotations ?? 1.0),
      '0.25',
      null,
      async v => {
        const val = Number.isFinite(v) ? v : 0
        const patch = { spin_rotations: val }
        if (_partMode) {
          await _partPatchFn(d => {
            const a = d.animations?.find(a => a.id === _activeAnimId)
            if (!a) return
            const k = a.keyframes?.find(k => k.id === kf.id)
            if (k) Object.assign(k, patch)
          })
        } else {
          await _api(api.updateKeyframe, api.updateAssemblyKeyframe)(_activeAnimId, kf.id, patch)
        }
      },
    )
    rotsInp.title = 'Number of full rotations across this keyframe (decimals OK; negative = reverse direction)'

    const invertWrap = document.createElement('label')
    invertWrap.style.cssText = 'display:flex;align-items:center;gap:3px;font-size:var(--text-xs);color:#8b949e;flex-shrink:0;cursor:pointer'
    invertWrap.title = 'Reverse the rotation direction about the chosen axis.'
    const invertChk = document.createElement('input')
    invertChk.type = 'checkbox'
    invertChk.checked = !!kf.spin_invert
    invertChk.style.cssText = 'margin:0;cursor:pointer'
    invertChk.addEventListener('keydown', e => e.stopPropagation())
    invertChk.addEventListener('change', async () => {
      const patch = { spin_invert: invertChk.checked }
      if (_partMode) {
        await _partPatchFn(d => {
          const a = d.animations?.find(a => a.id === _activeAnimId)
          if (!a) return
          const k = a.keyframes?.find(k => k.id === kf.id)
          if (k) Object.assign(k, patch)
        })
      } else {
        await _api(api.updateKeyframe, api.updateAssemblyKeyframe)(_activeAnimId, kf.id, patch)
      }
    })
    const invertLbl = document.createElement('span')
    invertLbl.textContent = 'Invert'
    invertWrap.append(invertChk, invertLbl)

    spinRow.append(spinAxisLbl, axisSel, spinRotLbl, rotsInp, invertWrap)

    poseSelect.addEventListener('keydown', e => e.stopPropagation())
    poseSelect.addEventListener('change', async () => {
      const val = poseSelect.value
      let patch
      if (val === SPIN_VALUE) {
        // Enable spin: clear camera_pose_id, default axis/rotations if blank.
        const newAxis = kf.spin_axis ?? 'z'
        const newRots = (kf.spin_rotations && kf.spin_rotations !== 0) ? kf.spin_rotations : 1.0
        patch = { camera_pose_id: null, spin_axis: newAxis, spin_rotations: newRots }
        axisSel.value = newAxis
        rotsInp.value = String(newRots)
        spinRow.style.display = 'flex'
      } else {
        // Disable spin and either clear (val='') or set a saved pose id.
        patch = { camera_pose_id: val || null, spin_axis: null, spin_rotations: 0 }
        spinRow.style.display = 'none'
      }
      if (_partMode) {
        await _partPatchFn(d => {
          const a = d.animations?.find(a => a.id === _activeAnimId)
          if (!a) return
          const k = a.keyframes?.find(k => k.id === kf.id)
          if (k) Object.assign(k, patch)
        })
      } else {
        await _api(api.updateKeyframe, api.updateAssemblyKeyframe)(_activeAnimId, kf.id, patch)
      }
    })

    poseRow.append(poseLbl, poseSelect)

    // ── State / configuration row ───────────────────────────────────────────
    // Design mode: "Pin to feature" button — opens the feature-log panel in
    // pick mode (avoids the old flat <select> that overflowed for designs with
    // 50+ features). Assembly mode keeps the <select> since configurations
    // form a smaller, named set.
    const cfgRow = document.createElement('div')
    cfgRow.style.cssText = 'display:flex;align-items:center;gap:5px;padding-left:18px'

    const cfgLbl = document.createElement('span')
    cfgLbl.textContent = 'State'
    cfgLbl.style.cssText = 'font-size:var(--text-xs);color:#484f58;flex-shrink:0'
    cfgRow.appendChild(cfgLbl)

    if (isTrajectory) {
      // Trajectory job picker + frame-range slider replaces the State selector.
      cfgRow.style.cssText = 'display:flex;flex-direction:column;gap:4px;align-items:stretch'
      cfgLbl.style.cssText = 'font-size:var(--text-xs);color:#c050d0;flex-shrink:0'
      cfgRow.appendChild(_makeTrajectoryControls(kf))
    } else if (isStrandAnim) {
      // Read-only summary in place of the feature-log/config selector.
      const saState = document.createElement('span')
      saState.textContent = _strandAnimSummary(strandAnimPhi, store.getState().currentDesign)
      saState.title = 'Edit in the right-sidebar Strand Animation panel (settings + φ), then “Update last”.'
      saState.style.cssText = 'flex:1;min-width:0;font-size:var(--text-xs);color:#c050d0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'
      cfgRow.appendChild(saState)
    } else if (_assemblyMode) {
      const cfgSelect = document.createElement('select')
      cfgSelect.style.cssText = [
        'flex:1;min-width:0;box-sizing:border-box',
        'background:#0d1117;border:1px solid #30363d;border-radius:3px',
        'color:#c9d1d9;padding:3px 3px;font-size:var(--text-xs)',
      ].join(';')
      const _addOpt = (val, label) => {
        const opt = document.createElement('option')
        opt.value = String(val); opt.textContent = label
        cfgSelect.appendChild(opt)
      }
      _addOpt('', '— no state change —')
      for (const cfg of configurations) {
        _addOpt(cfg.id, cfg.name ?? 'Configuration')
      }
      cfgSelect.value = kf.configuration_id ?? ''
      cfgSelect.addEventListener('keydown', e => e.stopPropagation())
      cfgSelect.addEventListener('change', async () => {
        const raw = cfgSelect.value
        await api.updateAssemblyKeyframe(_activeAnimId, kf.id, { configuration_id: raw || null })
      })
      cfgRow.appendChild(cfgSelect)
    } else {
      // Plain <select> over the top-level feature-log entries. Replaces the
      // earlier "pick from the Feature Log tab" flow — picking inline avoids
      // a tab switch and is easier to test. Children of routing-cluster
      // entries are intentionally NOT listed (those are minor sub-ops); the
      // dropdown shows only top-level "ticks".
      async function _persistPin(newIdx) {
        if (_partMode) {
          await _partPatchFn(d => {
            const a = d.animations?.find(a => a.id === _activeAnimId)
            if (!a) return
            const k = a.keyframes?.find(k => k.id === kf.id)
            if (k) k.feature_log_index = newIdx
          })
        } else {
          await _api(api.updateKeyframe, api.updateAssemblyKeyframe)(_activeAnimId, kf.id, { feature_log_index: newIdx })
        }
      }

      const cfgSelect = document.createElement('select')
      cfgSelect.style.cssText = [
        'flex:1;min-width:0;box-sizing:border-box',
        'background:#0d1117;border:1px solid #30363d;border-radius:3px',
        'color:#c9d1d9;padding:3px 3px;font-size:var(--text-xs)',
      ].join(';')
      cfgSelect.title = 'Pin this keyframe to a feature-log entry'
      cfgSelect.addEventListener('keydown', e => e.stopPropagation())

      const _addOpt = (val, label) => {
        const opt = document.createElement('option')
        opt.value = String(val); opt.textContent = label
        cfgSelect.appendChild(opt)
      }
      _addOpt('',   '— not pinned —')
      _addOpt('-2', 'F0 — initial')
      _addOpt('-1', 'All features (sequential)')
      for (let i = 0; i < featureLog.length; i++) {
        _addOpt(i, _featureLogTickLabel(featureLog[i], i))
      }

      const cur = kf.feature_log_index
      cfgSelect.value = (cur === null || cur === undefined) ? '' : String(cur)
      // If the saved index points past the current log (entry deleted/reverted),
      // leave the <select> on "— not pinned —" visually but don't auto-persist —
      // the user can pick a fresh target without losing the old pin silently.

      cfgSelect.addEventListener('change', async () => {
        const raw = cfgSelect.value
        const newIdx = raw === '' ? null : parseInt(raw, 10)
        await _persistPin(newIdx)
      })
      cfgRow.appendChild(cfgSelect)
    }

    // ── Timing row: transition + hold ─────────────────────────────────────────
    const timingRow = document.createElement('div')
    timingRow.style.cssText = 'display:flex;align-items:center;gap:6px;padding-left:18px'

    function _lbl(text) {
      const s = document.createElement('span')
      s.textContent = text
      s.style.cssText = 'font-size:var(--text-xs);color:#484f58;flex-shrink:0'
      return s
    }

    const transInp = _numInput(kf.transition_duration_s.toFixed(1), '0.1', '0', async v => {
      if (_partMode) {
        await _partPatchFn(d => {
          const a = d.animations?.find(a => a.id === _activeAnimId)
          if (!a) return
          const k = a.keyframes?.find(k => k.id === kf.id)
          if (k) k.transition_duration_s = Math.max(0, v)
        })
      } else {
        await _api(api.updateKeyframe, api.updateAssemblyKeyframe)(_activeAnimId, kf.id, { transition_duration_s: Math.max(0, v) })
      }
    })
    const holdInp = _numInput(kf.hold_duration_s.toFixed(1), '0.1', '0', async v => {
      if (_partMode) {
        await _partPatchFn(d => {
          const a = d.animations?.find(a => a.id === _activeAnimId)
          if (!a) return
          const k = a.keyframes?.find(k => k.id === kf.id)
          if (k) k.hold_duration_s = Math.max(0, v)
        })
      } else {
        await _api(api.updateKeyframe, api.updateAssemblyKeyframe)(_activeAnimId, kf.id, { hold_duration_s: Math.max(0, v) })
      }
    })

    timingRow.append(_lbl('trans'), transInp, _lbl('hold'), holdInp)

    // ── Drivers sub-row: per-driver reaction coordinate φ ──────────────────────
    // Bound (φ=1) / Unbound (φ=0) / Custom φ for a mid-transition keyframe.
    // A driver is an OverhangBinding (WC pair) or a linker (overhang_connection).
    let bindingsRow = null
    const bindDesign = _bindingsDesign()
    const bindings = (isStrandAnim || isTrajectory) ? [] : _drivers(bindDesign)
    if (bindings.length) {
      bindingsRow = document.createElement('div')
      bindingsRow.style.cssText = 'display:flex;flex-direction:column;gap:3px;padding-left:18px'
      for (const b of bindings) {
        const r = document.createElement('div')
        r.style.cssText = 'display:flex;align-items:center;gap:5px'
        const lbl = document.createElement('span')
        lbl.textContent = b.name || 'B'
        lbl.title = b._kind === 'linker' ? 'Linker' : 'Overhang binding'
        lbl.style.cssText = 'font-size:var(--text-xs);color:#484f58;flex-shrink:0;max-width:64px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'
        const sel = document.createElement('select')
        sel.style.cssText = poseSelect.style.cssText
        for (const [v, txt] of [['', '— ignore —'], ['1', 'Bound (φ=1)'], ['0', 'Unbound (φ=0)'], ['custom', 'Custom φ…']]) {
          const o = document.createElement('option'); o.value = v; o.textContent = txt; sel.appendChild(o)
        }
        const cur = kf.binding_states?.[b.id]
        const phiInp = _numInput(Number.isFinite(cur) ? cur : 0.5, '0.05', '0', async v => {
          await _patchKfBindingState(kf, b.id, Math.max(0, Math.min(1, v)))
        })
        phiInp.max = '1'
        if (cur == null)      { sel.value = '';       phiInp.style.display = 'none' }
        else if (cur === 1)   { sel.value = '1';      phiInp.style.display = 'none' }
        else if (cur === 0)   { sel.value = '0';      phiInp.style.display = 'none' }
        else                  { sel.value = 'custom'; phiInp.style.display = '' }
        sel.addEventListener('keydown', e => e.stopPropagation())
        sel.addEventListener('change', async () => {
          if (sel.value === '')        { phiInp.style.display = 'none'; await _patchKfBindingState(kf, b.id, null) }
          else if (sel.value === '1')  { phiInp.style.display = 'none'; await _patchKfBindingState(kf, b.id, 1) }
          else if (sel.value === '0')  { phiInp.style.display = 'none'; await _patchKfBindingState(kf, b.id, 0) }
          else                         { phiInp.style.display = '';     await _patchKfBindingState(kf, b.id, Number.isFinite(cur) ? cur : 0.5) }
        })
        r.append(lbl, sel, phiInp)
        bindingsRow.appendChild(r)
      }
    }

    row.append(topRow, poseRow, spinRow, cfgRow)
    if (bindingsRow) row.append(bindingsRow)
    row.append(timingRow)
    return row
  }

  // ── Add keyframe ─────────────────────────────────────────────────────────────

  addKfBtn?.addEventListener('click', async () => {
    if (!_activeAnimId) return
    const anim    = _getAnimations().find(a => a.id === _activeAnimId)
    const isFirst = !anim?.keyframes?.length
    const kfData = {
      camera_pose_id:        null,
      configuration_id:      null,
      feature_log_index:     null,
      transition_duration_s: isFirst ? 0.0 : 1.0,
      hold_duration_s:       1.0,
      easing:                'ease-in-out',
    }
    if (_partMode) {
      await _partPatchFn(d => {
        const a = d.animations?.find(a => a.id === _activeAnimId)
        if (a) a.keyframes = [...(a.keyframes ?? []), { id: crypto.randomUUID(), ...kfData }]
      })
    } else {
      await _api(api.createKeyframe, api.createAssemblyKeyframe)(_activeAnimId, kfData)
    }
  })

  // Add a trajectory keyframe (design / part-context only — oxDNA jobs are a
  // design concept). Plays an oxDNA trajectory range; the job + frame range are
  // chosen on the row after creation.
  addTrajBtn?.addEventListener('click', async () => {
    if (!_activeAnimId || _assemblyMode) return
    const anim    = _getAnimations().find(a => a.id === _activeAnimId)
    const isFirst = !anim?.keyframes?.length
    const kfData = {
      camera_pose_id:        null,
      feature_log_index:     null,
      transition_duration_s: isFirst ? 0.0 : 1.0,
      hold_duration_s:       2.0,
      easing:                'linear',
      is_trajectory:         true,
      trajectory_engine:     'oxdna',
      trajectory_job_id:     null,
      // Full per-job resolution by default — every frame the run wrote, not the
      // ~200-frame whole-lineage preview the animation path used to be pinned to.
      trajectory_scope:      'job',
    }
    if (_partMode) {
      await _partPatchFn(d => {
        const a = d.animations?.find(a => a.id === _activeAnimId)
        if (a) a.keyframes = [...(a.keyframes ?? []), { id: crypto.randomUUID(), ...kfData }]
      })
    } else {
      await api.createKeyframe(_activeAnimId, kfData)
    }
  })

  // ── Playback controls ─────────────────────────────────────────────────────────

  function _updateScrub(current, total) {
    if (!scrubEl) return
    scrubEl.max   = total > 0 ? total.toFixed(2) : '0'
    scrubEl.value = current.toFixed(2)
    if (timeEl) timeEl.textContent = `${current.toFixed(1)}s / ${total.toFixed(1)}s`
  }

  function _getActiveAnim() {
    return _getAnimations().find(a => a.id === _activeAnimId) ?? null
  }

  function _syncPlayPauseLabel() {
    if (playPauseBtn) {
      playPauseBtn.textContent = player.isPlaying() ? '⏸' : '▶'
      playPauseBtn.title       = player.isPlaying() ? 'Pause' : 'Play'
    }
  }

  // Snapshot of keyframe-affecting fields used to detect that the user has
  // edited the animation between play sessions. ``resume()`` reuses the
  // schedule + baked geometry from the previous ``play()`` call — without
  // this check, a keyframe added (or modified) after the first play would be
  // ignored because the player would resume against the stale schedule.
  let _lastPlayedKfSig = null
  function _kfSignature(keyframes) {
    return keyframes
      .map(k => [
        k.id,
        k.feature_log_index ?? 'null',
        k.camera_pose_id ?? 'null',
        k.configuration_id ?? 'null',
        k.transition_duration_s ?? 0,
        k.hold_duration_s ?? 0,
        k.easing ?? 'linear',
        k.spin_axis ?? 'null',
        k.spin_rotations ?? 0,
        k.spin_invert ? '1' : '0',
        k.text_overlay?.text ?? '',
        JSON.stringify(k.binding_states ?? {}),
      ].join(':'))
      .join('|')
  }

  playPauseBtn?.addEventListener('click', () => {
    const anim = _getActiveAnim()
    if (!anim?.keyframes?.length) return
    if (player.isPlaying()) {
      player.pause()
    } else {
      const sig = _kfSignature(anim.keyframes)
      const hasSchedule = player.getTotalDuration() > 0
      const atEnd       = hasSchedule && player.getCurrentTime() >= player.getTotalDuration()
      const animDirty   = sig !== _lastPlayedKfSig
      // Force a full re-bake on:
      //   1. First play (no schedule yet)
      //   2. Animation finished and user re-presses play (atEnd)
      //   3. Any keyframe added / removed / edited since last bake (animDirty)
      // Otherwise resume from the paused position.
      if (!hasSchedule || atEnd || animDirty) {
        let playOpts = {}
        if (_assemblyMode) {
          // Collect live joint values for restore-on-stop, then drive patches during playback
          const joints = store.getState().currentAssembly?.joints ?? []
          const liveJointValues = Object.fromEntries(joints.map(j => [j.id, j.current_value]))
          playOpts = {
            liveJointValues,
            onJointUpdate: (jointId, value) => {
              api.patchAssemblyJoint(jointId, { current_value: value, _silent: true })
            },
          }
        }
        _lastPlayedKfSig = sig
        // Playback takes the controllers over; a preview still holding them would fight
        // the player for every frame.
        _stopPreview()
        player.play(anim, playOpts)
      } else {
        player.resume()
      }
    }
  })

  bounceBtn?.addEventListener('click', () => {
    const next = !bounceBtn.classList.contains('is-active')
    bounceBtn.classList.toggle('is-active', next)
    player.setBounce(next)
  })

  // Initialize toggle visuals from current player state (in case the panel
  // is re-init'd after a hot reload).
  if (bounceBtn && player.getBounce?.()) bounceBtn.classList.add('is-active')

  // Skip-to-start: if playing, seek to 0 and keep playing; if paused/stopped,
  // tear down (stop) so memory is freed and the scrub display resets.
  skipStartBtn?.addEventListener('click', () => {
    if (player.isPlaying()) {
      player.seekTo(0)
    } else {
      _stopPlayback()
      _updateScrub(0, player.getTotalDuration())
    }
  })

  // Skip-to-end: snap to the last frame. If no schedule yet, no-op.
  skipEndBtn?.addEventListener('click', () => {
    const total = player.getTotalDuration()
    if (total > 0) player.seekTo(total)
  })

  // Disable poses: when on, _applyAt skips the camera-pose lerp so the user
  // can orbit/zoom freely while topology + clusters keep animating.
  disablePosesEl?.addEventListener('change', () => {
    player.setDisablePoses?.(disablePosesEl.checked)
  })

  let _scrubDragging = false
  scrubEl?.addEventListener('mousedown', () => { _scrubDragging = true })
  scrubEl?.addEventListener('mouseup',   () => { _scrubDragging = false })
  scrubEl?.addEventListener('input', () => {
    if (!_scrubDragging) return
    player.seekTo(parseFloat(scrubEl.value))
  })

  // ── Player event sync ─────────────────────────────────────────────────────────

  const _bakingTrack = document.getElementById('anim-baking-track')
  const _bakingLabel = document.getElementById('anim-baking-label')

  function _showBakingBar(label) {
    if (_bakingTrack) _bakingTrack.style.display = ''
    if (_bakingLabel) { _bakingLabel.style.display = ''; _bakingLabel.textContent = label }
  }
  function _hideBakingBar() {
    if (_bakingTrack) _bakingTrack.style.display = 'none'
    if (_bakingLabel) _bakingLabel.style.display = 'none'
  }

  // Track which centred op-progress sessions we've opened so hideOpProgress
  // is called the right number of times (its ref-counter fights with itself
  // if we lose track).
  let _bakeProgressOpen = false

  // Player calls this via onEvent callback (wired in main.js)
  function onPlayerEvent(evt) {
    // An export (from EITHER tab — this panel's Export button or the Photo tab's
    // Export Video) owns the popup for its whole run. The bake happens inside that
    // run, so its ticks belong to the export's phase bar, not to a second popup:
    // op_progress is ref-counted over ONE shared header and ONE cancel handler, so
    // showing a bake popup on top silently retitles the export and replaces its
    // Cancel with the bake's — which then does nothing for the hours-long part.
    const _exportSession = activeExportSession()
    if (_exportSession && evt.type?.startsWith('baking')) {
      _exportSession.handleBakeEvent(evt)
    }
    if (evt.type === 'baking') {
      // Geometry/atomistic batch fetch in progress — disable play button and show progress bar
      if (playPauseBtn) { playPauseBtn.disabled = true; playPauseBtn.textContent = '…' }
      const prepMsg = evt.hasSlow
        ? 'Building atomistic / surface frames — this can take a while…'
        : 'Preparing frames…'
      _showBakingBar(prepMsg)
      // Centred popup with frame-by-frame progress + Cancel button.
      // Skipped during export — the export session already owns the popup.
      if (!_exportSession) {
        _bakeProgressOpen = true
        showOpProgress('Rendering Animation', prepMsg, {
          onCancel: () => { player.cancelBake?.() },
        })
      }
    } else if (evt.type === 'baking_progress') {
      const { done, total } = evt
      // The panel-local indeterminate strip is all the user has to go on when the
      // popup belongs to an export, so keep its label current either way.
      if (evt.label) _showBakingBar(evt.label)
      if (_bakeProgressOpen) {
        if (total > 0) setOpProgressFraction(done / total)
        // The trajectory phase counts a different thing (frames of a simulation, not
        // feature-log positions) and says so in its own label.
        setOpProgressLabel(null, evt.label || `Rendering frame ${done} of ${total}`)
      }
    } else if (evt.type === 'baking_done') {
      // Batch complete, playback now starting — restore play button to pause label
      if (playPauseBtn) { playPauseBtn.disabled = false; playPauseBtn.textContent = '⏸'; playPauseBtn.title = 'Pause' }
      _hideBakingBar()
      if (_bakeProgressOpen) { _bakeProgressOpen = false; hideOpProgress() }
    } else if (evt.type === 'baking_cancelled') {
      // User clicked Cancel; revert UI to idle state.
      if (playPauseBtn) { playPauseBtn.disabled = false; playPauseBtn.textContent = '▶'; playPauseBtn.title = 'Play' }
      _hideBakingBar()
      if (_bakeProgressOpen) { _bakeProgressOpen = false; hideOpProgress() }
    } else if (evt.type === 'tick') {
      _updateScrub(evt.currentTime, evt.totalDuration)
    } else if (evt.type === 'finished' || evt.type === 'stopped') {
      _hideBakingBar()
      if (_bakeProgressOpen) { _bakeProgressOpen = false; hideOpProgress() }
      _updateScrub(
        evt.type === 'finished' ? player.getTotalDuration() : 0,
        player.getTotalDuration(),
      )
    }
    // Always sync button labels on any player state change (except baking overrides above)
    if (evt.type !== 'baking' && evt.type !== 'baking_done'
        && evt.type !== 'baking_progress' && evt.type !== 'baking_cancelled') {
      _syncPlayPauseLabel()
    }
  }

  // ── Export ────────────────────────────────────────────────────────────────────

  const exportBtn      = document.getElementById('anim-export-btn')
  const exportFormat   = document.getElementById('anim-export-format')
  const exportRes      = document.getElementById('anim-export-res')
  const exportFpsInput = document.getElementById('anim-export-fps')
  const exportProgress = document.getElementById('anim-export-progress')
  const exportStatus   = document.getElementById('anim-export-status')

  /** Live resampling check. The user picks fps to control file size and has no way to
   *  know it also decides how much of the SIMULATION survives into the video — the
   *  trajectory is resampled onto the capture grid, so too low a rate drops frames with
   *  no visible artefact beyond "the motion looks coarser than the run was". */
  function _refreshSamplingNote() {
    if (!exportStatus) return
    const anim = _getActiveAnim()
    const fpsVal = parseInt(exportFpsInput?.value)
    const fps = Number.isFinite(fpsVal) && fpsVal > 0 ? fpsVal : (anim?.fps ?? 30)
    const msg = _samplingWarning(anim, fps)
    // Never stomp a live export's own status line.
    if (activeExportSession()) return
    exportStatus.textContent = msg
    exportStatus.style.display = msg ? '' : 'none'
    exportStatus.style.color = msg ? '#e3b341' : ''
  }
  exportFpsInput?.addEventListener('input',  _refreshSamplingNote)
  exportFpsInput?.addEventListener('change', _refreshSamplingNote)
  selectEl?.addEventListener('change', () => setTimeout(_refreshSamplingNote, 0))

  exportBtn?.addEventListener('click', async () => {
    const anim = _getActiveAnim()
    if (!anim?.keyframes?.length) return
    if (!exportVideo || !renderer || !scene || !camera) return

    const fpsVal = parseInt(exportFpsInput?.value)
    const options = {
      format:     exportFormat?.value ?? 'webm',
      resolution: exportRes?.value    ?? 'current',
      fps:        Number.isFinite(fpsVal) && fpsVal > 0 ? fpsVal : undefined,
    }

    // Loud, once, at the moment it matters: this is the last point before a
    // potentially hours-long render that throws away most of the simulation.
    const samplingWarn = _samplingWarning(anim, options.fps ?? anim.fps ?? 30)
    if (samplingWarn) console.warn('[export]', samplingWarn)

    exportBtn.disabled  = true
    exportBtn.textContent = '…'
    if (exportProgress) { exportProgress.value = 0; exportProgress.style.display = '' }
    if (exportStatus)   { exportStatus.textContent = 'Rendering frames…'; exportStatus.style.display = ''; exportStatus.style.color = '' }

    // Pause live playback while exporting
    if (player.isPlaying()) player.pause()

    // Centred progress popup with Cancel button. The session owns the whole 0→1
    // range: bake phases (geometry / trajectory download / trajectory frames) arrive
    // via onPlayerEvent, capture/encode/save via onPhase below. Cancelling has to
    // abort BOTH the export loop and an in-flight bake — the bake is what runs for
    // the first several minutes, and it is the part users give up on.
    const cancelCtl = new AbortController()
    const session = beginExportSession({
      header: 'Exporting Animation',
      phases: planExportPhases({
        hasTrajectory:  trajectoryJobs(anim).size > 0,
        hasHeavyFrames: player.hasHeavyRep?.() ?? false,
        format:         options.format,
      }),
      onCancel: () => { cancelCtl.abort(); player.cancelBake?.() },
      onStatus: (u) => {
        if (exportProgress) exportProgress.value = u.fraction
        if (exportStatus)   exportStatus.textContent = u.text
      },
    })

    try {
      await exportVideo({
        animation: anim,
        renderer,
        scene,
        camera,
        player,
        options,
        signal: cancelCtl.signal,
        onPhase: (key, info = null) => {
          if (info?.total != null) session.tick(key, info.done, info.total)
          else session.begin(key)
        },
      })
      session.finish()
      if (exportStatus) exportStatus.textContent = 'Done!'
      setTimeout(() => {
        if (exportStatus) { exportStatus.textContent = ''; exportStatus.style.display = 'none' }
        if (exportProgress) exportProgress.style.display = 'none'
      }, 2000)
    } catch (err) {
      if (err?.name === 'AbortError') {
        if (exportStatus) { exportStatus.textContent = 'Cancelled.'; exportStatus.style.display = '' }
      } else {
        console.error('Export failed:', err)
        if (exportStatus) { exportStatus.textContent = `Error: ${err.message}`; exportStatus.style.display = '' }
      }
    } finally {
      endExportSession()
      exportBtn.disabled  = false
      exportBtn.textContent = '⬇ Export'
      if (exportProgress) exportProgress.value = 1
      setTimeout(_refreshSamplingNote, 2100)   // after the "Done!" message clears
    }
  })

  // ── Store subscription ────────────────────────────────────────────────────────

  // While the user is actively editing a keyframe field (e.g. typing trans/hold
  // durations), a design-slice change — typically their OWN async commit landing
  // a moment later — must NOT rebuild the keyframe list. The rebuild discards the
  // focused <input>, dropping focus to <body>, and the next typed digit then
  // escapes to the global number hotkeys (1–6). Defer the rebuild until focus
  // leaves the list, so the box the user is typing in stays alive and focused.
  let _pendingRebuild = false
  const _editingInKfList = () => !!kfListEl && kfListEl.contains(document.activeElement)

  function _rebuildSelectMaybeDefer(animations) {
    if (_editingInKfList()) { _pendingRebuild = true; return }
    _rebuildSelect(animations)
  }

  kfListEl?.addEventListener('focusout', (e) => {
    // Ignore focus moving between inputs within the list — only act when focus
    // actually leaves the list (relatedTarget null or outside).
    if (kfListEl.contains(e.relatedTarget)) return
    if (!_pendingRebuild) return
    _pendingRebuild = false
    _rebuildSelect(_getAnimations())
  })

  store.subscribeSlice('design', (n, p) => {
    if (_assemblyMode || _partMode) return  // other mode has its own data source
    if (n.currentDesign === p.currentDesign) return
    if (_selfKfPatch > 0) return           // our own edit; the row already shows it
    if (!_collapsed) _rebuildSelectMaybeDefer(n.currentDesign?.animations ?? [])
  })

  store.subscribeSlice('assembly', (n, p) => {
    if (!_assemblyMode) return
    if (n.currentAssembly === p.currentAssembly) return
    if (_selfKfPatch > 0) return           // our own edit; the row already shows it
    if (!_collapsed) _rebuildSelectMaybeDefer(n.currentAssembly?.animations ?? [])
  })

  // Initial render
  _rebuildSelect(store.getState().currentDesign?.animations ?? [])

  /** Switch the panel between design-mode and assembly-mode data sources. */
  function setAssemblyMode(active) {
    if (_assemblyMode === active) return
    _assemblyMode = active
    if (active) { _partMode = false; _partDesign = null; _partPatchFn = null }
    // Trajectory keyframes are design-only (oxDNA jobs belong to designs).
    if (addTrajBtn) {
      addTrajBtn.disabled = active
      addTrajBtn.style.opacity = active ? '0.4' : ''
      addTrajBtn.title = active
        ? 'Trajectory keyframes are available in the design editor only'
        : 'Add a keyframe that plays a range of frames from an oxDNA trajectory'
    }
    _stopPlayback()
    _rebuildSelect(_getAnimations())
  }

  function setPartContext(instanceId, design, patchFn) {
    _partMode    = true
    _partDesign  = design
    _partPatchFn = patchFn
    _stopPlayback()
    _rebuildSelect(_getAnimations())
  }

  function clearPartContext() {
    _partMode    = false
    _partDesign  = null
    _partPatchFn = null
    _stopPlayback()
    _rebuildSelect(_getAnimations())
  }

  /**
   * Context for the right-sidebar Strand Animation panel's capture buttons.
   * Design-mode only — the rich strand-anim driver operates on design overhangs.
   */
  function getKeyframeContext() {
    const anim = _getAnimations().find(a => a.id === _activeAnimId)
    const kfs = anim?.keyframes ?? []
    return {
      animId:       _activeAnimId,
      lastKfId:     kfs.length ? kfs[kfs.length - 1].id : null,
      lastKfPhi:    kfs.length ? { ...(kfs[kfs.length - 1].strand_anim_phi ?? {}) } : {},
      isDesignMode: !_partMode && !_assemblyMode,
    }
  }

  return { onPlayerEvent, setAssemblyMode, setPartContext, clearPartContext, getKeyframeContext, resumePreview }
}
