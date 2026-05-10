/**
 * periodic_md_overlay.js
 *
 * Scene-side renderer and file parsers for the Periodic MD panel.
 *
 * Parsers:
 *   parsePDB(text)                    → atom array  [{serial,name,resname,segname,x,y,z}…]
 *   parsePSF(text)                    → {natom, atomNames, segnames}
 *   parseDCDHeader(buf, fileSize)     → DCDInfo object
 *   parseDCDFrame(buf, i, info)       → {x,y,z} Float32Arrays (in Å)
 *   parseDCDFrameSlice(sliceBuf,info) → {x,y,z} Float32Arrays (in Å)
 *
 * Overlay:
 *   initPeriodicMdOverlay(scene) → controller
 *     .loadPDB(atoms)            — build ball-and-stick preview from parsed PDB atoms
 *     .getAtomIndices()          — PDB indices of the heavy atoms in the display model
 *     .setFrame(x,y,z,indices)   — update positions from a DCD frame
 *     .setPreviewAlignment(...)  — set GROMACS→design offset before loadPDB
 *     .applyToDesign(...)        — tile across green windows
 *     .clear()
 */

import * as THREE from 'three'
import { computeSegments } from './md_segmentation_overlay.js'

const NM_PER_ANG = 0.1    // Å → nm
const BALL_R     = 0.07   // nm, ball-and-stick sphere radius

// ── CPK colours by element ────────────────────────────────────────────────────
const ELEM_COLORS = {
  P: 0xFF8C00,   // orange
  C: 0x505050,   // dark grey
  N: 0x3050F8,   // blue
  O: 0xFF0D0D,   // red
  S: 0xFFFF44,   // yellow
}

function _elemColor(atomName) {
  const first = atomName[0]
  if (first in ELEM_COLORS) return ELEM_COLORS[first]
  return 0xaaaaaa
}

// ── Shared geometry/matrix temporaries ───────────────────────────────────────
const _m4   = new THREE.Matrix4()
const _col  = new THREE.Color()

// ── PDB parser ────────────────────────────────────────────────────────────────
export function parsePDB(text) {
  const atoms = []
  for (const line of text.split('\n')) {
    const rec = line.slice(0, 6)
    if (rec !== 'ATOM  ' && rec !== 'HETATM') continue
    atoms.push({
      serial:  parseInt(line.slice(6, 11))  || 0,
      name:    line.slice(12, 16).trim(),
      resname: line.slice(17, 21).trim(),
      chain:   line.slice(21, 22).trim(),
      resseq:  parseInt(line.slice(22, 26)) || 0,
      x:       parseFloat(line.slice(30, 38)),
      y:       parseFloat(line.slice(38, 46)),
      z:       parseFloat(line.slice(46, 54)),
      segname: line.slice(72, 76).trim(),
    })
  }
  return atoms
}

// ── PSF parser ────────────────────────────────────────────────────────────────
export function parsePSF(text) {
  const lines   = text.split('\n')
  let natom     = 0
  let inAtoms   = false
  const atomNames = [], segnames = [], resnames = []

  for (let i = 0; i < lines.length; i++) {
    const ln = lines[i].trim()
    if (!inAtoms) {
      const m = ln.match(/^\s*(\d+)\s+!NATOM/)
      if (m) { natom = parseInt(m[1]); inAtoms = true; continue }
    } else {
      if (!ln || ln.startsWith('!')) break
      const parts = ln.split(/\s+/)
      if (parts.length >= 5) {
        segnames.push(parts[1])
        resnames.push(parts[3])
        atomNames.push(parts[4])
      }
    }
  }
  return { natom, atomNames, segnames, resnames }
}

// ── DCD parser ────────────────────────────────────────────────────────────────
export function parseDCDHeader(buf, fileSize) {
  const dv  = new DataView(buf)
  let   pos = 0

  const rec1Len = dv.getInt32(pos, true); pos += 4
  const label   = String.fromCharCode(
    dv.getUint8(pos), dv.getUint8(pos+1), dv.getUint8(pos+2), dv.getUint8(pos+3),
  ); pos += 4

  const nframesHeader = dv.getInt32(pos, true); pos += 4
  const npriv         = dv.getInt32(pos, true); pos += 4
  const nsavc         = dv.getInt32(pos, true); pos += 4
  const nstep         = dv.getInt32(pos, true); pos += 4
  pos += 16
  const nfixed        = dv.getInt32(pos, true);  pos += 4
  const delta         = dv.getFloat32(pos, true); pos += 4  // NAMD writes float32, not float64
  const qcrys         = dv.getInt32(pos, true);  pos += 4

  pos = 4 + rec1Len + 4   // skip to end of record 1

  const rec2Len = dv.getInt32(pos, true); pos += 4
  const ntitle  = dv.getInt32(pos, true); pos += 4
  pos += ntitle * 80
  pos += 4

  pos += 4
  const natom = dv.getInt32(pos, true); pos += 4
  pos += 4

  const headerEnd    = pos
  const crystalBytes = qcrys ? (4 + 48 + 4) : 0
  const coordRecord  = 4 + natom * 4 + 4
  const frameBytes   = crystalBytes + 3 * coordRecord
  const _fileSize    = fileSize ?? buf.byteLength
  const actualFrames = Math.max(0, Math.floor((_fileSize - headerEnd) / frameBytes))
  const dtNs         = delta * 48.88e-6 * nsavc

  return {
    label, natom, nframesHeader, actualFrames,
    npriv, nsavc, nstep, nfixed,
    delta, dtNs, qcrys, ntitle,
    headerEnd, frameBytes, crystalBytes, coordRecord,
  }
}

export function parseDCDFrame(buf, frameIdx, info) {
  const { headerEnd, frameBytes, crystalBytes, coordRecord, natom } = info
  let pos = headerEnd + frameIdx * frameBytes
  if (crystalBytes) pos += crystalBytes

  const makeF32 = (offset) => {
    const arr = new Float32Array(natom)
    const dv  = new DataView(buf, offset + 4, natom * 4)
    for (let i = 0; i < natom; i++) arr[i] = dv.getFloat32(i * 4, true)
    return arr
  }

  const x = makeF32(pos);  pos += coordRecord
  const y = makeF32(pos);  pos += coordRecord
  const z = makeF32(pos)
  return { x, y, z }
}

export function parseDCDFrameSlice(sliceBuf, info) {
  const { crystalBytes, coordRecord, natom } = info
  let pos = 0
  if (crystalBytes) pos += crystalBytes

  const makeF32 = (offset) => {
    const arr = new Float32Array(natom)
    const dv  = new DataView(sliceBuf, offset + 4, natom * 4)
    for (let i = 0; i < natom; i++) arr[i] = dv.getFloat32(i * 4, true)
    return arr
  }

  const x = makeF32(pos); pos += coordRecord
  const y = makeF32(pos); pos += coordRecord
  const z = makeF32(pos)
  return { x, y, z }
}

// ── Private design-space helpers ──────────────────────────────────────────────

function _refHelixOf(design) {
  let best = null, bestLen = -Infinity
  for (const h of design.helices) {
    const dx = h.axis_end.x - h.axis_start.x
    const dy = h.axis_end.y - h.axis_start.y
    const dz = h.axis_end.z - h.axis_start.z
    const len = Math.sqrt(dx * dx + dy * dy + dz * dz)
    if (len > bestLen) { bestLen = len; best = h }
  }
  return best
}

function _bpToVec3(bp, ref) {
  const t = (bp - ref.bp_start) / ref.length_bp
  return new THREE.Vector3(
    ref.axis_start.x + t * (ref.axis_end.x - ref.axis_start.x),
    ref.axis_start.y + t * (ref.axis_end.y - ref.axis_start.y),
    ref.axis_start.z + t * (ref.axis_end.z - ref.axis_start.z),
  )
}

// ── Bond topology from PDB coords ─────────────────────────────────────────────
// Returns [[li, lj], ...] where li/lj are indices into the heavy[] array.
// Uses distance < 1.9 Å within each residue + explicit O3'→P backbone links.
function _computeBonds(heavy) {
  // Group atoms by chain+resseq, keeping local indices
  const residueMap = new Map()
  for (let i = 0; i < heavy.length; i++) {
    const a   = heavy[i]
    const key = `${a.chain}:${a.resseq}`
    if (!residueMap.has(key)) residueMap.set(key, [])
    residueMap.get(key).push({ a, li: i })
  }

  const pairs = []

  // Intra-residue covalent bonds (1.9 Å threshold — all heavy-atom covalent bonds < 1.85 Å)
  for (const [, entries] of residueMap) {
    for (let i = 0; i < entries.length; i++) {
      for (let j = i + 1; j < entries.length; j++) {
        const { a, li } = entries[i]
        const { a: b, li: lj } = entries[j]
        const dx = a.x - b.x, dy = a.y - b.y, dz = a.z - b.z
        if (dx*dx + dy*dy + dz*dz < 3.61) pairs.push([li, lj])   // 1.9² Å²
      }
    }
  }

  // Backbone O3'→P bonds between consecutive residues on the same chain.
  // Sorted by resseq; if adjacent residues are consecutive, add the backbone bond.
  const chainMap = new Map()
  for (const [key, entries] of residueMap) {
    const [chain, resseqStr] = key.split(':')
    const resseq = parseInt(resseqStr)
    if (!chainMap.has(chain)) chainMap.set(chain, [])
    chainMap.get(chain).push({ resseq, entries })
  }
  for (const [, resList] of chainMap) {
    resList.sort((a, b) => a.resseq - b.resseq)
    for (let ri = 0; ri < resList.length - 1; ri++) {
      if (resList[ri + 1].resseq !== resList[ri].resseq + 1) continue
      const o3Entry = resList[ri].entries.find(e => e.a.name === "O3'")
      const pEntry  = resList[ri + 1].entries.find(e => e.a.name === 'P')
      if (o3Entry && pEntry) pairs.push([o3Entry.li, pEntry.li])
    }
  }

  return pairs
}

// Build a LineSegments object for bonds.
// posArr is updated in-place each setFrame call; colArr is static (CPK by element).
function _makeBondLines(heavy, bondPairs, offset) {
  const nBonds = bondPairs.length
  if (!nBonds) return null

  const posArr = new Float32Array(nBonds * 6)
  const colArr = new Float32Array(nBonds * 6)

  for (let k = 0; k < nBonds; k++) {
    const [li, lj] = bondPairs[k]
    const ai = heavy[li], aj = heavy[lj]
    posArr[k*6+0] = ai.x*NM_PER_ANG + offset.x
    posArr[k*6+1] = ai.y*NM_PER_ANG + offset.y
    posArr[k*6+2] = ai.z*NM_PER_ANG + offset.z
    posArr[k*6+3] = aj.x*NM_PER_ANG + offset.x
    posArr[k*6+4] = aj.y*NM_PER_ANG + offset.y
    posArr[k*6+5] = aj.z*NM_PER_ANG + offset.z
    _col.setHex(_elemColor(ai.name))
    colArr[k*6+0] = _col.r; colArr[k*6+1] = _col.g; colArr[k*6+2] = _col.b
    _col.setHex(_elemColor(aj.name))
    colArr[k*6+3] = _col.r; colArr[k*6+4] = _col.g; colArr[k*6+5] = _col.b
  }

  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.BufferAttribute(posArr, 3))
  geo.setAttribute('color',    new THREE.BufferAttribute(colArr, 3))
  const lines = new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ vertexColors: true }))
  lines.frustumCulled = false
  return lines
}

// ── Scene overlay ─────────────────────────────────────────────────────────────

export function initPeriodicMdOverlay(scene) {
  // ── Preview group (live, updated each DCD frame) ──────────────────────────
  const _group    = new THREE.Group()
  _group.name     = 'periodicMdOverlay'
  scene.add(_group)

  let _mesh       = null   // InstancedMesh — all heavy DNA atoms
  let _bondLines  = null   // LineSegments — covalent bonds
  let _heavyAtoms = null   // filtered heavy atom array (length _nHeavy)
  let _pdbIndices = null   // PDB/DCD index of each heavy atom (length _nHeavy)
  let _bondPairs  = null   // [[li, lj], ...] bond topology (static)
  let _nHeavy     = 0
  let _alignOffset = new THREE.Vector3()

  // ── Applied group (tiled across green windows) ────────────────────────────
  const _applied  = new THREE.Group()
  _applied.name   = 'periodicMdApplied'
  scene.add(_applied)

  function _dispose() {
    if (_mesh) {
      _mesh.geometry.dispose()
      _mesh.material.dispose()
      _group.remove(_mesh)
      _mesh = null
    }
    if (_bondLines) {
      _bondLines.geometry.dispose()
      _bondLines.material.dispose()
      _group.remove(_bondLines)
      _bondLines = null
    }
    _heavyAtoms = null
    _pdbIndices = null
    _bondPairs  = null
    _nHeavy     = 0
    _alignOffset.set(0, 0, 0)
  }

  function _clearApplied() {
    while (_applied.children.length) {
      const c = _applied.children[0]
      c.geometry?.dispose()
      c.material?.dispose()
      _applied.remove(c)
    }
  }

  // ── loadPDB ───────────────────────────────────────────────────────────────
  function loadPDB(atoms) {
    _dispose()
    if (!atoms?.length) return

    // Collect heavy DNA atoms (no H, not water/ion)
    const heavy = []
    const pdbIdx = []
    for (let i = 0; i < atoms.length; i++) {
      const a = atoms[i]
      if (a.name.startsWith('H'))           continue
      if (a.segname.match(/^(SOL|ION)/i))   continue
      heavy.push(a)
      pdbIdx.push(i)
    }
    if (!heavy.length) return

    _heavyAtoms = heavy
    _pdbIndices = pdbIdx
    _nHeavy     = heavy.length
    _bondPairs  = _computeBonds(heavy)

    // InstancedMesh — one sphere per heavy atom, CPK per-instance colour
    const sphereGeo = new THREE.SphereGeometry(BALL_R, 7, 5)
    const mat       = new THREE.MeshPhongMaterial({ color: 0xffffff, shininess: 60 })
    _mesh           = new THREE.InstancedMesh(sphereGeo, mat, _nHeavy)
    _mesh.instanceColor  = new THREE.InstancedBufferAttribute(new Float32Array(_nHeavy * 3), 3)
    _mesh.frustumCulled  = false

    for (let i = 0; i < _nHeavy; i++) {
      const a = heavy[i]
      _m4.makeTranslation(
        a.x * NM_PER_ANG + _alignOffset.x,
        a.y * NM_PER_ANG + _alignOffset.y,
        a.z * NM_PER_ANG + _alignOffset.z,
      )
      _mesh.setMatrixAt(i, _m4)
      _col.setHex(_elemColor(a.name))
      _mesh.setColorAt(i, _col)
    }
    _mesh.instanceMatrix.needsUpdate = true
    _mesh.instanceColor.needsUpdate  = true
    _group.add(_mesh)

    // Bond lines (static topology, positions updated each frame)
    _bondLines = _makeBondLines(heavy, _bondPairs, _alignOffset)
    if (_bondLines) _group.add(_bondLines)
  }

  // ── setFrame ──────────────────────────────────────────────────────────────
  // dcdIndices[li] = DCD atom index for the li-th heavy atom.
  function setFrame(x, y, z, dcdIndices) {
    if (!_mesh || !dcdIndices?.length) return

    const n = Math.min(dcdIndices.length, _nHeavy)
    for (let li = 0; li < n; li++) {
      const ai = dcdIndices[li]
      _m4.makeTranslation(
        x[ai] * NM_PER_ANG + _alignOffset.x,
        y[ai] * NM_PER_ANG + _alignOffset.y,
        z[ai] * NM_PER_ANG + _alignOffset.z,
      )
      _mesh.setMatrixAt(li, _m4)
    }
    _mesh.instanceMatrix.needsUpdate = true

    if (_bondLines && _bondPairs?.length) {
      const posArr = _bondLines.geometry.attributes.position.array
      for (let k = 0; k < _bondPairs.length; k++) {
        const [li, lj] = _bondPairs[k]
        const ai = dcdIndices[li], aj = dcdIndices[lj]
        posArr[k*6+0] = x[ai]*NM_PER_ANG + _alignOffset.x
        posArr[k*6+1] = y[ai]*NM_PER_ANG + _alignOffset.y
        posArr[k*6+2] = z[ai]*NM_PER_ANG + _alignOffset.z
        posArr[k*6+3] = x[aj]*NM_PER_ANG + _alignOffset.x
        posArr[k*6+4] = y[aj]*NM_PER_ANG + _alignOffset.y
        posArr[k*6+5] = z[aj]*NM_PER_ANG + _alignOffset.z
      }
      _bondLines.geometry.attributes.position.needsUpdate = true
    }
  }

  // ── setPreviewAlignment ───────────────────────────────────────────────────
  // Must be called before loadPDB so the mesh is built at the correct position.
  // pAtoms: DNA P atoms (from DCD or static PDB) as {x,y,z} in Å.
  function setPreviewAlignment(design, pAtoms) {
    _alignOffset.set(0, 0, 0)
    if (!pAtoms?.length || !design?.helices?.length) return

    let cx = 0, cy = 0, cz = 0
    for (const a of pAtoms) { cx += a.x; cy += a.y; cz += a.z }
    const n = pAtoms.length
    cx = cx / n * NM_PER_ANG
    cy = cy / n * NM_PER_ANG
    cz = cz / n * NM_PER_ANG

    const { windows } = computeSegments(design)
    const pw  = windows.find(w => w.category === 'periodic')
    const ref = _refHelixOf(design)
    if (!ref) return

    const target = pw
      ? _bpToVec3((pw.bp + pw.bpEnd) / 2, ref)
      : _bpToVec3(ref.bp_start + ref.length_bp / 2, ref)

    _alignOffset.set(target.x - cx, target.y - cy, target.z - cz)
  }

  // ── applyToDesign ─────────────────────────────────────────────────────────
  // frames: pre-read DCD frames [{x,y,z}] — one per periodic window.
  // pIndices: PDB/DCD indices of DNA P atoms (used for per-window centroid alignment).
  // Heavy atom rendering uses the internal _pdbIndices built by loadPDB.
  function applyToDesign(design, frames, pIndices) {
    _clearApplied()
    if (!design?.helices?.length || !frames?.length || !pIndices?.length || !_pdbIndices?.length) return 0

    const { windows } = computeSegments(design)
    const periodicWins = windows.filter(w => w.category === 'periodic')
    if (!periodicWins.length) return 0

    const ref = _refHelixOf(design)
    if (!ref) return 0

    const nWins = Math.min(periodicWins.length, frames.length)
    const nP    = pIndices.length
    const nH    = _nHeavy

    for (let wi = 0; wi < nWins; wi++) {
      const w = periodicWins[wi]
      const { x, y, z } = frames[wi]

      // P-atom centroid in nm (GROMACS box coords)
      let cx = 0, cy = 0, cz = 0
      for (const ai of pIndices) { cx += x[ai]; cy += y[ai]; cz += z[ai] }
      cx = (cx / nP) * NM_PER_ANG
      cy = (cy / nP) * NM_PER_ANG
      cz = (cz / nP) * NM_PER_ANG

      const wc = _bpToVec3((w.bp + w.bpEnd) / 2, ref)
      const tx = wc.x - cx, ty = wc.y - cy, tz = wc.z - cz

      // ── Ball mesh ────────────────────────────────────────────────────────
      const sphereGeo = new THREE.SphereGeometry(BALL_R, 7, 5)
      const mat       = new THREE.MeshPhongMaterial({ color: 0xffffff, shininess: 60 })
      const mesh      = new THREE.InstancedMesh(sphereGeo, mat, nH)
      mesh.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(nH * 3), 3)
      mesh.frustumCulled = false

      for (let li = 0; li < nH; li++) {
        const ai = _pdbIndices[li]
        _m4.makeTranslation(x[ai]*NM_PER_ANG + tx, y[ai]*NM_PER_ANG + ty, z[ai]*NM_PER_ANG + tz)
        mesh.setMatrixAt(li, _m4)
        _col.setHex(_elemColor(_heavyAtoms[li].name))
        mesh.setColorAt(li, _col)
      }
      mesh.instanceMatrix.needsUpdate = true
      mesh.instanceColor.needsUpdate  = true
      _applied.add(mesh)

      // ── Bond lines ───────────────────────────────────────────────────────
      const nBonds = _bondPairs.length
      if (nBonds) {
        const posArr = new Float32Array(nBonds * 6)
        const colArr = new Float32Array(nBonds * 6)
        for (let k = 0; k < nBonds; k++) {
          const [li, lj] = _bondPairs[k]
          const ai = _pdbIndices[li], aj = _pdbIndices[lj]
          posArr[k*6+0] = x[ai]*NM_PER_ANG + tx; posArr[k*6+1] = y[ai]*NM_PER_ANG + ty; posArr[k*6+2] = z[ai]*NM_PER_ANG + tz
          posArr[k*6+3] = x[aj]*NM_PER_ANG + tx; posArr[k*6+4] = y[aj]*NM_PER_ANG + ty; posArr[k*6+5] = z[aj]*NM_PER_ANG + tz
          _col.setHex(_elemColor(_heavyAtoms[li].name))
          colArr[k*6+0] = _col.r; colArr[k*6+1] = _col.g; colArr[k*6+2] = _col.b
          _col.setHex(_elemColor(_heavyAtoms[lj].name))
          colArr[k*6+3] = _col.r; colArr[k*6+4] = _col.g; colArr[k*6+5] = _col.b
        }
        const geo   = new THREE.BufferGeometry()
        geo.setAttribute('position', new THREE.BufferAttribute(posArr, 3))
        geo.setAttribute('color',    new THREE.BufferAttribute(colArr, 3))
        const lines = new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ vertexColors: true }))
        lines.frustumCulled = false
        _applied.add(lines)
      }
    }

    return nWins
  }

  // ── Public API ────────────────────────────────────────────────────────────

  return {
    loadPDB,
    setFrame,
    setPreviewAlignment,
    applyToDesign,
    /** PDB/DCD indices of the heavy atoms currently in the display model. */
    getAtomIndices()        { return _pdbIndices },
    clearApplied()          { _clearApplied() },
    isApplied()             { return _applied.children.length > 0 },
    setPreviewVisible(v)    { _group.visible = v },
    clear()                 { _dispose(); _clearApplied() },
    isVisible()             { return _group.visible && _nHeavy > 0 },
    atomCount()             { return _nHeavy },
  }
}
