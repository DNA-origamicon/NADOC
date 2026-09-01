/**
 * What the key light's shadow frustum should be fitted to.
 *
 * Small, but every line here was paid for. Fitting a shadow camera to "the
 * scene bounding box" is the obvious implementation and it fails silently and
 * totally on a real design: the editor keeps overlay geometry (ghost planes,
 * hit targets, immobilisation surfaces) that is orders of magnitude larger than
 * the structure, and one of those stretches the frustum until the design sits
 * inside a single shadow texel. Nothing errors. The picture is just flat.
 *
 * So the bounds are computed with two defences:
 *   • a type/material exclusion list — things that cannot or must not occlude;
 *   • statistical rejection of gross outliers, with the offender reported.
 *
 * (Formerly part of multishadow_ao.js. The multishadow ambient-occlusion
 * experiment was removed — it never resolved origami-scale features usefully —
 * but the frustum fitting it needed is exactly what the key shadow needs too.)
 */

import * as THREE from 'three'

/**
 * Minimum contributors before the median extent is trustworthy enough to reject
 * on, and how far above it counts as "this is not part of the structure".
 */
const OUTLIER_MIN_MESHES = 5
const OUTLIER_RATIO      = 8
const OUTLIER_COHORT_RATIO = 2
const OUTLIER_COHORT_MIN   = 2

/**
 * True when `obj` must not cast shadows: the photo-mode floor (a ground plane
 * would shadow the whole underside), helper lines and additive glow sprites
 * (they would stamp depth where there is no real surface), anything explicitly
 * opted out with `userData.noAO`, and anything that does not write depth.
 */
export function isShadowExcluded(obj) {
  const m = obj.material
  return !!(
    obj.userData?.photoFloor
    || obj.userData?.noAO
    // Three's 100000×100000 TransformControls ray-picking plane is editor
    // infrastructure, not scene geometry. Its own visible flag can remain true
    // even while the control is hidden or detached.
    || obj.isTransformControlsPlane
    || obj.isSprite
    || m?.isLineBasicMaterial
    || m?.isLineDashedMaterial
    || m?.blending === THREE.AdditiveBlending
    // A mesh that does not write depth cannot occlude anything — by definition.
    // Also the signature of every editor overlay, and those are exactly the
    // objects that are enormous relative to the structure.
    || m?.depthWrite === false
  )
}

/** Three does not render a child of a hidden Group even when child.visible is
 * true. Object3D.traverse still visits it, however, so bounds code must mirror
 * the renderer's effective-visibility rule explicitly. */
function isEffectivelyVisible(obj, root) {
  for (let node = obj; node; node = node.parent) {
    if (!node.visible) return false
    if (node === root) break
  }
  return true
}

/**
 * Cheap fingerprint of the shadow-casting geometry, used to notice that the
 * scene changed and the frustum needs refitting.
 *
 * Keys off `Object3D.id`, which is fresh for every newly constructed mesh, so
 * any rebuild changes the signature. That matters because a REPRESENTATION
 * SWITCH replaces every mesh while writing no store field at all (only the
 * atomistic/surface reps set `atomisticMode`/`surfaceMode`), so a store
 * subscription silently misses four of the seven representations. ChimeraX
 * makes the same call — its invalidation hangs off the drawing manager, not off
 * any command or UI event.
 *
 * Deliberately does NOT hash instance matrices: that would mean touching every
 * instance on every check. Position-only changes are covered by the caller's
 * store subscription.
 *
 * @param {THREE.Object3D} root
 * @returns {string}
 */
export function sceneSignature(root) {
  let hash = 17
  let count = 0
  root.traverse(obj => {
    if ((!obj.isMesh && !obj.isInstancedMesh) || !isEffectivelyVisible(obj, root)) return
    if (isShadowExcluded(obj)) return
    count++
    hash = (Math.imul(hash, 31) + obj.id) | 0
    hash = (Math.imul(hash, 31) + (obj.geometry?.id ?? 0)) | 0
    if (obj.isInstancedMesh) hash = (Math.imul(hash, 31) + obj.count) | 0
  })
  return `${count}:${hash}`
}

/**
 * Bounding sphere of everything that should cast, in world space, with gross
 * outliers rejected.
 *
 * The median is a sound statistic here precisely because the geometry is
 * INSTANCED: one InstancedMesh's box already spans all of its instances, so the
 * median contributor is design-sized rather than bead-sized, and a legitimately
 * large mesh (the molecular surface) sits right at the median instead of
 * looking like an outlier.
 *
 * @param {THREE.Object3D} root
 * `box` and `corners` are returned alongside the sphere because the depth cue
 * needs an ORIENTATION-AWARE extent: a sphere is orientation-blind, so a long
 * thin bundle seen side-on reports its LENGTH as the depth extent when the real
 * depth is its diameter — an order of magnitude too wide. The corners get the
 * same outlier rejection as the sphere, so a stray 100 µm overlay cannot blow
 * out the cue window either.
 *
 * @returns {{center: THREE.Vector3, radius: number, box: THREE.Box3,
 *            corners: THREE.Vector3[], diagonal: number,
 *            contributors: object[], rejected: object[],
 *            medianExtent: number} | null}
 */
export function computeShadowBounds(root, { rejectOutliers = true } = {}) {
  const box = new THREE.Box3()
  const contributors = []
  const boxes = []
  let any = false

  root.traverse(obj => {
    if ((!obj.isMesh && !obj.isInstancedMesh) || !isEffectivelyVisible(obj, root)) return
    if (isShadowExcluded(obj)) return
    // InstancedMesh caches `boundingBox` and does NOT invalidate it when
    // instance matrices are rewritten — which is exactly what a simulation
    // frame, a cluster move, or an unfold does.
    if (obj.isInstancedMesh) { try { obj.computeBoundingBox() } catch { /* empty mesh */ } }
    const b = new THREE.Box3().setFromObject(obj)
    if (b.isEmpty()) return
    // Impostor quads are 2-triangle billboards whose geometry bounds are a flat
    // ±1 square; their real extent is instance centres ± radius.
    const pad = obj.material?.userData?.impostorRadius
    if (pad) b.expandByScalar(pad)
    boxes.push(b)
    contributors.push({
      object:   obj,
      name:     obj.name || '(unnamed)',
      type:     obj.isInstancedMesh ? `InstancedMesh×${obj.count}` : 'Mesh',
      material: obj.material?.type ?? '?',
      extent:   +b.getSize(new THREE.Vector3()).length().toFixed(2),
    })
    any = true
  })
  if (!any) return null

  const extents = contributors.map(c => c.extent).slice().sort((a, b) => a - b)
  const median  = extents[Math.floor(extents.length / 2)]
  const limit   = median * OUTLIER_RATIO
  const canReject = rejectOutliers && contributors.length >= OUTLIER_MIN_MESHES && median > 0

  // A real structure is commonly represented by several coextensive meshes
  // (backbone, bases, connectors, cones). An attached protein can contribute
  // enough smaller element meshes to pull the unweighted median below the DNA
  // span. In that case every DNA mesh clears `limit`, but they corroborate one
  // another and are not outliers. Only reject the oversized tail when its
  // largest scale is represented by a single contributor. Explicit overlay
  // types are already removed by isShadowExcluded() above.
  const oversized = canReject
    ? contributors.filter(c => c.extent > limit).sort((a, b) => b.extent - a.extent)
    : []
  const preservedOversized = new Set()
  for (const candidate of oversized) {
    const cohort = oversized.filter(other => {
      const ratio = Math.max(candidate.extent, other.extent)
        / Math.max(1e-9, Math.min(candidate.extent, other.extent))
      return ratio <= OUTLIER_COHORT_RATIO
    })
    if (cohort.length >= OUTLIER_COHORT_MIN) {
      for (const member of cohort) preservedOversized.add(member)
    }
  }

  const rejected = []
  for (let i = 0; i < contributors.length; i++) {
    if (canReject && contributors[i].extent > limit
        && !preservedOversized.has(contributors[i])) {
      rejected.push(contributors[i]); continue
    }
    box.union(boxes[i])
  }
  if (box.isEmpty()) return null

  const sphere = new THREE.Sphere()
  box.getBoundingSphere(sphere)
  if (!(sphere.radius > 0)) return null

  contributors.sort((a, b) => b.extent - a.extent)
  rejected.sort((a, b) => b.extent - a.extent)

  const mn = box.min, mx = box.max
  const corners = [
    new THREE.Vector3(mn.x, mn.y, mn.z), new THREE.Vector3(mx.x, mn.y, mn.z),
    new THREE.Vector3(mn.x, mx.y, mn.z), new THREE.Vector3(mx.x, mx.y, mn.z),
    new THREE.Vector3(mn.x, mn.y, mx.z), new THREE.Vector3(mx.x, mn.y, mx.z),
    new THREE.Vector3(mn.x, mx.y, mx.z), new THREE.Vector3(mx.x, mx.y, mx.z),
  ]

  return {
    center: sphere.center.clone(),
    radius: sphere.radius,
    box: box.clone(),
    corners,
    diagonal: box.getSize(new THREE.Vector3()).length(),
    contributors,
    rejected,
    medianExtent: median,
  }
}

/** Objects computeShadowBounds discarded as not-part-of-the-structure. They
 *  must also be barred from casting, or a 100 µm plane shadows everything. */
export function rejectedObjects(bounds) {
  return new Set((bounds?.rejected ?? []).map(r => r.object))
}

/**
 * Describe a bounds result whose radius was being set by one outlier, for a
 * console warning. Null when nothing was rejected.
 */
export function findBoundsOutlier(bounds) {
  const worst = bounds?.rejected?.[0]
  if (!worst || !(bounds.medianExtent > 0)) return null
  return {
    radius: bounds.radius,
    medianExtent: bounds.medianExtent,
    ratio: +(worst.extent / bounds.medianExtent).toFixed(1),
    rejectedCount: bounds.rejected.length,
    worst: { name: worst.name, type: worst.type, material: worst.material, extent: worst.extent },
  }
}
