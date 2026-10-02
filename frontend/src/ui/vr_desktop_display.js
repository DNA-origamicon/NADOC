export const VR_DESKTOP_DISPLAY_KEY = 'nadoc:vr-desktop-3d'

/** Browser drawing is optional during native VR; scene updates remain live. */
export function initVRDesktopDisplay({ document, setNativeVRActive, setNativeVRDesktopEnabled, storage } = {}) {
  if (storage === undefined) {
    try { storage = document.defaultView.localStorage } catch { storage = null }
  }
  let enabled = true
  try { enabled = storage?.getItem(VR_DESKTOP_DISPLAY_KEY) !== 'off' } catch { /* Use the existing default. */ }
  let active = false
  const toggle = document.getElementById('menu-help-vr-desktop-3d')
  const notice = document.getElementById('vr-desktop-paused')
  const resume = document.getElementById('vr-desktop-resume')
  function refresh() {
    toggle?.setAttribute('aria-pressed', String(enabled))
    toggle?.classList.toggle('is-on', enabled)
    if (notice) notice.hidden = !active || enabled
    setNativeVRDesktopEnabled(enabled)
  }
  function change(value) {
    enabled = value
    try { storage?.setItem(VR_DESKTOP_DISPLAY_KEY, enabled ? 'on' : 'off') } catch { /* Session-only preference. */ }
    refresh()
  }
  const onToggle = () => change(!enabled)
  const onResume = () => change(true)
  toggle?.addEventListener('click', onToggle)
  resume?.addEventListener('click', onResume)
  refresh()
  return {
    setActive(value) {
      active = Boolean(value)
      setNativeVRActive(active)
      refresh()
    },
    dispose() {
      toggle?.removeEventListener('click', onToggle)
      resume?.removeEventListener('click', onResume)
      if (notice) notice.hidden = true
    },
  }
}
