/**
 * CSS 3D View Cube — shows current camera orientation as a rotating cube in the
 * viewport corner.  Clicking a face smoothly animates the camera to look from
 * that world-space axis direction, centred on the loaded design's bounding box.
 *
 * Coordinate system note (NADOC):
 *   X = lattice columns, Y = lattice rows (up), Z = helix bp axis
 *
 * CSS 3D uses Y-down (opposite of Three.js Y-up).  The conversion: apply the
 * inverse camera quaternion to the cube, then negate off-diagonal Y elements
 * to flip the Y axis.  The face/normal mapping is verified in comments below.
 */
import * as THREE from 'three'

const SIZE    = 76      // cube face side-length in pixels
const HALF    = SIZE / 2
const CDOT    = 12      // corner dot diameter in pixels
const ANIM_MS = 350     // snap animation duration

// ── Face definitions ─────────────────────────────────────────────────────────
//  cls   — CSS class that positions the face on the cube
//  label — text shown on the face
//  n     — Three.js world direction the camera comes FROM when this face is clicked
//  up    — camera.up to set for that view
//
// CSS ↔ Three.js face mapping (after Y-flip transform):
//   vc-f  (translateZ)            → CSS +Z = Three.js +Z  → camera from +Z
//   vc-b  (rotateY 180°)          → CSS -Z = Three.js -Z  → camera from -Z
//   vc-r  (rotateY  90°)          → CSS +X = Three.js +X  → camera from +X
//   vc-l  (rotateY -90°)          → CSS -X = Three.js -X  → camera from -X
//   vc-u  (rotateX -90°)          → CSS -Y = Three.js +Y  → camera from +Y
//   vc-d  (rotateX  90°)          → CSS +Y = Three.js -Y  → camera from -Y
const FACES = [
  { cls: 'vc-f', label: 'Z+', n: new THREE.Vector3( 0,  0,  1), up: new THREE.Vector3(0,  1,  0) },
  { cls: 'vc-b', label: 'Z−', n: new THREE.Vector3( 0,  0, -1), up: new THREE.Vector3(0,  1,  0) },
  { cls: 'vc-r', label: 'X+', n: new THREE.Vector3( 1,  0,  0), up: new THREE.Vector3(0,  1,  0) },
  { cls: 'vc-l', label: 'X−', n: new THREE.Vector3(-1,  0,  0), up: new THREE.Vector3(0,  1,  0) },
  { cls: 'vc-u', label: 'Y+', n: new THREE.Vector3( 0,  1,  0), up: new THREE.Vector3(0,  0,  1) },
  { cls: 'vc-d', label: 'Y−', n: new THREE.Vector3( 0, -1,  0), up: new THREE.Vector3(0,  0,  1) },
]

// ── Corner definitions ───────────────────────────────────────────────────────
// Each corner sits at the intersection of 3 faces.  CSS position (x=left, y=top
// in the cube div, z=±HALF) maps to Three.js via the same Y-flip as the faces:
//   CSS left-edge (x=0)    → Three.js -X   CSS right-edge (x=SIZE) → Three.js +X
//   CSS top-edge  (y=0)    → Three.js +Y   CSS bottom-edge (y=SIZE)→ Three.js -Y
//   CSS front     (z=+HALF)→ Three.js +Z   CSS back        (z=-HALF)→Three.js -Z
// up=(0,1,0) works for all 8 corners since no diagonal normal is parallel to Y.
const _UP_Y = new THREE.Vector3(0, 1, 0)
const CORNERS = [
  // front face corners (CSS z = +HALF → Three.js +Z)
  { x: 0,    y: 0,    z: +HALF, n: new THREE.Vector3(-1, +1, +1).normalize() },
  { x: SIZE, y: 0,    z: +HALF, n: new THREE.Vector3(+1, +1, +1).normalize() },
  { x: 0,    y: SIZE, z: +HALF, n: new THREE.Vector3(-1, -1, +1).normalize() },
  { x: SIZE, y: SIZE, z: +HALF, n: new THREE.Vector3(+1, -1, +1).normalize() },
  // back face corners (CSS z = -HALF → Three.js -Z)
  { x: 0,    y: 0,    z: -HALF, n: new THREE.Vector3(-1, +1, -1).normalize() },
  { x: SIZE, y: 0,    z: -HALF, n: new THREE.Vector3(+1, +1, -1).normalize() },
  { x: 0,    y: SIZE, z: -HALF, n: new THREE.Vector3(-1, -1, -1).normalize() },
  { x: SIZE, y: SIZE, z: -HALF, n: new THREE.Vector3(+1, -1, -1).normalize() },
]

// ── Injected CSS ─────────────────────────────────────────────────────────────
const STYLE = `
  #vc-wrap {
    position: absolute;
    bottom: 12px; right: 12px;
    width: ${SIZE + 24}px; height: ${SIZE + 24}px;
    perspective: 380px;
    user-select: none;
    z-index: 15;
  }
  #vc-cube {
    position: absolute;
    top: 12px; left: 12px;
    width: ${SIZE}px; height: ${SIZE}px;
    transform-style: preserve-3d;
    pointer-events: none;
  }
  .vc-face {
    position: absolute;
    width: ${SIZE}px; height: ${SIZE}px;
    border: 1px solid rgba(80, 130, 220, 0.40);
    background: rgba(16, 28, 52, 0.68);
    color: #7aa8e0;
    font: bold 11px/1 'Consolas', monospace;
    letter-spacing: 0.03em;
    display: flex; align-items: center; justify-content: center;
    backface-visibility: hidden;
    -webkit-backface-visibility: hidden;
    pointer-events: all;
    cursor: pointer;
    transition: background 0.10s, color 0.10s;
  }
  .vc-face:hover {
    background: rgba(40, 80, 180, 0.85);
    color: #ddeeff;
    border-color: rgba(140, 190, 255, 0.70);
  }
  .vc-f { transform: translateZ(${HALF}px) }
  .vc-b { transform: rotateY(180deg) translateZ(${HALF}px) }
  .vc-r { transform: rotateY( 90deg) translateZ(${HALF}px) }
  .vc-l { transform: rotateY(-90deg) translateZ(${HALF}px) }
  .vc-u { transform: rotateX(-90deg) translateZ(${HALF}px) }
  .vc-d { transform: rotateX( 90deg) translateZ(${HALF}px) }
  .vc-corner {
    position: absolute;
    width: ${CDOT}px; height: ${CDOT}px;
    border-radius: 50%;
    background: rgba(80, 130, 220, 0.30);
    border: 1px solid rgba(80, 130, 220, 0.55);
    pointer-events: all;
    cursor: pointer;
    transition: background 0.10s, border-color 0.10s;
  }
  .vc-corner:hover {
    background: rgba(160, 200, 255, 0.90);
    border-color: rgba(200, 230, 255, 0.95);
  }
`

// ── Public init ───────────────────────────────────────────────────────────────

/**
 * @param {HTMLElement}          container  — #viewport-container
 * @param {THREE.PerspectiveCamera} camera
 * @param {*}                    controls   — OrbitControls / TrackballControls proxy
 * @param {() => THREE.Object3D} getRoot    — returns the design mesh root (may be null)
 */
export function initViewCube(container, camera, controls, getRoot) {
  // Inject CSS
  const styleEl = document.createElement('style')
  styleEl.textContent = STYLE
  document.head.appendChild(styleEl)

  // Build DOM
  const wrap = document.createElement('div')
  wrap.id = 'vc-wrap'

  const cube = document.createElement('div')
  cube.id = 'vc-cube'
  wrap.appendChild(cube)

  for (const face of FACES) {
    const el = document.createElement('div')
    el.className = `vc-face ${face.cls}`
    el.textContent = face.label
    el.addEventListener('click', (e) => {
      e.stopPropagation()
      _snapToNormal(face.n, face.up)
    })
    cube.appendChild(el)
  }

  for (const corner of CORNERS) {
    const el = document.createElement('div')
    el.className = 'vc-corner'
    // translate(-50%,-50%) centers the dot on the corner vertex; translateZ places it in 3D
    el.style.cssText = `left:${corner.x}px; top:${corner.y}px; transform:translate(-50%,-50%) translateZ(${corner.z}px)`
    el.addEventListener('click', e => {
      e.stopPropagation()
      _snapToNormal(corner.n, _UP_Y)
    })
    cube.appendChild(el)
  }

  container.appendChild(wrap)

  // ── Snap / flip animation ───────────────────────────────────────────────────
  let _animRaf = null
  const _tmpBox  = new THREE.Box3()
  const _tmpSize = new THREE.Vector3()
  const _qFlip   = new THREE.Quaternion()

  // If the camera is already looking from `normal` (dot > 0.92 ≈ 22°), spin
  // camera.up 180° around the view axis instead of re-snapping.  This fixes
  // cadnano imports that appear upside-down: click the face you're already on.
  function _snapToNormal(normal, up) {
    if (_animRaf) { cancelAnimationFrame(_animRaf); _animRaf = null }

    const fromDir = camera.position.clone().sub(controls.target).normalize()
    if (fromDir.dot(normal) > 0.92) {
      _startFlip(fromDir)
      return
    }

    // Compute bounding box of the current design (fallback: origin)
    let center = new THREE.Vector3()
    let dist   = 20
    const root = getRoot?.()
    if (root) {
      _tmpBox.makeEmpty().expandByObject(root)
      if (!_tmpBox.isEmpty()) {
        _tmpBox.getCenter(center)
        const radius = _tmpBox.getSize(_tmpSize).length() * 0.5
        dist = (radius / Math.sin(camera.fov * 0.5 * Math.PI / 180)) * 1.1
        dist = Math.max(dist, 5)
      }
    }

    const targetPos   = center.clone().addScaledVector(normal, dist)
    const startPos    = camera.position.clone()
    const startTarget = controls.target.clone()
    const startUp     = camera.up.clone()
    const startTime   = performance.now()

    function frame(now) {
      const raw = Math.min((now - startTime) / ANIM_MS, 1)
      const t = raw < 0.5 ? 2 * raw * raw : -1 + (4 - 2 * raw) * raw

      camera.position.lerpVectors(startPos, targetPos, t)
      controls.target.lerpVectors(startTarget, center, t)
      camera.up.lerpVectors(startUp, up, t).normalize()
      controls.update()

      _animRaf = raw < 1 ? requestAnimationFrame(frame) : null
    }
    _animRaf = requestAnimationFrame(frame)
  }

  // Rotate camera.up 180° around the current view direction via quaternion arc
  // (cannot lerp antipodal vectors — they pass through zero at t=0.5).
  function _startFlip(viewDir) {
    const startUp = camera.up.clone()
    // Rotation axis ⊥ both up and viewDir; gives a smooth arc through ±90°
    let axis = startUp.clone().cross(viewDir)
    if (axis.lengthSq() < 1e-6) {
      // up ∥ viewDir (degenerate) — pick any perpendicular
      axis.set(Math.abs(viewDir.x) < 0.9 ? 1 : 0, Math.abs(viewDir.x) < 0.9 ? 0 : 1, 0)
    }
    axis.normalize()
    const startTime = performance.now()

    function frame(now) {
      const raw = Math.min((now - startTime) / ANIM_MS, 1)
      const t   = raw < 0.5 ? 2 * raw * raw : -1 + (4 - 2 * raw) * raw
      _qFlip.setFromAxisAngle(axis, Math.PI * t)
      camera.up.copy(startUp).applyQuaternion(_qFlip).normalize()
      controls.update()
      _animRaf = raw < 1 ? requestAnimationFrame(frame) : null
    }
    _animRaf = requestAnimationFrame(frame)
  }

  // ── Cube orientation sync ───────────────────────────────────────────────────
  // We apply the inverse of the camera's rotation to the cube so it appears as
  // a world-fixed object as the camera orbits.  CSS 3D uses Y-down, Three.js
  // uses Y-up, so we conjugate by the Y-flip matrix S = diag(1,−1,1):
  //   R_css = S · R_inv · S  →  negate elements where exactly one index is Y.
  // In column-major layout: indices 1, 4, 6, 9  (row=1⊕col=1, excluding [1,1]).
  const _m = new THREE.Matrix4()
  const _q = new THREE.Quaternion()

  function _syncCube() {
    _q.copy(camera.quaternion).conjugate()
    _m.makeRotationFromQuaternion(_q)
    const e = _m.elements
    e[1] = -e[1]; e[4] = -e[4]; e[6] = -e[6]; e[9] = -e[9]
    cube.style.transform = `matrix3d(${e.join(',')})`
  }

  // Run a dedicated rAF loop — lightweight (one CSS write per frame).
  ;(function _loop() { _syncCube(); requestAnimationFrame(_loop) })()

  // ── Public API ──────────────────────────────────────────────────────────────
  return {
    show()               { wrap.style.display = '' },
    hide()               { wrap.style.display = 'none' },
    snapToNormal(n, up)  { _snapToNormal(n, up) },
  }
}
