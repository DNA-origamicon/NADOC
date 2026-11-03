/** Explicit display setup on the ordinary invite; secrets never enter its URL. */
export function mountDemoDisplayAccess({ base, document: doc = document, onExit = () => {} }) {
  const key = `nadoc-demo-display:${base}`
  let storage
  try { storage = doc.defaultView?.sessionStorage } catch {}
  let saved = null, field = null, enabled = false
  try { saved = JSON.parse(storage?.getItem(key) ?? 'null') } catch { /* Storage may be disabled. */ }
  if (typeof saved?.password !== 'string' || typeof saved?.name !== 'string') saved = null
  const row = doc.createElement('div'), toggle = doc.createElement('button'), exit = doc.createElement('button')
  toggle.type = exit.type = 'button'; toggle.textContent = 'Set up demo display'; toggle.dataset.demoDisplaySetup = ''
  exit.textContent = 'Exit demo display'; exit.hidden = true; exit.dataset.demoDisplayExit = ''
  exit.style.cssText = 'position:fixed;bottom:12px;right:12px;z-index:1101;padding:8px'
  row.append(toggle); doc.getElementById('join-error').before(row); doc.body.append(exit)
  function setup() {
    enabled = true; toggle.hidden = true
    const label = doc.createElement('label'); label.textContent = 'Demo display password'; label.htmlFor = 'demo-display-password'
    field = doc.createElement('input'); field.id = 'demo-display-password'; field.type = 'password'; field.autocomplete = 'off'; field.maxLength = 128; field.required = true
    field.style.cssText = 'width:100%;padding:10px'; field.value = saved?.password ?? ''
    const note = doc.createElement('p'); note.textContent = 'One protected place, in addition to 16 guests. Automatically follows the presenter. Enabled in this tab until you exit.'
    const cancel = doc.createElement('button'); cancel.type = 'button'; cancel.textContent = 'Use guest access'
    cancel.onclick = () => {
      clear(); enabled = false; field.value = ''; field = null; row.replaceChildren(toggle); toggle.hidden = false
      const ordinary = doc.getElementById('meeting-password-row'); if (ordinary) { ordinary.hidden = false; ordinary.querySelector('input').required = true }
    }
    row.append(label,field,note,cancel)
    const ordinary = doc.getElementById('meeting-password-row'); if (ordinary) { ordinary.hidden = true; ordinary.querySelector('input').required = false }
    if (saved) doc.getElementById('guest-name').value = saved.name
  }
  toggle.onclick = setup
  if (saved) setup()
  function clear() { saved = null; try { storage?.removeItem(key) } catch {} }
  exit.onclick = () => { clear(); onExit() }
  return {
    get enabled() { return enabled },
    get remembered() { return !!saved },
    credentials() { return enabled ? { role: 'display', password: field.value.trim() } : {} },
    accept(name) { saved = { name, password: field.value.trim() }; try { storage?.setItem(key,JSON.stringify(saved)) } catch {} ; exit.hidden = false },
    reject() { clear() },
    dispose() { if(field)field.value=''; row.remove(); exit.remove() },
  }
}
