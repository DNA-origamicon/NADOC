/** Box selection is a fallback gesture: a tool's claim lasts until the next press. */
export function createSelectionDragGuard(canvas, { controls, isDisabled = () => false } = {}) {
  let down = null, blocked = false, pending = null, timer = null
  function flush() {
    clearTimeout(timer); timer = null
    const callback = pending; pending = null
    callback?.()
  }
  const unavailable = event => controls?.enabled === false || isDisabled() ||
    event?.defaultPrevented || event?.cancelBubble
  function check(event) {
    if (unavailable(event) || down?.defaultPrevented) blocked = true
    return !blocked
  }
  function begin(event) {
    clearTimeout(timer); timer = null; pending = null
    down = event
    blocked = !!unavailable(event)
    // TransformControls and custom gizmos may be registered after selection.
    // Inspect again after every pointerdown listener has had a chance to claim it.
    setTimeout(() => { if (down === event) check(event) }, 0)
  }
  const cancel = () => { blocked = true; flush() }
  const up = event => { check(event); flush() }
  canvas.addEventListener('pointerdown', begin, true)
  canvas.addEventListener('pointermove', check, true)
  // Check before a gizmo's pointerup handler re-enables navigation.
  canvas.addEventListener('pointerup', up, true)
  canvas.addEventListener('pointercancel', cancel, true)
  return {
    begin, allows: check,
    afterEvent(callback) {
      pending = callback
      if (timer === null) timer = setTimeout(flush, 0)
    },
    dispose() {
      clearTimeout(timer); pending = null; down = null
      canvas.removeEventListener('pointerdown', begin, true)
      canvas.removeEventListener('pointermove', check, true)
      canvas.removeEventListener('pointerup', up, true)
      canvas.removeEventListener('pointercancel', cancel, true)
    },
  }
}
