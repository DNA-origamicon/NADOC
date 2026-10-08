/** Shared ordered XYZ editor, used for creation and feature edits. */
export function initSweepPoints(root, onChange, onSelect) {
  root.innerHTML = `<div class="sweep-points" role="listbox" aria-label="Sweep points"></div>
    <button type="button" class="def-btn" aria-label="Add sweep point">+ Add point</button>
    <div class="sweep-coordinates">${['X', 'Y', 'Z'].map(a => `<label>${a}<input type="number" step="1" aria-label="Point ${a} (nm)"></label>`).join('')}</div>
    <p class="tool-help">XYZ offsets in nm from the cross-section center. Origin is fixed.</p>`
  const list = root.querySelector('[role=listbox]')
  const inputs = [...root.querySelectorAll('input')]
  let points = [[0, 0, 0], [0, 0, 10]], selected = 1
  function render() {
    list.replaceChildren()
    points.forEach((p, index) => {
      const row = document.createElement('div')
      row.className = 'sweep-point-row'
      const choose = document.createElement('button')
      choose.type = 'button'; choose.className = 'btn sweep-point'
      choose.setAttribute('role', 'option'); choose.setAttribute('aria-selected', String(index === selected))
      choose.textContent = `${index === 0 ? 'Origin' : `Point ${index}`}  (${p.join(', ')})`
      choose.addEventListener('click', () => select(index))
      row.append(choose)
      if (index > 0) {
        const remove = document.createElement('button')
        remove.type = 'button'; remove.className = 'btn'; remove.textContent = '×'
        remove.setAttribute('aria-label', `Delete point ${index}`)
        remove.addEventListener('click', () => {
          points.splice(index, 1); selected = Math.min(selected, points.length - 1)
          render(); onSelect?.(selected); onChange?.()
        })
        row.append(remove)
      }
      list.append(row)
    })
    inputs.forEach((input, axis) => { input.value = points[selected][axis]; input.disabled = selected === 0 })
  }
  inputs.forEach((input, axis) => input.addEventListener('input', () => {
    if (selected === 0) return
    points[selected][axis] = input.valueAsNumber
    // Preserve focus and partially typed decimals while updating the row label.
    list.querySelectorAll('[role=option]')[selected].textContent = `Point ${selected}  (${points[selected].join(', ')})`
    onChange?.()
  }))
  root.querySelector('[aria-label="Add sweep point"]').addEventListener('click', () => {
    if (points.length >= 256) return
    const last = points.at(-1), previous = points.at(-2)
    const delta = previous ? last.map((v, i) => v - previous[i]) : [0, 0, 10]
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
    getPoints: () => points.map(p => [...p]),
    getSelected: () => selected,
    setPoints(value) { points = value.map(p => [...p]); selected = Math.min(1, points.length - 1); render() },
    select,
    move(index, value) {
      if (index <= 0 || index >= points.length || !value.every(Number.isFinite)) return
      points[index] = [...value]; render(); onChange?.()
    },
  }
}
