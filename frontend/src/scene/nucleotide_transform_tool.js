/** Representation-independent single-nucleotide transform session. */

import * as THREE from 'three'
import { TransformControls } from 'three/addons/controls/TransformControls.js'

import { baseKey, parseBaseKey } from './base_ref.js'
import { putNucleotideTransform, putNucleotideTransforms } from '../api/client.js'
import { showToast } from '../ui/toast.js'
import { canonicalSelection } from './selection_model.js'
import { selectionRefsEqual } from './selection_ref.js'

export function transformBodyForTarget(target, pivot, translation, quaternion, residueInfo = null) {
  const pose = {
    pivot: pivot.toArray(), translation: translation.toArray(),
    rotation: [quaternion.x, quaternion.y, quaternion.z, quaternion.w], compose: true,
  }
  if (target.helix_id !== '__xb__' && residueInfo?.slabMatrix && residueInfo?.beadMatrix) {
    const bead = new THREE.Vector3().setFromMatrixPosition(residueInfo.beadMatrix)
    const slab = new THREE.Vector3(), slabQ = new THREE.Quaternion(), slabScale = new THREE.Vector3()
    residueInfo.slabMatrix.decompose(slab, slabQ, slabScale)
    pose.display_slab_offset = slab.sub(bead).toArray()
    pose.display_slab_rotation = [slabQ.x, slabQ.y, slabQ.z, slabQ.w]
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
  const base = point('base_position')
  const bn = direction('base_normal')
  const at = direction('axis_tangent')
  return {
    helix_id: info.nuc.helix_id, bp_index: info.nuc.bp_index,
    direction: info.nuc.direction, copy: info.nuc.copy ?? 0,
    backbone_position: bb, base_position: base,
    nx: bn[0], ny: bn[1], nz: bn[2],
    tx: at[0], ty: at[1], tz: at[2],
  }
}

/** Resolve every non-cluster design selection to residue targets. This deliberately
 * uses logical geometry identities, so the same selection works in CG, atomistic,
 * surface, and mixed representations. */
export function transformTargetsForSelection(state, exactRef = null) {
  const refs = exactRef ? [exactRef] : canonicalSelection(state).items
  const explicit = refs
    .filter(ref => ref.kind === 'base' || ref.kind === 'end')
    .map(ref => ref.key)
  const geometry = state.currentGeometry ?? []
  const strands = new Set(refs.filter(ref => ref.kind === 'strand').map(ref => ref.id))
  const domains = new Set(refs.filter(ref => ref.kind === 'domain')
    .map(ref => `${ref.strandId}:${ref.domainIndex}`))
  const overhangs = new Set(refs.filter(ref => ref.kind === 'overhang').map(ref => ref.id))
  const extensions = new Set(refs.filter(ref => ref.kind === 'extension').map(ref => ref.id))
  const hasNonClusterGrain = explicit.length || domains.size || overhangs.size || extensions.size
  // Cluster refs retain the purpose-built cluster gizmo
  // (and its cluster-transform persistence) instead of exploding it into residues.
  if (refs.some(ref => ref.kind === 'cluster') && !hasNonClusterGrain) return []
  const keys = [...explicit]
  for (const nuc of geometry) {
    if (strands.has(nuc.strand_id) ||
        domains.has(`${nuc.strand_id}:${nuc.domain_index ?? 0}`) ||
        overhangs.has(nuc.overhang_id) || extensions.has(nuc.extension_id)) {
      const key = baseKey(nuc, nuc.copy ?? nuc.copy_k ?? 0)
      if (key) keys.push(key)
    }
  }
  return [...new Set(keys)].map(parseBaseKey).filter(Boolean)
}

export function initNucleotideTransformTool({ store, scene, camera, canvas, controls, designRenderer, atomisticRenderer, getAtomisticRenderers, moveRotatePanel, refreshCurrentSelection }) {
  let tc = null
  let helper = null
  let dummy = null
  let targets = []
  let pivot = null
  let dragging = false
  let mode = 'translate'
  let targetInfos = []
  let exactSessionRef = null
  let vrPreviewRef = null

  const identity = () => new THREE.Matrix4()
  function liveMatrix() {
    return new THREE.Matrix4().makeTranslation(dummy.position.x, dummy.position.y, dummy.position.z)
      .multiply(new THREE.Matrix4().makeRotationFromQuaternion(dummy.quaternion))
      .multiply(new THREE.Matrix4().makeTranslation(-pivot.x, -pivot.y, -pivot.z))
  }

  const selectedTargets = (exactRef = null) => transformTargetsForSelection(
    store.getState(), exactRef)

  function renderers() {
    const supplied = getAtomisticRenderers?.() ?? [atomisticRenderer]
    return supplied.filter((r, i, all) => r && all.indexOf(r) === i)
  }

  function infoFor(target) {
    for (const renderer of renderers()) {
      const info = renderer.residueInfo?.(target)
      if (info) return { target, info, kind: 'atomistic', renderer }
    }
    const info = target.helix_id === '__xb__'
      ? designRenderer.xoverResidueInfo?.(target)
      : designRenderer.residueTransformInfo?.(target)
    return info ? { target, info, kind: 'abstract', renderer: designRenderer } : null
  }

  function canActivate(exactRef = null) {
    const selected = selectedTargets(exactRef)
    return selected.length > 0 && selected.every(t => !!infoFor(t))
  }

  function activate({ exactRef = null } = {}) {
    if (!canActivate(exactRef)) return false
    targets = selectedTargets(exactRef)
    exactSessionRef = exactRef ? { ...exactRef } : null
    targetInfos = targets.map(infoFor)
    if (!targetInfos.length || targetInfos.some(x => !x)) {
      showToast('Some selected elements are not present in the current representation.', { severity: 'error' })
      targets = []; targetInfos = []
      return false
    }
    pivot = targetInfos.reduce((sum, x) => sum.add(x.info.centroid), new THREE.Vector3())
      .multiplyScalar(1 / targetInfos.length)
    dummy = new THREE.Object3D()
    dummy.position.copy(pivot)
    scene.add(dummy)
    tc = new TransformControls(camera, canvas)
    tc.attach(dummy); tc.setMode(mode); tc.setSpace('world')
    helper = tc.getHelper(); scene.add(helper)
    tc.addEventListener('dragging-changed', e => { dragging = e.value; controls.enabled = !e.value })
    tc.addEventListener('change', () => {
      if (!dragging) return
      for (const x of targetInfos) applyPreview(x, liveMatrix())
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

  function _pendingBodies() {
    const translation = dummy.position.clone().sub(pivot)
    return targetInfos.map(x => transformBodyForTarget(
      x.target, pivot, translation, dummy.quaternion, x.kind === 'abstract' ? x.info : null))
  }

  function _hasPendingMotion() {
    return !!dummy && !!pivot && (
      dummy.position.distanceToSquared(pivot) > 1e-16 ||
      dummy.quaternion.angleTo(new THREE.Quaternion()) > 1e-8
    )
  }

  async function _persistCurrent({ atomic = false } = {}) {
    if (!tc) return { accepted: false, reason: 'preview_required', result: null }
    if (!_hasPendingMotion()) {
      return { accepted: false, reason: 'no_change', result: null }
    }
    const committed = targetInfos
    const bodies = _pendingBodies()
    // Keep the post-drag matrices on screen while the mutation and atom build run.
    // Restoring the preview here produced an avoidable old-position flash; moreover,
    // the design-response subscriber already owns the one required atomistic refresh.
    detach(false)
    try {
      let result = null
      if (atomic) result = await putNucleotideTransforms(bodies)
      else for (const body of bodies) result = await putNucleotideTransform(body)
      if (result) {
        return {
          accepted: true,
          reason: 'committed',
          result,
          targetCount: bodies.length,
        }
      }
    } catch (error) {
      console.error('Nucleotide transform commit failed:', error)
    }
    // Persistence failed, so roll the optimistic matrices back to their source pose.
    for (const x of committed) applyPreview(x, identity())
    showToast('Could not save the selected elements move.', { severity: 'error' })
    return { accepted: false, reason: 'request_failed', result: null }
  }

  async function confirm() {
    return _persistCurrent()
  }

  async function confirmVRPreview() {
    if (!vrPreviewRef) {
      return { accepted: false, reason: 'preview_required', result: null }
    }
    return _persistCurrent({ atomic: true })
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
    for (const x of targetInfos) applyPreview(x, identity())
  }

  function applyPreview(x, matrix) {
    if (x.kind === 'atomistic') x.renderer.applyResidueMatrix?.(x.target, matrix)
    else if (x.target.helix_id === '__xb__') designRenderer.applyXoverResidueMatrix?.(x.info, matrix)
    else designRenderer.applyResidueTransformMatrix?.(x.info, matrix)
  }

  function detach(restore = true) {
    if (restore && targets.length) restorePreview()
    if (tc) { tc.detach(); scene.remove(helper); tc.dispose?.() }
    dummy?.parent?.remove(dummy)
    document.removeEventListener('keydown', onKey)
    controls.enabled = true
    if (moveRotatePanel?.panel) moveRotatePanel.panel.style.display = 'none'
    tc = helper = dummy = pivot = null
    targets = []; targetInfos = []
    exactSessionRef = null
    vrPreviewRef = null
    dragging = false
    document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
  }

  function beginVRPreview(selectedRef) {
    const primary = canonicalSelection(store.getState()).primary
    if (!selectedRef || !selectionRefsEqual(primary, selectedRef)) {
      return { accepted: false, reason: 'selection_changed' }
    }
    if (vrPreviewRef && selectionRefsEqual(vrPreviewRef, selectedRef)) {
      return { accepted: true }
    }
    if (tc) return { accepted: false, reason: 'desktop_tool_active' }
    if (!activate({ exactRef: selectedRef })) {
      return { accepted: false, reason: 'target_unavailable' }
    }
    vrPreviewRef = { ...selectedRef }
    return { accepted: true }
  }

  function applyVRPreviewMatrix(matrixValues) {
    if (!vrPreviewRef || !Array.isArray(matrixValues) || matrixValues.length !== 16 ||
        !matrixValues.every(Number.isFinite)) return false
    const primary = canonicalSelection(store.getState()).primary
    if (!selectionRefsEqual(primary, vrPreviewRef)) {
      cancel()
      return false
    }
    const matrix = new THREE.Matrix4().fromArray(matrixValues)
    // Keep the hidden desktop transaction object numerically aligned with the
    // native preview. Persistence serializes this pivot-relative pose; updating
    // only renderer matrices would make Confirm save an identity transform.
    dummy.position.copy(pivot).applyMatrix4(matrix)
    dummy.quaternion.setFromRotationMatrix(matrix).normalize()
    for (const targetInfo of targetInfos) applyPreview(targetInfo, matrix)
    return true
  }

  function cancelVRPreview() {
    if (!vrPreviewRef) return false
    cancel()
    return true
  }

  function handleSelectionChange(newState, previousState) {
    if (!vrPreviewRef || newState.selection === previousState.selection) return false
    const primary = canonicalSelection(newState).primary
    if (selectionRefsEqual(primary, vrPreviewRef)) return false
    cancel()
    return true
  }

  function onKey(e) {
    if (e.key === 'Escape') { e.preventDefault(); cancel() }
    else if (e.key === 'Tab' && ['CANVAS', 'BODY'].includes(e.target?.tagName?.toUpperCase())) {
      e.preventDefault(); mode = mode === 'translate' ? 'rotate' : 'translate'; tc?.setMode(mode)
    }
  }

  return {
    activate, confirm, cancel, reset, detach, canActivate,
    beginVRPreview, applyVRPreviewMatrix, confirmVRPreview, cancelVRPreview,
    handleSelectionChange,
    isVRPreviewActive: () => !!vrPreviewRef,
    isActive: () => !!tc,
    debugState: () => ({
      active: !!tc, mode, pivot: pivot?.toArray() ?? null,
      exactSessionRef: exactSessionRef ? { ...exactSessionRef } : null,
      vrPreview: !!vrPreviewRef,
    }),
  }
}
