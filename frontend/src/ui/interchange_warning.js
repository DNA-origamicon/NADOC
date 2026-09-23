/** Review the exact backend inventory; do not duplicate format capabilities here. */
export function showInterchangeWarning(report) {
  if (!report.issues.length) return Promise.resolve(true)
  return new Promise(resolve => {
    const previous = document.activeElement
    const dialog = document.createElement('dialog')
    dialog.setAttribute('aria-labelledby', 'interchange-warning-title')
    dialog.style.cssText = 'position:fixed;inset:0;margin:auto;height:fit-content;width:min(680px,90vw);max-height:85vh;overflow:auto;background:#161b22;color:#c9d1d9;border:1px solid #48576b;border-radius:10px;padding:24px;font:14px sans-serif'
    const title = document.createElement('h2')
    title.id = 'interchange-warning-title'
    title.textContent = `${report.format === 'cadnano' ? 'caDNAno' : 'scadnano'} export compatibility`
    title.style.marginTop = '0'
    const intro = document.createElement('p')
    intro.textContent = report.blocked
      ? 'Export is blocked because some molecular content cannot be preserved. Save as .nadoc to retain the complete design.'
      : 'These features in the current design will change or be omitted. Keep the .nadoc file as your complete design.'
    const list = document.createElement('ul')
    for (const issue of report.issues) {
      const item = document.createElement('li')
      item.style.cssText = 'margin:12px 0;line-height:1.45'
      const label = document.createElement('strong')
      label.textContent = `${issue.label} (${issue.count})${issue.severity === 'error' ? ' — blocks export' : ''}: `
      if (issue.severity === 'error') label.style.color = '#ffb4ab'
      item.append(label, document.createTextNode(issue.effect))
      list.appendChild(item)
    }
    const actions = document.createElement('div')
    actions.style.cssText = 'display:flex;justify-content:flex-end;gap:12px;position:sticky;bottom:-24px;background:#161b22;padding:16px 0'
    const finish = value => { dialog.close(); dialog.remove(); previous?.focus(); resolve(value) }
    const cancel = document.createElement('button')
    cancel.textContent = report.blocked ? 'Close' : 'Cancel'
    cancel.style.cssText = 'padding:9px 16px;border:1px solid #56657a;border-radius:5px;background:#26313f;color:#e6edf3;cursor:pointer'
    cancel.addEventListener('click', () => finish(false))
    actions.append(cancel)
    if (!report.blocked) {
      const proceed = document.createElement('button')
      proceed.textContent = 'Export with listed losses'
      proceed.style.cssText = 'padding:9px 16px;border:1px solid #579bf8;border-radius:5px;background:#1f6feb;color:white;cursor:pointer'
      proceed.addEventListener('click', () => finish(true))
      actions.append(proceed)
    }
    dialog.addEventListener('cancel', e => { e.preventDefault(); finish(false) })
    dialog.append(title, intro, list, actions)
    document.body.appendChild(dialog)
    dialog.showModal()
    cancel.focus()
  })
}

export function createInterchangeExport({ api, showWarning = showInterchangeWarning, onError }) {
  let busy = false
  return async target => {
    if (busy) return
    busy = true
    try {
      const report = await api.getExportCompatibility(target)
      if (!report) { onError(); return }
      if (!await showWarning(report) || report.blocked) return
      const exportFile = target === 'cadnano' ? api.exportCadnano : api.exportScadnano
      if (!await exportFile(report.token)) onError()
    } catch (error) {
      onError(error)
    } finally { busy = false }
  }
}
