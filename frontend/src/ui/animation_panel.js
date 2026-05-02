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
export function initAnimationPanel(store, { player, captureCurrentCamera, api, exportVideo, renderer, scene, camera }) {
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
  const playPauseBtn = document.getElementById('anim-playpause-btn')
  const bounceCheck  = document.getElementById('anim-bounce')
  const stopBtn      = document.getElementById('anim-stop-btn')
  const scrubEl      = document.getElementById('anim-scrub')
  const timeEl       = document.getElementById('anim-time-display')
  if (!heading || !kfListEl) return

  let _collapsed    = false
  let _activeAnimId = null   // currently selected animation ID
  let _dragId       = null
  let _dragOver     = null
  let _assemblyMode = false  // true when assembly mode is active

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
    player.stop()
    _activeAnimId = selectEl.value
    const anim = _getAnimations().find(a => a.id === _activeAnimId)
    _rebuildKfList(anim?.keyframes ?? [])
    _syncFpsLoop(anim)
  })

  // fps + loop settings (shown below selector)
  const _fpsInput  = document.getElementById('anim-fps')
  const _loopCheck = document.getElementById('anim-loop')

  function _syncFpsLoop(anim) {
    if (_fpsInput)  _fpsInput.value   = anim?.fps  ?? 30
    if (_loopCheck) _loopCheck.checked = anim?.loop ?? false
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
  _loopCheck?.addEventListener('change', async () => {
    if (!_activeAnimId) return
    if (_partMode) {
      await _partPatchFn(d => {
        const a = d.animations?.find(a => a.id === _activeAnimId)
        if (a) a.loop = _loopCheck.checked
      })
    } else {
      await _api(api.updateAnimation, api.updateAssemblyAnimation)(_activeAnimId, { loop: _loopCheck.checked })
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
    player.stop()
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

  function _makeKfRow(kf, index, allKfs) {
    const poses = _partMode
      ? (_partDesign?.camera_poses ?? [])
      : (_assemblyMode ? (store.getState().currentAssembly?.camera_poses ?? []) : (store.getState().currentDesign?.camera_poses ?? []))
    const featureLog = _partMode
      ? (_partDesign?.feature_log ?? [])
      : (store.getState().currentDesign?.feature_log ?? [])
    const configurations = _assemblyMode ? (store.getState().currentAssembly?.configurations ?? []) : []

    const row = document.createElement('div')
    row.dataset.kfId = kf.id
    row.style.cssText = [
      'display:flex;flex-direction:column;gap:4px',
      'padding:5px 6px;border-radius:4px',
      'border:1px solid #21262d;margin-bottom:3px',
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
    if (_assemblyMode && jointCount > 0) {
      const jBadge = document.createElement('span')
      jBadge.textContent = `Joints: ${jointCount}`
      jBadge.style.cssText = 'font-size:var(--text-xs);color:#ff8c00;background:#1a1200;border:1px solid #ff8c00;border-radius:3px;padding:0 3px;flex-shrink:0'
      topRow.append(handle, badge, spacer, jBadge, delBtn)
    } else {
      topRow.append(handle, badge, spacer, delBtn)
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

    // Build options: blank "none" + all saved poses
    const noneOpt = document.createElement('option')
    noneOpt.value = ''; noneOpt.textContent = '— no camera move —'
    poseSelect.appendChild(noneOpt)
    for (const p of poses) {
      const opt = document.createElement('option')
      opt.value = p.id; opt.textContent = p.name
      poseSelect.appendChild(opt)
    }
    poseSelect.value = kf.camera_pose_id ?? ''

    poseSelect.addEventListener('keydown', e => e.stopPropagation())
    poseSelect.addEventListener('change', async () => {
      const newPoseId = poseSelect.value || null
      if (_partMode) {
        await _partPatchFn(d => {
          const a = d.animations?.find(a => a.id === _activeAnimId)
          if (!a) return
          const k = a.keyframes?.find(k => k.id === kf.id)
          if (k) k.camera_pose_id = newPoseId
        })
      } else {
        await _api(api.updateKeyframe, api.updateAssemblyKeyframe)(_activeAnimId, kf.id, { camera_pose_id: newPoseId })
      }
    })

    poseRow.append(poseLbl, poseSelect)

    // ── State / configuration selector row ───────────────────────────────────
    // Design mode: feature log. Assembly mode: configuration snapshots.
    const cfgRow = document.createElement('div')
    cfgRow.style.cssText = 'display:flex;align-items:center;gap:5px;padding-left:18px'

    const cfgLbl = document.createElement('span')
    cfgLbl.textContent = 'State'
    cfgLbl.style.cssText = 'font-size:var(--text-xs);color:#484f58;flex-shrink:0'

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
    if (_assemblyMode) {
      for (const cfg of configurations) {
        const opt = document.createElement('option')
        opt.value = cfg.id
        opt.textContent = cfg.name ?? 'Configuration'
        cfgSelect.appendChild(opt)
      }
      cfgSelect.value = kf.configuration_id ?? ''
    } else {
      _addOpt(-2, 'F0 — initial')
      featureLog.forEach((e, i) => {
        let label = `F${i + 1}`
        if (e.feature_type === 'deformation' && e.op_snapshot) {
          const op = e.op_snapshot
          const kind = op.type ? (op.type.charAt(0).toUpperCase() + op.type.slice(1)) : 'Deform'
          label += `: ${kind} bp ${op.plane_a_bp}–${op.plane_b_bp}`
        } else if (e.feature_type === 'cluster_op') {
          label += ': Cluster transform'
        }
        _addOpt(i, label)
      })
      _addOpt(-1, 'All features')
      cfgSelect.value = kf.feature_log_index != null ? String(kf.feature_log_index) : ''
    }

    cfgSelect.addEventListener('keydown', e => e.stopPropagation())
    cfgSelect.addEventListener('change', async () => {
      const raw = cfgSelect.value
      if (_assemblyMode) {
        await api.updateAssemblyKeyframe(_activeAnimId, kf.id, { configuration_id: raw || null })
        return
      }
      const idx = raw === '' ? null : parseInt(raw, 10)
      if (_partMode) {
        await _partPatchFn(d => {
          const a = d.animations?.find(a => a.id === _activeAnimId)
          if (!a) return
          const k = a.keyframes?.find(k => k.id === kf.id)
          if (k) k.feature_log_index = idx
        })
      } else {
        await _api(api.updateKeyframe, api.updateAssemblyKeyframe)(_activeAnimId, kf.id, { feature_log_index: idx })
      }
    })

    cfgRow.append(cfgLbl, cfgSelect)

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

    row.append(topRow, poseRow, cfgRow, timingRow)
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
      playPauseBtn.textContent = player.isPlaying() ? '⏸ Pause' : '▶ Play'
    }
  }

  playPauseBtn?.addEventListener('click', () => {
    const anim = _getActiveAnim()
    if (!anim?.keyframes?.length) return
    if (player.isPlaying()) {
      player.pause()
    } else {
      const hasSchedule = player.getTotalDuration() > 0
      const atEnd = hasSchedule && player.getCurrentTime() >= player.getTotalDuration()
      if (!hasSchedule || atEnd) {
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
        player.play(anim, playOpts)
      } else {
        player.resume()
      }
    }
  })

  bounceCheck?.addEventListener('change', () => {
    player.setBounce(bounceCheck.checked)
  })

  stopBtn?.addEventListener('click', () => {
    player.stop()
    _updateScrub(0, 0)
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

  // Player calls this via onEvent callback (wired in main.js)
  function onPlayerEvent(evt) {
    if (evt.type === 'baking') {
      // Geometry/atomistic batch fetch in progress — disable play button and show progress bar
      if (playPauseBtn) { playPauseBtn.disabled = true; playPauseBtn.textContent = '…' }
      _showBakingBar(evt.hasSlow ? 'Preparing (loading model…)' : 'Preparing…')
    } else if (evt.type === 'baking_done') {
      // Batch complete, playback now starting — restore play button to pause label
      if (playPauseBtn) { playPauseBtn.disabled = false; playPauseBtn.textContent = '⏸ Pause' }
      _hideBakingBar()
    } else if (evt.type === 'tick') {
      _updateScrub(evt.currentTime, evt.totalDuration)
    } else if (evt.type === 'finished' || evt.type === 'stopped') {
      _hideBakingBar()
      _updateScrub(
        evt.type === 'finished' ? player.getTotalDuration() : 0,
        player.getTotalDuration(),
      )
    }
    // Always sync button labels on any player state change (except baking overrides above)
    if (evt.type !== 'baking' && evt.type !== 'baking_done') {
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

    exportBtn.disabled  = true
    exportBtn.textContent = '…'
    if (exportProgress) { exportProgress.value = 0; exportProgress.style.display = '' }
    if (exportStatus)   { exportStatus.textContent = 'Rendering frames…'; exportStatus.style.display = '' }

    // Pause live playback while exporting
    if (player.isPlaying()) player.pause()

    try {
      await exportVideo({
        animation: anim,
        renderer,
        scene,
        camera,
        player,
        options,
        onProgress: p => {
          if (exportProgress) exportProgress.value = p
          if (exportStatus)   exportStatus.textContent = `Rendering… ${Math.round(p * 100)}%`
        },
      })
      if (exportStatus) exportStatus.textContent = 'Done!'
      setTimeout(() => {
        if (exportStatus) { exportStatus.textContent = ''; exportStatus.style.display = 'none' }
        if (exportProgress) exportProgress.style.display = 'none'
      }, 2000)
    } catch (err) {
      console.error('Export failed:', err)
      if (exportStatus) { exportStatus.textContent = `Error: ${err.message}`; exportStatus.style.display = '' }
    } finally {
      exportBtn.disabled  = false
      exportBtn.textContent = '⬇ Export'
      if (exportProgress) exportProgress.value = 1
    }
  })

  // ── Store subscription ────────────────────────────────────────────────────────

  store.subscribeSlice('design', (n, p) => {
    if (_assemblyMode || _partMode) return  // other mode has its own data source
    if (n.currentDesign === p.currentDesign) return
    if (!_collapsed) _rebuildSelect(n.currentDesign?.animations ?? [])
  })

  store.subscribeSlice('assembly', (n, p) => {
    if (!_assemblyMode) return
    if (n.currentAssembly === p.currentAssembly) return
    if (!_collapsed) _rebuildSelect(n.currentAssembly?.animations ?? [])
  })

  // Initial render
  _rebuildSelect(store.getState().currentDesign?.animations ?? [])

  /** Switch the panel between design-mode and assembly-mode data sources. */
  function setAssemblyMode(active) {
    if (_assemblyMode === active) return
    _assemblyMode = active
    if (active) { _partMode = false; _partDesign = null; _partPatchFn = null }
    player.stop()
    _rebuildSelect(_getAnimations())
  }

  function setPartContext(instanceId, design, patchFn) {
    _partMode    = true
    _partDesign  = design
    _partPatchFn = patchFn
    player.stop()
    _rebuildSelect(_getAnimations())
  }

  function clearPartContext() {
    _partMode    = false
    _partDesign  = null
    _partPatchFn = null
    player.stop()
    _rebuildSelect(_getAnimations())
  }

  return { onPlayerEvent, setAssemblyMode, setPartContext, clearPartContext }
}
