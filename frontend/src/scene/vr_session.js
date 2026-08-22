import * as THREE from 'three'
import { refreshNativeVRJobs } from '../api/client.js'

const VIEW_SIZE_METERS = 0.55
const VIEW_DISTANCE_METERS = 0.8

function _durationLabel(milliseconds) {
  if (!Number.isFinite(milliseconds)) return 'unavailable'
  return milliseconds >= 1000
    ? `${(milliseconds / 1000).toFixed(1)} s`
    : `${milliseconds.toFixed(1)} ms`
}

function _errorMessage(error, secureContext) {
  if (!secureContext) {
    return 'VR requires NADOC to be opened from localhost or HTTPS.'
  }
  if (error?.name === 'NotSupportedError') {
    return 'Immersive VR is not available to this browser. Start SteamVR and use a WebXR-capable browser.'
  }
  if (error?.name === 'SecurityError') {
    return 'The browser blocked VR. Open NADOC from localhost or HTTPS and select View in VR again.'
  }
  const detail = error?.message ? `: ${error.message}` : ''
  return `Could not start VR${detail}`
}

/**
 * Connect the current Three.js scene to an immersive WebXR session.
 *
 * NADOC models use nanometres as scene units while WebXR uses metres. A
 * temporary XR camera rig supplies the world-units-per-metre conversion and
 * places the current scene at a comfortable inspection distance. Scene objects
 * are never reparented, so normal reactive renderer updates remain safe in VR.
 */
export function initVRSession({
  renderer,
  scene,
  camera,
  button,
  getRenderCamera = () => camera,
  setMenuToggle = () => {},
  showToast = () => {},
  xr = globalThis.navigator?.xr,
  secureContext = globalThis.isSecureContext ?? true,
  native = null,
  nativePollIntervalMs = 1000,
  nativeEventPollIntervalMs = 50,
  nativeJobPollIntervalMs = 1500,
  publishNativeJobs = refreshNativeVRJobs,
  onNativeEvent = null,
} = {}) {
  let session = null
  let nativeActive = false
  let nativePollTimer = null
  let nativeEventTimer = null
  let nativeJobPollTimer = null
  let nativePublishQueued = false
  let nativePublishPromise = null
  let lastNativeEventSequence = 0
  let lastNativeSelectSequence = 0
  let lastNativeLevelSequence = 0
  let lastNativeStyleSequence = 0
  let lastNativeToolSequence = 0
  let lastNativeToolConfigSequence = 0
  let lastNativePlanePickSequence = 0
  let lastNativeTransformSequence = 0
  let nativeTimingReported = false
  let cameraRig = null
  let cameraSnapshot = null
  let starting = false
  let ending = false
  let disposed = false

  const label = button?.querySelector('.vr-menu-label')

  function _setButtonState({ active = false, busy = false } = {}) {
    setMenuToggle(button?.id, active)
    if (button) {
      button.disabled = busy
      button.setAttribute('aria-pressed', String(active))
    }
    if (label) label.textContent = active ? 'Exit VR' : (busy ? 'Starting VR…' : 'View in VR')
  }

  function _sceneBounds() {
    const bounds = new THREE.Box3()
    for (const child of scene.children) {
      if (child === cameraRig || child.isLight || child.isCamera || !child.visible) continue
      bounds.expandByObject(child, true)
    }
    return bounds
  }

  function _installCameraRig() {
    scene.updateWorldMatrix(true, true)
    camera.updateWorldMatrix(true, false)

    const bounds = _sceneBounds()
    const center = bounds.isEmpty()
      ? new THREE.Vector3()
      : bounds.getCenter(new THREE.Vector3())
    const size = bounds.isEmpty()
      ? new THREE.Vector3(1, 1, 1)
      : bounds.getSize(new THREE.Vector3())
    const maxDimension = Math.max(size.x, size.y, size.z, Number.EPSILON)
    const worldUnitsPerMeter = maxDimension / VIEW_SIZE_METERS
    const forward = camera.getWorldDirection(new THREE.Vector3()).normalize()
    const worldQuaternion = camera.getWorldQuaternion(new THREE.Quaternion())
    const parent = camera.parent

    cameraSnapshot = {
      parent,
      parentIndex: parent?.children.indexOf(camera) ?? -1,
      position: camera.position.clone(),
      quaternion: camera.quaternion.clone(),
      scale: camera.scale.clone(),
      up: camera.up.clone(),
      fov: camera.fov,
      zoom: camera.zoom,
    }

    camera.removeFromParent()
    cameraRig = new THREE.Group()
    cameraRig.name = 'nadoc-vr-camera-rig'
    cameraRig.position.copy(center).addScaledVector(forward, -VIEW_DISTANCE_METERS * worldUnitsPerMeter)
    cameraRig.quaternion.copy(worldQuaternion)
    cameraRig.scale.setScalar(worldUnitsPerMeter)
    scene.add(cameraRig)
    cameraRig.add(camera)
    camera.position.set(0, 0, 0)
    camera.quaternion.identity()
    camera.scale.set(1, 1, 1)
    cameraRig.updateMatrixWorld(true)
  }

  function _restoreCamera() {
    if (!cameraRig || !cameraSnapshot) return

    cameraRig.remove(camera)
    scene.remove(cameraRig)
    const { parent, parentIndex, position, quaternion, scale, up, fov, zoom } = cameraSnapshot
    if (parent) {
      parent.add(camera)
      if (parentIndex >= 0) {
        const currentIndex = parent.children.indexOf(camera)
        parent.children.splice(currentIndex, 1)
        parent.children.splice(Math.min(parentIndex, parent.children.length), 0, camera)
      }
    }
    camera.position.copy(position)
    camera.quaternion.copy(quaternion)
    camera.scale.copy(scale)
    camera.up.copy(up)
    camera.fov = fov
    camera.zoom = zoom
    camera.updateProjectionMatrix()
    camera.updateMatrixWorld(true)

    cameraRig = null
    cameraSnapshot = null
  }

  function _onSessionEnd() {
    _restoreCamera()
    session = null
    starting = false
    ending = false
    _setButtonState()
  }

  function _clearNativePoll() {
    if (nativePollTimer !== null) clearTimeout(nativePollTimer)
    nativePollTimer = null
  }

  function _clearNativeEventPoll() {
    if (nativeEventTimer !== null) clearTimeout(nativeEventTimer)
    nativeEventTimer = null
  }

  function _clearNativeJobPoll() {
    if (nativeJobPollTimer !== null) clearTimeout(nativeJobPollTimer)
    nativeJobPollTimer = null
  }

  function _publishNativeState() {
    if (!nativeActive || disposed || typeof publishNativeJobs !== 'function') {
      return Promise.resolve(false)
    }
    nativePublishQueued = true
    if (nativePublishPromise) return nativePublishPromise
    nativePublishPromise = (async () => {
      while (nativePublishQueued && nativeActive && !disposed) {
        nativePublishQueued = false
        try { await publishNativeJobs() } catch { /* retain last complete revision */ }
      }
      return true
    })().finally(() => { nativePublishPromise = null })
    return nativePublishPromise
  }

  function _scheduleNativeJobPoll({ immediate = false } = {}) {
    _clearNativeJobPoll()
    if (!nativeActive || disposed || nativeJobPollIntervalMs <= 0 ||
        typeof publishNativeJobs !== 'function') return
    nativeJobPollTimer = setTimeout(async () => {
      nativeJobPollTimer = null
      await _publishNativeState()
      if (!disposed && nativeActive) _scheduleNativeJobPoll()
    }, immediate ? 0 : nativeJobPollIntervalMs)
  }

  function _scheduleNativeEventPoll() {
    _clearNativeEventPoll()
    if (!nativeActive || disposed || nativeEventPollIntervalMs <= 0 ||
        !native?.event || !onNativeEvent) return
    nativeEventTimer = setTimeout(async () => {
      nativeEventTimer = null
      let event = null
      try { event = await native.event() } catch { /* transient partial record/network */ }
      if (disposed || !nativeActive) return
      const sequence = Number(event?.sequence ?? 0)
      if (Number.isSafeInteger(sequence) && sequence > lastNativeEventSequence) {
        lastNativeEventSequence = sequence
        onNativeEvent({ sequence, type: 'hover', identity: event?.hover_identity ?? null })
        const selectSequence = Number(event?.select_sequence ?? 0)
        if (Number.isSafeInteger(selectSequence) &&
            selectSequence > lastNativeSelectSequence) {
          lastNativeSelectSequence = selectSequence
          onNativeEvent({
            sequence: selectSequence,
            type: 'select',
            identity: event?.select_identity ?? null,
            identities: Array.isArray(event?.select_identities)
              ? event.select_identities.filter(identity => typeof identity === 'string').slice(0, 16)
              : (typeof event?.select_identity === 'string' ? [event.select_identity] : []),
          })
        }
        const levelSequence = Number(event?.level_sequence ?? 0)
        if (Number.isSafeInteger(levelSequence) &&
            levelSequence > lastNativeLevelSequence) {
          lastNativeLevelSequence = levelSequence
          onNativeEvent({
            sequence: levelSequence,
            type: 'selection_level',
            level: event?.selection_level ?? 'default',
          })
        }
        const styleSequence = Number(event?.style_sequence ?? 0)
        if (Number.isSafeInteger(styleSequence) &&
            styleSequence > lastNativeStyleSequence &&
            ['cylinders', 'full', 'ballstick', 'stick'].includes(event?.representation) &&
            ['strand', 'base', 'cluster', 'cpk'].includes(event?.coloring)) {
          lastNativeStyleSequence = styleSequence
          onNativeEvent({
            sequence: styleSequence,
            type: 'style',
            representation: event.representation,
            coloring: event.coloring,
          })
        }
        const toolSequence = Number(event?.tool_sequence ?? 0)
        if (Number.isSafeInteger(toolSequence) &&
            toolSequence > lastNativeToolSequence) {
          lastNativeToolSequence = toolSequence
          onNativeEvent({
            sequence: toolSequence,
            type: 'tool',
            mode: event?.tool_mode ?? 'inspect',
            action: event?.tool_action ?? 'activate',
            targetIdentity: typeof event?.tool_target_identity === 'string'
              ? event.tool_target_identity : null,
            targetKind: typeof event?.tool_target_kind === 'string'
              ? event.tool_target_kind : 'none',
            targetOwnerTokens: Array.isArray(event?.tool_target_owner_tokens)
              ? event.tool_target_owner_tokens.filter(token => typeof token === 'string').slice(0, 8)
              : [],
          })
        }
        const toolConfigSequence = Number(event?.tool_config_sequence ?? 0)
        if (Number.isSafeInteger(toolConfigSequence) &&
            toolConfigSequence > lastNativeToolConfigSequence &&
            (event?.tool_config === null || typeof event?.tool_config === 'object')) {
          lastNativeToolConfigSequence = toolConfigSequence
          onNativeEvent({
            sequence: toolConfigSequence,
            type: 'tool_config',
            draft: event.tool_config === null ? null : structuredClone(event.tool_config),
          })
        }
        const planePickSequence = Number(event?.plane_pick_sequence ?? 0)
        const planePickConfigSequence = Number(event?.plane_pick_config_sequence ?? 0)
        if (Number.isSafeInteger(planePickSequence) &&
            planePickSequence > lastNativePlanePickSequence &&
            Number.isSafeInteger(planePickConfigSequence) && planePickConfigSequence > 0 &&
            ['a', 'b'].includes(event?.plane_pick_slot) &&
            typeof event?.plane_pick_identity === 'string' && event.plane_pick_identity) {
          lastNativePlanePickSequence = planePickSequence
          onNativeEvent({
            sequence: planePickSequence,
            type: 'plane_pick',
            toolConfigSequence: planePickConfigSequence,
            slot: event.plane_pick_slot,
            identity: event.plane_pick_identity,
          })
        }
        const transformSequence = Number(event?.transform_sequence ?? 0)
        const transformMatrix = event?.transform_matrix
        if (Number.isSafeInteger(transformSequence) &&
            transformSequence > lastNativeTransformSequence &&
            Array.isArray(transformMatrix) && transformMatrix.length === 16 &&
            transformMatrix.every(Number.isFinite)) {
          lastNativeTransformSequence = transformSequence
          onNativeEvent({
            sequence: transformSequence,
            type: 'tool_transform',
            matrix: [...transformMatrix],
          })
        }
      }
      _scheduleNativeEventPoll()
    }, nativeEventPollIntervalMs)
  }

  function _setNativeActive(active) {
    nativeActive = active
    if (!active) {
      _clearNativePoll()
      _clearNativeEventPoll()
      _clearNativeJobPoll()
      if (lastNativeEventSequence > 0) {
        onNativeEvent?.({ sequence: lastNativeEventSequence, type: 'hover', identity: null })
      }
      onNativeEvent?.({ type: 'native_session_end' })
    } else {
      lastNativeEventSequence = 0
      lastNativeSelectSequence = 0
      lastNativeLevelSequence = 0
      lastNativeStyleSequence = 0
      lastNativeToolSequence = 0
      lastNativeToolConfigSequence = 0
      lastNativePlanePickSequence = 0
      lastNativeTransformSequence = 0
      nativeTimingReported = false
      _scheduleNativeEventPoll()
      _scheduleNativeJobPoll({ immediate: true })
    }
    _setButtonState({ active })
  }

  function _scheduleNativePoll() {
    _clearNativePoll()
    if (!nativeActive || disposed || nativePollIntervalMs <= 0 || !native?.status) return
    nativePollTimer = setTimeout(async () => {
      nativePollTimer = null
      let status = null
      try { status = await native.status() } catch { /* next user action can retry */ }
      if (disposed || !nativeActive) return
      if (status?.running) {
        const timing = status?.timing
        if (!nativeTimingReported && timing?.first_frame_ready === true) {
          nativeTimingReported = true
          const totalMs = Number.isFinite(timing.click_to_first_frame_ms)
            ? timing.click_to_first_frame_ms : timing.launch_to_first_frame_ms
          showToast(
            `VR first frame submitted in ${_durationLabel(totalMs)} ` +
            `(jobs ${_durationLabel(timing.job_snapshot_ms)}; snapshot ` +
            `${_durationLabel(timing.snapshot_ms)}; viewer ` +
            `${_durationLabel(timing.process_to_first_frame_ms)}). ` +
            `Frame CPU ${_durationLabel(timing.first_frame_cpu_ms)} / ` +
            `${_durationLabel(timing.display_period_ms)} runtime period.`,
          )
        }
        _scheduleNativePoll()
      }
      else _setNativeActive(false)
    }, nativePollIntervalMs)
  }

  function _nativeFailureMessage() {
    return native?.errorMessage?.()
      || 'Could not start the native VR viewer. Make sure SteamVR is running and try again.'
  }

  async function _enterNative() {
    if (!native?.launch) {
      showToast('This browser does not provide WebXR immersive VR.', { severity: 'error' })
      return false
    }
    starting = true
    _setButtonState({ busy: true })
    let status = null
    try { status = await native.launch() } catch { /* API client reports the detail */ }
    starting = false
    if (!status?.running) {
      _setButtonState()
      showToast(_nativeFailureMessage(), { severity: 'error' })
      return false
    }
    _setNativeActive(true)
    _scheduleNativePoll()
    showToast('VR started. The desktop window mirrors the physical HMD left eye. Trigger: grab · right trackpad: select · both triggers: resize · menu: options.')
    return true
  }

  async function isSupported() {
    if (xr?.isSessionSupported) {
      try {
        if (await xr.isSessionSupported('immersive-vr')) return true
      } catch { /* try the native companion */ }
    }
    if (!native?.status) return false
    try { return (await native.status())?.available === true } catch { return false }
  }

  async function enter() {
    if (session || nativeActive || starting) return true
    if (!camera?.isPerspectiveCamera || getRenderCamera() !== camera) {
      showToast('Exit the current 2D or photo view before entering VR.', { severity: 'error' })
      return false
    }

    if (!xr?.requestSession) return _enterNative()

    starting = true
    _setButtonState({ busy: true })

    try {
      // requestSession is deliberately the first awaited operation: browsers
      // require it to consume the transient user activation from the menu click.
      const nextSession = await xr.requestSession('immersive-vr', {
        optionalFeatures: ['local-floor', 'bounded-floor'],
      })
      session = nextSession
      session.addEventListener('end', _onSessionEnd, { once: true })

      // `local` starts at the headset pose and does not require Room Setup,
      // making the basic viewer usable with a single Lighthouse/base station.
      renderer.xr.setReferenceSpaceType('local')
      _installCameraRig()
      await renderer.xr.setSession(session)

      starting = false
      _setButtonState({ active: true })
      showToast('VR view started. Move your head to inspect the structure.')
      return true
    } catch (error) {
      const failedSession = session
      session = null
      starting = false
      _restoreCamera()
      _setButtonState()
      if (failedSession) {
        try { await failedSession.end() } catch { /* already ended */ }
      }
      if (error?.name === 'NotSupportedError' && native?.launch) {
        return _enterNative()
      }
      starting = false
      _setButtonState()
      showToast(_errorMessage(error, secureContext), { severity: 'error' })
      return false
    }
  }

  async function exit() {
    if (nativeActive && !ending) {
      ending = true
      if (button) button.disabled = true
      try { await native?.stop?.() } catch { /* status polling confirms exit */ }
      ending = false
      _setNativeActive(false)
      return true
    }
    if (!session || ending) return false
    ending = true
    if (button) button.disabled = true
    try {
      await session.end()
    } catch {
      _onSessionEnd()
    }
    return true
  }

  async function toggle() {
    return (session || nativeActive) ? exit() : enter()
  }

  const onClick = () => { void toggle() }
  button?.addEventListener('click', onClick)
  _setButtonState()

  // This is advisory only. The button remains actionable so starting SteamVR
  // after page load does not require refreshing NADOC.
  void isSupported().then(supported => {
    if (!button || session || starting) return
    button.dataset.vrSupported = String(supported)
    button.title = supported
      ? (xr?.requestSession
          ? 'View the current 3D scene in an immersive VR headset.'
          : 'View the active Part with NADOC\'s native SteamVR companion.')
      : 'Immersive VR is not currently available to this browser. Start SteamVR or use a WebXR-capable browser.'
  })

  // Reconnect the menu state after a page refresh while the companion is open.
  if (native?.status) {
    void native.status().then(status => {
      if (!disposed && !session && !starting && status?.running) {
        _setNativeActive(true)
        _scheduleNativePoll()
      }
    }).catch(() => {})
  }

  function dispose() {
    disposed = true
    _clearNativePoll()
    _clearNativeEventPoll()
    _clearNativeJobPoll()
    button?.removeEventListener('click', onClick)
    if (session || nativeActive) void exit()
    else _restoreCamera()
  }

  return {
    isSupported,
    enter,
    exit,
    toggle,
    isActive: () => session !== null || nativeActive,
    publishNativeState: _publishNativeState,
    dispose,
  }
}
