import { chooseOrigamiImportOptions, importRelaxationMessage } from './import_origami_options.js'
import { showToast } from './toast.js'

/** Choose before clearing the active document, including for recent raw sources. */
export async function importRecentDesign(entry, { api, beforeImport }) {
  const type = entry.type ?? 'nadoc'
  const origami = type === 'cadnano' || type === 'scadnano'
  const options = origami ? await chooseOrigamiImportOptions() : {}
  if (!options) return { cancelled: true }
  beforeImport()
  const result = type === 'cadnano' ? await api.importCadnanoDesign(entry.content, options)
    : type === 'scadnano' ? await api.importScadnanoDesign(entry.content, undefined, options)
      : await api.importDesign(entry.content)
  if (result) {
    const message = importRelaxationMessage(result.relaxation)
    if (message) showToast(message, 8000)
    if (result.import_warnings?.length) showToast(result.import_warnings.join(' | '), 8000)
  }
  return result
}
