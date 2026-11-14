import { initTextScaling } from './text_scaling.js'
import { applyAppearance } from './appearance.js'
import { readPreferences, SETTINGS_EVENT } from './preferences.js'

export function initPreferenceEffects({ store, controls, renderer, canvas, setPreviewEnabled }) {
  const disposeTextScaling = initTextScaling()
  let previous = null
  const apply = () => {
    const values = readPreferences()
    applyAppearance(values)
    if (!previous || previous.navigationMode !== values.navigationMode) document.getElementById(`menu-view-orbit-${values.navigationMode}`)?.click()
    if (!previous || previous.pixelRatio !== values.pixelRatio) renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, values.pixelRatio))
    const patch = {}
    for (const key of ['coloringMode', 'showHelixLabels']) if (!previous || previous[key] !== values[key]) patch[key] = values[key]
    const filters = { ...store.getState().selectableTypes }
    for (const name of ['Scaffold', 'Staples', 'Strands', 'Domains', 'Ends']) {
      const key = `select${name}`
      if (!previous || previous[key] !== values[key]) filters[name.toLowerCase()] = values[key]
    }
    if (Object.keys(patch).length || !previous || Object.keys(values).some(k => k.startsWith('select') && values[k] !== previous[k])) store.setState({ ...patch, selectableTypes: filters })
    if (!previous || previous.preview !== values.preview) setPreviewEnabled?.(values.preview)
    previous = values
  }
  const warnBeforeUnload = event => {
    if (!readPreferences().warnUnsaved) return
    const state = store.getState()
    if (!(state.assemblyActive ? state.currentAssembly : state.currentDesign)) return
    if (!document.querySelector('#sync-status .sync-dot.yellow, #sync-status .sync-dot.red')) return
    event.preventDefault(); event.returnValue = ''
  }
  window.addEventListener('beforeunload', warnBeforeUnload)
  apply()
  window.addEventListener(SETTINGS_EVENT, apply)
  const scheme = window.matchMedia?.('(prefers-color-scheme: light)')
  scheme?.addEventListener('change', apply)
  return () => { disposeTextScaling(); window.removeEventListener('beforeunload', warnBeforeUnload); window.removeEventListener(SETTINGS_EVENT, apply); scheme?.removeEventListener('change', apply) }
}
