/** Numeric counterparts to the viewport handles, using the normal sidebar controls. */
export function createAnnotationBoxControls({ document, controller, id }) {
  const root = document.createElement('div')
  root.className = 'anno-box-controls'
  const inputs = {}
  for (const [key, label, min, max] of [['width', 'Box width (px)', 32, 10000], ['height', 'Box height (px)', 24, 10000], ['angle', 'Angle (°)', null, null]]) {
    const row = document.createElement('label'); row.className = 'anno-row'; row.textContent = label
    const input = document.createElement('input'); input.type = 'number'; input.step = 'any'
    input.setAttribute('aria-label', label); input.dataset.field = `box-${key}`
    if (min !== null) { input.min = min; input.max = max }
    input.placeholder = key === 'angle' ? '0' : 'Auto'
    row.append(input); root.append(row); inputs[key] = input
    input.addEventListener('change', () => {
      const value = Number(input.value)
      if (!input.value || !Number.isFinite(value) || (min !== null && (value < min || value > max))) { sync(); return }
      const entry = controller.get(id)
      if (key === 'angle') controller.update(id, { rotationDeg: value })
      else controller.update(id, { boxSize: { w: entry.boxSize?.w ?? 280, h: entry.boxSize?.h ?? 100, [key === 'width' ? 'w' : 'h']: value } })
      sync()
    })
    input.addEventListener('blur', sync)
    input.addEventListener('keydown', event => { event.stopPropagation(); if (event.key === 'Enter') input.blur() })
  }
  const reset = document.createElement('button'); reset.type = 'button'; reset.className = 'btn btn--sm'
  reset.textContent = 'Auto-size box'; reset.title = 'Fit the box to its text; keep its angle'
  reset.addEventListener('click', () => { controller.update(id, { boxSize: null }); sync() })
  root.append(reset)
  function sync() {
    const entry = controller.get(id)
    if (!entry) return
    for (const [key, value] of [['width', entry.boxSize?.w ?? ''], ['height', entry.boxSize?.h ?? ''], ['angle', entry.rotationDeg ?? 0]]) {
      if (document.activeElement !== inputs[key]) inputs[key].value = typeof value === 'number' ? String(Math.round(value * 100) / 100) : value
    }
  }
  sync()
  const off = controller.subscribe(event => { if (!event.id || event.id === id) sync() })
  return { root, dispose: off }
}
