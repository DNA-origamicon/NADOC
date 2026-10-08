import { onMediaExportChange } from '../shared/media_export_activity.js'
import { welcomeVisible, observeWelcomeVisibility } from '../shared/welcome_visibility.js'

export function initDesignReadinessVisibility({ widget, document = globalThis.document, window = globalThis.window }) {
  let lighting = !!document.getElementById('photo-lighting-enabled')?.checked
  let exporting = false
  const sync = () => widget.setSuppressed(lighting || exporting || welcomeVisible(document))
  const stopWelcome = observeWelcomeVisibility(sync, document)
  const lightingChanged = event => { lighting = !!event.detail?.active; sync() }
  window.addEventListener('nadoc:lighting-change', lightingChanged)
  const unsubscribe = onMediaExportChange(active => { exporting = active; sync() })
  return { dispose() {
    stopWelcome()
    unsubscribe()
    window.removeEventListener('nadoc:lighting-change', lightingChanged)
  } }
}
