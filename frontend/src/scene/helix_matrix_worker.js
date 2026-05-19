/**
 * helix_matrix_worker — Web Worker that computes per-bp InstancedMesh transform
 * matrices off the main thread. Phase 6a of the path-to-thousands refactor.
 *
 * The worker receives a serializable payload of plain typed arrays + scalars
 * describing the per-bp positions, base normals, axis tangents, etc. for a
 * single design build, and returns 4 packed Float32Arrays of 4x4 column-major
 * matrices (compatible with THREE.InstancedMesh.setMatrixAt / direct
 * `instanceMatrix.array.set`):
 *
 *   beadMatrices    — 16 * (sphereCount + cubeCount) floats. Backbone beads
 *                     (sphere ids first 0..sphereCount-1, then cube ids
 *                     0..cubeCount-1) — translation + identity rotation +
 *                     unit scale. Layout matches the main-thread sphereId /
 *                     cubeId counters, because the worker is told for each
 *                     nuc which mesh it lands on via `beadKind`.
 *   coneMatrices    — 16 * totalCones floats. Cone matrices for consecutive
 *                     bp pairs, with zero XZ scale on cross-helix arcs.
 *   slabMatrices    — 16 * slabCount floats. Slab matrices for base-pair
 *                     orientation boxes (with the precomputed quaternion).
 *   fluoroMatrices  — 16 * fluoroCount floats. Fluorophore beads.
 *
 * The output buffers are returned as Transferable ArrayBuffers (so no copy).
 *
 * The math here MUST match helix_renderer.js's sync per-bp loops:
 *   - Bead matrix = compose(pos, identity_quat, (1,1,1))
 *   - Cone  matrix = compose(midPos, quat_from_Y_to_dir, (r, coneHeight, r))
 *                    where r = 0 for cross-helix cones, else 0.075 (CONE_RADIUS)
 *   - Slab  matrix = compose(slab_center, slab_quat, (length, width, thickness))
 *                    where slab_quat is the basis quaternion from base normal
 *                    and axis tangent (see slabQuaternion in helix_renderer.js).
 *   - Fluoro matrix = compose(pos, identity_quat, (1,1,1))
 *
 * All quaternions/matrices follow Three.js conventions:
 *   - Quaternion (x, y, z, w)
 *   - Matrix4 column-major (te[0..15])
 *
 * The worker is intentionally Three.js-free. The math below is hand-rolled
 * to avoid bundling Three.js into the worker (which would multiply the worker
 * cold-start cost by ~30x and break the threshold heuristic).
 */

// ── Math helpers (pure, no Three.js) ─────────────────────────────────────────

const CONE_RADIUS = 0.075
const HELIX_RADIUS = 1.0
const SLAB_LEN = 0.30
const SLAB_WID = 0.06
const SLAB_THK = 0.70
const SLAB_DIST = 0.55

// In-place quaternion-from-unit-vectors (Three.js's setFromUnitVectors).
// vFrom is constant (0, 1, 0) here so we inline that case.
// Result is written into qOut = [x, y, z, w].
// vTo must be a unit vector (we normalize externally).
function quatFromYTo(vToX, vToY, vToZ, qOut) {
  // r = 1 + vFrom . vTo = 1 + vToY
  const r = 1 + vToY
  if (r < 1e-12) {
    // 180-degree rotation. Pick axis orthogonal to Y.
    // vFrom = (0,1,0) → choose (1,0,0) as orthogonal axis.
    qOut[0] = 1
    qOut[1] = 0
    qOut[2] = 0
    qOut[3] = 0
    return
  }
  // q.xyz = vFrom x vTo = (0,1,0) x (vTo) = (vToZ, 0, -vToX)
  qOut[0] = vToZ
  qOut[1] = 0
  qOut[2] = -vToX
  qOut[3] = r
  // Normalize
  const len = Math.hypot(qOut[0], qOut[1], qOut[2], qOut[3])
  if (len > 0) {
    const inv = 1 / len
    qOut[0] *= inv
    qOut[1] *= inv
    qOut[2] *= inv
    qOut[3] *= inv
  }
}

// Three.js Matrix4.compose(position, quaternion, scale) — column-major.
// Writes 16 floats into `out` starting at `off`.
function composeMatrix(out, off, px, py, pz, qx, qy, qz, qw, sx, sy, sz) {
  const x2 = qx + qx, y2 = qy + qy, z2 = qz + qz
  const xx = qx * x2, xy = qx * y2, xz = qx * z2
  const yy = qy * y2, yz = qy * z2, zz = qz * z2
  const wx = qw * x2, wy = qw * y2, wz = qw * z2

  out[off + 0]  = (1 - (yy + zz)) * sx
  out[off + 1]  = (xy + wz) * sx
  out[off + 2]  = (xz - wy) * sx
  out[off + 3]  = 0

  out[off + 4]  = (xy - wz) * sy
  out[off + 5]  = (1 - (xx + zz)) * sy
  out[off + 6]  = (yz + wx) * sy
  out[off + 7]  = 0

  out[off + 8]  = (xz + wy) * sz
  out[off + 9]  = (yz - wx) * sz
  out[off + 10] = (1 - (xx + yy)) * sz
  out[off + 11] = 0

  out[off + 12] = px
  out[off + 13] = py
  out[off + 14] = pz
  out[off + 15] = 1
}

// Identity-quaternion shortcut. compose(pos, IDQ, scale). Avoids reading qOut.
function composeMatrixIdentity(out, off, px, py, pz, sx, sy, sz) {
  out[off + 0]  = sx
  out[off + 1]  = 0
  out[off + 2]  = 0
  out[off + 3]  = 0
  out[off + 4]  = 0
  out[off + 5]  = sy
  out[off + 6]  = 0
  out[off + 7]  = 0
  out[off + 8]  = 0
  out[off + 9]  = 0
  out[off + 10] = sz
  out[off + 11] = 0
  out[off + 12] = px
  out[off + 13] = py
  out[off + 14] = pz
  out[off + 15] = 1
}

// Three.js slabQuaternion: basis(tangential, tanDir, bnDir) → quaternion.
// tanDir = axis_tangent (already normalized)
// bnDir  = base_normal (already normalized)
// tangential = cross(tanDir, bnDir).normalize()
// Then matrix.makeBasis(tangential, tanDir, bnDir) sets columns:
//   col0 = tangential, col1 = tanDir, col2 = bnDir
// Quaternion is extracted from this rotation matrix.
function slabQuaternion(bnX, bnY, bnZ, tanX, tanY, tanZ, qOut) {
  // tangential = tanDir x bnDir (Three.js Vector3.crossVectors(a, b))
  let tnX = tanY * bnZ - tanZ * bnY
  let tnY = tanZ * bnX - tanX * bnZ
  let tnZ = tanX * bnY - tanY * bnX
  const tnLen = Math.hypot(tnX, tnY, tnZ)
  if (tnLen > 0) {
    const inv = 1 / tnLen
    tnX *= inv
    tnY *= inv
    tnZ *= inv
  }
  // Rotation matrix R with columns (tn, tan, bn):
  //   R[0,0]=tnX  R[0,1]=tanX R[0,2]=bnX
  //   R[1,0]=tnY  R[1,1]=tanY R[1,2]=bnY
  //   R[2,0]=tnZ  R[2,1]=tanZ R[2,2]=bnZ
  // Three.js Quaternion.setFromRotationMatrix algorithm:
  const m00 = tnX,  m01 = tanX, m02 = bnX
  const m10 = tnY,  m11 = tanY, m12 = bnY
  const m20 = tnZ,  m21 = tanZ, m22 = bnZ
  const trace = m00 + m11 + m22
  let qx, qy, qz, qw
  if (trace > 0) {
    const s = 0.5 / Math.sqrt(trace + 1.0)
    qw = 0.25 / s
    qx = (m21 - m12) * s
    qy = (m02 - m20) * s
    qz = (m10 - m01) * s
  } else if (m00 > m11 && m00 > m22) {
    const s = 2.0 * Math.sqrt(1.0 + m00 - m11 - m22)
    qw = (m21 - m12) / s
    qx = 0.25 * s
    qy = (m01 + m10) / s
    qz = (m02 + m20) / s
  } else if (m11 > m22) {
    const s = 2.0 * Math.sqrt(1.0 + m11 - m00 - m22)
    qw = (m02 - m20) / s
    qx = (m01 + m10) / s
    qy = 0.25 * s
    qz = (m12 + m21) / s
  } else {
    const s = 2.0 * Math.sqrt(1.0 + m22 - m00 - m11)
    qw = (m10 - m01) / s
    qx = (m02 + m20) / s
    qy = (m12 + m21) / s
    qz = 0.25 * s
  }
  qOut[0] = qx
  qOut[1] = qy
  qOut[2] = qz
  qOut[3] = qw
}

// ── Worker entry point ───────────────────────────────────────────────────────

self.onmessage = (e) => {
  const payload = e.data
  try {
    const result = computeMatrices(payload)
    // Transferable list = the underlying ArrayBuffers of every Float32Array
    // we just produced, so the post is zero-copy.
    self.postMessage(result, [
      result.beadMatrices.buffer,
      result.coneMatrices.buffer,
      result.slabMatrices.buffer,
      result.fluoroMatrices.buffer,
      result.coneMidPos.buffer,
      result.coneQuat.buffer,
      result.coneHeights.buffer,
      result.slabQuat.buffer,
      result.slabCenter.buffer,
    ])
  } catch (err) {
    self.postMessage({ error: String(err?.stack ?? err) })
  }
}

function computeMatrices(payload) {
  const {
    // bead/fluoro arrays
    beadPositions,    // Float32Array, 3 * beadCount
    beadIds,          // Uint32Array, beadCount — instance id within its mesh (sphere or cube)
    beadKinds,        // Uint8Array, beadCount — 0=sphere, 1=cube
    sphereCount,
    cubeCount,

    fluoroPositions,  // Float32Array, 3 * fluoroCount
    fluoroCount,

    // cone arrays
    coneFromPos,      // Float32Array, 3 * coneCount
    coneToPos,        // Float32Array, 3 * coneCount
    coneCrossHelix,   // Uint8Array, coneCount — 1 if cross-helix (radius = 0)
    coneCount,

    // slab arrays
    slabPositions,    // Float32Array, 3 * slabCount  (= backbone position)
    slabNormals,      // Float32Array, 3 * slabCount  (= base_normal)
    slabTangents,     // Float32Array, 3 * slabCount  (= axis_tangent)
    slabCount,
  } = payload

  // Output buffers. Bead matrices: spheres first [0..sphereCount-1] then
  // cubes [0..cubeCount-1]. Total slots = sphereCount + cubeCount.
  const beadMatrices  = new Float32Array(16 * (sphereCount + cubeCount))
  const coneMatrices  = new Float32Array(16 * Math.max(1, coneCount))
  const slabMatrices  = new Float32Array(16 * Math.max(1, slabCount))
  const fluoroMatrices = new Float32Array(16 * Math.max(1, fluoroCount))

  // Side-channel arrays used by the main thread to populate per-entry
  // Vector3/Quaternion fields without re-running the math. These let the
  // main-thread loop skip clone+setFromUnitVectors+crossVectors and instead
  // do a single `.fromArray()` per Vector3. Big GC-pressure reduction at
  // 60 k cones/slabs.
  const coneMidPos     = new Float32Array(3 * Math.max(1, coneCount))      // (x,y,z) per cone
  const coneQuat       = new Float32Array(4 * Math.max(1, coneCount))      // (qx,qy,qz,qw) per cone
  const coneHeights    = new Float32Array(Math.max(1, coneCount))          // scalar per cone
  const slabQuat       = new Float32Array(4 * Math.max(1, slabCount))      // (qx,qy,qz,qw) per slab
  const slabCenter     = new Float32Array(3 * Math.max(1, slabCount))      // (x,y,z) per slab

  const qScratch = new Float32Array(4)

  // ── Beads ────────────────────────────────────────────────────────────────
  // bead matrix layout: sphere slots [0..sphereCount) live at byte offset
  // 16*sphereId; cube slots [sphereCount..sphereCount+cubeCount) live at
  // 16*(sphereCount + cubeId). The caller writes them into TWO InstancedMeshes
  // (iSpheres + iCubes) with the same id slicing, so we hand back ONE buffer
  // covering both — the caller will copy the sphere slice and the cube slice
  // into the two `.instanceMatrix.array` buffers separately.
  for (let b = 0; b < beadIds.length; b++) {
    const id    = beadIds[b]
    const kind  = beadKinds[b]
    const px = beadPositions[3 * b + 0]
    const py = beadPositions[3 * b + 1]
    const pz = beadPositions[3 * b + 2]
    const slot = (kind === 0) ? id : (sphereCount + id)
    composeMatrixIdentity(beadMatrices, 16 * slot, px, py, pz, 1, 1, 1)
  }

  // ── Fluoros ──────────────────────────────────────────────────────────────
  for (let f = 0; f < fluoroCount; f++) {
    const px = fluoroPositions[3 * f + 0]
    const py = fluoroPositions[3 * f + 1]
    const pz = fluoroPositions[3 * f + 2]
    composeMatrixIdentity(fluoroMatrices, 16 * f, px, py, pz, 1, 1, 1)
  }

  // ── Cones ────────────────────────────────────────────────────────────────
  for (let c = 0; c < coneCount; c++) {
    const fx = coneFromPos[3 * c + 0]
    const fy = coneFromPos[3 * c + 1]
    const fz = coneFromPos[3 * c + 2]
    const tx = coneToPos[3 * c + 0]
    const ty = coneToPos[3 * c + 1]
    const tz = coneToPos[3 * c + 2]
    const dx = tx - fx, dy = ty - fy, dz = tz - fz
    const dist = Math.hypot(dx, dy, dz)
    const coneHeight = Math.max(0.001, dist)
    const invDist = dist > 0 ? 1 / dist : 0
    const ux = dx * invDist, uy = dy * invDist, uz = dz * invDist
    // midPos = from + u * (dist / 2)
    const mx = fx + ux * (dist * 0.5)
    const my = fy + uy * (dist * 0.5)
    const mz = fz + uz * (dist * 0.5)
    quatFromYTo(ux, uy, uz, qScratch)
    const r = coneCrossHelix[c] ? 0 : CONE_RADIUS
    composeMatrix(coneMatrices, 16 * c, mx, my, mz,
                  qScratch[0], qScratch[1], qScratch[2], qScratch[3],
                  r, coneHeight, r)
    // Side-channel: midPos + quat + height for the main-thread entry build.
    coneMidPos[3 * c + 0] = mx
    coneMidPos[3 * c + 1] = my
    coneMidPos[3 * c + 2] = mz
    coneQuat[4 * c + 0]   = qScratch[0]
    coneQuat[4 * c + 1]   = qScratch[1]
    coneQuat[4 * c + 2]   = qScratch[2]
    coneQuat[4 * c + 3]   = qScratch[3]
    coneHeights[c]        = coneHeight
  }

  // ── Slabs ────────────────────────────────────────────────────────────────
  for (let s = 0; s < slabCount; s++) {
    const bx = slabPositions[3 * s + 0]
    const by = slabPositions[3 * s + 1]
    const bz = slabPositions[3 * s + 2]
    const bnX = slabNormals[3 * s + 0]
    const bnY = slabNormals[3 * s + 1]
    const bnZ = slabNormals[3 * s + 2]
    const tanX = slabTangents[3 * s + 0]
    const tanY = slabTangents[3 * s + 1]
    const tanZ = slabTangents[3 * s + 2]
    slabQuaternion(bnX, bnY, bnZ, tanX, tanY, tanZ, qScratch)
    // slabCenter = bbPos + bnDir * (HELIX_RADIUS - SLAB_DIST)
    const off = HELIX_RADIUS - SLAB_DIST
    const cx = bx + bnX * off
    const cy = by + bnY * off
    const cz = bz + bnZ * off
    composeMatrix(slabMatrices, 16 * s, cx, cy, cz,
                  qScratch[0], qScratch[1], qScratch[2], qScratch[3],
                  SLAB_LEN, SLAB_WID, SLAB_THK)
    // Side-channel: slab center + quat for the main-thread entry build.
    slabCenter[3 * s + 0] = cx
    slabCenter[3 * s + 1] = cy
    slabCenter[3 * s + 2] = cz
    slabQuat[4 * s + 0]   = qScratch[0]
    slabQuat[4 * s + 1]   = qScratch[1]
    slabQuat[4 * s + 2]   = qScratch[2]
    slabQuat[4 * s + 3]   = qScratch[3]
  }

  return {
    beadMatrices,
    coneMatrices,
    slabMatrices,
    fluoroMatrices,
    coneMidPos,
    coneQuat,
    coneHeights,
    slabQuat,
    slabCenter,
    sphereCount,
    cubeCount,
    coneCount,
    slabCount,
    fluoroCount,
  }
}

// Export pure compute helpers for unit tests (vitest can import this module
// directly when not running in a Worker context — `self.onmessage` simply
// gets registered as a no-op listener on the test runner's global).
export {
  computeMatrices,
  composeMatrix,
  composeMatrixIdentity,
  quatFromYTo,
  slabQuaternion,
}
