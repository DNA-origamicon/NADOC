/**
 * File → Convert history to verified… (re-plan R2).
 *
 * Converts the open part's pre-overhaul history so later features become
 * editable through the verified (isolated) editor, then saves the result under
 * a NEW file name. The original file is never written: the workspace path is
 * pointed at the new file before the conversion is applied, so autosave can no
 * longer target the original.
 */
export function initHistoryConversion({ api, store, showToast, openFileBrowser, showConfirm,
  getWorkspacePath, setWorkspacePath, setFileName,
  button = globalThis.document?.getElementById('menu-file-convert-history') }) {
  const toast = (message, severity = 'info') => showToast(message, { severity })

  function describe(c) {
    const lines = [`Earlier rows folded into an imported baseline: ${c.absorbed} of ${c.rows}.`,
      `Rows that stay editable as features: ${c.editable.length}` +
        (c.editable.length ? ` (${c.editable.join(', ')}).` : '.')]
    if (c.frozen) lines.push(`${c.frozen} legacy routing result(s) are kept frozen: editing an earlier bend or twist replays through them; earlier topology edits are refused.`)
    if (c.reason) lines.push(`Note: ${c.reason}.`)
    lines.push('The converted part reproduces the saved design exactly. It is saved as a new file; the original file is not changed.')
    return lines.join('\n')
  }

  async function run() {
    const state = store.getState()
    if (!state.currentDesign || state.assemblyActive) { toast('Open a part to convert its history.', 'error'); return false }
    const dry = await api.convertHistory({ apply: false })
    if (!dry) { toast(`Conversion check failed: ${store.getState().lastError?.message ?? 'unknown error'}`, 'error'); return false }
    const c = dry.conversion
    if (c.status === 'already_native') { toast('This part already has verified history.'); return false }
    if (c.status !== 'converted') { toast(`This part cannot be converted: ${c.reason}`, 'error'); return false }
    if (!await showConfirm({ title: 'Convert history to verified', message: describe(c), confirmLabel: 'Choose new file…' })) return false
    const original = getWorkspacePath()
    const stem = (original?.split('/').pop() ?? state.currentDesign.metadata?.name ?? 'Part').replace(/\.nadoc$/i, '')
    const dest = await openFileBrowser({ title: 'Save Converted Part As', mode: 'save', fileType: 'part',
      suggestedName: `${stem} (verified)`, suggestedExt: '.nadoc', noOverwrite: true, api })
    if (!dest) return false
    if (original && dest.path === original) { toast('Choose a new file name; the original file is kept unchanged.', 'error'); return false }
    setWorkspacePath(dest.path)
    const applied = await api.convertHistory({ apply: true, expectedRevision: dry.revision })
    if (!applied) {
      setWorkspacePath(original)
      toast(`Conversion was not applied: ${store.getState().lastError?.message ?? 'unknown error'}`, 'error')
      return false
    }
    const saved = await api.saveDesignAs(dest.path, false)
    if (!saved) { toast(`Converted in memory, but saving ${dest.name} failed. Use Save As to keep it.`, 'error'); return false }
    setFileName(dest.name)
    toast(`Converted history saved as ${dest.name}. ${c.editable.length} feature(s) are editable.`)
    return true
  }

  button?.addEventListener('click', () => { void run() })
  return { run }
}
