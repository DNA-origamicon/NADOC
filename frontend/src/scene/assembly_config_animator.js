/**
 * Animate an assembly into a saved configuration (extracted from main.js — see
 * `main_js_carveup.md` Tier 7 "Assembly context/linker menu + config animation").
 *
 * The Feature Log's "animate to configuration" action calls `animate(cfg)`: each
 * instance with a stored transform in `cfg.instance_states` is tweened from its
 * current live transform to the configuration's target transform over ~650 ms
 * (ease-in-out), driving both the part renderer and the joint renderer per frame.
 * When no instance has a target (nothing to tween), it falls straight through to
 * the backend restore. Either way the final state is committed by the backend's
 * `restoreAssemblyConfiguration` once the tween finishes.
 *
 * Display-layer only: every position written here goes through the renderers'
 * live-transform path; the Design topology is never touched.
 *
 * Pure cores (unit-tested with real THREE):
 *   - `easeInOutQuad(t)` — the easing curve.
 *   - `buildConfigAnimItems(assembly, cfg, getLiveTransform)` — decomposes each
 *     animatable instance's start/end matrices into pos/quat/scale triples.
 */

import * as THREE from 'three'

/** Ease-in-out quadratic, t in [0,1]. */
export function easeInOutQuad(t) {
  return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2
}

/**
 * Build the per-instance tween descriptors for a configuration restore.
 *
 * For every instance that has a `transform.values` entry in
 * `cfg.instance_states`, decompose its start matrix (the renderer's current live
 * transform, falling back to the instance's persisted transform) and its end
 * matrix (the configuration's stored transform) into position / quaternion /
 * scale. Instances without a stored target are skipped.
 *
 * @param {object} assembly        currentAssembly ({ instances: [...] })
 * @param {object} cfg             configuration ({ instance_states: [...] })
 * @param {(id:string)=>THREE.Matrix4|null} getLiveTransform
 * @returns {Array<{id,sp,sq,ss,ep,eq,es}>}
 */
export function buildConfigAnimItems(assembly, cfg, getLiveTransform) {
  const stateById = new Map((cfg?.instance_states ?? []).map(s => [s.instance_id, s]))
  const animItems = []
  for (const inst of assembly?.instances ?? []) {
    const state = stateById.get(inst.id)
    if (!state?.transform?.values) continue
    const startMat = getLiveTransform(inst.id)
      ?? new THREE.Matrix4().fromArray(inst.transform.values).transpose()
    const endMat = new THREE.Matrix4().fromArray(state.transform.values).transpose()
    const sp = new THREE.Vector3(), ss = new THREE.Vector3()
    const sq = new THREE.Quaternion()
    const ep = new THREE.Vector3(), es = new THREE.Vector3()
    const eq = new THREE.Quaternion()
    startMat.decompose(sp, sq, ss)
    endMat.decompose(ep, eq, es)
    animItems.push({ id: inst.id, sp, sq, ss, ep, eq, es })
  }
  return animItems
}

/**
 * @param {object} deps
 * @param {object} deps.store
 * @param {object} deps.api
 * @param {object} deps.assemblyRenderer
 * @param {object} deps.assemblyJointRenderer
 * @param {() => boolean} deps.hasAssemblyPending
 * @param {() => Promise<void>} deps.commitAssemblyPending
 * @returns {{ animate: (cfg:object) => Promise<void> }}
 */
export function initAssemblyConfigAnimator({
  store,
  api,
  assemblyRenderer,
  assemblyJointRenderer,
  hasAssemblyPending,
  commitAssemblyPending,
}) {
  async function animate(cfg) {
    const assembly = store.getState().currentAssembly
    if (!assembly || !cfg) return
    if (hasAssemblyPending()) await commitAssemblyPending()

    const animItems = buildConfigAnimItems(assembly, cfg, (id) => assemblyRenderer.getLiveTransform(id))
    if (!animItems.length) {
      await api.restoreAssemblyConfiguration(cfg.id)
      return
    }

    const duration = 650
    const start = performance.now()
    const mat = new THREE.Matrix4()
    const pos = new THREE.Vector3()
    const quat = new THREE.Quaternion()
    const scale = new THREE.Vector3()

    await new Promise(resolve => {
      function frame(now) {
        const t = Math.min(1, (now - start) / duration)
        const k = easeInOutQuad(t)
        for (const item of animItems) {
          pos.copy(item.sp).lerp(item.ep, k)
          quat.copy(item.sq).slerp(item.eq, k)
          scale.copy(item.ss).lerp(item.es, k)
          mat.compose(pos, quat, scale)
          assemblyRenderer.setLiveTransform(item.id, mat)
          assemblyJointRenderer.setLiveJointTransform(item.id, mat, assembly)
        }
        if (t < 1) requestAnimationFrame(frame)
        else resolve()
      }
      requestAnimationFrame(frame)
    })
    await api.restoreAssemblyConfiguration(cfg.id)
  }

  return { animate }
}
