/**
 * scene/cando_cylinders.js — the "CanDo style output" cylinder overlay.
 *
 * Draws the FEM-predicted shape exactly the way CanDo does: one tube per helix, a
 * chain of short cylinders (radius = duplex radius) threaded through the per-bp axis
 * positions, plus thin connector cylinders at the crossovers (the "joints").  PURE
 * CYLINDERS — no sphere fillers — so it keeps CanDo's characteristic "coin-stacked"
 * look (one flat disc per base pair) rather than a smooth tube.
 *
 * Each segment is heat-mapped by the RMSF at its base pair with CanDo's jet colour
 * ramp (bluest = rmsf_min / 0th percentile → reddest = rmsf_p95 / 95th percentile,
 * clamped above), matching CanDo's structure_NMA_RMSF.bild.  Segments with no RMSF
 * (or a job run without NMA) fall back to grey.
 *
 * Standalone representation: the caller hides the native NADOC model (via
 * setDesignVisible) so only these tubes show, like the mrDNA CG-beads mode.
 * Display-only / Physical layer — never touches topology.
 *
 * Usage:
 *   const cyl = initCandoCylinders(scene)
 *   cyl.update(data)   // data from GET /cando/jobs/{id}/cylinders
 *   cyl.clear()
 */

import * as THREE from 'three'
import { colormapRGB } from '../ui/colormaps.js'

const _GREY = new THREE.Color(0x8a8a8a)   // fallback when a segment has no RMSF
// Dim the jet ramp: full-saturation jet under an unlit material reads as glaring neon;
// scaling toward ~⅔ brightness keeps the hues but tones it down to CanDo's look.
// Exported so the colour-map legend renders the SAME dimmed jet as the tubes.
export const JET_BRIGHTNESS = 0.62

// Unit cylinder aligned along +Y (height 1), scaled per-instance.
const _CYL_GEO = new THREE.CylinderGeometry(1, 1, 1, 10, 1)
const _Y = new THREE.Vector3(0, 1, 0)
const _a = new THREE.Vector3()
const _b = new THREE.Vector3()
const _mid = new THREE.Vector3()
const _dir = new THREE.Vector3()
const _quat = new THREE.Quaternion()
const _scale = new THREE.Vector3()
const _m = new THREE.Matrix4()
const _col = new THREE.Color()

// CanDo's RMSF heat map is a jet ramp.  We use the VIVID variant (bright blue → cyan →
// green → yellow → red, no dark blue/red tails) so the low-flexibility core reads as a
// bright blue rather than near-black — matching how CanDo's render actually looks (their
// dark ramp tails are lifted by Chimera's lighting; our unlit material would show them raw).
const _JET = [[0, 0, 1], [0, 1, 1], [0, 1, 0], [1, 1, 0], [1, 0, 0]]

/** CanDo-style jet heat-map colour for t∈[0,1] → [r,g,b] in [0,1].
 *  t=0 → blue, 0.25 → cyan, 0.5 → green, 0.75 → yellow, 1 → red. */
export function jetRGB(t) {
  const x = Math.max(0, Math.min(1, Number.isFinite(t) ? t : 0))
  const seg = x * (_JET.length - 1)
  const i = Math.min(_JET.length - 2, Math.floor(seg))
  const f = seg - i
  const a = _JET[i], b = _JET[i + 1]
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f]
}

/**
 * Flatten cylinder data into coloured segments (pure, unit-tested).  Each tube segment
 * joins consecutive axis nodes and carries the MEAN RMSF of its two endpoints; joints
 * carry their own precomputed RMSF.  Returns { tubes, joints } as
 * [{ a:[x,y,z], b:[x,y,z], rmsf: number|null }].
 */
export function cylinderSegments(data) {
  const tubes = []
  for (const h of data?.helices || []) {
    const pts = h.points || []
    const rm = h.rmsf || []
    for (let i = 1; i < pts.length; i++) {
      tubes.push({ a: pts[i - 1], b: pts[i], rmsf: _mean(rm[i - 1], rm[i]) })
    }
  }
  const joints = []
  const jr = data?.joint_rmsf || []
  ;(data?.joints || []).forEach((j, i) => {
    if (Array.isArray(j) && j.length === 2) {
      joints.push({ a: j[0], b: j[1], rmsf: Number.isFinite(jr[i]) ? jr[i] : null })
    }
  })
  return { tubes, joints }
}

function _mean(x, y) {
  const v = [x, y].filter((n) => Number.isFinite(n))
  return v.length ? v.reduce((s, n) => s + n, 0) / v.length : null
}

export function initCandoCylinders(scene) {
  const _meshes = []

  function clear() {
    for (const m of _meshes) {
      scene.remove(m)
      m.material?.dispose?.()
      m.dispose?.()
    }
    _meshes.length = 0
  }

  /** One InstancedMesh of cylinders for `segs` ({a,b,rmsf}); per-instance colormap
   *  colour over [lo,hi] (grey when a segment has no RMSF / no ramp).  `colormap`
   *  names the shared registry ramp (default jet — CanDo's heat map). */
  function _instanced(segs, radius, lo, hi, hasRmsf, colormap = 'jet') {
    if (!segs.length) return
    // Unlit white material tinted PER-INSTANCE via instanceColor (setColorAt) — the jet
    // ramp then reads VIVID like CanDo's flat colormap render, independent of scene
    // lighting.  NB do NOT set vertexColors:true — that looks for geometry vertex colours
    // (the cylinder has none → renders black); instanceColor is the per-instance channel.
    const mat = new THREE.MeshBasicMaterial({ color: 0xffffff })
    const mesh = new THREE.InstancedMesh(_CYL_GEO, mat, segs.length)
    mesh.frustumCulled = false
    const span = hi - lo
    let n = 0
    for (const s of segs) {
      const p = s.a, q = s.b
      if (!p || !q) continue
      _a.set(p[0], p[1], p[2])
      _b.set(q[0], q[1], q[2])
      _dir.subVectors(_b, _a)
      const len = _dir.length()
      if (len < 1e-6) continue
      _dir.divideScalar(len)
      _mid.addVectors(_a, _b).multiplyScalar(0.5)
      _quat.setFromUnitVectors(_Y, _dir)
      _scale.set(radius, len, radius)
      _m.compose(_mid, _quat, _scale)
      mesh.setMatrixAt(n, _m)
      if (hasRmsf && Number.isFinite(s.rmsf) && span > 1e-9) {
        const [r, g, bl] = colormapRGB(colormap, (s.rmsf - lo) / span)
        // treat ramp values as display (sRGB) colours, dimmed from neon toward CanDo's tone
        _col.setRGB(r * JET_BRIGHTNESS, g * JET_BRIGHTNESS, bl * JET_BRIGHTNESS, THREE.SRGBColorSpace)
      } else {
        _col.copy(_GREY)
      }
      mesh.setColorAt(n, _col)
      n++
    }
    mesh.count = n
    mesh.instanceMatrix.needsUpdate = true
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
    scene.add(mesh)
    _meshes.push(mesh)
  }

  let _lastData = null   // cached response so the colour scale / colormap can recolour live

  /** Rebuild the tube overlay from the cached data at [lo,hi] on `colormap`. */
  function _draw(lo, hi, colormap) {
    clear()
    const data = _lastData
    if (!data || (!data.helices?.length && !data.joints?.length)) return
    const { tubes, joints } = cylinderSegments(data)
    const tubeR = Number.isFinite(data.tube_radius_nm) ? data.tube_radius_nm : 1.125
    const jointR = Number.isFinite(data.joint_radius_nm) ? data.joint_radius_nm : 0.2
    const hasRmsf = !!data.has_rmsf
    _instanced(tubes, tubeR, lo, hi, hasRmsf, colormap)
    _instanced(joints, jointR, lo, hi, hasRmsf, colormap)
  }

  return {
    /** Rebuild the tube overlay from a /cando/jobs/{id}/cylinders response.  Optional
     *  {lo, hi, colormap} override the RMSF window + ramp (default data min→p95, jet). */
    update(data, { lo = null, hi = null, colormap = 'jet' } = {}) {
      _lastData = data
      const dlo = Number.isFinite(lo) ? lo : (Number.isFinite(data?.rmsf_min) ? data.rmsf_min : 0)
      const dhi = Number.isFinite(hi) ? hi : (Number.isFinite(data?.rmsf_p95) ? data.rmsf_p95 : 0)
      _draw(dlo, dhi, colormap)
    },
    /** Recolour the current tubes to a new RMSF window / colormap (no re-fetch). */
    recolor(lo, hi, colormap = 'jet') { _draw(lo, hi, colormap) },
    clear,
    active: () => _meshes.length > 0,
  }
}
