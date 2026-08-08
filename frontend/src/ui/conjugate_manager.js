// Conjugate Manager — a windowed modal (sized/styled like the Overhangs Manager)
// that shows ONE imported protein in a fully operable 3D viewport and lets the
// user design an azide-oligo conjugate:
//   • left: the design's overhang list; selecting one fills the "ssDNA handle"
//     field with the overhang's reverse complement, a 5'/3' azide radio, and a
//     "Conjugate" button,
//   • centre: the protein in NADOC's bead/slab + connecting-cone model, with a
//     loading spinner while the surface sites are computed; surface-accessible
//     conjugation sites are pickable markers,
//   • right: a numbered, scrollable list of the conjugation sites. Selecting a
//     site (in the list OR by clicking its marker) glows it in both places;
//     "Conjugate" renders the ssDNA handle on the SELECTED site.
//
// Display/planning only — reads the protein's atoms + candidate residues from
// the backend and renders everything in a private THREE scene; it never mutates
// the design. Entry points wired in main.js → open(assetId).
//
// Factory (FEATURE_DEVELOPMENT.md): owns its own scene/renderer/DOM/listeners;
// pure logic (reverse complement, radial/perpendicular vectors, backbone points,
// marker colours, labels) lives in conjugate_manager_logic.js (tested).
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { docHeaders } from '../shared/doc_id.js'
import { initAtomisticRenderer } from '../scene/atomistic_renderer.js'
import {
  chemistryColor, chemistryCss, candidateLabel,
  reverseComplement, overhangLabel, radialOutward, perpendicular, ssdnaBackbonePoints,
} from './conjugate_manager_logic.js'

// Synthetic ssDNA preview constants; these do not define canonical duplex placement.
const BEAD_RADIUS = 0.10
const CONE_RADIUS = 0.075
const HELIX_RADIUS = 1.0
const SLAB = { length: 0.30, width: 0.06, thickness: 0.70, distance: 0.55 }
const SS_RISE_NM = 0.5            // ssDNA backbone bead spacing
const SS_COLOR = 0x4aa3ff         // handle strand colour
const Y_HAT = new THREE.Vector3(0, 1, 0)

function _ensureSpinStyle() {
  if (document.getElementById('cm-spin-style')) return
  const st = document.createElement('style')
  st.id = 'cm-spin-style'
  st.textContent =
    '@keyframes cm-spin{to{transform:rotate(360deg)}}' +
    '.cm-spinner{width:38px;height:38px;border:4px solid #30363d;border-top-color:#39c0ff;' +
    'border-radius:50%;animation:cm-spin .8s linear infinite}'
  document.head.appendChild(st)
}

export function initConjugateManager({ api, store } = {}) {
  let _ctx = null

  function _close() {
    if (!_ctx) return
    const c = _ctx
    _ctx = null
    if (c.raf) cancelAnimationFrame(c.raf)
    window.removeEventListener('keydown', c.onKey, true)
    window.removeEventListener('resize', c.onResize)
    try { c.controls?.dispose() } catch { /* ignore */ }
    try { c.glRenderer?.dispose() } catch { /* ignore */ }
    c.overlay.remove()
  }

  // ── pickable candidate markers ───────────────────────────────────────────────
  function _addMarkers(ctx, candidates) {
    const group = new THREE.Group()
    const geom = new THREE.SphereGeometry(0.24, 16, 12)
    ctx.markerMeshes = []
    candidates.forEach((cand, i) => {
      const mat = new THREE.MeshPhongMaterial({ color: chemistryColor(cand.chemistry), emissive: 0x000000 })
      const m = new THREE.Mesh(geom, mat)
      m.position.set(cand.x, cand.y, cand.z)
      m.userData.siteIndex = i
      group.add(m)
      ctx.markerMeshes.push(m)
    })
    ctx.scene.add(group)
    ctx.markerGroup = group
  }

  // ── select a site (drives BOTH the 3D glow and the right-hand list) ──────────
  function _selectSite(ctx, index) {
    ctx.selectedSiteIndex = index
    ctx.markerMeshes?.forEach((m, i) => {
      const on = i === index
      m.scale.setScalar(on ? 2.0 : 1.0)
      m.material.emissive.setHex(on ? m.material.color.getHex() : 0x000000)
    })
    ctx.listRows?.forEach((row, i) => row.classList.toggle('is-selected', i === index))
    if (index != null && ctx.listRows?.[index]) {
      ctx.listRows[index].scrollIntoView({ block: 'nearest' })
    }
    ctx.refreshApply?.()
  }

  // ── ssDNA handle in the bead/slab + connecting-cone model ────────────────────
  function _renderHandle(ctx, candidate, handleSeq, azideEnd) {
    if (ctx.handleGroup) { ctx.scene.remove(ctx.handleGroup); ctx.handleGroup = null }
    const c = ctx.renderer.centroidOf() || { x: 0, y: 0, z: 0 }
    const start = { x: candidate.x, y: candidate.y, z: candidate.z }
    const dir = radialOutward(start, c)
    const bn = perpendicular(dir)                     // base-normal for slabs
    const n = Math.max(1, (handleSeq || '').length || 6)
    const pts = ssdnaBackbonePoints(start, dir, n, SS_RISE_NM)

    const group = new THREE.Group()
    const dirV = new THREE.Vector3(dir.x, dir.y, dir.z)
    const bnV = new THREE.Vector3(bn.x, bn.y, bn.z)
    const coneQuat = new THREE.Quaternion().setFromUnitVectors(Y_HAT, dirV)
    // slab orientation: basis(tangential, tan, bn)
    const tangential = new THREE.Vector3().crossVectors(dirV, bnV).normalize()
    const slabQuat = new THREE.Quaternion().setFromRotationMatrix(
      new THREE.Matrix4().makeBasis(tangential, dirV, bnV))

    const beadGeom = new THREE.SphereGeometry(BEAD_RADIUS, 10, 8)
    const coneGeom = new THREE.ConeGeometry(CONE_RADIUS, 1, 8)
    const slabGeom = new THREE.BoxGeometry(SLAB.length, SLAB.width, SLAB.thickness)
    const mat = new THREE.MeshPhongMaterial({ color: SS_COLOR })
    const slabMat = new THREE.MeshPhongMaterial({ color: SS_COLOR, transparent: true, opacity: 0.9 })

    pts.forEach((p, i) => {
      const pv = new THREE.Vector3(p.x, p.y, p.z)
      // backbone bead
      const bead = new THREE.Mesh(beadGeom, mat)
      bead.position.copy(pv)
      group.add(bead)
      // Synthetic handle-preview slab. This is not the canonical duplex slab solver.
      const slab = new THREE.Mesh(slabGeom, slabMat)
      slab.position.copy(pv).addScaledVector(bnV, HELIX_RADIUS - SLAB.distance)
      slab.quaternion.copy(slabQuat)
      group.add(slab)
      // connecting cone to the next bead
      if (i < pts.length - 1) {
        const cone = new THREE.Mesh(coneGeom, mat)
        cone.position.copy(pv).addScaledVector(dirV, SS_RISE_NM / 2)
        cone.quaternion.copy(coneQuat)
        cone.scale.set(1, SS_RISE_NM, 1)
        group.add(cone)
      }
    })

    // azide-end marker (anchored tip): 5' = first bead, 3' = last bead
    const azPt = azideEnd === '3p' ? pts[pts.length - 1] : pts[0]
    const az = new THREE.Mesh(new THREE.SphereGeometry(0.45, 16, 12),
      new THREE.MeshPhongMaterial({ color: 0xff3b3b, emissive: 0x550000 }))
    az.position.set(azPt.x, azPt.y, azPt.z)
    group.add(az)

    ctx.scene.add(group)
    ctx.handleGroup = group
  }

  function _frame(ctx, atoms) {
    const c = ctx.renderer.centroidOf() || { x: 0, y: 0, z: 0 }
    let r = 1
    for (const a of atoms) {
      const dx = a.x - c.x, dy = a.y - c.y, dz = a.z - c.z
      r = Math.max(r, Math.sqrt(dx * dx + dy * dy + dz * dz))
    }
    const dist = r * 2.6 + 2
    ctx.controls.target.set(c.x, c.y, c.z)
    ctx.camera.position.set(c.x + dist * 0.4, c.y + dist * 0.35, c.z + dist)
    ctx.camera.near = Math.max(0.05, r / 100)
    ctx.camera.far = dist * 10
    ctx.camera.updateProjectionMatrix()
    ctx.controls.update()
  }

  // ── left sidebar: overhang list + handle field + azide radio + Conjugate ─────
  function _buildLeft(sidebar, ctx) {
    const overhangs = (store?.getState?.().currentDesign?.overhangs) ?? []

    const h = document.createElement('div')
    h.textContent = 'Overhangs'
    h.style.cssText = 'font-size:12px;color:#8b949e;text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px;'
    sidebar.appendChild(h)

    const list = document.createElement('div')
    list.style.cssText = 'flex:1;min-height:80px;overflow-y:auto;border:1px solid #30363d;border-radius:4px;margin-bottom:10px;'
    if (!overhangs.length) {
      list.innerHTML = '<div style="padding:14px;font-size:11px;color:#6e7681;text-align:center">No overhangs in this design.</div>'
    }
    sidebar.appendChild(list)

    const handleLbl = document.createElement('label')
    handleLbl.textContent = 'ssDNA handle'
    handleLbl.style.cssText = 'font-size:12px;color:#c9d1d9;display:block;margin-bottom:3px;'
    const handleInput = document.createElement('input')
    handleInput.type = 'text'; handleInput.readOnly = true; handleInput.placeholder = 'select an overhang'
    handleInput.style.cssText = 'width:100%;box-sizing:border-box;background:#0d1117;border:1px solid #30363d;'
      + 'border-radius:4px;color:#39c0ff;font-family:monospace;font-size:12px;padding:5px 7px;margin-bottom:10px;'
    sidebar.append(handleLbl, handleInput)

    const azWrap = document.createElement('div')
    azWrap.style.cssText = 'font-size:12px;color:#c9d1d9;margin-bottom:10px;'
    azWrap.innerHTML = 'Azide modification &nbsp;'
      + `<label style="margin-right:10px;"><input type="radio" name="cm-azide" value="5p" checked> 5′ end</label>`
      + `<label><input type="radio" name="cm-azide" value="3p"> 3′ end</label>`
    sidebar.appendChild(azWrap)

    const conjugateBtn = document.createElement('button')
    conjugateBtn.textContent = 'Conjugate'; conjugateBtn.disabled = true
    conjugateBtn.style.cssText = 'width:100%;background:#1f6feb;color:#fff;border:none;border-radius:5px;padding:8px;cursor:pointer;font-size:13px;'
    sidebar.appendChild(conjugateBtn)

    const status = document.createElement('div')
    status.style.cssText = 'font-size:11px;color:#8b949e;margin:8px 0;min-height:14px;'
    sidebar.appendChild(status)

    // Apply (commit to design) / Cancel (discard + close).
    const btnRow = document.createElement('div')
    btnRow.style.cssText = 'display:flex;gap:8px;margin-top:auto;'
    const cancelBtn = document.createElement('button')
    cancelBtn.textContent = 'Cancel'
    cancelBtn.style.cssText = 'flex:1;background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:5px;padding:8px;cursor:pointer;font-size:13px;'
    cancelBtn.addEventListener('click', _close)
    const applyBtn = document.createElement('button')
    applyBtn.textContent = 'Apply'; applyBtn.disabled = true
    applyBtn.style.cssText = 'flex:1;background:#238636;color:#fff;border:none;border-radius:5px;padding:8px;cursor:pointer;font-size:13px;'
    btnRow.append(cancelBtn, applyBtn)
    sidebar.appendChild(btnRow)

    // Apply enabled only once an overhang AND a site are both selected.
    ctx.refreshApply = () => { applyBtn.disabled = !(ctx.selectedOverhang && ctx.selectedSiteIndex != null) }

    applyBtn.addEventListener('click', async () => {
      if (!ctx.selectedOverhang || ctx.selectedSiteIndex == null) return
      const cand = ctx.candidates[ctx.selectedSiteIndex]
      const azideEnd = sidebar.querySelector('input[name="cm-azide"]:checked')?.value ?? '5p'
      applyBtn.disabled = true; status.textContent = 'Applying…'
      try {
        const res = await api?.conjugateProteinToOverhang?.({
          assetId: ctx.assetId, overhangId: ctx.selectedOverhang.id,
          conjugationAtomSerial: cand.functional_atom_serial, azideEnd,
        })
        if (res) { _close(); return }
        status.textContent = 'Conjugation failed.'; ctx.refreshApply()
      } catch (e) {
        status.textContent = 'Conjugation failed: ' + (e?.message ?? e); ctx.refreshApply()
      }
    })

    ctx.selectedOverhang = null
    const _selectOverhang = (ovhg, row) => {
      ctx.selectedOverhang = ovhg
      list.querySelectorAll('.ohc-list-row').forEach(r => r.classList.remove('is-selected'))
      row.classList.add('is-selected')
      const handle = reverseComplement(ovhg.sequence)
      handleInput.value = handle || ''
      handleInput.placeholder = handle ? '' : '(overhang has no sequence)'
      conjugateBtn.disabled = false
      ctx.refreshApply()
    }
    overhangs.forEach((ovhg) => {
      const row = document.createElement('div')
      row.className = 'ohc-list-row'
      row.style.cssText = 'padding:6px 9px;cursor:pointer;font-size:12px;border-bottom:1px solid #21262d;'
      row.textContent = overhangLabel(ovhg)
      row.addEventListener('click', () => _selectOverhang(ovhg, row))
      list.appendChild(row)
    })

    conjugateBtn.addEventListener('click', () => {
      if (!ctx.selectedOverhang) return
      const cands = ctx.candidates ?? []
      if (!cands.length) { status.textContent = 'No surface-accessible sites on this protein.'; return }
      // Use the selected site; if none chosen yet, pick one at random and select it.
      let idx = ctx.selectedSiteIndex
      if (idx == null) { idx = Math.floor(Math.random() * cands.length); _selectSite(ctx, idx) }
      const cand = cands[idx]
      const azideEnd = sidebar.querySelector('input[name="cm-azide"]:checked')?.value ?? '5p'
      const handle = reverseComplement(ctx.selectedOverhang.sequence)
      _renderHandle(ctx, cand, handle, azideEnd)
      status.textContent = `ssDNA on #${idx + 1} ${cand.res_name} ${cand.chain_id}:${cand.res_seq} `
        + `(azide ${azideEnd === '3p' ? '3′' : '5′'}, ${(handle || '').length || 6} nt)`
    })
  }

  // ── right sidebar: numbered conjugation-site list ────────────────────────────
  function _buildRight(rightbar, ctx, candidates) {
    rightbar.innerHTML = ''
    const h = document.createElement('div')
    h.textContent = `Conjugation sites (${candidates.length})`
    h.style.cssText = 'font-size:12px;color:#8b949e;text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px;'
    rightbar.appendChild(h)

    const list = document.createElement('div')
    list.style.cssText = 'flex:1;overflow-y:auto;border:1px solid #30363d;border-radius:4px;'
    if (!candidates.length) {
      list.innerHTML = '<div style="padding:14px;font-size:11px;color:#6e7681;text-align:center">No surface-accessible sites found.</div>'
    }
    rightbar.appendChild(list)

    ctx.listRows = []
    candidates.forEach((cand, i) => {
      const row = document.createElement('div')
      row.className = 'ohc-list-row'
      row.style.cssText = 'padding:5px 8px;cursor:pointer;font-size:12px;border-bottom:1px solid #21262d;white-space:nowrap;'
      row.innerHTML = `<span style="color:#6e7681;display:inline-block;width:22px">${i + 1}.</span>`
        + `<span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:${chemistryCss(cand.chemistry)};margin-right:6px;"></span>`
        + candidateLabel(cand)
      row.addEventListener('click', () => _selectSite(ctx, i))
      list.appendChild(row)
      ctx.listRows.push(row)
    })
  }

  // ── 3D marker picking (click a marker → select its site) ─────────────────────
  function _wireMarkerPicking(ctx, canvas) {
    const rc = new THREE.Raycaster()
    let downX = 0, downY = 0
    canvas.addEventListener('pointerdown', (e) => { downX = e.clientX; downY = e.clientY })
    canvas.addEventListener('pointerup', (e) => {
      if (Math.hypot(e.clientX - downX, e.clientY - downY) > 5) return  // was a drag (orbit/pan)
      if (!ctx.markerMeshes?.length) return
      const rect = canvas.getBoundingClientRect()
      const ndc = { x: ((e.clientX - rect.left) / rect.width) * 2 - 1, y: -((e.clientY - rect.top) / rect.height) * 2 + 1 }
      rc.setFromCamera(ndc, ctx.camera)
      const hit = rc.intersectObjects(ctx.markerMeshes, false)[0]
      if (hit) _selectSite(ctx, hit.object.userData.siteIndex)
    })
  }

  async function open(assetId) {
    if (!assetId) return
    _close()
    _ensureSpinStyle()

    // ── overlay + centered window (mirrors #overhangs-manager-modal) ─────────────
    const overlay = document.createElement('div')
    overlay.id = 'conjugate-manager-overlay'
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:9000;display:flex;align-items:center;justify-content:center;'
    overlay.addEventListener('click', (e) => { if (e.target === overlay) _close() })

    const win = document.createElement('div')
    win.style.cssText = 'background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px;'
      + 'width:960px;height:600px;max-width:96vw;max-height:90vh;display:flex;flex-direction:column;font-family:monospace;color:#e6e6e6;'

    const header = document.createElement('div')
    header.style.cssText = 'display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;flex:0 0 auto;'
    const title = document.createElement('div')
    title.style.cssText = 'font-size:15px;font-weight:600;'
    title.textContent = 'Conjugate Manager — azide-oligo to ssDNA handle'
    const closeBtn = document.createElement('button')
    closeBtn.textContent = '×'
    closeBtn.style.cssText = 'background:none;border:none;color:#8b949e;font-size:20px;cursor:pointer;padding:0 4px;'
    closeBtn.addEventListener('click', _close)
    header.append(title, closeBtn)

    const body = document.createElement('div')
    body.style.cssText = 'flex:1;display:flex;gap:14px;min-height:0;'

    const leftbar = document.createElement('div')
    leftbar.style.cssText = 'flex:0 0 230px;display:flex;flex-direction:column;min-height:0;'
    const canvasWrap = document.createElement('div')
    canvasWrap.style.cssText = 'flex:1;position:relative;min-width:0;border:1px solid #30363d;border-radius:4px;overflow:hidden;'
    const canvas = document.createElement('canvas')
    canvas.style.cssText = 'width:100%;height:100%;display:block;'
    canvasWrap.appendChild(canvas)
    const rightbar = document.createElement('div')
    rightbar.style.cssText = 'flex:0 0 200px;display:flex;flex-direction:column;min-height:0;'

    // loading spinner overlay (shown while the surface sites compute)
    const spinWrap = document.createElement('div')
    spinWrap.style.cssText = 'position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;color:#8b949e;font-size:12px;'
    spinWrap.innerHTML = '<div class="cm-spinner"></div><div>Computing surface sites…</div>'
    canvasWrap.appendChild(spinWrap)

    body.append(leftbar, canvasWrap, rightbar)
    win.append(header, body)
    overlay.appendChild(win)
    document.body.appendChild(overlay)

    // ── isolated THREE scene ─────────────────────────────────────────────────────
    const glRenderer = new THREE.WebGLRenderer({ canvas, antialias: true })
    glRenderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    const scene = new THREE.Scene()
    scene.background = new THREE.Color(0x0d1117)
    scene.add(new THREE.AmbientLight(0xffffff, 0.6))
    const keyLight = new THREE.DirectionalLight(0xffffff, 0.8)
    keyLight.position.set(1, 1, 1)
    scene.add(keyLight)
    const camera = new THREE.PerspectiveCamera(55, 1, 0.1, 2000)
    const controls = new OrbitControls(camera, canvas)
    controls.enableDamping = true
    controls.enablePan = true
    const renderer = initAtomisticRenderer(scene)

    function _sizeToCanvas() {
      const w = canvasWrap.clientWidth || 1, h = canvasWrap.clientHeight || 1
      glRenderer.setSize(w, h, false)
      camera.aspect = w / h
      camera.updateProjectionMatrix()
    }

    const onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); _close() } }
    const onResize = () => _sizeToCanvas()
    window.addEventListener('keydown', onKey, true)
    window.addEventListener('resize', onResize)

    _ctx = {
      overlay, glRenderer, scene, camera, controls, renderer, raf: null, onKey, onResize, assetId,
      candidates: [], markerMeshes: [], listRows: [], handleGroup: null, selectedSiteIndex: null,
    }
    _sizeToCanvas()
    _buildLeft(leftbar, _ctx)
    _buildRight(rightbar, _ctx, [])
    _wireMarkerPicking(_ctx, canvas)

    const tick = () => {
      if (!_ctx) return
      controls.update()
      glRenderer.render(scene, camera)
      _ctx.raf = requestAnimationFrame(tick)
    }
    _ctx.raf = requestAnimationFrame(tick)

    // ── data: atoms + conjugation candidates (spinner up until both land) ────────
    try {
      const resp = await fetch(`/api/design/protein/atomistic?asset_id=${encodeURIComponent(assetId)}`, { headers: docHeaders() })
      const atomData = resp.ok ? await resp.json() : { atoms: [] }
      if (!_ctx) return
      if (atomData?.atoms?.length) { renderer.setMode('vdw'); renderer.update(atomData) }
      const candResp = await api?.getConjugationCandidates?.(assetId)
      const candidates = candResp?.candidates ?? []
      if (!_ctx) return
      _ctx.candidates = candidates
      _addMarkers(_ctx, candidates)
      _buildRight(rightbar, _ctx, candidates)
      _frame(_ctx, atomData?.atoms ?? [])
    } catch (e) {
      console.error('Conjugate Manager load error:', e)
    } finally {
      spinWrap.remove()
    }
  }

  // ── one-item context menu used by the protein right-click entry point ────────
  function showConjugateMenu({ x, y, assetId } = {}) {
    if (!assetId) return
    document.getElementById('conjugate-context-menu')?.remove()
    const menu = document.createElement('div')
    menu.id = 'conjugate-context-menu'
    menu.style.cssText = `position:fixed;left:${x}px;top:${y}px;z-index:9500;background:#23262b;`
      + 'border:1px solid #555;border-radius:5px;padding:4px 0;box-shadow:0 2px 10px rgba(0,0,0,0.5);font-family:sans-serif;font-size:13px;color:#e6e6e6;'
    const item = document.createElement('div')
    item.textContent = 'Conjugate protein to ssDNA…'
    item.style.cssText = 'padding:6px 16px;cursor:pointer;white-space:nowrap;'
    item.addEventListener('mouseenter', () => { item.style.background = '#3a82f6' })
    item.addEventListener('mouseleave', () => { item.style.background = '' })
    const dismiss = () => { menu.remove(); window.removeEventListener('pointerdown', onOutside, true) }
    const onOutside = (ev) => { if (!menu.contains(ev.target)) dismiss() }
    item.addEventListener('click', () => { dismiss(); open(assetId) })
    menu.appendChild(item)
    document.body.appendChild(menu)
    setTimeout(() => window.addEventListener('pointerdown', onOutside, true), 0)
  }

  if (window.__NADOC_DBG__) window.__NADOC_DBG__.conjugateManager = { open, close: _close }

  return { open, close: _close, showConjugateMenu, isOpen: () => _ctx !== null }
}
