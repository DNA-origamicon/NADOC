/**
 * Atom/bond subset filter extracted from main.js (parameterized: the atom cache
 * is now an argument rather than a closure read, so this is pure). Unit-tested in
 * atom_filter.test.js.
 *
 * @param {{atoms?:Array, bonds?:Array, element_meta?:any}} cache  all-atom data
 * @param {Set<string>} colSet  keep atoms whose "helix_id:bp_index" is in this set
 * @param {boolean} withBonds   also keep bonds whose both endpoints survive
 */
export function filterAtomData(cache, colSet, withBonds) {
  const atoms = (cache?.atoms ?? []).filter(a => colSet.has(`${a.helix_id}:${a.bp_index}`))
  let bonds = []
  if (withBonds && Array.isArray(cache?.bonds)) {
    const live = new Set(atoms.map(a => a.serial))
    bonds = cache.bonds.filter(([i, j]) => live.has(i) && live.has(j))
  }
  return { atoms, bonds, element_meta: cache?.element_meta }
}
