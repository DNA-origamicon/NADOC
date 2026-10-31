/** Nonblocking backend root-length exemptions beside the connection controls. */
export function initRootExemptionNotice({ store, host }) {
  if (!host) return { dispose() {} }
  const section = document.createElement('div')
  section.className = 'root-length-exemptions'
  section.style.cssText = 'font-size:12px;color:var(--color-text-dim);margin-top:8px'
  host.append(section)
  function render(state) {
    const notices = state.currentDesign ? state.validationReport?.exemptions ?? [] : []
    section.hidden = notices.length === 0
    section.replaceChildren(...notices.map(notice => {
      const row = document.createElement('p')
      row.textContent = notice.message
      return row
    }))
  }
  render(store.getState())
  const unsubscribe = store.subscribe((state, previous) => {
    if (state.validationReport !== previous.validationReport || state.currentDesign !== previous.currentDesign) render(state)
  })
  return { dispose() { unsubscribe(); section.remove() } }
}
