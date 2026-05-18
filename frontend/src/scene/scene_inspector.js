/**
 * Scene Inspector — temporary debug overlay for identifying mystery 3D objects.
 *
 * Usage:
 *   1. Press Ctrl+Shift+I (or Cmd+Shift+I on Mac) to toggle inspect mode.
 *   2. Click any 3D object. A toast + console table show:
 *      - The clicked object's name, type, material, userData.
 *      - Its full ancestor chain up to scene root (with names + types).
 *      - World position.
 *   3. Press Ctrl+Shift+I again (or Esc) to exit inspect mode.
 *
 * The inspector raycasts against EVERY mesh in the scene (not just selectable
 * ones), bypassing the regular selection filter — so debug-only meshes, helper
 * lines, indicators, etc. all get hit.
 *
 * Designed to be left in the codebase as a low-cost diagnostic; bundle impact
 * is < 200 lines of code, no allocations until the user activates it.
 *
 * To launch programmatically:
 *   window.__nadocInspect.toggle()
 *   window.__nadocInspect.setActive(true|false)
 */

import * as THREE from 'three'
import { showToast, showPersistentToast, dismissToast } from '../ui/toast.js'

export function initSceneInspector({ scene, camera, canvas }) {
  let _active = false
  const _rc = new THREE.Raycaster()
  _rc.params.Line = { threshold: 0.18 }
  _rc.params.Points = { threshold: 0.5 }

  function _ndc(e) {
    const r = canvas.getBoundingClientRect()
    return {
      x:  ((e.clientX - r.left) / r.width)  * 2 - 1,
      y: -((e.clientY - r.top)  / r.height) * 2 + 1,
    }
  }

  /**
   * Match what the renderer actually shows: a leaf is "hittable" only if every
   * ancestor up to the scene root is also visible. (Three.js's renderer walks
   * the parent chain for visibility — `_allHittables` used to check only the
   * leaf's own `.visible`, surfacing hits on hidden subtrees and crowding out
   * the real culprit.)
   */
  function _isVisibleChain(obj) {
    let cur = obj
    while (cur) {
      if (cur.visible === false) return false
      cur = cur.parent
    }
    return true
  }

  function _allHittables() {
    const out = []
    scene.traverse((obj) => {
      if (!obj.isMesh && !obj.isLineSegments && !obj.isLine && !obj.isPoints && !obj.isSprite) return
      if (!_isVisibleChain(obj)) return
      out.push(obj)
    })
    return out
  }

  function _ancestorChain(obj) {
    const chain = []
    let cur = obj
    while (cur) {
      const label = cur.name || `(${cur.type || 'Object3D'})`
      const tag = cur.userData?.tag ? ` tag="${cur.userData.tag}"` : ''
      const inst = cur.userData?.assemblyInstance ? ` instance="${cur.userData.assemblyInstance}"` : ''
      chain.push(`${label}${tag}${inst}`)
      cur = cur.parent
    }
    return chain
  }

  function _summarize(hit) {
    const o = hit.object
    const worldPos = new THREE.Vector3()
    o.getWorldPosition(worldPos)
    const matName = o.material?.constructor?.name || (Array.isArray(o.material) ? 'array' : 'none')
    const matColor = (() => {
      const m = Array.isArray(o.material) ? o.material[0] : o.material
      return m?.color ? '#' + m.color.getHexString() : 'n/a'
    })()
    const summary = {
      type:      o.type,
      name:      o.name || '(unnamed)',
      material:  matName,
      color:     matColor,
      worldPos:  [worldPos.x, worldPos.y, worldPos.z].map(v => Number(v.toFixed(3))),
      userData:  o.userData || {},
      hitPoint:  [hit.point.x, hit.point.y, hit.point.z].map(v => Number(v.toFixed(3))),
      distance:  Number(hit.distance.toFixed(3)),
      ancestors: _ancestorChain(o.parent),
    }
    // Instanced-mesh detail: pull this exact instance's local matrix + world position.
    if (o.isInstancedMesh && typeof hit.instanceId === 'number') {
      summary.instanceId  = hit.instanceId
      summary.totalCount  = o.count
      summary.capacity    = o.instanceMatrix?.count ?? '?'
      const local = new THREE.Matrix4()
      o.getMatrixAt(hit.instanceId, local)
      const lp = new THREE.Vector3(), lq = new THREE.Quaternion(), ls = new THREE.Vector3()
      local.decompose(lp, lq, ls)
      summary.instanceLocalPos = [lp.x, lp.y, lp.z].map(v => Number(v.toFixed(3)))
      summary.instanceScale    = [ls.x, ls.y, ls.z].map(v => Number(v.toFixed(3)))
      const world = new THREE.Matrix4().multiplyMatrices(o.matrixWorld, local)
      const wp = new THREE.Vector3().setFromMatrixPosition(world)
      summary.instanceWorldPos = [wp.x, wp.y, wp.z].map(v => Number(v.toFixed(3)))
      // Per-instance color, if assigned.
      if (o.instanceColor && typeof o.getColorAt === 'function') {
        const c = new THREE.Color()
        o.getColorAt(hit.instanceId, c)
        summary.instanceColor = '#' + c.getHexString()
      }
      // Flag suspicious values (NaN / huge scale / huge offsets — phantom signs).
      const flags = []
      if (!Number.isFinite(lp.x) || !Number.isFinite(lp.y) || !Number.isFinite(lp.z)) flags.push('NaN-position')
      if (Math.max(Math.abs(ls.x), Math.abs(ls.y), Math.abs(ls.z)) > 1e3) flags.push('huge-scale')
      if (Math.min(Math.abs(ls.x), Math.abs(ls.y), Math.abs(ls.z)) < 1e-6) flags.push('zero-scale')
      if (flags.length) summary.flags = flags.join(',')
    }
    return summary
  }

  function _onClick(e) {
    if (!_active) return
    if (e.button !== 0) return
    e.preventDefault()
    e.stopPropagation()
    _rc.setFromCamera(_ndc(e), camera)
    const hits = _rc.intersectObjects(_allHittables(), false)
    if (!hits.length) {
      showToast('Inspector: nothing under cursor.', { duration: 1500 })
      return
    }
    // Show closest 1–3 hits; the user may have wanted a stacked one.
    const top = hits.slice(0, 3).map(_summarize)
    console.group('%c[scene_inspector]', 'color:#58a6ff;font-weight:bold', 'hit @ click')
    for (let i = 0; i < top.length; i++) {
      console.group(`hit #${i + 1}`)
      console.table(top[i])
      console.log('ancestor chain (innermost → root):')
      console.log(top[i].ancestors.join('\n  → '))
      console.dir(hits[i].object)
      console.groupEnd()
    }
    console.groupEnd()

    const headline = top[0].name !== '(unnamed)'
      ? top[0].name
      : (top[0].userData?.tag || top[0].ancestors.slice(0, 3).join(' → '))
    showToast(
      `Inspector: ${top[0].type} · ${headline} · ${top[0].material}${top.length > 1 ? ` · +${top.length - 1} behind` : ''}. See console for full chain.`,
      { duration: 6000 },
    )
  }

  function _onKey(e) {
    if (_active && e.key === 'Escape') {
      e.preventDefault()
      setActive(false)
      return
    }
    // Ctrl/Cmd + Shift + I  → toggle. (Browser dev tools also bind this, so
    // we only intercept when Shift is held alongside Ctrl/Meta to leave the
    // normal dev tools toggle untouched.)
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'I' || e.key === 'i')) {
      e.preventDefault()
      toggle()
    }
  }

  function setActive(on) {
    on = !!on
    if (on === _active) return
    _active = on
    if (on) {
      canvas.style.cursor = 'crosshair'
      canvas.addEventListener('pointerdown', _onClick, true)
      showPersistentToast(
        'Scene inspector ON — click anything · Esc to exit · console.table will show the hit chain',
        { severity: 'info' },
      )
    } else {
      canvas.style.cursor = ''
      canvas.removeEventListener('pointerdown', _onClick, true)
      dismissToast()
      showToast('Scene inspector OFF', { duration: 1200 })
    }
  }
  function toggle() { setActive(!_active) }
  function isActive() { return _active }

  document.addEventListener('keydown', _onKey)

  // Expose globally for console use.
  window.__nadocInspect = { toggle, setActive, isActive }
  return { toggle, setActive, isActive }
}
