/** Independent atomistic residue transform session. */

import * as THREE from 'three'
import { TransformControls } from 'three/addons/controls/TransformControls.js'

import { parseBaseKey } from './base_ref.js'
import { putNucleotideTransform } from '../api/client.js'
import { showToast } from '../ui/toast.js'

export function transformBodyForTarget(target, pivot, translation, quaternion) {
  const pose = {
    pivot: pivot.toArray(), translation: translation.toArray(),
    rotation: [quaternion.x, quaternion.y, quaternion.z, quaternion.w], compose: true,
  }
  return target.helix_id === '__xb__'
    ? { ...pose, kind: 'extra_base', crossover_id: target.crossover_id, extra_base_k: target.k }
    : { ...pose, kind: 'base', helix_id: target.helix_id, bp_index: target.bp_index,
        direction: target.direction, copy_k: target.copy ?? 0 }
}

export function initNucleotideTransformTool({ store, scene, camera, canvas, controls, atomisticRenderer, refreshAtomistic }) {
  let tc = null
  let helper = null
  let dummy = null
  let target = null
  let pivot = null
  let dragging = false
  let mode = 'translate'

  const identity = () => new THREE.Matrix4()
  function liveMatrix() {
    return new THREE.Matrix4().makeTranslation(dummy.position.x, dummy.position.y, dummy.position.z)
      .multiply(new THREE.Matrix4().makeRotationFromQuaternion(dummy.quaternion))
      .multiply(new THREE.Matrix4().makeTranslation(-pivot.x, -pivot.y, -pivot.z))
  }

  function selectedTarget() {
    const keys = store.getState().multiSelectedBaseKeys ?? []
    return keys.length === 1 ? parseBaseKey(keys[0]) : null
  }

  function canActivate() {
    return atomisticRenderer.getMode?.() !== 'off' && !!selectedTarget()
  }

  function activate() {
    if (!canActivate()) return false
    target = selectedTarget()
    const info = atomisticRenderer.residueInfo(target)
    if (!info) {
      showToast('The selected nucleotide is not present in the atomistic model.', { severity: 'error' })
      target = null
      return false
    }
    pivot = info.centroid.clone()
    dummy = new THREE.Object3D()
    dummy.position.copy(pivot)
    scene.add(dummy)
    tc = new TransformControls(camera, canvas)
    tc.attach(dummy); tc.setMode(mode); tc.setSpace('world')
    helper = tc.getHelper(); scene.add(helper)
    tc.addEventListener('dragging-changed', e => { dragging = e.value; controls.enabled = !e.value })
    tc.addEventListener('change', () => {
      if (dragging) atomisticRenderer.applyResidueMatrix(target, liveMatrix())
    })
    document.getElementById('mode-indicator').textContent =
      'NUCLEOTIDE MOVE/ROTATE — Tab: move/rotate · M: apply · Esc: cancel'
    document.addEventListener('keydown', onKey)
    return true
  }

  async function confirm() {
    if (!tc) return
    const translation = dummy.position.clone().sub(pivot)
    const body = transformBodyForTarget(target, pivot, translation, dummy.quaternion)
    detach(false)
    await putNucleotideTransform(body)
    await refreshAtomistic?.()
  }

  function cancel() {
    if (!tc) return
    atomisticRenderer.applyResidueMatrix(target, identity())
    detach(false)
  }

  function detach(restore = true) {
    if (restore && target) atomisticRenderer.applyResidueMatrix(target, identity())
    if (tc) { tc.detach(); scene.remove(helper); tc.dispose?.() }
    dummy?.parent?.remove(dummy)
    document.removeEventListener('keydown', onKey)
    controls.enabled = true
    tc = helper = dummy = target = pivot = null
    dragging = false
    document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
  }

  function onKey(e) {
    if (e.key === 'Escape') { e.preventDefault(); cancel() }
    else if (e.key === 'Tab') {
      e.preventDefault(); mode = mode === 'translate' ? 'rotate' : 'translate'; tc?.setMode(mode)
    }
  }

  return { activate, confirm, cancel, detach, canActivate, isActive: () => !!tc }
}
