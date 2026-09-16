import './section_view_controls.css'

/** Compact controls shared by numeric entry and the canvas plane gizmo. */
export function createSectionViewControls({ document, parent, readPose, writeValue, setMode, flip, reset, setControlsHidden, readPlanes, addPlane, selectPlane, deletePlane, togglePlane }) {
  const panel = document.createElement('fieldset')
  panel.id = 'section-view-controls'
  panel.className = 'section-view-controls'
  panel.hidden = true
  const legend = document.createElement('legend')
  legend.textContent = 'Section planes'
  panel.append(legend)
  const list = document.createElement('div')
  list.className = 'section-view-controls__planes'
  list.setAttribute('role', 'group')
  list.setAttribute('aria-label', 'Section planes')
  const actions = document.createElement('div')
  actions.className = 'section-view-controls__toolbar'
  const add = document.createElement('button')
  add.type = 'button'; add.textContent = '+'; add.id = 'section-add-plane'
  add.setAttribute('aria-label', 'Add section plane')
  add.addEventListener('click', addPlane)
  const remove = document.createElement('button')
  remove.type = 'button'; remove.textContent = 'Delete'; remove.id = 'section-delete-plane'
  remove.setAttribute('aria-label', 'Delete selected plane')
  remove.addEventListener('click', deletePlane)
  actions.append(add, remove)
  panel.append(list, actions)
  let listKey = '', selectedId = null
  const toolbar = document.createElement('div')
  toolbar.className = 'section-view-controls__toolbar'
  const modes = []
  for (const [label, mode] of [['Move', 'translate'], ['Rotate', 'rotate']]) {
    const button = document.createElement('button')
    button.className = 'def-btn'
    button.type = 'button'; button.textContent = label
    button.setAttribute('aria-pressed', String(mode === 'translate'))
    button.addEventListener('click', () => {
      setMode(mode)
      for (const [b, m] of modes) b.setAttribute('aria-pressed', String(m === mode))
    })
    modes.push([button, mode]); toolbar.append(button)
  }
  const flipButton = document.createElement('button')
  flipButton.className = 'def-btn'
  flipButton.type = 'button'; flipButton.textContent = 'Flip'
  flipButton.title = 'Reverse the retained side of the section'
  flipButton.addEventListener('click', flip)
  toolbar.append(flipButton)
  const resetButton = document.createElement('button')
  resetButton.className = 'def-btn'
  resetButton.type = 'button'; resetButton.textContent = 'Reset'
  resetButton.id = 'section-reset-btn'
  resetButton.title = 'Center on the part and reset rotation to 180°, 0°, 0°'
  resetButton.addEventListener('click', () => { reset(); sync(true) })
  toolbar.append(resetButton)
  panel.append(toolbar)
  const inputs = []
  function commit(input, kind, axis, delta = 0) {
    const value = input.value.trim() === '' ? NaN : input.valueAsNumber
    if (Number.isFinite(value)) writeValue(kind, axis, value + delta)
    sync(true)
  }
  for (const [kind, title, unit, step] of [['position', 'Position', 'nm', 2], ['rotation', 'Rotation', '°', 5]]) {
    const heading = document.createElement('div')
    heading.className = 'section-view-controls__heading'
    heading.textContent = `${title} (${unit})`
    panel.append(heading)
    for (const axis of ['x', 'y', 'z']) {
      const row = document.createElement('div')
      row.className = 'section-view-controls__row'
      const input = document.createElement('input')
      input.type = 'number'; input.step = 'any'
      input.id = `section-${kind}-${axis}`
      input.setAttribute('aria-label', `${title} ${axis.toUpperCase()} (${unit})`)
      const label = document.createElement('label')
      label.htmlFor = input.id; label.textContent = axis.toUpperCase()
      const buttons = [-1, 1].map(sign => {
        const b = document.createElement('button')
        b.className = 'def-btn'
        b.type = 'button'; b.textContent = `${sign < 0 ? '−' : '+'}${step}${unit === '°' ? '°' : ''}`
        b.setAttribute('aria-label', `${sign < 0 ? 'Decrease' : 'Increase'} ${title.toLowerCase()} ${axis.toUpperCase()} by ${step} ${unit === '°' ? 'degrees' : 'nm'}`)
        b.addEventListener('click', () => commit(input, kind, axis, sign * step))
        return b
      })
      input.addEventListener('change', () => commit(input, kind, axis))
      input.addEventListener('keydown', event => {
        if (event.key === 'Enter') { event.preventDefault(); commit(input, kind, axis) }
        if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
          event.preventDefault(); commit(input, kind, axis, event.key === 'ArrowUp' ? step : -step)
        }
      })
      row.append(label, buttons[0], input, buttons[1]); panel.append(row)
      inputs.push({ input, kind, axis })
    }
  }
  const hideLabel = document.createElement('label')
  hideLabel.className = 'section-view-controls__hide'
  const hide = document.createElement('input')
  hide.type = 'checkbox'; hide.id = 'section-hide-controls'
  hide.addEventListener('change', () => setControlsHidden(hide.checked))
  hideLabel.append(hide, document.createTextNode('Hide controls'))
  hideLabel.title = 'Hide the canvas gizmo and plane outline; keep the section active'
  panel.append(hideLabel)
  parent.append(panel)
  function sync(force = false) {
    const entries = readPlanes()
    const key = JSON.stringify(entries)
    if (key !== listKey) {
      listKey = key
      const focusedId = list.contains(document.activeElement) ? document.activeElement.id : null
      list.replaceChildren(...entries.map(entry => {
        const row = document.createElement('div')
        row.className = 'section-view-controls__plane'
        const select = document.createElement('button')
        select.id = `section-select-${entry.id}`
        select.type = 'button'; select.textContent = `plane ${entry.id}`
        select.setAttribute('aria-pressed', String(entry.selected))
        select.addEventListener('click', () => selectPlane(entry.id))
        const eye = document.createElement('button')
        eye.id = `section-toggle-${entry.id}`
        eye.type = 'button'
        eye.setAttribute('aria-label', `Toggle plane ${entry.id} visibility`)
        eye.setAttribute('aria-pressed', String(entry.visible))
        eye.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>${entry.visible ? '' : '<path d="m3 3 18 18"/>'}</svg>`
        eye.addEventListener('click', () => togglePlane(entry.id))
        row.append(select, eye)
        return row
      }))
      if (focusedId) document.getElementById(focusedId)?.focus({ preventScroll: true })
      const nextSelectedId = entries.find(entry => entry.selected)?.id
      if (nextSelectedId !== selectedId) {
        selectedId = nextSelectedId
        const row = document.getElementById(`section-select-${selectedId}`)?.parentElement
        if (row) {
          const top = row.offsetTop, bottom = top + row.offsetHeight
          if (top < list.scrollTop) list.scrollTop = top
          else if (bottom > list.scrollTop + list.clientHeight) list.scrollTop = bottom - list.clientHeight
        }
      }
    }
    const hasSelection = entries.some(p => p.selected)
    remove.disabled = !hasSelection
    for (const element of panel.querySelectorAll('.section-view-controls__row button, .section-view-controls__row input')) element.disabled = !hasSelection
    for (const element of toolbar.querySelectorAll('button')) element.disabled = !hasSelection
    const pose = readPose()
    for (const { input, kind, axis } of inputs) {
      if (!force && document.activeElement === input) continue
      const value = String(Number(pose[kind][axis].toFixed(4)))
      if (input.value !== value) input.value = value
    }
  }
  return { panel, sync, setVisible(visible) { panel.hidden = !visible; if (visible) sync(true) }, dispose() { panel.remove() } }
}
