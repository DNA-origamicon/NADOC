import { estimateStapleTemperatures } from '../scene/staple_temperature.js'
import { initTemperatureLegend, syncTemperatureButton } from '../ui/staple_temperature_legend.js'

export function nextViewTools(current, key) {
  if (key === 'stapleTemperature') return { ...current, lengthHeatmap: false,
    stapleTemperature: { off: 'domain', domain: 'total', total: 'off' }[current.stapleTemperature ?? 'off'] }
  return { ...current, [key]: !current[key], ...(key === 'lengthHeatmap' ? { stapleTemperature: 'off' } : {}) }
}

export function initEditorViewTools({ store }) {
  const element = document.getElementById('view-tools')
  const legend = initTemperatureLegend(document.getElementById('pathview-container'), bounds => {
    store.setState({ viewTools: { ...store.getState().viewTools, temperatureBounds: bounds } })
  })
  let cachedDesign, estimates
  function sync() {
    const { viewTools, design } = store.getState()
    const mode = viewTools.stapleTemperature ?? 'off'
    for (const button of element.querySelectorAll('.vt-btn')) {
      if (button.dataset.vt === 'stapleTemperature') syncTemperatureButton(button, mode)
      else button.classList.toggle('active', !!viewTools[button.dataset.vt])
    }
    document.getElementById('menu-view-periodic-boundary')?.classList.toggle('is-checked', !!viewTools.periodicBoundary)
    if (mode !== 'off' && cachedDesign !== design) {
      cachedDesign = design; estimates = estimateStapleTemperatures(design)
    }
    legend.update(mode, estimates, !design ? 'Open a sequenced part.' : null, viewTools.temperatureBounds)
  }
  function click(event) {
    const button = event.target.closest('.vt-btn')
    if (!button || !element.contains(button)) return
    store.setState({ viewTools: nextViewTools(store.getState().viewTools, button.dataset.vt) })
  }
  element.addEventListener('click', click)
  const unsubscribe = store.subscribe((next, prev) => {
    if (next.design !== prev.design || next.viewTools !== prev.viewTools) sync()
  })
  sync()
  return { element, dispose() { legend.dispose(); unsubscribe(); element.removeEventListener('click', click); legend.element?.remove() } }
}
