import * as THREE from 'three'
import { createCrossSectionTransition } from './cross_section_transition.js'

export const CROSS_SECTION_HELP = 'Click or drag to select cells. Tab switches paint/box selection. Next keeps this footprint; Previous returns to it.'

/** Fit into the unobscured canvas region beside the shared tool popup. */
export function crossSectionViewPose(box, normal, up, { aspect = 1, fov = 45, fraction = 1, offset = 0, perspective = false } = {}) {
  if (!box || box.isEmpty()) return null
  const n = normal.clone().normalize(), u = up.clone().normalize()
  const right = new THREE.Vector3().crossVectors(u, n).normalize()
  const direction = perspective ? n.clone().addScaledVector(right, 1.1).addScaledVector(u, 0.65).normalize() : n
  const screenRight = new THREE.Vector3().crossVectors(u, direction).normalize()
  const radius = Math.max(2, box.getSize(new THREE.Vector3()).length() / 2)
  const tangent = Math.tan(THREE.MathUtils.degToRad(fov / 2))
  let distance = radius * 1.15 / Math.sin(Math.atan(tangent * Math.min(1, aspect * fraction)))
  if (!perspective) {
    const center = box.getCenter(new THREE.Vector3())
    const screenUp = new THREE.Vector3().crossVectors(direction, screenRight).normalize()
    distance = 2
    for (const x of [box.min.x, box.max.x]) for (const y of [box.min.y, box.max.y]) for (const z of [box.min.z, box.max.z]) {
      const delta = new THREE.Vector3(x, y, z).sub(center)
      distance = Math.max(distance, delta.dot(direction) + Math.max(
        Math.abs(delta.dot(screenUp)) / tangent,
        Math.abs(delta.dot(screenRight)) / (tangent * aspect * fraction),
      ))
    }
    distance *= 1.1
  }
  const target = box.getCenter(new THREE.Vector3()).addScaledVector(screenRight, -offset * distance * tangent * aspect)
  return { target, position: target.clone().addScaledVector(direction, distance), up: u, distance }
}

/** Shared Extrude/Sweep cross-section camera and picking lifecycle. */
export function createCrossSectionWorkflow({ slicePlane, getCamera, getControls, canvas, popup, beginAuthoringDisplay, transitionOptions }) {
  let active = false, step = 1, priorRotate = true, controlsOwner = null
  let releaseDisplay = null
  const transition = createCrossSectionTransition({ ...transitionOptions, onActive(value) {
    if (popup?.root) popup.root.dataset.cameraTransition = String(value)
  } })
  const interrupt = () => transition.cancel()
  canvas?.addEventListener('pointerdown', interrupt)
  canvas?.addEventListener('wheel', interrupt)
  function fit(perspective = false) {
    const camera = getCamera?.(), controls = getControls?.()
    const box = slicePlane.getAuthoringBounds?.(perspective)
    if (!camera || !controls || !box) return
    const bounds = canvas?.getBoundingClientRect(), tool = popup?.root?.getBoundingClientRect()
    let fraction = 1, offset = 0
    if (bounds?.width && tool?.width && tool.right > bounds.left && tool.left < bounds.right) {
      const left = Math.max(0, tool.left - bounds.left - 16), right = Math.max(0, bounds.right - tool.right - 16)
      const available = Math.max(left, right)
      if (available > 160) {
        fraction = available / bounds.width
        offset = right >= left ? 1 - fraction : fraction - 1
      }
    }
    const pose = crossSectionViewPose(box, slicePlane.getPlaneNormalWorld(), slicePlane.getPlaneUpWorld(), {
      aspect: camera.aspect ?? (bounds?.width / bounds?.height || 1), fov: camera.fov ?? 45, fraction, offset, perspective,
    })
    if (!pose) return
    const zoom = camera.isOrthographicCamera
      ? Math.min((camera.right - camera.left) * fraction, camera.top - camera.bottom) / (box.getSize(new THREE.Vector3()).length() * 1.15)
      : camera.zoom
    transition.move(camera, controls, pose, zoom)
  }
  function setStep(value, { fitView = true } = {}) {
    step = value
    if (!active) {
      active = true; releaseDisplay = beginAuthoringDisplay?.(); controlsOwner = getControls?.(); priorRotate = controlsOwner?.enableRotate ?? true
    }
    slicePlane.setAuthoringStage?.(step === 1 ? 'section' : 'length')
    if (controlsOwner) controlsOwner.enableRotate = step !== 1
    if (fitView) fit(step === 2)
  }
  const unsubscribe = slicePlane.subscribeSource?.(() => {
    if (!active) return
    slicePlane.setAuthoringStage?.(step === 1 ? 'section' : 'length')
    if (controlsOwner) controlsOwner.enableRotate = step !== 1
    if (step === 1) fit(false)
  })
  function close() {
    if (!active) return
    transition.cancel(); releaseDisplay?.(); releaseDisplay = null
    active = false; slicePlane.setAuthoringStage?.(null)
    if (controlsOwner && controlsOwner === getControls?.()) controlsOwner.enableRotate = priorRotate
    controlsOwner = null
  }
  return { setStep, refit: () => { if (active) fit(step === 2) }, close, dispose() { close(); unsubscribe?.(); canvas?.removeEventListener('pointerdown', interrupt); canvas?.removeEventListener('wheel', interrupt) } }
}
