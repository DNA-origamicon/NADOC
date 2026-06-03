/**
 * FRET quenching helper extracted from main.js. Pure given the donor/r0 lookup
 * maps (those stay in main.js, populated from the FRET pair table). Unit-tested
 * in fret_util.test.js.
 *
 * @param {Array<{nuc?:{modification?:string}, pos:{distanceTo:(o:any)=>number}}>} allEntries
 * @param {Map<string, string[]>} donorMap  donor mod → acceptor mod keys (gate: is-donor)
 * @param {Map<string, number>} r0Map       "donor:acceptor" → Förster radius r0 (nm)
 * @returns {Set} entries whose donor is within r0 of a compatible acceptor
 */
export function fretQuenchedDonors(allEntries, donorMap, r0Map) {
  const quenched = new Set()
  for (const entry of allEntries) {
    const mod          = entry.nuc?.modification
    const acceptorKeys = donorMap.get(mod)
    if (!acceptorKeys) continue
    for (const other of allEntries) {
      if (other === entry) continue
      const otherMod = other.nuc?.modification
      if (!otherMod) continue
      const r0 = r0Map.get(`${mod}:${otherMod}`)
      if (r0 === undefined) continue
      if (entry.pos.distanceTo(other.pos) <= r0) { quenched.add(entry); break }
    }
  }
  return quenched
}
