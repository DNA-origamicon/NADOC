import { clampBounds, fractionToValue, valueToFraction } from './flex_scale.js'
import { DEFAULT_TEMPERATURE_BOUNDS } from '../scene/staple_temperature_colors.js'

/** Temperature analogue of the flex-map handles, precise bounds and full-range reset. */
export function initTemperatureScale(parent, onChange = () => {}) {
  const root = document.createElement('div')
  root.className = 'temperature-scale'
  root.innerHTML = `<div class="temperature-bound-inputs">
    <label>Lower °C <input data-temperature-low type="number" step="0.1" aria-label="Temperature lower bound (°C)"></label>
    <label>Upper °C <input data-temperature-high type="number" step="0.1" aria-label="Temperature upper bound (°C)"></label></div>
    <div class="temperature-gradient" data-temperature-track title="Temperatures below the lower bound are blue; temperatures above the upper bound are red.">
      <button type="button" data-temperature-handle="lo" role="slider" aria-label="Lower temperature bound" title="Drag lower bound"></button>
      <button type="button" data-temperature-handle="hi" role="slider" aria-label="Upper temperature bound" title="Drag upper bound"></button>
    </div><div class="temperature-ticks"><span data-temperature-tick="lo"></span><span data-temperature-tick="mid"></span><span data-temperature-tick="hi"></span></div>
    <button type="button" data-temperature-reset title="Reset to the full estimated temperature range">Reset full range</button>`
  parent?.appendChild(root)
  const low = root.querySelector('[data-temperature-low]'), high = root.querySelector('[data-temperature-high]')
  const track = root.querySelector('[data-temperature-track]')
  let bounds = { ...DEFAULT_TEMPERATURE_BOUNDS }, data = { ...bounds }, stopDrag = null
  const format = value => String(Number(value.toFixed(2)))
  function render() {
    low.value = format(bounds.lo); high.value = format(bounds.hi)
    const min = Math.min(data.lo, bounds.lo), max = Math.max(data.hi, bounds.hi)
    const left = valueToFraction(bounds.lo, min, max), right = valueToFraction(bounds.hi, min, max)
    track.style.background = `linear-gradient(to right, ${[240, 180, 120, 60, 0].map((hue, i) =>
      `hsl(${hue},90%,50%) ${(left + (right - left) * i / 4) * 100}%`).join(', ')})`
    for (const handle of root.querySelectorAll('[data-temperature-handle]')) {
      const value = bounds[handle.dataset.temperatureHandle]
      handle.style.left = `${valueToFraction(value, min, max) * 100}%`
      handle.setAttribute('aria-valuemin', min); handle.setAttribute('aria-valuemax', max)
      handle.setAttribute('aria-valuenow', value)
    }
    root.querySelector('[data-temperature-tick="lo"]').textContent = format(min)
    root.querySelector('[data-temperature-tick="mid"]').textContent = format((min + max) / 2)
    root.querySelector('[data-temperature-tick="hi"]').textContent = `${format(max)} °C`
  }
  function setBounds(next, emit = false) {
    if (!Number.isFinite(next?.lo) || !Number.isFinite(next?.hi)) { render(); return }
    bounds = clampBounds(next.lo, next.hi)
    if (bounds.hi - bounds.lo < .1) bounds.hi = bounds.lo + .1
    render()
    if (emit) onChange({ ...bounds })
  }
  low.addEventListener('change', () => setBounds({ lo: low.valueAsNumber, hi: bounds.hi }, true))
  high.addEventListener('change', () => setBounds({ lo: bounds.lo, hi: high.valueAsNumber }, true))
  root.querySelector('[data-temperature-reset]').addEventListener('click', () => setBounds(data, true))
  for (const handle of root.querySelectorAll('[data-temperature-handle]')) {
    const which = handle.dataset.temperatureHandle
    handle.addEventListener('keydown', e => {
      if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) return
      e.preventDefault(); e.stopPropagation()
      const delta = ['ArrowRight', 'ArrowUp'].includes(e.key) ? .1 : -.1
      setBounds({ ...bounds, [which]: which === 'lo' ? Math.min(bounds.lo + delta, bounds.hi - .1) : Math.max(bounds.hi + delta, bounds.lo + .1) }, true)
    })
    handle.addEventListener('pointerdown', e => {
      e.preventDefault(); e.stopPropagation(); stopDrag?.()
      const rect = track.getBoundingClientRect()
      const min = Math.min(data.lo, bounds.lo), max = Math.max(data.hi, bounds.hi)
      const move = event => {
        if (!rect.width) return
        const value = fractionToValue((event.clientX - rect.left) / rect.width, min, max)
        setBounds({ ...bounds, [which]: which === 'lo' ? Math.min(value, bounds.hi - .1) : Math.max(value, bounds.lo + .1) }, true)
      }
      stopDrag = () => {
        window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', stopDrag)
        window.removeEventListener('pointercancel', stopDrag); stopDrag = null
      }
      window.addEventListener('pointermove', move); window.addEventListener('pointerup', stopDrag)
      window.addEventListener('pointercancel', stopDrag)
    })
  }
  render()
  return { getBounds: () => ({ ...bounds }), setBounds,
    setDataRange(lo, hi) {
      const known = Number.isFinite(lo) && Number.isFinite(hi)
      data = known ? clampBounds(lo, hi) : { ...DEFAULT_TEMPERATURE_BOUNDS }
      root.querySelector('[data-temperature-reset]').disabled = !known
      render()
    },
    cancelDrag: () => stopDrag?.(), dispose() { stopDrag?.(); root.remove() },
  }
}
