import * as THREE from 'three'
import { baseKey, xbKey } from './base_ref.js'
import { worldPosOf } from './base_pick.js'
import { extraBaseOwners } from '../design/strand_junctions.js'

// These are synthetic residues, never the duplex anchors at either end. Only
// strand/base picking consumes them; domain/end/cluster picks keep their own pool.
function extraNucleotide(strand, crossoverId, k) {
  return { helix_id: '__xb__', bp_index: k, crossover_id: crossoverId, k, extra_base_k: k,
    strand_id: strand.id, strand_type: strand.strand_type }
}

export function pickEntryKey(entry) {
  return entry?.baseKey ?? baseKey(entry?.nuc, entry?._copy)
}

export function extraBasePickEntries(entries, design) {
  if (!entries?.length) return []
  const owners = extraBaseOwners(design)
  return entries.flatMap(e => {
    const strand = owners.get(e.xoId)
    if (!strand) return []
    const position = new THREE.Vector3()
    return [{ ...e, baseKey: xbKey(e.xoId, e.simK),
      nuc: extraNucleotide(strand, e.xoId, e.simK),
      get pos() { return worldPosOf(e, position) },
    }]
  })
}

export function extraBaseAtomEntry(atom, design) {
  if (atom?.crossover_id == null || atom?.extra_base_k == null) return null
  const strand = extraBaseOwners(design).get(atom.crossover_id)
  return strand ? { baseKey: xbKey(atom.crossover_id, atom.extra_base_k),
    nuc: extraNucleotide(strand, atom.crossover_id, atom.extra_base_k) } : null
}
