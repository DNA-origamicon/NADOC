/** A placement incident latches rendering and export off until the page reloads. */
import { lastPlacementFailure, PLACEMENT_FAILURE_EVENT } from './native_placement.js'

let activeFailure = null

export function assertPlacementExportSafe(scene) {
  const failure = scene?.userData?.placementIntegrityFailure ?? activeFailure
  if (!failure) return
  const error = new Error('Molecular rendering and export are blocked by a DNA positioning integrity failure. Complete the required review, then reload.')
  error.code = 'NATIVE_PLACEMENT_INTEGRITY'
  error.detail = failure
  throw error
}

export function installPlacementSceneGuard({ scene, renderer, store, stopNativeVR, target = window }) {
  let failure = null
  let visible = scene.visible
  const add = scene.add
  Object.defineProperty(scene, 'visible', { configurable: true,
    get: () => failure ? false : visible,
    set: value => { if (!failure) visible = value },
  })
  scene.add = function (...objects) {
    assertPlacementExportSafe(scene)
    return add.apply(this, objects)
  }

  function block(detail) {
    if (failure) return
    failure = detail ?? { code: 'NATIVE_PLACEMENT_INTEGRITY', review_required: true }
    activeFailure = failure
    Object.defineProperty(scene.userData, 'placementIntegrityFailure', { value: failure, enumerable: true })
    renderer.render = () => assertPlacementExportSafe(scene)
    const setLoop = renderer.setAnimationLoop.bind(renderer)
    renderer.setAnimationLoop = callback => { if (callback) assertPlacementExportSafe(scene); return setLoop(callback) }
    const attempt = (operation, action) => {
      try { return action() } catch (error) {
        failure.render_shutdown_errors ??= {}
        failure.render_shutdown_errors[operation] = String(error)
      }
    }
    // Permanent guards are already installed. A lost GL context or one failing
    // shutdown operation cannot prevent the remaining independent safeguards.
    attempt('stop_animation_loop', () => setLoop(null))
    attempt('clear_xr_buffer', () => renderer.clear?.(true, true, true))
    attempt('select_desktop_buffer', () => renderer.setRenderTarget?.(null))
    attempt('clear_desktop_buffer', () => renderer.clear?.(true, true, true))
    const recordShutdownError = error => {
      failure.render_shutdown_error = String(error)
      console.error('[native-placement] VR shutdown failed after rendering was blocked:', error)
    }
    const session = attempt('get_xr_session', () => renderer.xr?.getSession?.())
    if (session) Promise.resolve().then(() => session.end()).catch(recordShutdownError)
    if (stopNativeVR) Promise.resolve().then(stopNativeVR).catch(recordShutdownError)
    // Keep document data available for an evidence-preserving save.
    attempt('publish_failure_state', () => store?.setState({ placementIntegrityFailure: failure }))
  }
  const onFailure = event => block(event.detail)
  target.addEventListener(PLACEMENT_FAILURE_EVENT, onFailure)
  const previous = lastPlacementFailure() ?? activeFailure
  if (previous) block(previous)
  return { blocked: () => Boolean(failure), dispose: () => target.removeEventListener(PLACEMENT_FAILURE_EVENT, onFailure) }
}
