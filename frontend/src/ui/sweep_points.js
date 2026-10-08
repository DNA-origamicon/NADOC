const positionFormat = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2, roundingMode: 'trunc', useGrouping: false })
export const displaySweepPosition = value => Number.isFinite(value) ? positionFormat.format(value).replace(/^-0$/, '0') : ''

/** Shared ordered XYZ editor, used for creation and feature edits. */
export function initSweepPoints(root, onChange, onSelect, getOrientation) {
  root.innerHTML = `<div class="sweep-points" role="listbox" aria-label="Sweep points"></div>
    <button type="button" class="def-btn" aria-label="Add sweep point">+ Add point</button>
    <div class="sweep-coordinates" title="XYZ offsets in nm from the cross-section center. The origin is fixed. Display values are truncated to two decimals; stored coordinates retain full precision.">${['X', 'Y', 'Z'].map(a => `<label>${a}<input type="number" step="1" aria-label="Point ${a} (nm)"></label>`).join('')}</div>
    <label title="Green arrows show direction; amber arrows show the right axis. Disable direction control to restore automatic orientation. Select a point and press Tab on the canvas or point entry to switch between position and free-angle rotation gizmos. VR grips snap to 15°."><input type="checkbox" aria-label="Control point orientation"> Control direction and twist</label>
    <div class="sweep-orientation">${['Tilt X', 'Tilt Y', 'Twist'].map(a => `<label>${a}<input type="number" min="-360" max="360" step="any" aria-label="${a} (degrees)"></label>`).join('')}</div>
`
  const list = root.querySelector('[role=listbox]')
  const inputs = [...root.querySelectorAll('.sweep-coordinates input')]
  const enabled = root.querySelector('[aria-label="Control point orientation"]')
  const angles = [...root.querySelectorAll('.sweep-orientation input')]
  let orientations = [null, null], attached = false
  function orient(index, value, { snap = false } = {}) {
    if (index < 0 || index >= points.length || (index === 0 && attached)) return
    orientations[index] = value == null ? null : value.map(v => Math.max(-360, Math.min(360, snap ? Math.round(v / 15) * 15 : v)))
    render(); onChange?.()
  }
  enabled.addEventListener('change', () => orient(selected, enabled.checked ? getOrientation?.(selected) ?? [0, 0, 0] : null))
  angles.forEach((input, axis) => input.addEventListener('change', () => {
    if (!Number.isFinite(input.valueAsNumber)) { render(); return }
    const value = [...(orientations[selected] ?? [0, 0, 0])]; value[axis] = input.valueAsNumber; orient(selected, value)
  }))
  let points = [[0, 0, 0], [0, 0, 10]], selected = 1
  function render() {
    list.replaceChildren()
    points.forEach((p, index) => {
      const row = document.createElement('div')
      row.className = 'sweep-point-row'
      const choose = document.createElement('button')
      choose.type = 'button'; choose.className = 'btn sweep-point'
      choose.setAttribute('role', 'option'); choose.setAttribute('aria-selected', String(index === selected))
      choose.textContent = `${index === 0 ? 'Origin' : `Point ${index}`}  (${p.map(displaySweepPosition).join(', ')})`
      choose.addEventListener('click', () => select(index))
      row.append(choose)
      if (index > 0) {
        const remove = document.createElement('button')
        remove.type = 'button'; remove.className = 'btn'; remove.textContent = '×'
        remove.setAttribute('aria-label', `Delete point ${index}`)
        remove.addEventListener('click', () => {
          points.splice(index, 1); orientations.splice(index, 1); selected = Math.min(selected, points.length - 1)
          render(); onSelect?.(selected); onChange?.()
        })
        row.append(remove)
      }
      list.append(row)
    })
    enabled.checked = orientations[selected] != null
    enabled.disabled = selected === 0 && attached
    angles.forEach((input, axis) => { input.value = displaySweepPosition(orientations[selected]?.[axis] ?? 0); input.disabled = !enabled.checked || enabled.disabled })
    inputs.forEach((input, axis) => { input.value = displaySweepPosition(points[selected][axis]); input.disabled = selected === 0 })
  }
  inputs.forEach((input, axis) => input.addEventListener('input', () => {
    if (selected === 0) return
    points[selected][axis] = input.valueAsNumber
    // Preserve focus and partially typed decimals while updating the row label.
    list.querySelectorAll('[role=option]')[selected].textContent = `Point ${selected}  (${points[selected].map(displaySweepPosition).join(', ')})`
    onChange?.()
  }))
  inputs.forEach((input, axis) => input.addEventListener('blur', () => { input.value = displaySweepPosition(points[selected][axis]) }))
  root.querySelector('[aria-label="Add sweep point"]').addEventListener('click', () => {
    if (points.length >= 256) return
    const last = points.at(-1), previous = points.at(-2)
    const delta = previous ? last.map((v, i) => v - previous[i]) : [0, 0, 10]
    orientations.push(null)
    points.push(last.map((v, i) => v + delta[i])); selected = points.length - 1
    render(); list.lastElementChild?.scrollIntoView?.({ block: 'nearest' }); onSelect?.(selected); onChange?.()
  })
  function select(index) {
    if (index < 0 || index >= points.length) return
    selected = index; render(); onSelect?.(selected)
    list.children[index]?.scrollIntoView?.({ block: 'nearest' })
  }
  render()
  return {
    getOrientations: () => orientations.map(a => a && [...a]),
    setOrientations(value, fixedOrigin = false) { orientations = value?.map(a => a && [...a]) ?? points.map(() => null); attached = fixedOrigin; render() },
    orient,
    canOrient: index => !(index === 0 && attached),
    getPoints: () => points.map(p => [...p]),
    getSelected: () => selected,
    setPoints(value) { points = value.map(p => [...p]); orientations = points.map(() => null); selected = Math.min(1, points.length - 1); render() },
    select,
    move(index, value) {
      if (index <= 0 || index >= points.length || !value.every(Number.isFinite)) return
      points[index] = [...value]; render(); onChange?.()
    },
  }
}
