/** Nonmodal work indicator shared by sequence writes and their deferred checks. */
export function createSequenceActivity({ document: doc = globalThis.document } = {}) {
  let count = 0, node
  function render() {
    if (!doc?.body) return
    if (!node?.isConnected) {
      node = doc.createElement('div')
      node.id = 'overhang-sequence-activity'
      node.setAttribute('role', 'status')
      node.setAttribute('aria-live', 'polite')
      node.style.cssText = 'position:fixed;bottom:18px;left:50%;transform:translateX(-50%);z-index:10000;pointer-events:none;background:#182330;color:#e6edf3;padding:9px 14px;border:1px solid #46729c;border-radius:6px;align-items:center;gap:9px;font:13px sans-serif'
      node.style.pointerEvents = 'none'
      const wheel = doc.createElement('span')
      wheel.setAttribute('aria-hidden', 'true')
      wheel.style.cssText = 'display:inline-block;width:15px;height:15px;border:2px solid #53697f;border-top-color:#78bbff;border-radius:50%'
      wheel.animate?.([{ transform: 'rotate(0deg)' }, { transform: 'rotate(360deg)' }], { duration: 800, iterations: Infinity })
      node.append(wheel, doc.createTextNode('Updating overhang sequences…'))
      doc.body.append(node)
    }
    node.style.display = count ? 'flex' : 'none'
    node.setAttribute('aria-busy', String(count > 0))
  }
  return {
    begin() {
      count++; render()
      let ended = false
      return () => { if (!ended) { ended = true; count--; render() } }
    },
    get pending() { return count },
  }
}
export const sequenceActivity = createSequenceActivity()
export const afterSequencePaint = () => new Promise(resolve => {
  if (!globalThis.requestAnimationFrame || globalThis.document?.hidden) { resolve(); return }
  const timer = setTimeout(resolve, 2000)
  requestAnimationFrame(() => requestAnimationFrame(() => { clearTimeout(timer); resolve() }))
})
