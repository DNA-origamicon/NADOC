/** Folded DNA imports create native oligos; all sources use the same mapping. */
export async function openImportAptamerModal({ api, onImport }) {
  const overlay = document.createElement('div')
  overlay.style.cssText = 'position:fixed;inset:0;background:#0009;z-index:10001;display:grid;place-items:center'
  const dialog = document.createElement('form')
  dialog.setAttribute('role', 'dialog')
  dialog.setAttribute('aria-modal', 'true')
  dialog.setAttribute('aria-label', 'Import Aptamer')
  dialog.style.cssText = 'background:#161b22;color:#c9d1d9;border:1px solid #30363d;border-radius:8px;padding:20px;width:460px;max-width:90vw;display:grid;gap:12px'
  dialog.innerHTML = `
    <h3 style="margin:0">Import Aptamer</h3>
    <p style="margin:0">Add a folded G4 motif as editable DNA strands. Extend its 5′ and 3′ ends to design attachment overhangs.</p>
    <label>Potassium-responsive motif <select name="template" aria-label="Aptamer template"></select></label>
    <p data-description style="margin:0"></p>
    <a data-source target="_blank" rel="noopener noreferrer">View deposited structure</a>
    <label>Or import a DNA PDB file <input name="file" type="file" accept=".pdb,.ent" aria-label="Aptamer PDB file"></label>
    <small>Uses DNA from the first model; solvent and ions are omitted. K+ responsiveness depends on buffer and attachment geometry; this imports a folded structure, not a concentration-driven simulation.</small>
    <p role="status" style="margin:0"></p>
    <div style="display:flex;justify-content:flex-end;gap:8px"><button type="button" data-close>Cancel</button><button type="submit" disabled>Import</button></div>`
  overlay.append(dialog)
  document.body.append(overlay)
  const previousFocus = document.activeElement
  const select = dialog.elements.template
  const file = dialog.elements.file
  const submit = dialog.querySelector('[type=submit]')
  const cancel = dialog.querySelector('[data-close]')
  const status = dialog.querySelector('[role=status]')
  let busy = false
  let closed = false
  function close() {
    if (busy) return
    closed = true
    overlay.remove()
    previousFocus?.focus()
  }
  cancel.onclick = close
  overlay.onclick = e => { if (e.target === overlay) close() }
  dialog.onkeydown = e => {
    if (e.key === 'Escape') { e.preventDefault(); close() }
    if (e.key === 'Tab') {
      const focusable = [...dialog.querySelectorAll('button:not(:disabled), select:not(:disabled), input:not(:disabled), a[href]')]
      const first = focusable[0], last = focusable.at(-1)
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
    }
  }
  let templates = []
  select.onchange = () => {
    const entry = templates.find(t => t.id === select.value)
    dialog.querySelector('[data-description]').textContent = entry?.description ?? ''
    const link = dialog.querySelector('[data-source]')
    link.href = entry?.url ?? '#'
    link.hidden = !entry
  }
  file.onchange = () => { submit.disabled = !file.files?.length && !select.value }
  dialog.onsubmit = async e => {
    e.preventDefault()
    if (busy) return
    busy = true
    submit.disabled = cancel.disabled = select.disabled = file.disabled = true
    status.textContent = 'Importing aptamer…'
    try {
      const chosen = file.files?.[0]
      const args = chosen ? { content: await chosen.text(), name: chosen.name.replace(/\.(pdb|ent)$/i, '') } : { template_id: select.value }
      const result = await onImport(args)
      if (!result) throw new Error('Import failed. Check the selected structure and try again.')
      busy = false
      close()
    } catch (error) {
      status.textContent = error.message
      busy = false
      submit.disabled = cancel.disabled = select.disabled = file.disabled = false
    }
  }
  try {
    const result = await api.getAptamerCatalog()
    if (closed) return
    templates = result?.templates ?? []
    for (const entry of templates) {
      const option = document.createElement('option')
      option.value = entry.id
      option.textContent = `${entry.name} (${entry.id})`
      select.append(option)
    }
    select.onchange()
    submit.disabled = !templates.length
    if (!templates.length) status.textContent = 'Templates unavailable. You can import a local PDB file.'
    select.focus()
  } catch (error) {
    status.textContent = error.message
  }
  return overlay
}
