/**
 * Multi-select union BoxHelper for assembly mode (extracted from main.js — see
 * `main_js_carveup.md` Tier 3 "Multi-select visual feedback").
 *
 * Renders ONE union box around every instance in `multiSelectedInstanceIds`. An
 * `activeGroupId` means every transitive member is conceptually selected, so the
 * group's members are folded into the union too — the user needs feedback for
 * the group as a whole, not just ad-hoc multi-selects.
 *
 * A SINGLE Ctrl-selected part (one id, no group) is drawn WHITE — matching the
 * renderer's per-instance highlight — so the selection is visible immediately
 * (ISSUE-3a); two-or-more parts (or any group) get the purple union box. Note
 * this reads only `multiSelectedInstanceIds` + `activeGroupId`, never
 * `activeInstanceId`, so a plain single-click (which the renderer already boxes
 * white) is left untouched here — no double box.
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
const SINGLE_BOX_COLOR = 0xffffff

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
    // Drop any stale box first, then bail only when nothing is selected. A single
    // Ctrl-selected part still draws (white) so the user gets immediate feedback.
    _remove()
    if (wanted.size === 0) return
    const centers = assemblyRenderer.getInstanceCenters?.() ?? []
    const union = instanceUnionBox(centers, wanted)
    if (!union) return
    const color = (wanted.size >= 2 || s.activeGroupId) ? MULTI_BOX_COLOR : SINGLE_BOX_COLOR
    box = new THREE.Box3Helper(union, color)
    box.name = 'assemblyMultiBox'
    box.material.depthTest = false
    box.material.transparent = true
    box.material.opacity = 0.95
    box.renderOrder = 1001
    scene.add(box)
  }

  function dispose() { _remove() }

  return { update, dispose }
}
