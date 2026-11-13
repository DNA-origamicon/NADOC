/** Defer a table/panel refresh while its sequence field owns an unfinished draft. */
export function createSequenceDraftGuard(root) {
  let documentKey, pending = null, watched = null
  function refresh(key, render) {
    const input = root?.ownerDocument.activeElement
    if (key === documentKey && root?.contains(input) && (input?.matches('[data-overhang-sequence]') || pending)) {
      pending = () => refresh(key, render)
      if (watched !== input) {
        watched = input
        input.addEventListener('blur', () => {
          watched = null
          queueMicrotask(() => pending?.())
        }, { once: true })
      }
      return
    }
    const deferred = !!pending
    pending = null
    documentKey = key
    render(deferred)
  }
  return refresh
}
