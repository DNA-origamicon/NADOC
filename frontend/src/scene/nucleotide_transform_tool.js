/** Representation-independent single-nucleotide transform session. */

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

export function abstractResidueInfo(target, geometry = []) {
  if (!target || target.helix_id === '__xb__') return null
  const nuc = geometry.find(n => n.helix_id === target.helix_id &&
    n.bp_index === target.bp_index && n.direction === target.direction &&
    (n.copy ?? 0) === (target.copy ?? 0))
  return nuc ? { nuc, centroid: new THREE.Vector3(...nuc.backbone_position) } : null
}

export function abstractPreviewUpdate(info, matrix) {
  if (!info?.nuc) return null
  const point = field => new THREE.Vector3(...info.nuc[field]).applyMatrix4(matrix).toArray()
  const direction = field => new THREE.Vector3(...info.nuc[field]).transformDirection(matrix).toArray()
  const bb = point('backbone_position')
  const bn = direction('base_normal')
  const at = direction('axis_tangent')
  return {
    helix_id: info.nuc.helix_id, bp_index: info.nuc.bp_index,
    direction: info.nuc.direction, copy: info.nuc.copy ?? 0,
    backbone_position: bb,
    nx: bn[0], ny: bn[1], nz: bn[2],
    tx: at[0], ty: at[1], tz: at[2],
  }
}

export function initNucleotideTransformTool({ store, scene, camera, canvas, controls, designRenderer, atomisticRenderer, moveRotatePanel, refreshCurrentSelection, refreshAtomistic }) {
  let tc = null
  let helper = null
  let dummy = null
  let target = null
  let pivot = null
  let dragging = false
  let mode = 'translate'
  let previewKind = null
  let abstractInfo = null

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
    const selected = selectedTarget()
    if (!selected) return false
    if (atomisticRenderer.getMode?.() !== 'off') return !!atomisticRenderer.residueInfo(selected)
    return selected.helix_id === '__xb__'
      ? !!designRenderer.xoverResidueInfo?.(selected)
      : !!abstractResidueInfo(selected, store.getState().currentGeometry)
  }

  function activate() {
    if (!canActivate()) return false
    target = selectedTarget()
    previewKind = atomisticRenderer.getMode?.() !== 'off' ? 'atomistic' : 'abstract'
    abstractInfo = previewKind === 'abstract'
      ? (target.helix_id === '__xb__'
          ? designRenderer.xoverResidueInfo?.(target)
          : abstractResidueInfo(target, store.getState().currentGeometry))
      : null
    const info = previewKind === 'atomistic' ? atomisticRenderer.residueInfo(target) : abstractInfo
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
      if (!dragging) return
      if (previewKind === 'atomistic') atomisticRenderer.applyResidueMatrix(target, liveMatrix())
      else if (target.helix_id === '__xb__') designRenderer.applyXoverResidueMatrix?.(abstractInfo, liveMatrix())
      else {
        const update = abstractPreviewUpdate(abstractInfo, liveMatrix())
        if (update) designRenderer.applyFemPositions([update])
      }
    })
    document.getElementById('mode-indicator').textContent =
      'NUCLEOTIDE MOVE/ROTATE — Tab: move/rotate · M: apply · Esc: cancel'
    moveRotatePanel?.setAssemblyCtx(null)
    moveRotatePanel?.setSessionMode?.('nucleotide')
    moveRotatePanel?.setTransformValues?.(0, 0, 0, 0, 0, 0)
    refreshCurrentSelection?.()
    if (moveRotatePanel?.panel) moveRotatePanel.panel.style.display = ''
    document.addEventListener('keydown', onKey)
    return true
  }

  async function confirm() {
    if (!tc) return
    const translation = dummy.position.clone().sub(pivot)
    const body = transformBodyForTarget(target, pivot, translation, dummy.quaternion)
    const committedPreviewKind = previewKind
    restorePreview()
    detach(false)
    await putNucleotideTransform(body)
    if (committedPreviewKind === 'atomistic') await refreshAtomistic?.()
  }

  function cancel() {
    if (!tc) return
    restorePreview()
    detach(false)
  }

  function reset() {
    if (!tc) return
    restorePreview()
    dummy.position.copy(pivot)
    dummy.quaternion.identity()
    tc.updateMatrixWorld?.()
  }

  function restorePreview() {
    if (previewKind === 'atomistic' && target) atomisticRenderer.applyResidueMatrix(target, identity())
    else if (previewKind === 'abstract' && target?.helix_id === '__xb__') {
      designRenderer.applyXoverResidueMatrix?.(abstractInfo, identity())
    } else if (previewKind === 'abstract') designRenderer.applyFemPositions(null)
  }

  function detach(restore = true) {
    if (restore && target) restorePreview()
    if (tc) { tc.detach(); scene.remove(helper); tc.dispose?.() }
    dummy?.parent?.remove(dummy)
    document.removeEventListener('keydown', onKey)
    controls.enabled = true
    if (moveRotatePanel?.panel) moveRotatePanel.panel.style.display = 'none'
    tc = helper = dummy = target = pivot = abstractInfo = null
    dragging = false
    previewKind = null
    document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
  }

  function onKey(e) {
    if (e.key === 'Escape') { e.preventDefault(); cancel() }
    else if (e.key === 'Tab') {
      e.preventDefault(); mode = mode === 'translate' ? 'rotate' : 'translate'; tc?.setMode(mode)
    }
  }

  return { activate, confirm, cancel, reset, detach, canActivate, isActive: () => !!tc }
}
