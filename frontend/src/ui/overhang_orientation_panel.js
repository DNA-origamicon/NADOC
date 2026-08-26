/**
 * Overhang Orientation right-sidebar panel — extracted from main.js (carve-up #64).
 *
 * Lets the user rotate one or more overhangs about their junction (root-bead) pivot:
 * a rotate-only TransformControls gizmo + ±45° step buttons + absolute XYZ-degree
 * fields, with instant client-side preview (no server round-trip until Apply). Apply
 * commits a *delta* rotation composed onto each overhang's Apply baseline via
 * `api.patchOverhangRotationsBatch`; Reset previews each overhang back to identity
 * (client-side only, baseline → identity, committed only on the following Apply);
 * Cancel reverts the preview by re-fetching server geometry. The panel auto-closes
 * when overhangs are structurally added/removed (not on a rotation patch).
 *
 * Factory `initOverhangOrientationPanel({deps})→{open, close, getActiveIds}`.
 * Pure core `buildOverhangRotationOps` (delta-compose op builder) is unit-tested.
 */
import * as THREE from 'three'
import { initOverhangGizmo } from '../scene/overhang_gizmo.js'
import { ovhgDomainIds, ovhgBinderDomainIds } from '../scene/design_queries.js'

/**
 * Build the rotation patch ops for `activeIds`: compose the world-space delta
 * `R_delta` (THREE.Quaternion) onto each overhang's Apply baseline. The baseline
 * defaults to the overhang's stored `rotation`, but `baseRotations` (a
 * `{id: [qx,qy,qz,qw]}` map) overrides it per-id — Reset sets the baseline to
 * identity so a subsequent Apply commits identity composed with any further
 * gizmo delta. Pure — THREE-only, no DOM/store/scene access.
 * @returns {{overhang_id: string, rotation: [number,number,number,number]}[]}
 */
export function buildOverhangRotationOps(activeIds, currentDesign, R_delta, baseRotations = null) {
  const ops = []
  for (const id of activeIds) {
    const o = currentDesign?.overhangs?.find(x => x.id === id)
    if (!o) continue
    const base = baseRotations?.[id] ?? o.rotation
    const R_existing = new THREE.Quaternion(base[0], base[1], base[2], base[3])
    const R_new = R_delta.clone().multiply(R_existing)
    ops.push({ overhang_id: id, rotation: [R_new.x, R_new.y, R_new.z, R_new.w] })
  }
  return ops
}

// The overhang's own strand domains PLUS any binder domains hybridized to it
// (OH_BINDER, LINKER complement, or end-to-root binder spliced into a STAPLE).
// This is the full set of domains that must rotate rigidly with the overhang —
// including a binder's toehold extending past the overhang on the same helix.
function domsForOverhang(id, design) {
  return [...(ovhgDomainIds(id, design) ?? []), ...ovhgBinderDomainIds(id, design)]
}

export function initOverhangOrientationPanel({
  store, api, scene, camera, canvas, controls,
  designRenderer, bluntEnds, overhangLocations, assemblyRenderer,
  getOvhgRootMap,
}) {
  const _ooPanel     = document.getElementById('overhang-orient-panel')
  const _ooInfo      = document.getElementById('overhang-orient-info')
  const _ooApplyBtn  = document.getElementById('oo-apply-btn')
  const _ooResetBtn  = document.getElementById('oo-reset-btn')
  const _ooCancelBtn = document.getElementById('oo-cancel-btn')
  const _ooRxInp     = document.getElementById('oo-rx')
  const _ooRyInp     = document.getElementById('oo-ry')
  const _ooRzInp     = document.getElementById('oo-rz')
  let   _ooActiveIds          = []    // overhang_id strings currently being edited
  let   _ooRightClickedId     = null  // anchor ID — gizmo centres on this overhang's pivot
  let   _ooOriginalRotations  = {}    // {id: [qx,qy,qz,qw]} captured on open, used by Cancel
  let   _ooBaseRotations      = {}    // {id: [qx,qy,qz,qw]} Apply baseline (Reset sets → identity)
  let   _ooPivotPositions     = {}    // {id: THREE.Vector3} junction bead positions in world space
  let   _ooDirtyPreview       = false // true once any drag-preview frame has fired

  function _ooOpen(ovhgIds, rightClickedId = null) {
    _ooActiveIds         = ovhgIds
    _ooRightClickedId    = rightClickedId ?? ovhgIds[0]
    _ooOriginalRotations = {}
    _ooBaseRotations     = {}
    _ooPivotPositions    = {}
    _ooDirtyPreview      = false

    const { currentDesign } = store.getState()
    for (const id of ovhgIds) {
      const o = currentDesign?.overhangs?.find(x => x.id === id)
      if (o) { _ooOriginalRotations[id] = [...o.rotation]; _ooBaseRotations[id] = [...o.rotation] }
      const root = getOvhgRootMap().get(id)
      if (root) _ooPivotPositions[id] = root.pos
    }

    if (!_ooPanel) return
    _ooPanel.style.display = ''

    if (_ooInfo) {
      const n = ovhgIds.length
      if (n === 1) {
        const label = currentDesign?.overhangs?.find(o => o.id === ovhgIds[0])?.label
        _ooInfo.textContent = label ? `"${label}"` : ovhgIds[0]
      } else {
        _ooInfo.textContent = `${n} overhangs selected`
      }
    }

    _ooUpdateAngleFields(new THREE.Quaternion())

    const anchorPivot = _ooPivotPositions[_ooRightClickedId] ?? null
    overhangGizmo.attach(_ooRightClickedId, ovhgIds, currentDesign, anchorPivot)
  }

  function _ooClose() {
    _ooActiveIds        = []
    _ooRightClickedId   = null
    _ooOriginalRotations = {}
    _ooBaseRotations    = {}
    if (_ooPanel) _ooPanel.style.display = 'none'
    overhangGizmo.detach()
    if (_ooDirtyPreview) {
      _ooDirtyPreview = false
      api.getGeometry()   // revert client-side preview — re-fetches current server geometry
    }
  }

  function _ooUpdateAngleFields(q) {
    const e = new THREE.Euler().setFromQuaternion(q, 'XYZ')
    const fmt = rad => parseFloat(THREE.MathUtils.radToDeg(rad).toFixed(1))
    if (_ooRxInp) _ooRxInp.value = fmt(e.x)
    if (_ooRyInp) _ooRyInp.value = fmt(e.y)
    if (_ooRzInp) _ooRzInp.value = fmt(e.z)
  }

  async function _ooApplyDelta(R_delta) {
    if (!_ooActiveIds.length) return
    const { currentDesign } = store.getState()
    const ops = buildOverhangRotationOps(_ooActiveIds, currentDesign, R_delta, _ooBaseRotations)
    if (ops.length) await api.patchOverhangRotationsBatch(ops)
    if (store.getState().assemblyActive) {
      const { activeInstanceId, currentAssembly } = store.getState()
      if (activeInstanceId) assemblyRenderer.invalidateInstance(activeInstanceId)
      await assemblyRenderer.rebuild(currentAssembly)
    }
    _ooDirtyPreview = false
    const { currentDesign: updated } = store.getState()
    const anchorPivot = _ooPivotPositions[_ooRightClickedId] ?? null
    overhangGizmo.attach(_ooRightClickedId, _ooActiveIds, updated, anchorPivot)
    _ooUpdateAngleFields(new THREE.Quaternion())
  }

  async function _ooApply() {
    await _ooApplyDelta(overhangGizmo.getCurrentRDelta())
    _ooClose()
  }

  // Instant client-side preview of an incremental rotation q_inc (world-space quaternion).
  // Captures the current rendered base, applies q_inc about each overhang's root bead,
  // and accumulates into the gizmo so getCurrentRDelta() and Apply stay consistent.
  // No server round-trip — same path as onPreview during a gizmo drag.
  function _ooPreviewIncrement(q_inc) {
    if (!_ooActiveIds.length) return
    const { currentDesign } = store.getState()
    const helixCtrl = designRenderer.getHelixCtrl()
    const helixIds = [], allDomainIds = []
    for (const id of _ooActiveIds) {
      const o = currentDesign?.overhangs?.find(x => x.id === id)
      if (!o) continue
      helixIds.push(o.helix_id)
      const domIds = domsForOverhang(id, currentDesign)
      if (domIds) allDomainIds.push(...domIds)
    }
    helixCtrl?.captureClusterBase(helixIds, allDomainIds.length ? allDomainIds : null)
    bluntEnds?.captureClusterBase(new Set(_ooActiveIds))
    _ooDirtyPreview = true
    for (const id of _ooActiveIds) {
      const o = currentDesign?.overhangs?.find(x => x.id === id)
      if (!o) continue
      const pivot = _ooPivotPositions[id]
        ?? new THREE.Vector3(o.pivot[0], o.pivot[1], o.pivot[2])
      const domIds = domsForOverhang(id, currentDesign)
      helixCtrl?.applyClusterTransform([o.helix_id], pivot, pivot, q_inc, domIds)
      bluntEnds?.applyClusterTransform([id], pivot, pivot, q_inc)
    }
    overhangGizmo.accumulateDelta(q_inc)
    _ooUpdateAngleFields(overhangGizmo.getCurrentRDelta())
  }

  // Reset every active overhang back to identity orientation — CLIENT-SIDE PREVIEW
  // only (no server round-trip; the zeroing commits on the following Apply). Unlike
  // the gizmo/step previews, "identity" is absolute, not a session delta, and each
  // overhang carries its own current orientation, so we apply a PER-OVERHANG world
  // delta that cancels (currentGizmoDelta · baselineᵢ). Setting each baseline to
  // identity makes Apply send identity (composed with any later gizmo delta), and
  // marks the panel dirty so Cancel reverts it via getGeometry.
  function _ooResetPreview() {
    if (!_ooActiveIds.length) return
    const { currentDesign } = store.getState()
    const helixCtrl = designRenderer.getHelixCtrl()
    const R_curInv = overhangGizmo.getCurrentRDelta().invert()  // undo the uniform gizmo delta

    // Capture the current rendered geometry as the base (same set as the preview path).
    const helixIds = [], allDomainIds = []
    for (const id of _ooActiveIds) {
      const o = currentDesign?.overhangs?.find(x => x.id === id)
      if (!o) continue
      helixIds.push(o.helix_id)
      const domIds = domsForOverhang(id, currentDesign)
      if (domIds) allDomainIds.push(...domIds)
    }
    helixCtrl?.captureClusterBase(helixIds, allDomainIds.length ? allDomainIds : null)
    bluntEnds?.captureClusterBase(new Set(_ooActiveIds))

    _ooDirtyPreview = true
    for (const id of _ooActiveIds) {
      const o = currentDesign?.overhangs?.find(x => x.id === id)
      if (!o) continue
      // current rendered orientation = R_cur · baselineᵢ; incremental world delta to
      // reach identity = baselineᵢ⁻¹ · R_cur⁻¹.
      const base = _ooBaseRotations[id] ?? [0, 0, 0, 1]
      const inc = new THREE.Quaternion(base[0], base[1], base[2], base[3]).invert().multiply(R_curInv)
      const pivot = _ooPivotPositions[id]
        ?? new THREE.Vector3(o.pivot[0], o.pivot[1], o.pivot[2])
      const domIds = domsForOverhang(id, currentDesign)
      helixCtrl?.applyClusterTransform([o.helix_id], pivot, pivot, inc, domIds)
      bluntEnds?.applyClusterTransform([id], pivot, pivot, inc)
      _ooBaseRotations[id] = [0, 0, 0, 1]
    }
  }

  // Preview the absolute Euler angles typed into the fields by computing the delta
  // from the current accumulated rotation to the target, then applying it incrementally.
  function _ooPreviewFromFields() {
    const rx = parseFloat(_ooRxInp?.value) || 0
    const ry = parseFloat(_ooRyInp?.value) || 0
    const rz = parseFloat(_ooRzInp?.value) || 0
    const Q_target = new THREE.Quaternion().setFromEuler(
      new THREE.Euler(
        THREE.MathUtils.degToRad(rx),
        THREE.MathUtils.degToRad(ry),
        THREE.MathUtils.degToRad(rz),
        'XYZ'
      )
    )
    const Q_delta = Q_target.clone().multiply(overhangGizmo.getCurrentRDelta().invert())
    _ooPreviewIncrement(Q_delta)
  }

  if (_ooApplyBtn)  _ooApplyBtn.addEventListener('click', _ooApply)
  if (_ooCancelBtn) _ooCancelBtn.addEventListener('click', _ooClose)

  if (_ooResetBtn) _ooResetBtn.addEventListener('click', () => {
    if (!_ooActiveIds.length) return
    _ooResetPreview()   // client-side preview to identity; commits only on the next Apply
    // Re-attach the gizmo at the (unchanged) junction pivot so it stays centred on the
    // right-clicked overhang — passing the cached pivot avoids the [0,0,0] fallback for
    // inline overhangs — and reset its accumulated delta to identity.
    const { currentDesign } = store.getState()
    const anchorPivot = _ooPivotPositions[_ooRightClickedId] ?? null
    overhangGizmo.attach(_ooRightClickedId, _ooActiveIds, currentDesign, anchorPivot)
    _ooUpdateAngleFields(new THREE.Quaternion())
  })

  // ── Overhang angle field wiring ──────────────────────────────────────────────

  const _ooAxisVecs = {
    rx: new THREE.Vector3(1, 0, 0),
    ry: new THREE.Vector3(0, 1, 0),
    rz: new THREE.Vector3(0, 0, 1),
  }

  function _ooStepAxis(axis, deg) {
    const q = new THREE.Quaternion().setFromAxisAngle(_ooAxisVecs[axis], THREE.MathUtils.degToRad(deg))
    _ooPreviewIncrement(q)
  }

  document.getElementById('oo-rx-dec')?.addEventListener('click', () => _ooStepAxis('rx', -45))
  document.getElementById('oo-rx-inc')?.addEventListener('click', () => _ooStepAxis('rx', +45))
  document.getElementById('oo-ry-dec')?.addEventListener('click', () => _ooStepAxis('ry', -45))
  document.getElementById('oo-ry-inc')?.addEventListener('click', () => _ooStepAxis('ry', +45))
  document.getElementById('oo-rz-dec')?.addEventListener('click', () => _ooStepAxis('rz', -45))
  document.getElementById('oo-rz-inc')?.addEventListener('click', () => _ooStepAxis('rz', +45))

  for (const inp of [_ooRxInp, _ooRyInp, _ooRzInp]) {
    inp?.addEventListener('keydown', e => { if (e.key === 'Enter') _ooPreviewFromFields() })
  }

  // ── Overhang gizmo (TransformControls, rotate-only) ─────────────────────────

  // Axis motion is always domain scoped. A no-scaffold stub is not necessarily
  // exclusive: imported designs can place several independent overhang domains
  // on it, so helix-wide movement is never a safe proxy for ownership.
  const overhangGizmo = initOverhangGizmo(scene, camera, canvas, controls)
  overhangGizmo.setCallbacks({
    onDragStart: (helixIds) => {
      const { currentDesign } = store.getState()
      const helixCtrl = designRenderer.getHelixCtrl()
      const allDomainIds = _ooActiveIds.flatMap(id => domsForOverhang(id, currentDesign))
      helixCtrl?.captureClusterBase(helixIds, allDomainIds.length ? allDomainIds : null)
      bluntEnds?.captureClusterBase(new Set(_ooActiveIds))
    },
    onPreview: (R_delta) => {
      _ooDirtyPreview = true
      const { currentDesign } = store.getState()
      const helixCtrl = designRenderer.getHelixCtrl()
      for (const id of _ooActiveIds) {
        const o = currentDesign?.overhangs?.find(x => x.id === id)
        if (!o) continue
        const pivot = _ooPivotPositions[id]
          ?? new THREE.Vector3(o.pivot[0], o.pivot[1], o.pivot[2])
        const domIds = domsForOverhang(id, currentDesign)
        helixCtrl?.applyClusterTransform([o.helix_id], pivot, pivot, R_delta, domIds)
        bluntEnds?.applyClusterTransform([id], pivot, pivot, R_delta)
      }
      _ooUpdateAngleFields(overhangGizmo.getCurrentRDelta())
    },
    onDragEnd: () => { /* no auto-commit — user presses Apply */ },
  })

  // Close the panel when overhangs are structurally added or removed (not on rotation patch).
  store.subscribe((newState, prevState) => {
    if (newState.currentDesign !== prevState.currentDesign) {
      const oldIds = new Set((prevState.currentDesign?.overhangs ?? []).map(o => o.id))
      const newIds = new Set((newState.currentDesign?.overhangs ?? []).map(o => o.id))
      const setsChanged = oldIds.size !== newIds.size || [...oldIds].some(id => !newIds.has(id))
      if (setsChanged && _ooActiveIds.length) _ooClose()
    }
  })

  return {
    open: _ooOpen,
    close: _ooClose,
    getActiveIds: () => _ooActiveIds,
  }
}
