import { estimateStapleTemperatures } from '../scene/staple_temperature.js'
import { temperatureColor } from '../scene/staple_temperature_colors.js'
import { initTemperatureLegend, syncTemperatureButton } from './staple_temperature_legend.js'

export { temperatureColor, UNKNOWN_TEMPERATURE_COLOR } from '../scene/staple_temperature_colors.js'

/** Independent, transient view overlay; never edits or persists a design. */
export function initStapleTemperatureView({ store, designRenderer, onActivate = () => {}, getCurrentRepr = () => 'full' }) {
  const button = document.querySelector('[data-vt="stapleTemperature"]')
  const legend = initTemperatureLegend(document.getElementById('canvas-area'), () => apply())
  let mode = 'off', cachedDesign, estimates
  const LAYER = 'stapleTemperature'
  const entries = () => [...(designRenderer.getBackboneEntries?.() ?? []),
    ...(designRenderer.getSlabEntries?.() ?? []), ...(designRenderer.getConeEntries?.() ?? [])]

  // Painted on a renderer false-colour layer: selection highlight/restore and
  // colouring-mode repaints land underneath it, and clearing reveals whatever
  // the underlying colour is by then.
  function restore() { designRenderer.clearFalseColors(LAYER) }
  function apply() {
    if (mode === 'off') return
    const state = store.getState(), design = state.currentDesign
    const supported = !state.assemblyActive && ['full', 'beads'].includes(getCurrentRepr())
    if (design !== cachedDesign) {
      cachedDesign = design
      estimates = estimateStapleTemperatures(design)
    }
    const bounds = legend.getBounds()
    if (supported) for (const entry of entries()) {
      const nuc = entry.nuc ?? entry.fromNuc
      const result = estimates?.get(nuc?.strand_id ?? entry.strandId)
      if (!result) continue
      const value = mode === 'domain' ? result.domains[nuc?.domain_index]?.tm : result.total
      designRenderer.paintFalseColor(LAYER, entry, temperatureColor(value, bounds))
    }
    legend.update(mode, estimates, !supported ? 'Heatmap: open the part in Full or Beads view.'
      : !design ? 'Open a sequenced part.' : null)
    window.dispatchEvent(new Event('nadoc:view-scene-changed'))
  }
  function setMode(next) {
    restore()
    mode = next
    if (mode !== 'off') onActivate()
    syncTemperatureButton(button, mode)
    legend.update(mode, estimates)
    apply()
  }
  const click = () => setMode({ off: 'domain', domain: 'total', total: 'off' }[mode])
  button?.addEventListener('click', click)
  const refresh = () => { restore(); apply() }
  const unsubscribe = store.subscribe((next, prev) => {
    if (mode === 'off') return
    if (['currentDesign', 'currentGeometry', 'currentHelixAxes', 'representation', 'assemblyActive', 'coloringMode', 'strandColors', 'strandGroups', 'loopStrandIds'].some(k => next[k] !== prev[k])) refresh()
  })
  window.addEventListener('nadoc:display-rebuilt', refresh)
  window.addEventListener('nadoc:representation-change', refresh)
  setMode('off')
  return { getMode: () => mode, setMode, refresh,
    dispose() { setMode('off'); legend.dispose(); unsubscribe?.(); button?.removeEventListener('click', click); window.removeEventListener('nadoc:display-rebuilt', refresh); window.removeEventListener('nadoc:representation-change', refresh) },
  }
}
