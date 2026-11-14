// Exact MD heavy atoms for zoom-volume insets.
//
// Display MD streams per-nucleotide frames when the main viewport is coarse-grained.
// An atomistic inset registers the residues it shows; the MD display controller asks
// its trajectory socket for those residues' real atoms and publishes them here, keyed
// exactly like the inset's design atoms. Physical display state only: nothing here is
// written to the design or to simulation inputs.

// CHARMM (NAMD PSF) names → the design atomistic model's PDB v3 names.
const NAME_ALIASES = { O1P: 'OP1', O2P: 'OP2', C5M: 'C7' }

/** Canonical heavy-atom name shared by design and MD atom records. */
export function canonicalAtomName(name) {
  return NAME_ALIASES[name] ?? name
}

export function createMdInsetAtomHub() {
  const owners = new Map()
  const requestListeners = new Set()
  let atoms = null
  let version = 0
  let requestSignature = ''

  function residueKeys() {
    return [...new Set([...owners.values()].flat())].sort()
  }
  return {
    /** Register (or with null/empty, release) one inset's residue base keys. */
    setResidues(owner, keys) {
      if (keys?.length) owners.set(owner, [...new Set(keys)])
      else owners.delete(owner)
      const next = residueKeys()
      const signature = next.join('\n')
      if (signature === requestSignature) return
      requestSignature = signature
      for (const listener of requestListeners) listener(next)
    },
    residueKeys,
    onRequest(listener) { requestListeners.add(listener); return () => requestListeners.delete(listener) },
    /** Replace the published atoms with one frame's `[baseKey, name, x, y, z]` rows. */
    publish(rows) {
      atoms = rows?.length ? new Map(rows.map(([key, name, x, y, z]) => [`${key}:${canonicalAtomName(name)}`, [x, y, z]])) : null
      version++
    },
    clear() { if (atoms) { atoms = null; version++ } },
    /** Map `${baseKey}:${canonicalName}` → [x, y, z] for the displayed frame, or null. */
    atoms: () => atoms,
    version: () => version,
  }
}

/** The single Display-MD controller and every zoom volume share this hub. */
export const mdInsetAtoms = createMdInsetAtomHub()
