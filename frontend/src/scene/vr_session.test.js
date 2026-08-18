import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { initVRSession } from './vr_session.js'

class FakeSession extends EventTarget {
  async end() { this.dispatchEvent(new Event('end')) }
}

function makeHarness({
  requestError = null,
  xr: xrOverride,
  native = null,
  nativePollIntervalMs = 0,
  nativeEventPollIntervalMs = 0,
  onNativeEvent = null,
} = {}) {
  document.body.innerHTML = `
    <button id="menu-help-view-vr" aria-pressed="false">
      <span class="vr-menu-label">View in VR</span><span class="menu-toggle-pill"></span>
    </button>`
  const button = document.getElementById('menu-help-view-vr')
  const session = new FakeSession()
  const defaultXr = {
    isSessionSupported: vi.fn().mockResolvedValue(true),
    requestSession: requestError
      ? vi.fn().mockRejectedValue(requestError)
      : vi.fn().mockResolvedValue(session),
  }
  const xr = xrOverride === undefined ? defaultXr : xrOverride
  const renderer = {
    xr: {
      setReferenceSpaceType: vi.fn(),
      setSession: vi.fn().mockResolvedValue(undefined),
    },
  }
  const scene = new THREE.Scene()
  const camera = new THREE.PerspectiveCamera(55, 1, 0.1, 2000)
  camera.position.set(6, 3, 7)
  camera.lookAt(0, 0, 7)
  const light = new THREE.AmbientLight()
  const model = new THREE.Mesh(new THREE.BoxGeometry(20, 10, 5), new THREE.MeshBasicMaterial())
  model.position.set(10, 0, 7)
  scene.add(light, model)

  const setMenuToggle = vi.fn((id, on) => button.classList.toggle('is-on', on))
  const showToast = vi.fn()
  const controller = initVRSession({
    renderer, scene, camera, button, xr, native, nativePollIntervalMs,
    nativeEventPollIntervalMs, onNativeEvent,
    setMenuToggle, showToast,
  })

  return {
    button, session, xr, renderer, scene, camera, light, model, controller,
    setMenuToggle, showToast,
  }
}

describe('initVRSession', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('starts from the menu click, fits an XR camera rig to the scene, and marks the toggle on', async () => {
    const h = makeHarness()
    h.button.click()
    await vi.waitFor(() => expect(h.controller.isActive()).toBe(true))

    expect(h.xr.requestSession).toHaveBeenCalledWith('immersive-vr', {
      optionalFeatures: ['local-floor', 'bounded-floor'],
    })
    expect(h.renderer.xr.setReferenceSpaceType).toHaveBeenCalledWith('local')
    expect(h.renderer.xr.setSession).toHaveBeenCalledWith(h.session)
    expect(h.button.getAttribute('aria-pressed')).toBe('true')
    expect(h.button.classList.contains('is-on')).toBe(true)
    expect(h.button.querySelector('.vr-menu-label').textContent).toBe('Exit VR')

    const rig = h.scene.getObjectByName('nadoc-vr-camera-rig')
    expect(rig).toBeTruthy()
    expect(rig.children).toContain(h.camera)
    expect(h.model.parent).toBe(h.scene)
    expect(h.light.parent).toBe(h.scene)
    expect(rig.scale.x).toBeCloseTo(20 / 0.55)
    const center = new THREE.Box3().setFromObject(h.model, true).getCenter(new THREE.Vector3())
    const centerFromViewer = center.clone().sub(rig.position).applyQuaternion(rig.quaternion.clone().invert())
    expect(centerFromViewer.x / rig.scale.x).toBeCloseTo(0)
    expect(centerFromViewer.y / rig.scale.y).toBeCloseTo(0)
    expect(centerFromViewer.z / rig.scale.z).toBeCloseTo(-0.8)
  })

  it('ends from the same menu item and restores the exact original scene order', async () => {
    const h = makeHarness()
    const original = [...h.scene.children]
    const cameraPosition = h.camera.position.clone()
    const cameraQuaternion = h.camera.quaternion.clone()
    await h.controller.enter()
    await h.controller.exit()

    expect(h.controller.isActive()).toBe(false)
    expect(h.scene.children).toEqual(original)
    expect(h.camera.parent).toBeNull()
    expect(h.camera.position).toEqual(cameraPosition)
    expect(h.camera.quaternion.angleTo(cameraQuaternion)).toBeCloseTo(0)
    expect(h.scene.getObjectByName('nadoc-vr-camera-rig')).toBeUndefined()
    expect(h.button.getAttribute('aria-pressed')).toBe('false')
    expect(h.button.querySelector('.vr-menu-label').textContent).toBe('View in VR')
  })

  it('leaves reactive scene content untouched while VR is active', async () => {
    const h = makeHarness()
    await h.controller.enter()
    const added = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshBasicMaterial())
    h.scene.add(added)

    expect(added.parent).toBe(h.scene)
    expect(h.model.parent).toBe(h.scene)
    await h.controller.exit()
    expect(added.parent).toBe(h.scene)
  })

  it('reports an unavailable runtime without changing the scene', async () => {
    const error = new DOMException('No runtime', 'NotSupportedError')
    const h = makeHarness({ requestError: error })
    const original = [...h.scene.children]

    await expect(h.controller.enter()).resolves.toBe(false)
    expect(h.scene.children).toEqual(original)
    expect(h.controller.isActive()).toBe(false)
    expect(h.showToast).toHaveBeenCalledWith(
      expect.stringContaining('not available to this browser'),
      { severity: 'error' },
    )
  })

  it('uses the native OpenXR companion when Linux Firefox has no WebXR', async () => {
    const native = {
      status: vi.fn().mockResolvedValue({ available: true, running: false }),
      launch: vi.fn().mockResolvedValue({ available: true, running: true, pid: 1234 }),
      stop: vi.fn().mockResolvedValue({ available: true, running: false }),
      errorMessage: vi.fn(),
    }
    const h = makeHarness({ xr: null, native })

    await expect(h.controller.enter()).resolves.toBe(true)
    expect(native.launch).toHaveBeenCalledOnce()
    expect(h.renderer.xr.setSession).not.toHaveBeenCalled()
    expect(h.controller.isActive()).toBe(true)
    expect(h.button.querySelector('.vr-menu-label').textContent).toBe('Exit VR')

    await expect(h.controller.exit()).resolves.toBe(true)
    expect(native.stop).toHaveBeenCalledOnce()
    expect(h.controller.isActive()).toBe(false)
    expect(h.button.querySelector('.vr-menu-label').textContent).toBe('View in VR')
  })

  it('reports native first-frame timing once per launch', async () => {
    vi.useFakeTimers()
    const native = {
      status: vi.fn().mockResolvedValue({ available: true, running: false }),
      launch: vi.fn().mockResolvedValue({ available: true, running: true, pid: 1234 }),
      stop: vi.fn().mockResolvedValue({ available: true, running: false }),
    }
    const h = makeHarness({ xr: null, native, nativePollIntervalMs: 10 })
    await vi.advanceTimersByTimeAsync(0)
    native.status.mockResolvedValue({
      available: true,
      running: true,
      timing: {
        first_frame_ready: true,
        snapshot_ms: 54_800,
        process_to_first_frame_ms: 1400,
        launch_to_first_frame_ms: 56_200,
        click_to_first_frame_ms: 56_500,
        job_snapshot_ms: 300,
        first_frame_cpu_ms: 8.5,
        display_period_ms: 11.111,
      },
    })

    await h.controller.enter()
    await vi.advanceTimersByTimeAsync(25)
    const timingCalls = h.showToast.mock.calls.filter(([message]) =>
      message.startsWith('VR first frame submitted'))
    expect(timingCalls).toEqual([[
      'VR first frame submitted in 56.5 s (jobs 300.0 ms; snapshot 54.8 s; viewer 1.4 s). ' +
      'Frame CPU 8.5 ms / 11.1 ms runtime period.',
    ]])
    await h.controller.exit()
    vi.useRealTimers()
  })

  it('delivers sequenced native events only while the companion is active', async () => {
    vi.useFakeTimers()
    const onNativeEvent = vi.fn()
    const native = {
      status: vi.fn().mockResolvedValue({ available: true, running: false }),
      launch: vi.fn().mockResolvedValue({ available: true, running: true, pid: 1234 }),
      stop: vi.fn().mockResolvedValue({ available: true, running: false }),
      event: vi.fn()
        .mockResolvedValueOnce({
          sequence: 2,
          hover_identity: 'nuc:s1',
          select_sequence: 1,
          select_identity: 'nuc:s1',
          level_sequence: 1,
          selection_level: 'domain',
          tool_sequence: 1,
          tool_mode: 'twist',
          tool_action: 'preview',
          tool_target_identity: 'nuc:s1',
          tool_target_kind: 'domain',
          tool_target_owner_tokens: ['domain-token'],
          tool_config_sequence: 1,
          tool_config: {
            mode: 'twist',
            target_identity: 'nuc:s1',
            target_kind: 'domain',
            target_owner_tokens: ['domain-token'],
            plane_a_bp: null,
            plane_b_bp: null,
            amount_mode: 'total_degrees',
            amount: 90,
          },
          plane_pick_sequence: 1,
          plane_pick_config_sequence: 1,
          plane_pick_slot: 'a',
          plane_pick_identity: 'nuc:s1:0:h1:12:FORWARD:0',
          transform_sequence: 1,
          transform_matrix: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 2, 3, 4, 1],
        })
        .mockResolvedValue({
          sequence: 2,
          hover_identity: 'nuc:s1',
          select_sequence: 1,
          select_identity: 'nuc:s1',
          level_sequence: 1,
          selection_level: 'domain',
          tool_sequence: 1,
          tool_mode: 'twist',
          tool_action: 'preview',
          tool_target_identity: 'nuc:s1',
          tool_target_kind: 'domain',
          tool_target_owner_tokens: ['domain-token'],
          tool_config_sequence: 1,
          tool_config: {
            mode: 'twist',
            target_identity: 'nuc:s1',
            target_kind: 'domain',
            target_owner_tokens: ['domain-token'],
            plane_a_bp: null,
            plane_b_bp: null,
            amount_mode: 'total_degrees',
            amount: 90,
          },
          plane_pick_sequence: 1,
          plane_pick_config_sequence: 1,
          plane_pick_slot: 'a',
          plane_pick_identity: 'nuc:s1:0:h1:12:FORWARD:0',
          transform_sequence: 1,
          transform_matrix: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 2, 3, 4, 1],
        }),
    }
    const h = makeHarness({
      xr: null,
      native,
      nativeEventPollIntervalMs: 10,
      onNativeEvent,
    })

    await h.controller.enter()
    await vi.advanceTimersByTimeAsync(25)
    expect(onNativeEvent.mock.calls).toEqual([
      [{ sequence: 2, type: 'hover', identity: 'nuc:s1' }],
      [{ sequence: 1, type: 'select', identity: 'nuc:s1' }],
      [{ sequence: 1, type: 'selection_level', level: 'domain' }],
      [{
        sequence: 1, type: 'tool', mode: 'twist', action: 'preview',
        targetIdentity: 'nuc:s1', targetKind: 'domain',
        targetOwnerTokens: ['domain-token'],
      }],
      [{
        sequence: 1,
        type: 'tool_config',
        draft: {
          mode: 'twist',
          target_identity: 'nuc:s1',
          target_kind: 'domain',
          target_owner_tokens: ['domain-token'],
          plane_a_bp: null,
          plane_b_bp: null,
          amount_mode: 'total_degrees',
          amount: 90,
        },
      }],
      [{
        sequence: 1,
        type: 'plane_pick',
        toolConfigSequence: 1,
        slot: 'a',
        identity: 'nuc:s1:0:h1:12:FORWARD:0',
      }],
      [{
        sequence: 1,
        type: 'tool_transform',
        matrix: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 2, 3, 4, 1],
      }],
    ])

    await h.controller.exit()
    expect(onNativeEvent.mock.calls.slice(-2)).toEqual([
      [{ sequence: 2, type: 'hover', identity: null }],
      [{ type: 'native_session_end' }],
    ])
    const callsAfterExit = native.event.mock.calls.length
    await vi.advanceTimersByTimeAsync(50)
    expect(native.event).toHaveBeenCalledTimes(callsAfterExit)
    vi.useRealTimers()
  })
})
