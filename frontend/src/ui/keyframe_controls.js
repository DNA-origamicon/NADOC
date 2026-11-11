import './animation_sidebar.css'

export function initKeyframeControls({ player, getAnimation, getAnnotations, getViewVolumes = () => [], getZoomVolumes = () => [], getPlayOptions = () => ({}), stopPreview,
  save, capture, duplicate, onError, window: win = window }) {
  const collapsed = new Set()
  let selected = null, generation = 0, frame = null, starting = false
  let savedDisablePoses = null
  function cancel() {
    generation++; if (frame !== null) win.cancelAnimationFrame(frame); frame = null
    if (savedDisablePoses !== null) player.setDisablePoses?.(savedDisablePoses)
    savedDisablePoses = null
    selected = null
    paintSelection()
  }
  const viewport = win.document.getElementById('canvas-area')
  const deselect = () => { if (selected !== null) { cancel(); player.stop() } }
  viewport?.addEventListener('pointerdown', deselect, true)
  async function show(id, play) {
    cancel()
    const token = generation
    const source = getAnimation()
    if (!source?.keyframes?.some(k => k.id === id)) return
    selected = id
    paintSelection()
    stopPreview()
    const animation = { ...source, loop: false, keyframes: source.keyframes.slice(0, source.keyframes.findIndex(k => k.id === id) + 1).map(k => ({ ...k, hold_duration_s: Math.max(0.001, k.hold_duration_s ?? 0) })) }
    try {
      savedDisablePoses = player.getDisablePoses?.() ?? false
      player.setDisablePoses?.(false)
      starting = true
      const preparation = player.play(animation, { ...getPlayOptions(), holdKeyframeText: true })
      starting = false
      await preparation
      if (token !== generation) return
      player.pause()
      const range = player.getKeyframeRange(id)
      if (!range) return
      // A tiny offset selects this segment rather than the previous inclusive endpoint.
      let time = play ? Math.min(range.end, range.start + 1e-7) : range.end
      player.seekTo(time)
      await player.settleFrame()
      if (!play || token !== generation) return
      let previous = win.performance.now()
      async function tick(now) {
        if (token !== generation) return
        time = Math.min(range.end, time + Math.max(0, now - previous) / 1000)
        try { player.seekTo(time); await player.settleFrame() }
        catch (error) { if (token === generation) { cancel(); onError(error) }; return }
        if (token !== generation) return
        previous = win.performance.now()
        frame = time < range.end ? win.requestAnimationFrame(tick) : null
      }
      frame = win.requestAnimationFrame(tick)
    } catch (error) { starting = false; if (token === generation) { cancel(); onError(error) } }
  }
  function paintSelection() {
    for (const row of win.document.querySelectorAll('.anim-keyframe')) {
      row.classList.toggle('is-selected', row.dataset.kfId === selected)
      row.querySelector('.anim-keyframe-title')?.setAttribute('aria-pressed', String(row.dataset.kfId === selected))
    }
  }
  function decorate(row, kf, index, poses) {
    const doc = row.ownerDocument, header = row.firstElementChild
    row.classList.add('anim-keyframe')
    const collapse = doc.createElement('button')
    collapse.type = 'button'; collapse.title = 'Collapse keyframe'; collapse.className = 'btn btn--sm btn--icon'
    const sync = () => {
      row.classList.toggle('is-collapsed', collapsed.has(kf.id))
      collapse.textContent = collapsed.has(kf.id) ? '▸' : '▾'
      collapse.setAttribute('aria-expanded', String(!collapsed.has(kf.id)))
    }
    collapse.addEventListener('click', () => { collapsed.has(kf.id) ? collapsed.delete(kf.id) : collapsed.add(kf.id); sync() })
    sync(); header.prepend(collapse)
    const title = doc.createElement('button')
    title.type = 'button'; title.className = 'btn btn--sm anim-keyframe-title'
    title.textContent = kf.name || `Keyframe ${index + 1}${kf.camera_pose_id ? ' · ' + (poses.find(p => p.id === kf.camera_pose_id)?.name ?? 'Missing pose') : ''}`
    title.title = 'Select keyframe: show its pose and state'
    title.addEventListener('click', () => { void show(kf.id, false) })
    const spacer = [...header.children].find(element => element.style.flexGrow === '1')
    if (spacer) spacer.replaceWith(title)
    else header.insertBefore(title, header.lastElementChild)
    const preview = doc.createElement('button')
    preview.type = 'button'; preview.textContent = '▶'; preview.title = 'Preview keyframe'; preview.className = 'btn btn--sm btn--icon'
    preview.addEventListener('click', () => { void show(kf.id, true) })
    const deleteButton = header.lastElementChild
    header.insertBefore(preview, deleteButton)
    if (duplicate) {
      const copy = actionButton(doc, 'Duplicate keyframe', () => duplicate(kf))
      copy.className = 'btn btn--sm btn--icon'
      copy.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V4H4v12h4"/></svg>'
      header.insertBefore(copy, deleteButton)
    }
    if (capture) {
      const button = actionButton(doc, 'Capture keyframe', () => capture(kf))
      button.dataset.role = 'capture-keyframe'; button.className = 'btn btn--sm'
      button.style.marginLeft = '18px'
      const poseRow = row.querySelector('[data-role="keyframe-pose"]')?.parentElement
      if (poseRow) row.insertBefore(button, poseRow)
    }
    for (const [field, title, getEntries, noun, sidebar] of [
      ['annotation_ids', 'Annotations', getAnnotations, 'Annotation', 'Annotations'],
      ['view_volume_ids', 'View Volumes', getViewVolumes, 'View Volume', 'Visualization'],
      ['zoom_volume_ids', 'Zoom Volumes', getZoomVolumes, 'Zoom Volume', 'Visualization'],
    ]) row.append(visibilityPicker(doc, kf, field, title, getEntries, noun, sidebar))
    row.classList.toggle('is-selected', selected === kf.id)
    title.setAttribute('aria-pressed', String(selected === kf.id))
  }
  function actionButton(doc, label, action) {
    const button = doc.createElement('button')
    button.type = 'button'; button.textContent = label; button.title = label; button.setAttribute('aria-label', label)
    button.addEventListener('click', async event => {
      event.stopPropagation(); button.disabled = true
      try { await action() } catch (error) { onError(error) }
      finally { button.disabled = false }
    })
    return button
  }
  function visibilityPicker(doc, kf, field, title, getEntries, noun, sidebar) {
    const root = doc.createElement('details'); root.className = 'anim-annotation-picker'; root.dataset.field = field
    const summary = doc.createElement('summary'), choices = doc.createElement('div')
    choices.className = 'choices'
    let selection = kf[field] == null ? null : [...kf[field]]
    const label = () => { summary.textContent = `${title} · ${selection === null ? 'Current visibility' : selection.length ? `${selection.length} selected` : 'None'}` }
    const commit = async next => {
      const old = selection; selection = next; label()
      for (const control of choices.querySelectorAll('input, button')) control.disabled = true
      try { await save(kf, { [field]: next }) }
      catch (error) { selection = old; label(); onError(error) }
      if (root.isConnected) populate()
    }
    function populate() {
      const entries = getEntries()
      choices.replaceChildren()
      const actions = doc.createElement('div'), list = doc.createElement('div')
      actions.className = 'anim-annotation-actions'; list.className = 'anim-annotation-list'
      choices.append(actions, list)
      for (const [text, select] of [['All', () => entries.map(e => e.id)], ['None', () => []]]) {
        const button = doc.createElement('button'); button.type = 'button'; button.textContent = text
        button.className = 'btn btn--sm'
        button.addEventListener('click', () => { void commit(select()) }); actions.append(button)
      }
      for (const [index, entry] of entries.entries()) {
        const row = doc.createElement('label'), input = doc.createElement('input')
        input.type = 'checkbox'; input.checked = selection === null ? entry.visible !== false : selection.includes(entry.id)
        input.addEventListener('change', () => {
          const ids = new Set(selection ?? entries.filter(e => e.visible !== false).map(e => e.id))
          input.checked ? ids.add(entry.id) : ids.delete(entry.id)
          void commit([...ids])
        })
        const name = doc.createElement('span'); name.textContent = entry.name || `${noun} ${index + 1}`
        row.title = name.textContent
        row.append(input, name); list.append(row)
      }
      if (!entries.length) list.append(doc.createTextNode(`No ${title.toLowerCase()} yet. Add them in the ${sidebar} sidebar.`))
    }
    root.addEventListener('toggle', () => { if (root.open) populate() })
    root.addEventListener('keydown', event => event.stopPropagation())
    root.append(summary, choices); label()
    return root
  }
  return { decorate, show, cancel, dispose() { cancel(); viewport?.removeEventListener('pointerdown', deselect, true) },
    onPlayerEvent(event) {
      if ((!starting && ['stopped', 'baking'].includes(event.type)) || ['baking_cancelled', 'baking_error'].includes(event.type)) cancel()
    },
  }
}
