import { Vector3 } from 'three'
import { atomBaseKey, baseKey, xbKey } from '../base_ref.js'

// Display-only heavy-atom criteria, in nm. Standard neutral A/C/G/T/U bases.
// No topology or pairing is inferred; absent/modified ring atoms are skipped.
const RING = ['N1', 'C2', 'N3', 'C4', 'C5', 'C6']
const ACCEPTOR_NEIGHBORS = { N1: ['C2', 'C6'], N3: ['C2', 'C4'], N7: ['C5', 'C8'], O2: ['C2'], O4: ['C4'], O6: ['C6'] }
const CHEMISTRY = {
  A: { donors: { N6: ['C6'] }, acceptors: ['N1', 'N3', 'N7'] },
  G: { donors: { N1: ['C2', 'C6'], N2: ['C2'] }, acceptors: ['O6', 'N3', 'N7'] },
  C: { donors: { N4: ['C4'] }, acceptors: ['O2', 'N3'] },
  T: { donors: { N3: ['C2', 'C4'] }, acceptors: ['O2', 'O4'] },
}

export function singleInteractionBase(selection, mode) {
  if (!['ballstick', 'stick'].includes(mode) || selection?.bases?.length !== 1) return null
  if (['strandIds', 'helixIds', 'domains', 'extensionIds', 'bonds'].some(k => selection[k]?.length)) return null
  const b = selection.bases[0]
  return b.helix_id === '__xb__' ? xbKey(b.crossover_id, b.k) : baseKey(b, b.copy_k ?? b.copy ?? 0)
}

/** Read live rendered positions (not the original atom payload). */
export function interactionResidues(table, position) {
  const groups = new Map()
  for (let row = 0; row < table.count; row++) {
    const a = table.get(row), key = atomBaseKey(a)
    if (!key || !/^[CNO][1-9]$/.test(a.name ?? '')) continue
    const p = position(row)
    if (!p || !p.every(Number.isFinite)) continue
    let g = groups.get(key)
    if (!g) groups.set(key, g = { key, atoms: new Map(), modified: false })
    g.modified ||= !!a.is_modified
    g.atoms.set(a.name, new Vector3(...p))
  }
  const residues = []
  for (const g of groups.values()) {
    const a = g.atoms
    if (g.modified || !RING.every(n => a.has(n))) continue
    const type = a.has('N9') ? (a.has('N6') ? 'A' : a.has('O6') && a.has('N2') ? 'G' : null)
      : a.has('N4') && a.has('O2') ? 'C' : a.has('O2') && a.has('O4') ? 'T' : null
    if (!type) continue
    const names = a.has('N9') ? [...RING, 'N7', 'C8', 'N9'] : RING
    if (!names.every(n => a.has(n))) continue
    const center = names.reduce((sum, n) => sum.add(a.get(n)), new Vector3()).divideScalar(names.length)
    const normal = a.get('C2').clone().sub(a.get('N1')).cross(a.get('C6').clone().sub(a.get('N1'))).normalize()
    if (normal.lengthSq() < .9 || names.some(n => Math.abs(a.get(n).clone().sub(center).dot(normal)) > .04)) continue
    residues.push({ ...g, center, normal, chemistry: CHEMISTRY[type] })
  }
  return residues
}

function hydrogenBonds(donor, acceptor, out) {
  for (const [name, neighbors] of Object.entries(donor.chemistry.donors)) {
    const d = donor.atoms.get(name)
    if (!d || !neighbors.every(n => donor.atoms.has(n))) continue
    for (const name of acceptor.chemistry.acceptors) {
      const a = acceptor.atoms.get(name)
      if (!a) continue
      const direction = a.clone().sub(d), distance = direction.length()
      if (distance < .24 || distance > .35) continue
      direction.divideScalar(distance)
      // sp2 donor/acceptor contacts must lie near both base planes. Heavy
      // neighbor–donor–acceptor angles >= 90° exclude back-facing donors.
      if (Math.abs(direction.dot(donor.normal)) > .5 || Math.abs(direction.dot(acceptor.normal)) > .5) continue
      if (neighbors.some(n => donor.atoms.get(n).clone().sub(d).normalize().dot(direction) > 1e-6)) continue
      const acceptorNeighbors = ACCEPTOR_NEIGHBORS[name]
      if (acceptorNeighbors.some(n => !acceptor.atoms.has(n) || acceptor.atoms.get(n).clone().sub(a).normalize().dot(direction) < -1e-6)) continue
      out.push({ type: 'hydrogen', keys: [donor.key, acceptor.key], start: d, end: a })
    }
  }
}

/** Spatial hashing bounds the global search; selection limits emitted contacts. */
export function findBaseInteractions(residues, selectedKey = null) {
  const cells = new Map(), cell = p => [p.x, p.y, p.z].map(v => Math.floor(v / 1.2))
  residues.forEach((r, i) => {
    const key = cell(r.center).join(','), bucket = cells.get(key) ?? []
    bucket.push(i); cells.set(key, bucket)
  })
  const out = []
  residues.forEach((a, i) => {
    if (selectedKey && a.key !== selectedKey) return
    const [x, y, z] = cell(a.center)
    for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) for (let dz = -1; dz <= 1; dz++) {
      for (const j of cells.get([x + dx, y + dy, z + dz].join(',')) ?? []) {
        if (selectedKey ? j === i : j <= i) continue
        const b = residues[j], delta = b.center.clone().sub(a.center), distance = delta.length()
        if (distance > 1.2) continue
        hydrogenBonds(a, b, out); hydrogenBonds(b, a, out)
        if (distance > .55 || Math.abs(a.normal.dot(b.normal)) < Math.cos(Math.PI / 6)) continue
        const heightA = Math.abs(delta.dot(a.normal)), heightB = Math.abs(delta.dot(b.normal))
        const offset = Math.max(Math.sqrt(Math.max(0, distance ** 2 - heightA ** 2)), Math.sqrt(Math.max(0, distance ** 2 - heightB ** 2)))
        if (Math.min(heightA, heightB) < .25 || Math.max(heightA, heightB) > .45 || offset > .25) continue
        out.push({ type: 'stacking', keys: [a.key, b.key], start: a.center, end: b.center })
      }
    }
  })
  return out
}
