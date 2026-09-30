/** Browser-owned wheel catalogs and serialized desktop-authoritative edits. */
import { endRole, isValidPair, ligationArgs } from './force_ligation.js'

export function createVRLigation({ getState, api, clearSelection = () => {}, onOutcome = () => {} }) {
  let design, geometry, snapshot, version = 0, dirty = true, busy = false
  let published = '', publishing = false, status = 'ready'

  function catalog() {
    const state = getState()
    if (!dirty && design === state.currentDesign && geometry === state.currentGeometry &&
        snapshot.assembly === !!state.assemblyActive) return snapshot
    design = state.currentDesign; geometry = state.currentGeometry; dirty = false
    const strands = new Map((design?.strands ?? []).map((s, i) => [s.id, { strand: s, index: i }]))
    const ends = [], nucleotides = []
    if (!state.assemblyActive) for (const n of geometry ?? []) {
      const role = endRole(n), source = strands.get(n.strand_id)
      if (!role || !source || (n.copy_k ?? 0) !== 0 || n.helix_id?.startsWith('__')) continue
      const terminal = role === '3p' ? source.strand.domains.at(-1) : source.strand.domains[0]
      if (!terminal || terminal.helix_id !== n.helix_id || terminal.direction !== n.direction ||
          (role === '3p' ? terminal.end_bp : terminal.start_bp) !== n.bp_index) continue
      if (!Array.isArray(n.backbone_position) || !n.backbone_position.every(Number.isFinite)) continue
      const identity = encodeURIComponent(['nuc', n.strand_id, n.domain_index ?? 0, n.helix_id, n.bp_index, n.direction, 0, 'backbone'].join(':'))
      ends.push({ role: role === '3p' ? 3 : 5, strand: source.index, identity,
        position: [...n.backbone_position], tangent: n.axis_tangent ?? [0,0,1] })
      nucleotides.push(n)
    }
    // Match the renderer's 5′→3′ domain ordering. Never promote a loop copy
    // or synthetic residue to the core-coordinate nick API.
    const byStrand = new Map(), coordinateOwners = new Map()
    const key = n => JSON.stringify([n.helix_id, n.bp_index, n.direction])
    for (const n of geometry ?? []) {
      if (!byStrand.has(n.strand_id)) byStrand.set(n.strand_id, [])
      byStrand.get(n.strand_id).push(n)
      if ((n.copy_k ?? 0) === 0) coordinateOwners.set(key(n), (coordinateOwners.get(key(n)) ?? 0) + 1)
    }
    const bonds = [], nickArgs = []
    if (!state.assemblyActive) for (const [id, ns] of byStrand) {
      if (!strands.has(id)) continue
      ns.sort((a,b) => (a.domain_index ?? 0) - (b.domain_index ?? 0) ||
        (a.direction === 'FORWARD' ? 1 : -1) * (a.bp_index - b.bp_index || (a.copy_k ?? 0) - (b.copy_k ?? 0)))
      for (let i=0; i+1<ns.length; ++i) {
        const a=ns[i], b=ns[i+1]
        if (a.is_three_prime || b.is_five_prime || a.helix_id?.startsWith('__') || b.helix_id?.startsWith('__') ||
            (a.copy_k ?? 0) !== 0 || (b.copy_k ?? 0) !== 0 || coordinateOwners.get(key(a)) !== 1 ||
            ![a,b].every(n => Array.isArray(n.backbone_position) && n.backbone_position.length === 3 && n.backbone_position.every(Number.isFinite))) continue
        bonds.push({ a: a.backbone_position, b: b.backbone_position })
        nickArgs.push({ helixId:a.helix_id, bpIndex:a.bp_index, direction:a.direction })
      }
    }
    snapshot = { version: ++version, ends, nucleotides, bonds, nickArgs, assembly: !!state.assemblyActive }
    return snapshot
  }

  async function publish() {
    if (publishing || busy) return
    const current = catalog()
    const key = `${current.version}:${status}`
    if (key === published) return
    publishing = true
    try {
      await api.sendVRLigationEnds({ version: current.version, status, ends: current.ends, bonds: current.bonds })
      published = key
    } catch { /* Retry publication on the next native poll. */ }
    finally { publishing = false }
  }

  async function commit(event) {
    if (busy) return false
    const current = catalog()
    const action = event.action ?? 'ligate'
    const a = current.nucleotides[event.source], b = current.nucleotides[event.target]
    const valid = !current.assembly && (action === 'nick'
      ? Number.isSafeInteger(event.source) && !!current.nickArgs[event.source]
      : action === 'undo' || action === 'redo' || action === 'ligate' &&
        Number.isSafeInteger(event.source) && Number.isSafeInteger(event.target) && isValidPair(a,b))
    if (event.version !== current.version || !valid) {
      status = 'refused'; dirty = true; onOutcome('Design changed; select the wheel action again')
      await publish(); return false
    }
    busy = true
    try {
      clearSelection()
      let result
      if (action === 'nick') result = await api.addNick(current.nickArgs[event.source])
      else if (action === 'undo' || action === 'redo') result = await api[action]()
      else {
        const args = ligationArgs(a,b)
        result = await api.forcedLigation(args.three_prime_strand_id, args.five_prime_strand_id)
      }
      if (!result) throw new Error(action === 'undo' || action === 'redo' ? `Nothing to ${action}` : `${action} failed`)
      clearSelection()
      const refresh = await api.refreshNativeVRScene({ expected_design_id: getState().currentDesign.id,
        expected_revision: api.currentRevisionWatermark() })
      if (!refresh?.published) throw new Error('Edit saved, but VR scene refresh failed')
      status = 'created'
      return true
    } catch (error) {
      status = 'failed'; onOutcome(error.message)
      return false
    } finally {
      busy = false; dirty = true; await publish()
    }
  }

  return { publish, commit, catalog,
    reset() { published = ''; dirty = true; status = 'ready' },
    get busy() { return busy },
  }
}
