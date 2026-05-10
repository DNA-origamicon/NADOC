import * as THREE from 'three'
import { XRControllerModelFactory } from 'three/addons/webxr/XRControllerModelFactory.js'
import { showToast } from '../ui/toast.js'

/**
 * Manages a WebXR immersive-vr session for grab-and-manipulate inspection of
 * a single loaded DNA part.
 *
 * Interaction model:
 *   One grip button  → grab + drag to translate/rotate the model
 *   Both grip buttons → pinch to scale; midpoint of hands drives position
 *
 * Auto-scale: on entry the model is scaled so its longest axis ≈ 0.4 m and
 * positioned at (0, 1.2, -0.5) in VR-space (comfortable arm's length).
 *
 * @param {THREE.WebGLRenderer} renderer
 * @param {THREE.Scene} scene
 * @param {Function} addFrameCallback    — register fn() to run each render frame
 * @param {Function} removeFrameCallback — unregister frame callback
 * @param {object} store                 — Zustand-style reactive store
 */
export function initVRSession(renderer, scene, addFrameCallback, removeFrameCallback, store) {
  let _session    = null
  let _vrWrapper  = null

  const _controllers = [null, null]
  const _grips       = [null, null]
  const _squeezing   = new Set()
  const _grabState   = [null, null]
  let   _twoHandData = null

  // ── Support check ───────────────────────────────────────────────────────────

  async function isSupported() {
    if (!navigator.xr) return false
    try { return await navigator.xr.isSessionSupported('immersive-vr') }
    catch { return false }
  }

  // ── Scene wrapping ──────────────────────────────────────────────────────────

  function _wrapScene() {
    _vrWrapper = new THREE.Group()
    _vrWrapper.name = 'vrWrapper'

    // Move all non-light children into the wrapper so we can scale/move the
    // whole model as one unit without touching individual renderer internals.
    const toWrap = scene.children.filter(c => !(c instanceof THREE.Light))
    toWrap.forEach(c => _vrWrapper.add(c))
    scene.add(_vrWrapper)

    // Auto-fit: scale bounding sphere to ≈ 0.4 m.
    const bb = new THREE.Box3().setFromObject(_vrWrapper)
    if (!bb.isEmpty()) {
      const size = bb.getSize(new THREE.Vector3())
      const maxDim = Math.max(size.x, size.y, size.z)
      const scale  = maxDim > 0 ? 0.4 / maxDim : 0.01
      const center = bb.getCenter(new THREE.Vector3())
      _vrWrapper.scale.setScalar(scale)
      // Offset so model centre sits at comfortable arm's length in front.
      _vrWrapper.position.set(
        -center.x * scale,
        1.2 - center.y * scale,
        -0.5 - center.z * scale,
      )
    } else {
      _vrWrapper.scale.setScalar(0.01)
      _vrWrapper.position.set(0, 1.2, -0.5)
    }
  }

  function _unwrapScene() {
    if (!_vrWrapper) return
    ;[..._vrWrapper.children].forEach(c => scene.add(c))
    scene.remove(_vrWrapper)
    _vrWrapper = null
  }

  // ── Controller setup ────────────────────────────────────────────────────────

  function _setupControllers() {
    const factory = new XRControllerModelFactory()
    for (let i = 0; i < 2; i++) {
      const ctrl = renderer.xr.getController(i)
      ctrl.addEventListener('squeezestart', () => _onSqueezeStart(i))
      ctrl.addEventListener('squeezeend',   () => _onSqueezeEnd(i))
      scene.add(ctrl)
      _controllers[i] = ctrl

      const grip = renderer.xr.getControllerGrip(i)
      grip.add(factory.createControllerModel(grip))
      scene.add(grip)
      _grips[i] = grip
    }
  }

  function _cleanupControllers() {
    for (let i = 0; i < 2; i++) {
      if (_controllers[i]) { scene.remove(_controllers[i]); _controllers[i] = null }
      if (_grips[i])       { scene.remove(_grips[i]);       _grips[i] = null }
    }
  }

  // ── Grab interaction ────────────────────────────────────────────────────────

  function _onSqueezeStart(i) {
    if (!_vrWrapper) return
    _squeezing.add(i)

    // Snapshot the inverse controller matrix and the wrapper matrix at grab time.
    _grabState[i] = {
      ctrlInv:    new THREE.Matrix4().copy(_controllers[i].matrixWorld).invert(),
      wrapperMat: _vrWrapper.matrix.clone(),
    }

    if (_squeezing.size === 2) {
      const p0 = new THREE.Vector3().setFromMatrixPosition(_controllers[0].matrixWorld)
      const p1 = new THREE.Vector3().setFromMatrixPosition(_controllers[1].matrixWorld)
      _twoHandData = {
        initialDist:  p0.distanceTo(p1),
        initialScale: _vrWrapper.scale.x,
      }
    }
  }

  function _onSqueezeEnd(i) {
    _squeezing.delete(i)
    _grabState[i] = null
    if (_squeezing.size < 2) _twoHandData = null
  }

  // Reusable temporaries to avoid per-frame allocation.
  const _tmpMat   = new THREE.Matrix4()
  const _tmpPos   = new THREE.Vector3()
  const _tmpQuat  = new THREE.Quaternion()
  const _tmpScale = new THREE.Vector3()

  function _updateGrab() {
    if (!_vrWrapper || _squeezing.size === 0) return

    if (_squeezing.size === 2 && _twoHandData) {
      // Two-hand: position at midpoint, scale by hand-distance ratio.
      const p0  = new THREE.Vector3().setFromMatrixPosition(_controllers[0].matrixWorld)
      const p1  = new THREE.Vector3().setFromMatrixPosition(_controllers[1].matrixWorld)
      const mid = new THREE.Vector3().addVectors(p0, p1).multiplyScalar(0.5)
      const s   = _twoHandData.initialScale * (p0.distanceTo(p1) / _twoHandData.initialDist)
      _vrWrapper.scale.setScalar(s)
      _vrWrapper.position.copy(mid)
    } else {
      // Single hand: apply the controller's delta transform to the wrapper.
      const i  = [..._squeezing][0]
      const gs = _grabState[i]
      if (!gs) return

      // delta = currentCtrl × ctrlInvAtGrab
      _tmpMat.multiplyMatrices(_controllers[i].matrixWorld, gs.ctrlInv)
      // newWrapper = delta × wrapperAtGrab
      _tmpMat.multiply(gs.wrapperMat)
      _tmpMat.decompose(_tmpPos, _tmpQuat, _tmpScale)
      _vrWrapper.position.copy(_tmpPos)
      _vrWrapper.quaternion.copy(_tmpQuat)
    }
  }

  // ── Public API ──────────────────────────────────────────────────────────────

  async function enter() {
    const { assemblyActive, currentDesign } = store.getState()

    if (assemblyActive) {
      showToast('VR is only available for single parts — exit Assembly mode first')
      return
    }
    if (!currentDesign) {
      showToast('Load a design before launching VR')
      return
    }
    if (!await isSupported()) {
      showToast('WebXR unavailable — is SteamVR running? Launch Chrome with: chromium --enable-features=WebXR')
      return
    }

    let session
    try {
      session = await navigator.xr.requestSession('immersive-vr', {
        requiredFeatures: ['local-floor'],
      })
    } catch (e) {
      showToast(`Could not start VR session: ${e.message}`)
      return
    }

    _session = session
    await renderer.xr.setSession(session)

    _wrapScene()
    _setupControllers()
    addFrameCallback(_updateGrab)

    session.addEventListener('end', _onSessionEnd)
  }

  function _onSessionEnd() {
    removeFrameCallback(_updateGrab)
    _cleanupControllers()
    _unwrapScene()
    _squeezing.clear()
    _grabState[0] = null
    _grabState[1] = null
    _twoHandData  = null
    _session      = null
  }

  function exit() {
    if (_session) {
      _session.end().catch(() => {})
      // _onSessionEnd will fire via the 'end' event listener.
    }
  }

  return { isSupported, enter, exit }
}
