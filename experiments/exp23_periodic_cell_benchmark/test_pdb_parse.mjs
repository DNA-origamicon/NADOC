/**
 * test_pdb_parse.mjs — Verify PDB/DCD parsing logic matches frontend code.
 *
 * Run from any directory:
 *   node experiments/exp23_periodic_cell_benchmark/test_pdb_parse.mjs [PDB_PATH] [DCD_PATH]
 *
 * Defaults to the exp23 run directory if no arguments given.
 */

import { readFileSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const __dir = dirname(fileURLToPath(import.meta.url))
const RUN_DIR = resolve(__dir, 'results/periodic_cell_run')

const pdbPath = process.argv[2] ?? resolve(RUN_DIR, 'B_tube_periodic_1x.pdb')
const dcdPath = process.argv[3] ?? null  // optional

// ── Replicated parsing logic (must match periodic_md_overlay.js exactly) ──────

function parsePDB(text) {
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

function selectPreviewAtoms(atoms) {
  let selected = atoms.filter(a =>
    a.name === 'P' &&
    !a.segname.match(/^(SOL|ION)/i) &&
    (a.resname === 'DA' || a.resname === 'DT' ||
     a.resname === 'DG' || a.resname === 'DC' ||
     a.resname === 'ADE' || a.resname === 'THY' ||
     a.resname === 'GUA' || a.resname === 'CYT')
  )
  if (!selected.length) {
    selected = atoms.filter(a =>
      a.name === 'P' && !a.segname.match(/^(SOL|ION)/i)
    )
  }
  return selected
}

function parseDCDHeader(buf, fileSize) {
  const dv  = new DataView(buf)
  let   pos = 0

  const rec1Len       = dv.getInt32(pos, true); pos += 4
  pos += 4  // label
  const nframesHeader = dv.getInt32(pos, true); pos += 4
  const npriv         = dv.getInt32(pos, true); pos += 4
  const nsavc         = dv.getInt32(pos, true); pos += 4
  const nstep         = dv.getInt32(pos, true); pos += 4
  pos += 16
  const nfixed        = dv.getInt32(pos, true);  pos += 4
  const delta         = dv.getFloat32(pos, true); pos += 4  // NAMD writes float32, not float64
  const qcrys         = dv.getInt32(pos, true);  pos += 4

  pos = 4 + rec1Len + 4

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

  return { natom, nframesHeader, actualFrames, nsavc, delta, dtNs, qcrys,
           headerEnd, frameBytes, crystalBytes, coordRecord }
}

function parseDCDFrameSlice(sliceBuf, info) {
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

// ── Tests ─────────────────────────────────────────────────────────────────────

let pass = 0, fail = 0
function assert(label, cond, detail = '') {
  if (cond) {
    console.log(`  ✓  ${label}`)
    pass++
  } else {
    console.error(`  ✗  ${label}${detail ? '  ← ' + detail : ''}`)
    fail++
  }
}

// PDB tests
console.log(`\nPDB: ${pdbPath}`)
const pdbText = readFileSync(pdbPath, 'utf8')
const atoms   = parsePDB(pdbText)
const selected = selectPreviewAtoms(atoms)

const segnames    = [...new Set(atoms.map(a => a.segname))]
const pAtoms      = atoms.filter(a => a.name === 'P')
const dnaResnames = [...new Set(pAtoms.map(a => a.resname))]

console.log(`  Total atoms parsed  : ${atoms.length.toLocaleString()}`)
console.log(`  P atoms (all)       : ${pAtoms.length.toLocaleString()}`)
console.log(`  P atoms selected    : ${selected.length.toLocaleString()}`)
console.log(`  Unique segnames     : ${JSON.stringify(segnames)}`)
console.log(`  P atom resnames     : ${JSON.stringify(dnaResnames)}`)

let xMin=Infinity,xMax=-Infinity,yMin=Infinity,yMax=-Infinity,zMin=Infinity,zMax=-Infinity
for (const a of atoms) {
  if (a.x < xMin) xMin=a.x; if (a.x > xMax) xMax=a.x
  if (a.y < yMin) yMin=a.y; if (a.y > yMax) yMax=a.y
  if (a.z < zMin) zMin=a.z; if (a.z > zMax) zMax=a.z
}
const cellX = ((xMax - xMin) * 0.1).toFixed(2)
const cellY = ((yMax - yMin) * 0.1).toFixed(2)
const cellZ = ((zMax - zMin) * 0.1).toFixed(2)
console.log(`  Cell dims (nm)      : ${cellX} × ${cellY} × ${cellZ}`)

assert('atoms parsed > 0',      atoms.length > 0)
assert('P atoms found > 0',     pAtoms.length > 0)
assert('preview atoms > 0',     selected.length > 0,
       `got ${selected.length} — check segname/resname filter`)
assert('preview count matches P count', selected.length === pAtoms.length,
       `preview=${selected.length} vs all-P=${pAtoms.length}`)
assert('no NaN coordinates',
  atoms.every(a => isFinite(a.x) && isFinite(a.y) && isFinite(a.z)))

// DCD tests (optional) — uses header-only read + on-demand frame slicing (same as browser)
if (dcdPath) {
  console.log(`\nDCD: ${dcdPath}`)
  try {
    const { openSync, readSync, closeSync, statSync } = await import('fs')
    const stat = statSync(dcdPath)
    const fd   = openSync(dcdPath, 'r')

    // Read only the first 4 KB for header parsing (mirrors browser File.slice(0,4096))
    const headerBytes = new Uint8Array(4096)
    readSync(fd, headerBytes, 0, 4096, 0)
    const headerBuf = headerBytes.buffer

    const info = parseDCDHeader(headerBuf, stat.size)
    console.log(`  file size       : ${(stat.size / 1e9).toFixed(3)} GB`)
    console.log(`  natom           : ${info.natom.toLocaleString()}`)
    console.log(`  frames (header) : ${info.nframesHeader}`)
    console.log(`  frames (actual) : ${info.actualFrames}`)
    console.log(`  dt per frame    : ${info.dtNs.toFixed(6)} ns`)
    console.log(`  total time      : ${(info.dtNs * info.actualFrames).toFixed(3)} ns`)
    console.log(`  qcrys           : ${info.qcrys}`)
    console.log(`  frameBytes      : ${(info.frameBytes / 1e6).toFixed(2)} MB/frame`)

    assert('DCD natom > 0',        info.natom > 0)
    assert('DCD actualFrames > 0', info.actualFrames > 0)
    assert('DCD dtNs > 0',         info.dtNs > 0)
    assert('DCD natom matches PDB atom count', info.natom === atoms.length,
           `DCD=${info.natom} vs PDB=${atoms.length}`)

    // Test on-demand frame read of last frame (mirrors browser _readDCDFrame)
    const lastFi = info.actualFrames - 1
    const start  = info.headerEnd + lastFi * info.frameBytes
    const frameBuf = new Uint8Array(info.frameBytes)
    readSync(fd, frameBuf, 0, info.frameBytes, start)
    closeSync(fd)

    const { x, y, z } = parseDCDFrameSlice(frameBuf.buffer, info)
    const sampleX = x[0], sampleY = y[0], sampleZ = z[0]
    console.log(`  last frame atom0: (${sampleX.toFixed(2)}, ${sampleY.toFixed(2)}, ${sampleZ.toFixed(2)}) Å`)
    assert('last frame coords finite', isFinite(sampleX) && isFinite(sampleY) && isFinite(sampleZ))
  } catch (e) {
    console.error(`  ERROR reading DCD: ${e.message}`)
    fail++
  }
} else {
  console.log('\nDCD: skipped (pass a DCD path as second argument to test)')
}

// Summary
console.log(`\n${'─'.repeat(50)}`)
console.log(`Result: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
