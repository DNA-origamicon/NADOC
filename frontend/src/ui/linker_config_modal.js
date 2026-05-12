/**
 * Interactive linker-shape picker / FJC sim modal.
 *
 * Two entry points share this modal:
 *   showLinkerConfigModal({ conn })            — interactive Apply/Cancel.
 *   showLinkerConfigModal({ readOnly: true })  — Help → "FJC sim" diagnostic.
 *
 * Layout: stats header, R_ee + Rg histograms SIDE BY SIDE, an orbitable
 * 3D snapshot of the selected bin, and a horizontal strip of small 2D
 * thumbnails for browsing.
 *
 * The R_ee histogram carries two draggable thumbs of distinct colors
 * (orange = min, cyan = max) that crop the kinematic range. The Rg
 * histogram is recomputed from ``rg_subcounts`` whenever the user
 * releases a thumb. The selected snapshot defaults to the bin whose
 * mid-R_ee is closest to the range centre.
 */

import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import {
  ensureLoaded as ensureFjcLookup,
  lookupEntry,
  defaultBinIndex,
  resolveBinIndex,
  filteredRgHistogram,
} from '../scene/ssdna_fjc.js'
import * as api from '../api/client.js'

// ── Colors ──────────────────────────────────────────────────────────────────
const COLOR_HIST_FG    = '#3b6fb0'
const COLOR_HIST_DIM   = '#1f3a5a'
const COLOR_AXIS       = '#8b949e'
const COLOR_LABEL      = '#c9d1d9'
const COLOR_THUMB_MIN  = '#f0883e'    // orange = lower limit
const COLOR_THUMB_MAX  = '#39d0d8'    // cyan   = upper limit
const COLOR_SELECTED   = '#f0883e'
const COLOR_RANGE_TINT = 'rgba(88,166,255,0.08)'

let _modalEl = null

// ── Histogram drawing ───────────────────────────────────────────────────────

function _drawReeHistogram(canvas, edges, bins, ctx) {
  const W = canvas.width
  const H = canvas.height
  const g = canvas.getContext('2d')
  g.clearRect(0, 0, W, H)

  const padL = 32, padR = 10, padT = 14, padB = 22
  const innerW = W - padL - padR
  const innerH = H - padT - padB
  const minX = edges[0], maxX = edges[edges.length - 1]
  const xToPx = v => padL + ((v - minX) / Math.max(1e-9, maxX - minX)) * innerW
  const pxToX = px => minX + ((px - padL) / innerW) * Math.max(1e-9, maxX - minX)
  const maxC = Math.max(1, ...bins.map(b => b.count ?? 0))

  if (ctx.interactive && Number.isFinite(ctx.rEeMin) && Number.isFinite(ctx.rEeMax)) {
    g.fillStyle = COLOR_RANGE_TINT
    g.fillRect(xToPx(ctx.rEeMin), padT, xToPx(ctx.rEeMax) - xToPx(ctx.rEeMin), innerH)
  }

  for (let i = 0; i < bins.length; i++) {
    const x0 = xToPx(edges[i])
    const x1 = xToPx(edges[i + 1])
    const c = bins[i].count ?? 0
    const y0 = padT + (1 - c / maxC) * innerH
    const y1 = padT + innerH
    const mid = 0.5 * (edges[i] + edges[i + 1])
    const inRange = !ctx.interactive ||
      (mid >= ctx.rEeMin - 1e-9 && mid <= ctx.rEeMax + 1e-9)
    let fill = inRange ? COLOR_HIST_FG : COLOR_HIST_DIM
    if (i === ctx.selectedBinIndex) fill = COLOR_SELECTED
    else if (i === ctx.hoverBinIndex && inRange) fill = '#58a6ff'
    g.fillStyle = fill
    g.fillRect(x0 + 0.5, y0, Math.max(0.5, x1 - x0 - 1), y1 - y0)
  }

  g.strokeStyle = COLOR_AXIS
  g.lineWidth = 1
  g.beginPath()
  g.moveTo(padL, padT); g.lineTo(padL, padT + innerH); g.lineTo(padL + innerW, padT + innerH); g.stroke()

  g.fillStyle = COLOR_LABEL
  g.font = '10px var(--font-ui,sans-serif)'
  g.textAlign = 'left';  g.fillText(`${minX.toFixed(2)}`, padL, H - 6)
  g.textAlign = 'right'; g.fillText(`${maxX.toFixed(2)} nm`, W - padR, H - 6)
  g.textAlign = 'right'
  g.fillText(`${maxC}`, padL - 4, padT + 8)
  g.fillText('0', padL - 4, padT + innerH)

  let thumbPxMin = padL, thumbPxMax = padL + innerW
  if (ctx.interactive) {
    thumbPxMin = xToPx(ctx.rEeMin)
    thumbPxMax = xToPx(ctx.rEeMax)
    // Min thumb (orange) — handle ABOVE the axis line.
    _drawThumb(g, thumbPxMin, padT, padT + innerH, COLOR_THUMB_MIN, /*up=*/false)
    g.fillStyle = COLOR_THUMB_MIN
    g.font = 'bold 10px var(--font-ui,sans-serif)'; g.textAlign = 'center'
    g.fillText(`min ${ctx.rEeMin.toFixed(2)}`, thumbPxMin, padT - 3)
    // Max thumb (cyan).
    _drawThumb(g, thumbPxMax, padT, padT + innerH, COLOR_THUMB_MAX, /*up=*/true)
    g.fillStyle = COLOR_THUMB_MAX
    g.fillText(`max ${ctx.rEeMax.toFixed(2)}`, thumbPxMax, padT - 3)
  }

  return {
    xToPx, pxToX,
    thumbPxMin, thumbPxMax,
    padL, padR, padT, padB, innerW, innerH,
    binAtPx(px) {
      if (px < padL || px > padL + innerW) return -1
      const x = pxToX(px)
      for (let i = 0; i < bins.length; i++) {
        if (x >= edges[i] && x <= edges[i + 1]) return i
      }
      return -1
    },
  }
}

function _drawThumb(g, x, yTop, yBot, color, /*unused*/_up) {
  g.strokeStyle = color; g.lineWidth = 2
  g.beginPath(); g.moveTo(x, yTop); g.lineTo(x, yBot); g.stroke()
  g.fillStyle = color
  // Diamond handle straddling the axis baseline so it's always grabbable.
  g.beginPath()
  g.moveTo(x, yBot - 8)
  g.lineTo(x + 6, yBot)
  g.lineTo(x, yBot + 8)
  g.lineTo(x - 6, yBot)
  g.closePath(); g.fill()
}

function _drawRgHistogram(canvas, edges, counts) {
  const W = canvas.width, H = canvas.height
  const g = canvas.getContext('2d')
  g.clearRect(0, 0, W, H)
  if (!edges?.length || !counts?.length) return
  const padL = 32, padR = 10, padT = 14, padB = 22
  const innerW = W - padL - padR
  const innerH = H - padT - padB
  const minX = edges[0], maxX = edges[edges.length - 1]
  const maxC = Math.max(1, ...counts)
  const xToPx = v => padL + ((v - minX) / Math.max(1e-9, maxX - minX)) * innerW

  g.fillStyle = COLOR_HIST_FG
  for (let i = 0; i < counts.length; i++) {
    const x0 = xToPx(edges[i])
    const x1 = xToPx(edges[i + 1])
    const c = counts[i]
    const y0 = padT + (1 - c / maxC) * innerH
    g.fillRect(x0 + 0.5, y0, Math.max(0.5, x1 - x0 - 1), padT + innerH - y0)
  }
  g.strokeStyle = COLOR_AXIS
  g.beginPath()
  g.moveTo(padL, padT); g.lineTo(padL, padT + innerH); g.lineTo(padL + innerW, padT + innerH); g.stroke()
  g.fillStyle = COLOR_LABEL
  g.font = '10px var(--font-ui,sans-serif)'
  g.textAlign = 'left';  g.fillText(`${minX.toFixed(2)}`, padL, H - 6)
  g.textAlign = 'right'; g.fillText(`${maxX.toFixed(2)} nm`, W - padR, H - 6)
  g.textAlign = 'right'
  g.fillText(`${maxC}`, padL - 4, padT + 8)
  g.fillText('0', padL - 4, padT + innerH)
}

function _drawChainThumb(canvas, positions, color) {
  const W = canvas.width, H = canvas.height
  const g = canvas.getContext('2d')
  g.clearRect(0, 0, W, H)
  if (!positions?.length) return
  const xs = positions.map(p => p[0])
  const ys = positions.map(p => -p[1])
  const minX = Math.min(...xs), maxX = Math.max(...xs)
  const minY = Math.min(...ys), maxY = Math.max(...ys)
  const span = Math.max(maxX - minX, maxY - minY, 0.5)
  const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2
  const pad = 8
  const s = Math.min((W - 2 * pad) / span, (H - 2 * pad) / span)
  const px = v => W / 2 + (v - cx) * s
  const py = v => H / 2 + (v - cy) * s

  g.strokeStyle = color; g.lineWidth = 1.2
  g.beginPath()
  for (let i = 0; i < positions.length; i++) {
    const x = px(positions[i][0]); const y = py(-positions[i][1])
    if (i === 0) g.moveTo(x, y); else g.lineTo(x, y)
  }
  g.stroke()
  g.fillStyle = '#fff'
  g.beginPath(); g.arc(px(positions[0][0]), py(-positions[0][1]), 2.5, 0, Math.PI * 2); g.fill()
  g.beginPath(); g.arc(px(positions.at(-1)[0]), py(-positions.at(-1)[1]), 2.5, 0, Math.PI * 2); g.fill()
}

// ── Orbitable 3D snapshot viewer ────────────────────────────────────────────

/**
 * A small Three.js scene wrapped in an OrbitControls. Render-on-demand:
 * each frame is rendered only while the user drags or after `setChain`.
 * Returns { setChain(positions), dispose() }.
 */
function _create3DViewer(container, width = 700, height = 320) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false })
  renderer.setPixelRatio(window.devicePixelRatio || 1)
  renderer.setSize(width, height, /*updateStyle=*/true)
  renderer.setClearColor(0x0d1117, 1)
  container.appendChild(renderer.domElement)

  const scene = new THREE.Scene()
  const camera = new THREE.PerspectiveCamera(45, width / height, 0.01, 200)
  camera.position.set(0, 0, 6)
  scene.add(new THREE.AmbientLight(0xffffff, 0.6))
  const dirLight = new THREE.DirectionalLight(0xffffff, 0.7)
  dirLight.position.set(2, 3, 4)
  scene.add(dirLight)
  scene.add(new THREE.AxesHelper(0.4))

  const controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  controls.dampingFactor = 0.1

  const chainGroup = new THREE.Group()
  scene.add(chainGroup)

  let needsRender = true
  let raf = null
  let alive = true

  function _render() {
    if (!alive) return
    controls.update()
    renderer.render(scene, camera)
  }
  function _loop() {
    if (!alive) return
    raf = requestAnimationFrame(_loop)
    // Damping needs continuous updates while damping is settling.
    if (controls.enableDamping || needsRender) {
      _render()
      needsRender = false
    }
  }
  _loop()

  controls.addEventListener('change', () => { needsRender = true })

  function _disposeGroup() {
    while (chainGroup.children.length) {
      const c = chainGroup.children.pop()
      c.geometry?.dispose?.()
      const mats = Array.isArray(c.material) ? c.material : [c.material]
      mats.forEach(m => m?.dispose?.())
    }
  }

  return {
    setChain(positions) {
      _disposeGroup()
      if (!positions || positions.length < 1) { needsRender = true; return }

      // Centre on chain centroid.
      const centre = new THREE.Vector3()
      for (const p of positions) centre.add(new THREE.Vector3(p[0], p[1], p[2]))
      centre.divideScalar(positions.length)

      const sphereGeo = new THREE.SphereGeometry(0.13, 14, 10)
      const endSphereGeo = new THREE.SphereGeometry(0.22, 16, 12)
      const beadMat = new THREE.MeshPhongMaterial({ color: 0xf0883e, shininess: 60 })
      const endMat  = new THREE.MeshPhongMaterial({ color: 0xffffff, shininess: 60 })
      const bondMat = new THREE.MeshPhongMaterial({ color: 0xfdbf80, shininess: 30 })

      const pts = positions.map(p => new THREE.Vector3(p[0] - centre.x, p[1] - centre.y, p[2] - centre.z))

      // Beads.
      pts.forEach((p, i) => {
        const isEnd = (i === 0 || i === pts.length - 1)
        const m = new THREE.Mesh(isEnd ? endSphereGeo : sphereGeo, isEnd ? endMat : beadMat)
        m.position.copy(p)
        chainGroup.add(m)
      })

      // Bonds as cylinders between consecutive beads.
      const up = new THREE.Vector3(0, 1, 0)
      for (let i = 0; i < pts.length - 1; i++) {
        const a = pts[i], b = pts[i + 1]
        const v = new THREE.Vector3().subVectors(b, a)
        const len = v.length()
        if (len < 1e-6) continue
        const cyl = new THREE.Mesh(
          new THREE.CylinderGeometry(0.045, 0.045, len, 10, 1, false),
          bondMat,
        )
        cyl.position.copy(a).addScaledVector(v, 0.5)
        cyl.quaternion.setFromUnitVectors(up, v.clone().normalize())
        chainGroup.add(cyl)
      }

      // Frame the camera around the chain's bounding sphere.
      const radius = Math.max(0.5, ...pts.map(p => p.length()))
      const distance = radius / Math.tan((camera.fov / 2) * Math.PI / 180) * 1.4
      camera.position.set(distance, distance * 0.4, distance)
      camera.lookAt(0, 0, 0)
      controls.target.set(0, 0, 0)
      controls.update()
      needsRender = true
    },
    dispose() {
      alive = false
      if (raf) cancelAnimationFrame(raf)
      _disposeGroup()
      controls.dispose()
      renderer.dispose()
      renderer.domElement.remove()
    },
  }
}

// ── Modal controller ────────────────────────────────────────────────────────

function _connNbp(conn) {
  const v = Number(conn?.length_value ?? 1)
  if (conn?.length_unit === 'nm') return Math.max(1, Math.round(v / 0.334))
  return Math.max(1, Math.round(v))
}

function _buildModal({ readOnly, conn }) {
  const backdrop = document.createElement('div')
  backdrop.style.cssText =
    'position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:10001;' +
    'display:flex;align-items:center;justify-content:center'
  const dialog = document.createElement('div')
  dialog.style.cssText =
    'background:#161b22;border:1px solid #30363d;border-radius:6px;' +
    'padding:14px 16px;width:min(1080px,96vw);max-height:94vh;overflow:auto;' +
    'font-family:var(--font-ui,sans-serif);font-size:12px;color:#c9d1d9'
  backdrop.appendChild(dialog)

  // Header bar
  const hdr = document.createElement('div')
  hdr.style.cssText = 'display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:8px'
  const titleEl = document.createElement('h3')
  titleEl.style.cssText = 'margin:0;color:#e6edf3;font-size:14px'
  titleEl.textContent = readOnly
    ? 'FJC sim — ssDNA lookup diagnostic'
    : `Configure ss linker · ${conn?.name ?? conn?.id ?? ''}`
  const hdrRight = document.createElement('div')
  hdrRight.style.cssText = 'display:flex;align-items:center;gap:8px'
  const lenLbl = document.createElement('label')
  lenLbl.textContent = 'Length:'; lenLbl.style.cssText = 'color:#8b949e;font-size:11px'
  const lenSel = document.createElement('select')
  lenSel.style.cssText = 'background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:4px;padding:3px 6px;font-family:inherit;font-size:11px'
  const closeBtn = document.createElement('button')
  closeBtn.textContent = '✕'
  closeBtn.style.cssText = 'background:#21262d;border:1px solid #30363d;border-radius:3px;color:#c9d1d9;cursor:pointer;padding:3px 8px'
  hdrRight.append(lenLbl, lenSel, closeBtn)
  hdr.append(titleEl, hdrRight)
  dialog.appendChild(hdr)

  const statsEl = document.createElement('div')
  statsEl.style.cssText  = 'color:#8b949e;font-size:11px;padding:2px 0 8px'
  dialog.appendChild(statsEl)

  // Side-by-side histogram grid
  const histGrid = document.createElement('div')
  histGrid.style.cssText = 'display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px'
  dialog.appendChild(histGrid)

  function _histCell(titleText) {
    const wrap = document.createElement('div')
    const t = document.createElement('div')
    t.style.cssText = 'color:#8b949e;font-size:11px;margin-bottom:4px'
    t.textContent = titleText
    const c = document.createElement('canvas')
    c.width = 520; c.height = 200
    c.style.cssText = 'background:#0d1117;border:1px solid #30363d;border-radius:4px;width:100%;height:200px;display:block;cursor:pointer'
    wrap.append(t, c)
    histGrid.appendChild(wrap)
    return c
  }
  const reeCanvas = _histCell(readOnly
    ? 'R_ee (end-to-end) histogram'
    : 'R_ee histogram — drag the orange (min) and cyan (max) thumbs to set kinematic limits')
  const rgCanvas  = _histCell('Rg (radius of gyration) histogram — auto-filters to the R_ee range above')

  // 3D snapshot viewer
  const previewTitle = document.createElement('div')
  previewTitle.style.cssText = 'color:#8b949e;font-size:11px;margin-bottom:4px'
  previewTitle.textContent = '3D snapshot (left-drag to orbit, right-drag to pan, scroll to zoom)'
  const previewContainer = document.createElement('div')
  previewContainer.style.cssText = 'border:1px solid #30363d;border-radius:4px;overflow:hidden;background:#0d1117;width:100%;height:320px'
  const previewMeta = document.createElement('div')
  previewMeta.style.cssText = 'color:#c9d1d9;font-size:11px;margin-top:4px'
  dialog.append(previewTitle, previewContainer, previewMeta)

  // Snapshot strip
  const stripTitle = document.createElement('div')
  stripTitle.style.cssText = 'color:#8b949e;font-size:11px;margin:10px 0 4px'
  stripTitle.textContent = 'Bins in range (click to select)'
  const stripEl = document.createElement('div')
  stripEl.style.cssText = 'display:flex;gap:4px;overflow-x:auto;padding-bottom:6px'
  dialog.append(stripTitle, stripEl)

  // Footer
  const footerEl = document.createElement('div')
  footerEl.style.cssText = 'display:flex;justify-content:flex-end;gap:8px;padding-top:10px;border-top:1px solid #30363d;margin-top:10px'
  dialog.appendChild(footerEl)

  // ── State ──────────────────────────────────────────────────────────
  const state = {
    statusEl:      null,
    nBp:           conn ? _connNbp(conn) : 20,
    initialNBp:    conn ? _connNbp(conn) : null,
    selectedBin:   conn?.bridge_bin_index ?? null,
    rEeMin:        conn?.bridge_r_ee_min_nm ?? null,
    rEeMax:        conn?.bridge_r_ee_max_nm ?? null,
    hoverBin:      -1,
    draggingThumb: null,   // 'min' | 'max' | null
    entry:         null,
    helper:        null,
    viewer:        null,
  }

  // Footer buttons (interactive mode only)
  let applyBtn = null
  if (!readOnly) {
    const status = document.createElement('div')
    status.style.cssText = 'flex:1;color:#8b949e;font-size:11px;align-self:center'
    footerEl.appendChild(status)
    state.statusEl = status
    const cancelBtn = document.createElement('button')
    cancelBtn.textContent = 'Cancel'
    cancelBtn.style.cssText = 'padding:5px 14px;background:#21262d;border:1px solid #30363d;border-radius:4px;color:#c9d1d9;cursor:pointer;font-family:inherit;font-size:12px'
    cancelBtn.addEventListener('click', () => _close())
    applyBtn = document.createElement('button')
    applyBtn.textContent = 'Apply'
    applyBtn.style.cssText = 'padding:5px 16px;background:#1f6feb;border:1px solid #1f6feb;border-radius:4px;color:#fff;cursor:pointer;font-family:inherit;font-size:12px;font-weight:bold'
    applyBtn.addEventListener('click', () => _apply())
    footerEl.append(cancelBtn, applyBtn)
  }

  document.body.appendChild(backdrop)
  backdrop.addEventListener('click', e => { if (e.target === backdrop) _close() })
  closeBtn.addEventListener('click', () => _close())

  function _close() {
    state.viewer?.dispose?.()
    state.viewer = null
    if (_modalEl === backdrop) _modalEl = null
    backdrop.remove()
  }

  // Initialise the 3D viewer once (it sizes itself to its container).
  state.viewer = _create3DViewer(previewContainer, 700, 320)

  // ── Apply ──────────────────────────────────────────────────────────
  async function _apply() {
    if (!conn) return _close()
    applyBtn.disabled = true
    state.statusEl.textContent = 'Applying…'
    try {
      if (state.nBp !== state.initialNBp) {
        const lengthRes = await api.patchOverhangConnection(conn.id, {
          length_value: state.nBp,
          length_unit:  'bp',
        })
        if (lengthRes == null) throw new Error('length update failed')
      }
      const res = await api.relaxLinker(conn.id, null, {
        binIndex: state.selectedBin,
        rEeMinNm: state.rEeMin,
        rEeMaxNm: state.rEeMax,
      })
      if (res == null) throw new Error('relax failed')
      _close()
    } catch (err) {
      state.statusEl.textContent = `Apply failed: ${err?.message || err}`
      applyBtn.disabled = false
    }
  }

  // ── Length picker ──────────────────────────────────────────────────
  function _populateLengthOptions(maxBp) {
    lenSel.innerHTML = ''
    for (let n = 2; n <= Math.min(maxBp, 100); n++) {
      const opt = document.createElement('option')
      opt.value = String(n); opt.textContent = `${n} bp`
      lenSel.appendChild(opt)
    }
  }
  lenSel.addEventListener('change', () => {
    state.nBp = parseInt(lenSel.value, 10)
    // New ensemble → reset thumbs + selection to the new defaults.
    state.rEeMin = null
    state.rEeMax = null
    state.selectedBin = null
    _loadEntry()
  })

  // ── R_ee canvas interactions ───────────────────────────────────────
  function _canvasPx(e, canvas) {
    const r = canvas.getBoundingClientRect()
    return ((e.clientX - r.left) / r.width) * canvas.width
  }
  function _onReePointerDown(e) {
    const px = _canvasPx(e, reeCanvas)
    if (readOnly) {
      const k = state.helper?.binAtPx(px) ?? -1
      if (k >= 0 && state.entry.bins[k].count > 0) {
        state.selectedBin = resolveBinIndex(state.nBp, k) ?? state.selectedBin
        _render()
      }
      return
    }
    const dMin = Math.abs(px - state.helper.thumbPxMin)
    const dMax = Math.abs(px - state.helper.thumbPxMax)
    if (Math.min(dMin, dMax) <= 12) {
      state.draggingThumb = dMin < dMax ? 'min' : 'max'
      reeCanvas.setPointerCapture?.(e.pointerId)
      e.preventDefault()
      return
    }
    const k = state.helper.binAtPx(px)
    if (k >= 0) {
      const mid = 0.5 * (state.entry.r_ee_bin_edges_nm[k] + state.entry.r_ee_bin_edges_nm[k + 1])
      if (mid >= state.rEeMin - 1e-9 && mid <= state.rEeMax + 1e-9 && state.entry.bins[k].count > 0) {
        state.selectedBin = resolveBinIndex(state.nBp, k) ?? state.selectedBin
        _render()
      }
    }
  }
  function _onReePointerMove(e) {
    const px = _canvasPx(e, reeCanvas)
    if (state.draggingThumb) {
      const val = state.helper.pxToX(px)
      const lo  = state.entry.r_ee_bin_edges_nm[0]
      const hi  = state.entry.r_ee_bin_edges_nm.at(-1)
      const clamped = Math.max(lo, Math.min(hi, val))
      if (state.draggingThumb === 'min') {
        state.rEeMin = Math.min(clamped, state.rEeMax - 1e-3)
      } else {
        state.rEeMax = Math.max(clamped, state.rEeMin + 1e-3)
      }
      _renderHistograms()
    } else {
      const k = state.helper.binAtPx(px)
      if (k !== state.hoverBin) { state.hoverBin = k; _renderHistograms() }
    }
  }
  function _onReePointerUp() {
    if (state.draggingThumb) {
      state.draggingThumb = null
      _ensureSelectionInRange()
      _render()
    }
  }
  reeCanvas.addEventListener('pointerdown', _onReePointerDown)
  reeCanvas.addEventListener('pointermove', _onReePointerMove)
  reeCanvas.addEventListener('pointerup',   _onReePointerUp)
  reeCanvas.addEventListener('pointerleave',() => { if (state.hoverBin !== -1) { state.hoverBin = -1; _renderHistograms() } })

  function _ensureSelectionInRange() {
    const edges = state.entry.r_ee_bin_edges_nm
    const bins  = state.entry.bins
    const sel = state.selectedBin
    if (sel != null && bins[sel]) {
      const mid = 0.5 * (edges[sel] + edges[sel + 1])
      if (mid >= state.rEeMin - 1e-9 && mid <= state.rEeMax + 1e-9 && bins[sel].count > 0) return
    }
    const centre = 0.5 * (state.rEeMin + state.rEeMax)
    let best = sel, bestErr = Infinity
    for (let k = 0; k < bins.length; k++) {
      if (bins[k].count === 0) continue
      const mid = 0.5 * (edges[k] + edges[k + 1])
      if (mid < state.rEeMin - 1e-9 || mid > state.rEeMax + 1e-9) continue
      const err = Math.abs(mid - centre)
      if (err < bestErr) { bestErr = err; best = k }
    }
    state.selectedBin = best ?? state.selectedBin
  }

  // ── Renderers ──────────────────────────────────────────────────────
  function _renderHistograms() {
    state.helper = _drawReeHistogram(reeCanvas, state.entry.r_ee_bin_edges_nm, state.entry.bins, {
      interactive: !readOnly,
      rEeMin: state.rEeMin, rEeMax: state.rEeMax,
      selectedBinIndex: state.selectedBin,
      hoverBinIndex: state.hoverBin,
    })
    const filtered = filteredRgHistogram(state.nBp, state.rEeMin, state.rEeMax)
    _drawRgHistogram(rgCanvas, filtered?.bin_edges_nm, filtered?.counts)
  }

  function _renderPreview() {
    const entry = state.entry
    const bins = entry.bins
    let idx = state.selectedBin
    if (idx == null || !bins[idx] || bins[idx].count === 0) {
      idx = resolveBinIndex(state.nBp, idx ?? defaultBinIndex(state.nBp) ?? 0) ?? 0
      state.selectedBin = idx
    }
    const b = bins[idx]
    state.viewer.setChain(b?.rep_positions ?? [])
    const c = b?.count ?? 0
    previewMeta.innerHTML = `
      <strong style="color:${COLOR_SELECTED}">Bin ${idx}</strong> · R_ee = ${b?.rep_r_ee_nm?.toFixed(3) ?? '—'} nm · Rg = ${b?.rep_rg_nm?.toFixed(3) ?? '—'} nm · sampled count = ${c}
    `
  }

  function _renderStrip() {
    stripEl.innerHTML = ''
    const entry = state.entry
    const edges = entry.r_ee_bin_edges_nm
    for (let k = 0; k < entry.bins.length; k++) {
      const b = entry.bins[k]
      if (b.count === 0) continue
      const mid = 0.5 * (edges[k] + edges[k + 1])
      if (mid < state.rEeMin - 1e-9 || mid > state.rEeMax + 1e-9) continue
      const cell = document.createElement('div')
      const isSel = state.selectedBin === k
      cell.style.cssText = (
        'flex:0 0 110px;padding:4px;border-radius:4px;cursor:pointer;' +
        `border:1px solid ${isSel ? COLOR_SELECTED : '#30363d'};` +
        `background:${isSel ? '#2a1f12' : '#0d1117'}`
      )
      const c = document.createElement('canvas')
      c.width = 100; c.height = 60
      c.style.cssText = 'width:100%;height:60px;display:block'
      cell.appendChild(c)
      _drawChainThumb(c, b.rep_positions, isSel ? COLOR_SELECTED : '#58a6ff')
      const lbl = document.createElement('div')
      lbl.style.cssText = 'font-size:9px;color:#8b949e;text-align:center;margin-top:2px'
      lbl.textContent = `R_ee ${b.rep_r_ee_nm.toFixed(2)} · Rg ${b.rep_rg_nm.toFixed(2)}`
      cell.appendChild(lbl)
      cell.addEventListener('click', () => { state.selectedBin = k; _render() })
      stripEl.appendChild(cell)
    }
  }

  function _renderStats() {
    const entry = state.entry
    statsEl.innerHTML = `
      <strong>n_bp = ${entry.n_bp}</strong> · N_kuhn = ${entry.n_kuhn} · wall D = ${entry.wall_separation_nm?.toFixed(2)} nm |
      ⟨R_ee⟩ = ${entry.r_ee_mean_nm?.toFixed(2)} ± ${entry.r_ee_std_nm?.toFixed(2)} nm |
      ⟨Rg⟩ = ${entry.rg_mean_nm?.toFixed(2)} ± ${entry.rg_std_nm?.toFixed(2)} nm |
      pool n_both_ok = ${entry.n_both_ok}
    `
  }

  function _render() {
    _renderHistograms()
    _renderPreview()
    _renderStrip()
  }

  function _loadEntry() {
    const entry = lookupEntry(state.nBp)
    state.entry = entry
    if (!entry) {
      statsEl.textContent = `No data for n_bp=${state.nBp}.`
      return
    }
    _renderStats()
    // Default R_ee thumbs at ~10% inset from each extreme (interactive mode).
    // Use the populated-bin edges so the thumbs don't sit over an empty tail.
    const edges = entry.r_ee_bin_edges_nm
    const occBins = entry.bins.map((b, k) => b.count > 0 ? k : -1).filter(k => k >= 0)
    const occLo = occBins.length ? edges[occBins[0]]               : edges[0]
    const occHi = occBins.length ? edges[occBins.at(-1) + 1]       : edges.at(-1)
    const span  = Math.max(1e-9, occHi - occLo)
    if (state.rEeMin == null) state.rEeMin = occLo + span * 0.10
    if (state.rEeMax == null) state.rEeMax = occHi - span * 0.10
    state.rEeMin = Math.max(state.rEeMin, edges[0])
    state.rEeMax = Math.min(state.rEeMax, edges.at(-1))
    if (state.rEeMax <= state.rEeMin) {
      state.rEeMin = occLo; state.rEeMax = occHi   // safety: thumbs collapsed → re-expand
    }

    if (state.selectedBin == null || !entry.bins[state.selectedBin]?.count) {
      state.selectedBin = defaultBinIndex(state.nBp) ?? 0
    }
    _ensureSelectionInRange()
    _render()
  }

  ensureFjcLookup().then(payload => {
    const maxBp = payload?.metadata?.max_new_algorithm_bp ?? 35
    _populateLengthOptions(maxBp)
    lenSel.value = String(Math.min(Math.max(state.nBp, 2), maxBp))
    state.nBp = parseInt(lenSel.value, 10)
    _loadEntry()
  }).catch(err => {
    statsEl.textContent = `Lookup load failed: ${err?.message || err}`
  })

  return backdrop
}

/** Open the linker config / FJC sim modal.
 *  @param {{ readOnly?: boolean, conn?: object }} opts */
export function showLinkerConfigModal(opts = {}) {
  if (_modalEl) {
    _modalEl.remove()
    _modalEl = null
  }
  _modalEl = _buildModal({
    readOnly: !!opts.readOnly,
    conn:     opts.conn ?? null,
  })
}
