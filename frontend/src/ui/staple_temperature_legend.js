import { initTemperatureScale } from './temperature_scale.js'
import './staple_temperature_legend.css'

const MARKUP = `<div id="staple-temperature-legend" hidden role="status">
            <strong data-temperature-title>Domain Tm (°C)</strong>
            <div data-temperature-scale></div>
            <div data-temperature-status></div>
            <small>10 mM MgCl₂ · 200 nM staples (excess)<br>No added monovalent salt; free Mg²⁺ assumed.<br>Gray: unknown / unsupported / unpaired.<br>Domain: SantaLucia–Owczarzy Tm.<br>Total: PNAS 2024 estimated Tfold; each scaffold circular.<br>Terminal tails excluded. Estimates do not predict folding order.</small>
          </div>`

export function syncTemperatureButton(button, mode) {
  if (!button) return
  button.dataset.mode = mode
  button.classList.toggle('active', mode !== 'off')
  button.setAttribute('aria-pressed', String(mode !== 'off'))
  button.setAttribute('aria-label', `Staple temperature: ${mode}. Click to cycle off, domain Tm, total staple Tfold.`)
  const label = button.querySelector('.sf-label-text')
  if (label) label.textContent = { off: 'Tm', domain: 'Tm domain', total: 'Tfold total' }[mode]
}

/** Same Celsius scale, conditions and unavailable counts in both editors. */
export function initTemperatureLegend(parent, onBoundsChange = () => {}) {
  let element = document.getElementById('staple-temperature-legend')
  if (!element && parent) {
    parent.insertAdjacentHTML('beforeend', MARKUP)
    element = document.getElementById('staple-temperature-legend')
  }
  const scale = initTemperatureScale(element?.querySelector('[data-temperature-scale]') ?? element, onBoundsChange)
  return { element, getBounds: scale.getBounds, dispose: scale.dispose, update(mode, estimates, message = null, bounds = null) {
    if (bounds) scale.setBounds(bounds)
    if (!element) return
    element.hidden = mode === 'off'
    if (mode === 'off') { scale.cancelDrag(); return }
    let min = Infinity, max = -Infinity, known = 0, unknown = 0
    for (const result of estimates?.values() ?? []) {
      for (const value of mode === 'domain' ? result.domains.map(d => d.tm) : [result.total]) {
        if (value == null || !Number.isFinite(value)) unknown++
        else { min = Math.min(min, value); max = Math.max(max, value); known++ }
      }
    }
    scale.setDataRange(min, max)
    element.querySelector('[data-temperature-title]').textContent = mode === 'domain' ? 'Domain Tm (°C)' : 'Total staple Tfold (°C)'
    element.querySelector('[data-temperature-status]').textContent = message
      ?? `${known ? `${min.toFixed(1)}–${max.toFixed(1)} °C` : 'No estimates'} · ${unknown} gray / unavailable`
  } }
}
