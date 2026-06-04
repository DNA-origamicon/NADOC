/**
 * Multi-select union BoxHelper for assembly mode (extracted from main.js — see
 * `main_js_carveup.md` Tier 3 "Multi-select visual feedback").
 *
 * Renders ONE purple union box around every instance in
 * `multiSelectedInstanceIds`. An `activeGroupId` means every transitive member
 * is conceptually selected, so the group's members are folded into the union
 * too — the user needs feedback for the group as a whole, not just ad-hoc
 * multi-selects. Hidden for single-part selections (< 2 ids and no active
 * group): the renderer's per-instance white BoxHelper already covers that case.
 *
 * Recomputed via `update()` whenever the multi-select set, the active group, OR
 * the assembly changes (a move/rotate of any member must re-fit the box). The
 * pure union math lives in `selection_bbox.js` (`instanceUnionBox`); this
 * factory owns only the scene mutation + store/group read.
 */
import * as THREE from 'three'
import { instanceUnionBox } from './selection_bbox.js'
import { collectGroupMemberInstanceIds } from './assembly_groups_util.js'

const MULTI_BOX_COLOR = 0x8b5cf6

/**
 * @param {object} deps
 * @param {THREE.Scene} deps.scene
 * @param {object} deps.store             reactive store (getState)
 * @param {object} deps.assemblyRenderer  must expose getInstanceCenters()
 * @returns {{ update: () => void, dispose: () => void }}
 */
export function initAssemblyMultiBox({ scene, store, assemblyRenderer }) {
  let box = null

  function _remove() {
    if (!box) return
    scene.remove(box)
    box.geometry?.dispose?.()
    box.material?.dispose?.()
    box = null
  }

  function update() {
    const s = store.getState()
    const wanted = new Set(s.multiSelectedInstanceIds ?? [])
    if (s.activeGroupId) {
      for (const id of collectGroupMemberInstanceIds(s.currentAssembly, s.activeGroupId)) {
        wanted.add(id)
      }
    }
    // Drop any stale box first, then bail for the cases the per-instance white
    // helper already covers (nothing selected, or a single part with no group).
    _remove()
    if (wanted.size === 0) return
    if (wanted.size < 2 && !s.activeGroupId) return
    const centers = assemblyRenderer.getInstanceCenters?.() ?? []
    const union = instanceUnionBox(centers, wanted)
    if (!union) return
    box = new THREE.Box3Helper(union, MULTI_BOX_COLOR)
    box.material.depthTest = false
    box.material.transparent = true
    box.material.opacity = 0.95
    box.renderOrder = 1001
    scene.add(box)
  }

  function dispose() { _remove() }

  return { update, dispose }
}
