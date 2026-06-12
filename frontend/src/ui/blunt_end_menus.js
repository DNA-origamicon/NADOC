// Blunt-end (domain-end) interaction menus: the right-sidebar action panel and
// the right-click context menu shown when a domain/blunt end is picked. Both
// share the same three actions (Extrude continuation / Bend / Twist) over a
// captured domain-end info object. Extracted verbatim from main.js (#88).
import { startToolAtBp } from '../scene/deformation_editor.js'
import { showToast } from './toast.js'

// deps: { store, api, slicePlane, expandedSpacing, deformView, clusterDeformGuard, extrudePanel }
// `clusterDeformGuard` is main.js's hoisted `_clusterDeformGuard` (aliased here
// to keep the moved handler bodies byte-identical). `extrudePanel` opens the
// right-sidebar Extrude panel (which hosts the slice-extrude controls) for the
// blunt-end continuation / deformed-continuation flows.
export function initBluntEndMenus({ store, api, slicePlane, expandedSpacing, deformView, clusterDeformGuard: _clusterDeformGuard, extrudePanel }) {
  // ── Blunt end sidebar panel ──────────────────────────────────────────────────
  const _bluntPanel        = document.getElementById('blunt-panel-actions')
  const _bluntPanelEmpty   = document.getElementById('blunt-panel-empty')
  const _bluntPanelInfo    = document.getElementById('blunt-panel-info')
  let   _domainEndInfo     = null  // { helixId, bp, diskBp, openSide, plane, offsetNm, hasDeformations }

  function _showBluntPanel(info) {
    _domainEndInfo = info
    if (_bluntPanelEmpty)  _bluntPanelEmpty.style.display  = 'none'
    if (_bluntPanelInfo)   _bluntPanelInfo.textContent = `helix ${info.helixId}  bp ${info.bp}`
    if (_bluntPanel)       _bluntPanel.style.display = 'block'
  }
  function _hideBluntPanel() {
    _domainEndInfo = null
    if (_bluntPanel)      _bluntPanel.style.display      = 'none'
    if (_bluntPanelEmpty) _bluntPanelEmpty.style.display = ''
  }

  // ── Blunt end right-click context menu ──────────────────────────────────────
  const _bluntCtx = document.getElementById('blunt-end-ctx-menu')
  let _domainEndCtxInfo = null  // { helixId, bp, diskBp, openSide, plane, offsetNm, hasDeformations }

  function _showBluntCtx(x, y, info) {
    _domainEndCtxInfo = info
    if (_bluntCtx) {
      _bluntCtx.style.left = `${x}px`
      _bluntCtx.style.top  = `${y}px`
      _bluntCtx.style.display = 'block'
    }
  }
  function _hideBluntCtx() {
    if (_bluntCtx) _bluntCtx.style.display = 'none'
    _domainEndCtxInfo = null
  }

  document.addEventListener('pointerdown', e => {
    if (_bluntCtx?.style.display !== 'none' && !_bluntCtx.contains(e.target)) _hideBluntCtx()
  })

  async function _bluntExtrude() {
    const info = _domainEndInfo   // capture before _hideBluntPanel nulls it
    _hideBluntPanel()
    if (!info) return
    const { plane, helixId, hasDeformations } = info
    // Anchor the continuation on the helix's axis endpoint, not the between-index
    // disk slot.  axis_end sits one rise PAST the last bp (so far end: diskBp=bp+1),
    // but axis_start sits AT the first bp (so near end must use bp, not bp-1).
    //   near (openSide -1) → bp        far (openSide +1) → bp+1 (= diskBp)
    // Default the ±dir to "away from the body" (openSide): minus for near, plus for far.
    const continuationBp = info.bp + Math.max(0, info.openSide)
    store.setState({ currentPlane: plane })
    expandedSpacing.forceOff()   // expanded spacing off while slice plane is active
    const { deformVisuActive } = store.getState()
    if (hasDeformations && deformVisuActive) {
      const frame = await api.getDeformedFrame(continuationBp, helixId)
      if (frame) {
        extrudePanel?.activate('deformed', { plane })
        slicePlane.showDeformed(frame, { plane, continuation: true, refHelixId: helixId, defaultDirSign: info.openSide })
        document.getElementById('mode-indicator').textContent =
          'DEFORMED CONTINUATION — amber = extend existing strand · select cells → Extrude · Esc to close'
        return
      }
    }
    extrudePanel?.activate('continuation', { plane })
    slicePlane.showAtEnd(helixId, continuationBp, true, { defaultDirSign: info.openSide })
    document.getElementById('mode-indicator').textContent =
      'CONTINUATION — amber = extend existing strand · select cells → Extrude · Esc to close'
  }

  // Retarget an *armed primitive placement* onto this blunt-end face: the primitive's
  // footprint becomes a continuation extrude from the end (cells over existing helix-
  // ends extend them; fresh cells make new helices). Mirrors _bluntExtrude's face
  // targeting, but arms the slice-plane placement instead of the extrude panel.
  async function _placeOnEnd(info) {
    if (!info) return
    const { plane, helixId, hasDeformations } = info
    const continuationBp = info.bp + Math.max(0, info.openSide)
    store.setState({ currentPlane: plane })
    expandedSpacing.forceOff()
    const { deformVisuActive } = store.getState()
    let armed
    if (hasDeformations && deformVisuActive) {
      // Bent end → place onto the DEFORMED cross-section frame (same path as the
      // deformed blunt-end continuation).
      const frame = await api.getDeformedFrame(continuationBp, helixId)
      armed = frame && slicePlane.showPlacementDeformed(frame, { plane, refHelixId: helixId, defaultDirSign: info.openSide })
    } else {
      armed = slicePlane.showPlacementAtEnd(helixId, continuationBp, { defaultDirSign: info.openSide })
    }
    if (!armed) {
      showToast('Placing this primitive on a face isn’t supported yet (try a flat end / a beam primitive).', { severity: 'error' })
      return
    }
    document.getElementById('mode-indicator').textContent =
      'PLACE PRIMITIVE ON FACE — hover a lattice cell · click to place · Esc to cancel'
  }

  document.getElementById('blunt-extrude-btn')?.addEventListener('click', _bluntExtrude)
  document.getElementById('blunt-bend-btn')?.addEventListener('click', () => {
    const info = _domainEndInfo
    _hideBluntPanel()
    if (!info) return
    if (!deformView.isActive() && store.getState().currentDesign?.deformations?.length) {
      showToast('Switch back to deformed view (View → Deformed View) before adding further deformations.', { severity: 'error' })
      return
    }
    if (!_clusterDeformGuard()) return
    startToolAtBp('bend', info.helixId, info.bp, info.openSide)
    document.getElementById('mode-indicator').textContent =
      'BEND — drag planes to adjust segment · apply in popup · Esc to cancel'
  })
  document.getElementById('blunt-twist-btn')?.addEventListener('click', () => {
    const info = _domainEndInfo
    _hideBluntPanel()
    if (!info) return
    if (!deformView.isActive() && store.getState().currentDesign?.deformations?.length) {
      showToast('Switch back to deformed view (View → Deformed View) before adding further deformations.', { severity: 'error' })
      return
    }
    if (!_clusterDeformGuard()) return
    startToolAtBp('twist', info.helixId, info.bp, info.openSide)
    document.getElementById('mode-indicator').textContent =
      'TWIST — drag planes to adjust segment · apply in popup · Esc to cancel'
  })

  // ── Context menu button wiring (right-click blunt end) ────────────────────
  document.getElementById('blunt-extrude-btn-ctx')?.addEventListener('click', async () => {
    const info = _domainEndCtxInfo
    _hideBluntCtx()
    if (!info) return
    const { plane, helixId, hasDeformations } = info
    // See _bluntExtrude: anchor on the axis endpoint (near→bp, far→bp+1) and default
    // the ±dir to "away from the body" (openSide).
    const continuationBp = info.bp + Math.max(0, info.openSide)
    store.setState({ currentPlane: plane })
    expandedSpacing.forceOff()   // expanded spacing off while slice plane is active
    const { deformVisuActive } = store.getState()
    if (hasDeformations && deformVisuActive) {
      const frame = await api.getDeformedFrame(continuationBp, helixId)
      if (frame) {
        extrudePanel?.activate('deformed', { plane })
        slicePlane.showDeformed(frame, { plane, continuation: true, refHelixId: helixId, defaultDirSign: info.openSide })
        document.getElementById('mode-indicator').textContent =
          'DEFORMED CONTINUATION — amber = extend existing strand · select cells → Extrude · Esc to close'
        return
      }
    }
    extrudePanel?.activate('continuation', { plane })
    slicePlane.showAtEnd(helixId, continuationBp, true, { defaultDirSign: info.openSide })
    document.getElementById('mode-indicator').textContent =
      'CONTINUATION — amber = extend existing strand · select cells → Extrude · Esc to close'
  })
  document.getElementById('blunt-bend-btn-ctx')?.addEventListener('click', () => {
    const info = _domainEndCtxInfo
    _hideBluntCtx()
    if (!info) return
    if (!deformView.isActive() && store.getState().currentDesign?.deformations?.length) {
      showToast('Switch back to deformed view (View → Deformed View) before adding further deformations.', { severity: 'error' })
      return
    }
    if (!_clusterDeformGuard()) return
    startToolAtBp('bend', info.helixId, info.bp, info.openSide)
    document.getElementById('mode-indicator').textContent =
      'BEND — drag planes to adjust segment · apply in popup · Esc to cancel'
  })
  document.getElementById('blunt-twist-btn-ctx')?.addEventListener('click', () => {
    const info = _domainEndCtxInfo
    _hideBluntCtx()
    if (!info) return
    if (!deformView.isActive() && store.getState().currentDesign?.deformations?.length) {
      showToast('Switch back to deformed view (View → Deformed View) before adding further deformations.', { severity: 'error' })
      return
    }
    if (!_clusterDeformGuard()) return
    startToolAtBp('twist', info.helixId, info.bp, info.openSide)
    document.getElementById('mode-indicator').textContent =
      'TWIST — drag planes to adjust segment · apply in popup · Esc to cancel'
  })

  return {
    showPanel: _showBluntPanel,
    hidePanel: _hideBluntPanel,
    showCtx:   _showBluntCtx,
    hideCtx:   _hideBluntCtx,
    placeOnEnd: _placeOnEnd,
  }
}
