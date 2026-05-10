/**
 * ui/periodic_md_panel.js — Periodic MD panel
 *
 * File pickers for PSF (topology), PDB (coordinates), and DCD (trajectory).
 * After loading, displays status and a live DCD frame scrubber.
 * Delegates 3D preview to periodicMdOverlay (scene module).
 *
 * DCD access: only the header (first 4 KB) is read up-front; individual frames
 * are loaded on-demand via File.slice() to handle multi-GB trajectories.
 */

import {
  parsePDB,
  parsePSF,
  parseDCDHeader,
  parseDCDFrameSlice,
} from '../scene/periodic_md_overlay.js'
import { computeSegments } from '../scene/md_segmentation_overlay.js'

export function initPeriodicMdPanel(store, { periodicMdOverlay, setCGVisible, getDesign }) {
  // ── DOM refs ───────────────────────────────────────────────────────────────
  const panel   = document.getElementById('periodic-md-panel')
  if (!panel) return

  const heading = document.getElementById('periodic-md-heading')
  const arrow   = document.getElementById('periodic-md-arrow')
  const body    = document.getElementById('periodic-md-body')

  const psfName    = document.getElementById('pmd-psf-name')
  const psfBrowse  = document.getElementById('pmd-psf-browse')
  const pdbName    = document.getElementById('pmd-pdb-name')
  const pdbBrowse  = document.getElementById('pmd-pdb-browse')
  const dcdName    = document.getElementById('pmd-dcd-name')
  const dcdBrowse  = document.getElementById('pmd-dcd-browse')
  const loadBtn    = document.getElementById('pmd-load-btn')
  const statusBlk  = document.getElementById('pmd-status')
  const scrubWrap  = document.getElementById('pmd-scrub-wrap')
  const scrubber   = document.getElementById('pmd-scrubber')
  const timeCur    = document.getElementById('pmd-time-cur')
  const timeTot    = document.getElementById('pmd-time-tot')
  const logEl      = document.getElementById('pmd-log')
  const applyBtn   = document.getElementById('pmd-apply-btn')

  // ── Collapse toggle ────────────────────────────────────────────────────────
  heading?.addEventListener('click', () => {
    const open = body.style.display !== 'none'
    body.style.display = open ? 'none' : 'block'
    arrow?.classList.toggle('is-collapsed', open)
  })

  // ── State ──────────────────────────────────────────────────────────────────
  let _psfText      = null
  let _pdbAtoms     = null
  let _dcdFile      = null   // File object — NOT a full ArrayBuffer (file can be multi-GB)
  let _dcdInfo      = null   // parsed from header-only slice
  let _dnaIndices   = null   // PDB atom indices for DNA P atoms (centroid + alignment)
  let _heavyIndices = null   // PDB atom indices for all heavy DNA atoms (rendering)

  function _log(msg) {
    if (!logEl) return
    logEl.textContent += msg + '\n'
    logEl.scrollTop = logEl.scrollHeight
  }

  // ── Read a single DCD frame on-demand (slice, not full load) ───────────────
  // Retries once after 200 ms to tolerate concurrent writes from a live simulation.
  async function _readDCDFrame(fi, retries = 1) {
    const { headerEnd, frameBytes } = _dcdInfo
    const start = headerEnd + fi * frameBytes
    try {
      const sliceBuf = await _dcdFile.slice(start, start + frameBytes).arrayBuffer()
      return parseDCDFrameSlice(sliceBuf, _dcdInfo)
    } catch (err) {
      if (retries > 0) {
        await new Promise(r => setTimeout(r, 200))
        return _readDCDFrame(fi, retries - 1)
      }
      throw err
    }
  }

  // Safe upper bound for frame access: stay 2 frames back from the reported end
  // to avoid partially-written trailing frames in a live simulation.
  function _safeLastFrame() {
    return Math.max(0, (_dcdInfo?.actualFrames ?? 1) - 3)
  }

  // ── Button state helpers ───────────────────────────────────────────────────
  function _updateLoadBtn() {
    const ready = _pdbAtoms !== null
    if (loadBtn) {
      loadBtn.disabled = !ready
      loadBtn.style.color  = ready ? '#c9d1d9' : '#484f58'
      loadBtn.style.cursor = ready ? 'pointer'  : 'not-allowed'
    }
  }

  let _applyActive = false

  function _updateApplyBtn() {
    const ready = _dcdFile !== null && _dnaIndices !== null
    if (!applyBtn) return
    applyBtn.disabled = !ready
    if (_applyActive) {
      applyBtn.textContent       = 'Revert to CG'
      applyBtn.style.color       = '#c9d1d9'
      applyBtn.style.cursor      = 'pointer'
      applyBtn.style.background  = '#1f4a8a'
      applyBtn.style.borderColor = '#388bfd'
    } else {
      applyBtn.textContent       = 'Apply to Design'
      applyBtn.style.color       = ready ? '#c9d1d9' : '#484f58'
      applyBtn.style.cursor      = ready ? 'pointer'  : 'not-allowed'
      applyBtn.style.background  = '#21262d'
      applyBtn.style.borderColor = '#30363d'
    }
  }

  function _setApplyActive(active) {
    _applyActive = active
    _updateApplyBtn()
  }

  // ── File helpers ───────────────────────────────────────────────────────────
  function _makeHiddenInput(accept, onFile) {
    const inp = document.createElement('input')
    inp.type   = 'file'
    inp.accept = accept
    inp.style.display = 'none'
    document.body.appendChild(inp)
    inp.addEventListener('change', () => {
      const f = inp.files[0]
      if (f) onFile(f)
      inp.value = ''
    })
    return inp
  }

  // PSF
  const _psfInput = _makeHiddenInput('.psf', f => {
    if (psfName) { psfName.textContent = f.name; psfName.title = f.name }
    f.text().then(txt => { _psfText = txt; _log(`PSF: ${f.name}`) })
  })
  psfBrowse?.addEventListener('click', () => _psfInput.click())

  // PDB
  const _pdbInput = _makeHiddenInput('.pdb', f => {
    if (pdbName) { pdbName.textContent = f.name; pdbName.title = f.name }
    f.text().then(txt => {
      _pdbAtoms = parsePDB(txt)
      _log(`PDB: ${f.name}  (${_pdbAtoms.length.toLocaleString()} atoms)`)
      _updateLoadBtn()
    })
  })
  pdbBrowse?.addEventListener('click', () => _pdbInput.click())

  // DCD — read only the first 4 KB to parse the header; store the File for on-demand frame access
  const _dcdInput = _makeHiddenInput('.dcd', f => {
    if (dcdName) { dcdName.textContent = f.name; dcdName.title = f.name }
    f.slice(0, 4096).arrayBuffer()
      .then(headerBuf => {
        _dcdInfo = parseDCDHeader(headerBuf, f.size)
        _dcdFile = f
        const { natom, actualFrames, dtNs } = _dcdInfo
        _log(`DCD: ${f.name}  (${natom.toLocaleString()} atoms, ${actualFrames} frames, ${(dtNs * actualFrames).toFixed(3)} ns)`)
        _updateApplyBtn()
      })
      .catch(err => _log(`DCD header error: ${err.message}`))
  })
  dcdBrowse?.addEventListener('click', () => _dcdInput.click())

  // ── Load & Preview ─────────────────────────────────────────────────────────
  loadBtn?.addEventListener('click', async () => {
    if (!_pdbAtoms) return
    logEl && (logEl.textContent = '')
    periodicMdOverlay.clear()

    // ── Step 1: compute DNA P-atom indices early (needed for alignment and scrubber) ──
    const pIndicesBase = _pdbAtoms
      .map((a, i) => ({ a, i }))
      .filter(({ a }) =>
        a.name === 'P' &&
        !a.segname.match(/^(SOL|ION)/i) &&
        (a.resname === 'DA' || a.resname === 'DT' || a.resname === 'DG' || a.resname === 'DC' ||
         a.resname === 'ADE' || a.resname === 'THY' || a.resname === 'GUA' || a.resname === 'CYT'),
      )
      .map(({ i }) => i)
    _dnaIndices = pIndicesBase.length
      ? pIndicesBase
      : _pdbAtoms.map((a,i)=>({a,i})).filter(({a})=>a.name==='P'&&!a.segname.match(/^(SOL|ION)/i)).map(({i})=>i)

    // ── Step 2: compute alignment BEFORE loadPDB so the mesh is built at the right position ──
    // Prefer DCD frame 0 centroid (more accurate after minimization) over static PDB centroid.
    const design = getDesign?.()
    let alignFrame = null
    if (_dcdFile && _dcdInfo && _dnaIndices.length) {
      try {
        alignFrame = await _readDCDFrame(0)
        const dcdPAtoms = _dnaIndices.map(i => ({ x: alignFrame.x[i], y: alignFrame.y[i], z: alignFrame.z[i] }))
        periodicMdOverlay.setPreviewAlignment(design, dcdPAtoms)
        _log('Alignment: DCD frame 0')
      } catch {
        alignFrame = null
      }
    }
    if (!alignFrame) {
      const pAtoms = _pdbAtoms.filter(a => a.name === 'P' && !a.segname.match(/^(SOL|ION)/i))
      periodicMdOverlay.setPreviewAlignment(design, pAtoms)
      _log('Alignment: static PDB centroid')
    }

    // ── Step 3: build mesh (now uses the correct _alignOffset from Step 2) ──
    periodicMdOverlay.loadPDB(_pdbAtoms)
    _heavyIndices = periodicMdOverlay.getAtomIndices()
    const nPreview = periodicMdOverlay.atomCount()
    _log(`Preview: ${nPreview} heavy atoms`)

    // ── Step 4: apply DCD frame 0 to get equilibrated positions ──
    if (alignFrame && _heavyIndices?.length) {
      periodicMdOverlay.setFrame(alignFrame.x, alignFrame.y, alignFrame.z, _heavyIndices)
    }

    // ── Status block ──────────────────────────────────────────────────────────
    const dnaAtoms = _pdbAtoms.filter(a => !a.segname.match(/^(SOL|ION)/i))
    const watAtoms = _pdbAtoms.filter(a =>  a.segname.match(/^SOL/i))
    const ionAtoms = _pdbAtoms.filter(a =>  a.segname.match(/^ION/i))

    let xMin=Infinity,xMax=-Infinity,yMin=Infinity,yMax=-Infinity,zMin=Infinity,zMax=-Infinity
    for (const a of _pdbAtoms) {
      if (a.x < xMin) xMin=a.x; if (a.x > xMax) xMax=a.x
      if (a.y < yMin) yMin=a.y; if (a.y > yMax) yMax=a.y
      if (a.z < zMin) zMin=a.z; if (a.z > zMax) zMax=a.z
    }
    const cellX = ((xMax - xMin) * 0.1).toFixed(2)
    const cellY = ((yMax - yMin) * 0.1).toFixed(2)
    const cellZ = ((zMax - zMin) * 0.1).toFixed(2)

    const safeFrames = _dcdInfo ? Math.max(0, _dcdInfo.actualFrames - 2) : 0
    _setStatus([
      `Total atoms  : ${_pdbAtoms.length.toLocaleString()}`,
      `DNA atoms    : ${dnaAtoms.length.toLocaleString()}`,
      `Water        : ${(watAtoms.length / 3) | 0} molecules`,
      `Ions         : ${ionAtoms.length}`,
      `Cell (nm)    : ${cellX} × ${cellY} × ${cellZ}`,
      _dcdInfo
        ? `DCD frames   : ${safeFrames}  (${(_dcdInfo.dtNs * safeFrames).toFixed(2)} ns)`
        : 'DCD          : not loaded',
    ])

    if (_psfText) {
      const psf = parsePSF(_psfText)
      _log(`PSF NATOM: ${psf.natom.toLocaleString()}`)
      if (psf.natom !== _pdbAtoms.length) {
        _log(`⚠ PSF/PDB atom count mismatch (${psf.natom} vs ${_pdbAtoms.length})`)
      }
    }

    // ── DCD scrubber ──────────────────────────────────────────────────────────
    if (_dcdInfo && safeFrames > 0) {
      scrubber.min   = 0
      scrubber.max   = safeFrames - 1
      scrubber.value = 0
      if (timeTot) timeTot.textContent = (_dcdInfo.dtNs * safeFrames).toFixed(3) + ' ns'
      if (scrubWrap) scrubWrap.style.display = 'block'
    } else {
      if (scrubWrap) scrubWrap.style.display = 'none'
    }
    _updateApplyBtn()
  })

  // ── Scrubber ───────────────────────────────────────────────────────────────
  scrubber?.addEventListener('input', async () => {
    const fi = parseInt(scrubber.value)
    if (timeCur && _dcdInfo) timeCur.textContent = (fi * _dcdInfo.dtNs).toFixed(3) + ' ns'
    await _applyFrame(fi)
  })

  async function _applyFrame(fi) {
    if (!_dcdFile || !_dcdInfo || !_heavyIndices) return
    try {
      const { x, y, z } = await _readDCDFrame(fi)
      periodicMdOverlay.setFrame(x, y, z, _heavyIndices)
    } catch (err) {
      _log(`Frame ${fi} read error: ${err.message}`)
    }
  }

  // ── Apply to design toggle ─────────────────────────────────────────────────
  applyBtn?.addEventListener('click', async () => {
    if (_applyActive) {
      periodicMdOverlay.clearApplied()
      periodicMdOverlay.setPreviewVisible(true)
      setCGVisible?.(true)
      _setApplyActive(false)
      _log('Reverted to CG representation')
      return
    }

    const design = getDesign?.()
    if (!design) { _log('No design loaded'); return }
    if (!_dcdFile || !_dcdInfo || !_dnaIndices) { _log('Load PDB/DCD first'); return }

    // Determine which frames to read: last N frames for N periodic windows
    const { windows } = computeSegments(design)
    const periodicWins = windows.filter(w => w.category === 'periodic')
    if (!periodicWins.length) { _log('No periodic windows found in design'); return }

    const N       = periodicWins.length
    const safeLast = _safeLastFrame()
    const startFr  = Math.max(0, safeLast - N + 1)
    _log(`Reading ${N} frames (${startFr}–${startFr + N - 1} of ${_dcdInfo.actualFrames}, safe cap ${safeLast})…`)

    if (applyBtn) { applyBtn.disabled = true; applyBtn.textContent = 'Loading…' }

    try {
      const frames = []
      for (let i = 0; i < N; i++) {
        const fi = Math.min(startFr + i, safeLast)
        frames.push(await _readDCDFrame(fi))
      }

      setCGVisible?.(false)
      periodicMdOverlay.setPreviewVisible(false)
      const n = periodicMdOverlay.applyToDesign(design, frames, _dnaIndices)

      if (n === 0) {
        setCGVisible?.(true)
        periodicMdOverlay.setPreviewVisible(true)
        _log('No windows rendered')
      } else {
        _log(`Applied: ${n} periodic windows`)
        _setApplyActive(true)
      }
    } catch (err) {
      setCGVisible?.(true)
      periodicMdOverlay.setPreviewVisible(true)
      _log(`Apply error: ${err.message}`)
    } finally {
      _updateApplyBtn()
    }
  })

  // ── Helpers ────────────────────────────────────────────────────────────────
  function _setStatus(lines) {
    if (!statusBlk) return
    statusBlk.innerHTML = lines.map(l => `<div>${l}</div>`).join('')
    statusBlk.style.display = 'block'
  }
}
