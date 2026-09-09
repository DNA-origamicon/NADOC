import './section_view_controls.css'

/** Compact controls shared by numeric entry and the canvas plane gizmo. */
export function createSectionViewControls({ document, parent, readPose, writeValue, setMode, flip, reset, setControlsHidden }) {
  const panel = document.createElement('fieldset')
  panel.id = 'section-view-controls'
  panel.className = 'section-view-controls'
  panel.hidden = true
  const legend = document.createElement('legend')
  legend.textContent = 'Section plane'
  panel.append(legend)
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
    const pose = readPose()
    for (const { input, kind, axis } of inputs) {
      if (!force && document.activeElement === input) continue
      const value = String(Number(pose[kind][axis].toFixed(4)))
      if (input.value !== value) input.value = value
    }
  }
  return { panel, sync, setVisible(visible) { panel.hidden = !visible; if (visible) sync(true) }, dispose() { panel.remove() } }
}
