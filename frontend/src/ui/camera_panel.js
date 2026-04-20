/**
 * Camera Poses panel — sidebar list of saved camera viewpoints.
 *
 * Each pose stores position/target/up/fov/orbitMode so the camera can be
 * restored exactly.  Poses persist inside the .nadoc file.
 *
 * @param {object} store
 * @param {object} opts
 * @param {function(): object} opts.captureCurrentCamera  — returns current camera state
 * @param {function(object): Promise} opts.animateCameraTo — animates camera to a pose
 * @param {object} opts.api                               — API module
 */
export function initCameraPanel(store, { captureCurrentCamera, animateCameraTo, api }) {
  const listEl   = document.getElementById('camera-pose-list')
  const captureBtn = document.getElementById('camera-pose-capture-btn')
  const heading  = document.getElementById('camera-panel-heading')
  const arrow    = document.getElementById('camera-panel-arrow')
  const body     = document.getElementById('camera-panel-body')
  if (!listEl || !captureBtn || !heading) return

  let _collapsed = false

  // ── Collapse / expand ─────────────────────────────────────────────────────
  heading.addEventListener('click', () => {
    _collapsed = !_collapsed
    body.style.display = _collapsed ? 'none' : ''
    arrow.textContent  = _collapsed ? '▶' : '▼'
  })

  // ── Capture current view ──────────────────────────────────────────────────
  captureBtn.addEventListener('click', async () => {
    const { currentDesign } = store.getState()
    if (!currentDesign) return
    const n = (currentDesign.camera_poses?.length ?? 0) + 1
    const camState = captureCurrentCamera()
    await api.createCameraPose(`Pose ${n}`, camState)
  })

  // ── Rebuild list when design changes ─────────────────────────────────────
  store.subscribeSlice('design', (n, p) => {
    if (n.currentDesign === p.currentDesign) return
    if (!_collapsed) _rebuild(n.currentDesign?.camera_poses ?? [])
  })

  // Drag state for reorder
  let _dragId   = null
  let _dragOver = null

  function _rebuild(poses) {
    listEl.innerHTML = ''

    if (!poses.length) {
      const empty = document.createElement('div')
      empty.style.cssText = 'color:#484f58;font-size:11px;padding:4px 0'
      empty.textContent = 'No saved poses. Navigate to a view and click Capture.'
      listEl.appendChild(empty)
      return
    }

    for (const pose of poses) {
      const row = _makeRow(pose, poses)
      listEl.appendChild(row)
    }
  }

  const _editStyle  = 'background:#21262d;border:1px solid #30363d;color:#8b949e;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:1px 5px;flex-shrink:0'
  const _saveStyle  = 'background:#162420;border:1px solid #3fb950;color:#3fb950;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:1px 5px;flex-shrink:0'
  const _goStyle    = 'background:#0d2a3d;border:1px solid #1f6feb;color:#58a6ff;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:1px 5px;flex-shrink:0'
  const _updateStyle = 'background:#1f2d0d;border:1px solid #588a1e;color:#8ec550;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:1px 5px;flex-shrink:0'
  const _delStyle   = 'background:#2d1515;border:1px solid #c93c3c;color:#c93c3c;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:1px 5px;flex-shrink:0'

  function _makeRow(pose, allPoses) {
    const row = document.createElement('div')
    row.dataset.poseId = pose.id
    row.style.cssText = [
      'display:flex;align-items:center;gap:5px;padding:5px 6px',
      'border-radius:4px;cursor:default;user-select:none',
      'border:1px solid transparent',
    ].join(';')
    row.style.cursor = 'pointer'
    row.title = 'Click to snap camera to this pose'
    row.addEventListener('mouseenter', () => { row.style.background = '#161b22' })
    row.addEventListener('mouseleave', () => { row.style.background = 'transparent' })
    // Row click → animate camera to pose (buttons stop propagation for their own actions)
    row.addEventListener('click', () => {
      animateCameraTo({ position: pose.position, target: pose.target, up: pose.up, fov: pose.fov, duration: 600 })
    })

    // ── Drag handle ────────────────────────────────────────────────────────
    const handle = document.createElement('span')
    handle.textContent = '⠿'
    handle.title = 'Drag to reorder'
    handle.style.cssText = 'color:#484f58;cursor:grab;font-size:12px;flex-shrink:0;line-height:1'
    handle.draggable = true

    handle.addEventListener('dragstart', e => {
      _dragId = pose.id
      e.dataTransfer.effectAllowed = 'move'
      row.style.opacity = '0.5'
    })
    handle.addEventListener('dragend', () => {
      row.style.opacity = ''
      _dragId   = null
      _dragOver = null
      // Remove all drop indicators
      listEl.querySelectorAll('[data-pose-id]').forEach(r => { r.style.borderTop = ''; r.style.borderBottom = '' })
    })

    row.addEventListener('dragover', e => {
      if (!_dragId || _dragId === pose.id) return
      e.preventDefault()
      e.dataTransfer.dropEffect = 'move'
      const rect  = row.getBoundingClientRect()
      const isTop = (e.clientY - rect.top) < rect.height / 2
      listEl.querySelectorAll('[data-pose-id]').forEach(r => { r.style.borderTop = ''; r.style.borderBottom = '' })
      if (isTop) { row.style.borderTop = '2px solid #58a6ff' }
      else       { row.style.borderBottom = '2px solid #58a6ff' }
      _dragOver = { id: pose.id, before: isTop }
    })

    row.addEventListener('drop', async e => {
      e.preventDefault()
      if (!_dragId || !_dragOver) return
      const { currentDesign } = store.getState()
      const poses = [...(currentDesign?.camera_poses ?? [])]
      const fromIdx = poses.findIndex(p => p.id === _dragId)
      let   toIdx   = poses.findIndex(p => p.id === _dragOver.id)
      if (fromIdx === -1 || toIdx === -1 || fromIdx === toIdx) return
      const [moved] = poses.splice(fromIdx, 1)
      if (!_dragOver.before && toIdx >= fromIdx) toIdx++
      else if (_dragOver.before && toIdx > fromIdx) toIdx--
      poses.splice(_dragOver.before ? toIdx : toIdx + 1, 0, moved)
      await api.reorderCameraPoses(poses.map(p => p.id))
    })

    // ── Name label + inline edit ─────────────────────────────────────────
    const nameSpan = document.createElement('span')
    nameSpan.textContent = pose.name
    nameSpan.style.cssText = 'flex:1;min-width:0;font-size:11px;color:#c9d1d9;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'

    const editBtn = document.createElement('button')
    editBtn.textContent = '✎'
    editBtn.title = 'Rename pose'
    editBtn.style.cssText = _editStyle
    editBtn.addEventListener('pointerenter', () => {
      editBtn.style.background = editBtn.textContent === '✓' ? '#1f3d2a' : '#2d333b'
      editBtn.style.color      = editBtn.textContent === '✓' ? '#57d05a' : '#c9d1d9'
    })
    editBtn.addEventListener('pointerleave', () => {
      editBtn.style.cssText = editBtn.textContent === '✓' ? _saveStyle : _editStyle
    })

    function _enterEdit(e) {
      e.stopPropagation()
      const inp = document.createElement('input')
      inp.type = 'text'
      inp.value = pose.name
      inp.style.cssText = 'flex:1;min-width:0;box-sizing:border-box;' +
        'background:#0d1117;border:1px solid #30363d;border-radius:4px;' +
        'color:#c9d1d9;padding:2px 5px;font-family:monospace;font-size:11px;'
      nameSpan.replaceWith(inp)
      inp.focus(); inp.select()
      editBtn.textContent = '✓'
      editBtn.title = 'Save name'
      editBtn.style.cssText = _saveStyle

      async function _save() {
        const newName = inp.value.trim() || pose.name
        inp.replaceWith(nameSpan)
        nameSpan.textContent = newName
        editBtn.textContent = '✎'
        editBtn.title = 'Rename pose'
        editBtn.style.cssText = _editStyle
        editBtn.onclick = _enterEdit
        if (newName !== pose.name) await api.updateCameraPose(pose.id, { name: newName })
      }
      inp.addEventListener('keydown', e2 => {
        e2.stopPropagation()
        if (e2.key === 'Enter')  { e2.preventDefault(); _save() }
        if (e2.key === 'Escape') {
          inp.replaceWith(nameSpan)
          editBtn.textContent = '✎'; editBtn.title = 'Rename pose'
          editBtn.style.cssText = _editStyle; editBtn.onclick = _enterEdit
        }
      })
      editBtn.onclick = e2 => { e2.stopPropagation(); _save() }
    }
    editBtn.onclick = _enterEdit

    // ── "Go to" button ──────────────────────────────────────────────────
    const goBtn = document.createElement('button')
    goBtn.textContent = '▶'
    goBtn.title = 'Animate camera to this pose'
    goBtn.style.cssText = _goStyle
    goBtn.addEventListener('pointerenter', () => { goBtn.style.background = '#0f3a5c'; goBtn.style.color = '#79bcff' })
    goBtn.addEventListener('pointerleave', () => { goBtn.style.cssText = _goStyle })
    goBtn.addEventListener('click', async e => {
      e.stopPropagation()
      await animateCameraTo({
        position: pose.position,
        target:   pose.target,
        up:       pose.up,
        fov:      pose.fov,
        duration: 600,
      })
    })

    // ── "Update" button (overwrite pose with current camera) ────────────
    const updateBtn = document.createElement('button')
    updateBtn.textContent = '⟳'
    updateBtn.title = 'Overwrite pose with current camera view'
    updateBtn.style.cssText = _updateStyle
    updateBtn.addEventListener('pointerenter', () => { updateBtn.style.background = '#2a3f0e'; updateBtn.style.color = '#aee060' })
    updateBtn.addEventListener('pointerleave', () => { updateBtn.style.cssText = _updateStyle })
    updateBtn.addEventListener('click', async e => {
      e.stopPropagation()
      const camState = captureCurrentCamera()
      await api.updateCameraPose(pose.id, {
        position:  camState.position,
        target:    camState.target,
        up:        camState.up,
        fov:       camState.fov,
        orbitMode: camState.orbitMode,
      })
    })

    // ── Delete button ────────────────────────────────────────────────────
    const delBtn = document.createElement('button')
    delBtn.textContent = '×'
    delBtn.title = 'Delete pose'
    delBtn.style.cssText = _delStyle
    delBtn.addEventListener('pointerenter', () => { delBtn.style.background = '#3d1c1c'; delBtn.style.color = '#ff6b6b' })
    delBtn.addEventListener('pointerleave', () => { delBtn.style.cssText = _delStyle })
    delBtn.addEventListener('click', async e => {
      e.stopPropagation()
      await api.deleteCameraPose(pose.id)
    })

    row.append(handle, nameSpan, goBtn, updateBtn, editBtn, delBtn)
    return row
  }

  // Initial render in case a design is already loaded when this panel mounts
  _rebuild(store.getState().currentDesign?.camera_poses ?? [])

  return {}
}
