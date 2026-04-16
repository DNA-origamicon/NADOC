/**
 * Minimal API client for the cadnano editor.
 *
 * Standalone — does not import the main app's store.  All functions
 * return the parsed JSON or null on error.
 */

import { editorStore } from './store.js'
import { nadocBroadcast } from '../shared/broadcast.js'

const BASE = '/api'

async function _request(method, path, body) {
  editorStore.setState({ loading: true })
  const opts = {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
    body:    body !== undefined ? JSON.stringify(body) : undefined,
  }
  try {
    const r    = await fetch(`${BASE}${path}`, opts)
    const json = await r.json().catch(() => null)
    if (!r.ok) {
      editorStore.setState({ lastError: { status: r.status, message: json?.detail ?? r.statusText }, loading: false })
      return null
    }
    editorStore.setState({ lastError: null, loading: false })
    return json
  } catch (err) {
    editorStore.setState({ lastError: { status: 0, message: err.message }, loading: false })
    return null
  }
}

/** Fetch the current design and update the editor store. */
export async function fetchDesign() {
  const json = await _request('GET', '/design')
  if (json?.design) editorStore.setState({ design: json.design })
  return json
}

/**
 * Perform a mutation, update the editor store, and notify other tabs.
 * `mutationFn` receives `_request` and should return the response JSON.
 */
export async function mutate(mutationFn) {
  const json = await mutationFn(_request)
  if (json?.design) {
    editorStore.setState({ design: json.design })
    nadocBroadcast.emit('design-changed')
  }
  return json
}

/**
 * Add a helix at a lattice cell (row, col).
 * The backend computes axis position, phase, and twist from the lattice type.
 */
export async function addHelixAtCell(row, col, length_bp = 42) {
  return mutate(req => req('POST', '/design/helix-at-cell', { row, col, length_bp }))
}

/** Delete a helix by ID. */
export async function deleteHelix(helixId) {
  return mutate(req => req('DELETE', `/design/helix/${helixId}`))
}

/**
 * Extend a helix's bp range to cover [loBp, hiBp].  Never shrinks.
 * Adjusts axis geometry and phase so existing nucleotides stay in place.
 */
export async function extendHelixBounds(helixId, loBp, hiBp) {
  return mutate(req =>
    req('PATCH', `/design/helices/${helixId}/extend`, { lo_bp: loBp, hi_bp: hiBp })
  )
}

/** Auto-scaffold the design. */
export async function autoScaffold(opts = {}) {
  const { minStapleMargin = 3 } = opts
  return mutate(req => req('POST', '/design/auto-scaffold', {
    min_staple_margin: minStapleMargin,
  }))
}

/**
 * Paint a scaffold domain onto a helix from the pencil tool.
 * loBp/hiBp are bp indices left-to-right (order-independent).
 * The server determines strand direction from the helix's grid_pos.
 */
export async function scaffoldDomainPaint(helixId, loBp, hiBp) {
  return mutate(req =>
    req('POST', '/design/scaffold-domain-paint', { helix_id: helixId, lo_bp: loBp, hi_bp: hiBp })
  )
}

/**
 * Paint a new single-domain staple strand on the given helix + direction.
 * direction: 'FORWARD' | 'REVERSE'
 * loBp/hiBp: bp indices left-to-right (order-independent).
 */
export async function paintStapleDomain(helixId, direction, loBp, hiBp) {
  const isFwd = direction === 'FORWARD'
  return mutate(req =>
    req('POST', '/design/strands', {
      domains: [{
        helix_id:  helixId,
        start_bp:  isFwd ? loBp : hiBp,
        end_bp:    isFwd ? hiBp : loBp,
        direction,
      }],
      strand_type: 'staple',
    })
  )
}

/**
 * Place a crossover atomically: nick helix A, nick helix B, register the record.
 * All three steps are a single undo checkpoint — one Ctrl-Z fully reverts placement.
 * halfA/halfB carry index = sprite bp (used for the crossover record).
 * nickBpA/nickBpB are the nick positions computed by the pathview bow-direction rules.
 */
export async function placeCrossover(halfA, halfB, nickBpA, nickBpB) {
  return mutate(req => req('POST', '/design/crossovers/place', {
    half_a:    { helix_id: halfA.helix_id, index: halfA.index, strand: halfA.strand },
    half_b:    { helix_id: halfB.helix_id, index: halfB.index, strand: halfB.strand },
    nick_bp_a: nickBpA,
    nick_bp_b: nickBpB,
  }))
}

/** Move an existing crossover to a new bp index, resizing adjacent domains. */
export async function moveCrossover(crossoverId, newIndex) {
  return mutate(req => req('POST', '/design/crossovers/move', {
    crossover_id: crossoverId,
    new_index:    newIndex,
  }))
}

/** Move multiple crossovers to new bp indices in a single atomic operation. */
export async function batchMoveCrossovers(moves) {
  return mutate(req => req('POST', '/design/crossovers/batch-move', { moves }))
}

/** Remove a crossover by ID. */
export async function deleteCrossover(crossoverId) {
  return mutate(req => req('DELETE', `/design/crossovers/${crossoverId}`))
}

/** Remove multiple crossovers in a single atomic request. */
export async function batchDeleteCrossovers(crossoverIds) {
  if (!crossoverIds.length) return null
  return mutate(req => req('POST', '/design/crossovers/batch-delete', { crossover_ids: crossoverIds }))
}

/** Set (or clear) extra bases on a single crossover. Pass sequence='' to remove. */
export async function patchCrossoverExtraBases(crossoverId, sequence) {
  return mutate(req => req('PATCH', `/design/crossovers/${crossoverId}/extra-bases`, { sequence }))
}

/** Batch-set extra bases on multiple crossovers in one atomic request.
 *  entries: Array of { crossover_id: string, sequence: string }
 */
export async function batchCrossoverExtraBases(entries) {
  return mutate(req => req('PATCH', '/design/crossovers/extra-bases/batch', { entries }))
}

/** Delete a strand. */
export async function deleteStrand(strandId) {
  return mutate(req => req('DELETE', `/design/strands/${strandId}`))
}

/**
 * Delete a single domain from a strand by its index.
 * Fails (409) if a crossover references the domain.
 */
export async function deleteDomain(strandId, domainIdx) {
  return mutate(req => req('DELETE', `/design/strands/${strandId}/domains/${domainIdx}`))
}

/**
 * Nick a strand at the 3′ side of bp_index.
 * direction: 'FORWARD' | 'REVERSE'
 */
export async function nickStrand(helixId, bpIndex, direction) {
  return mutate(req =>
    req('POST', '/design/nick', { helix_id: helixId, bp_index: bpIndex, direction })
  )
}

/**
 * Ligate (repair) a nick by merging the two strand ends adjacent to bp_index.
 * bp_index is the 3′ end of the left fragment — same convention as nickStrand.
 */
export async function ligateStrand(helixId, bpIndex, direction) {
  return mutate(req =>
    req('POST', '/design/ligate', { helix_id: helixId, bp_index: bpIndex, direction })
  )
}

/**
 * Forced ligation — connect any 3' end to any 5' end, bypassing crossover
 * lookup tables.  Manual pencil-tool feature only; must NOT be used by
 * autocrossover or any automated pipeline.
 */
export async function forcedLigation(threePrimeStrandId, fivePrimeStrandId) {
  return mutate(req =>
    req('POST', '/design/forced-ligation', {
      three_prime_strand_id: threePrimeStrandId,
      five_prime_strand_id:  fivePrimeStrandId,
    })
  )
}

/** Remove a forced ligation by ID — splits the strand back into two fragments. */
export async function deleteForcedLigation(flId) {
  return mutate(req => req('DELETE', `/design/forced-ligations/${flId}`))
}

/** Remove multiple forced ligations in a single atomic request. */
export async function batchDeleteForcedLigations(flIds) {
  if (!flIds.length) return null
  return mutate(req => req('POST', '/design/forced-ligations/batch-delete', { forced_ligation_ids: flIds }))
}

/**
 * Update editable strand metadata (color and/or notes).
 * color: '#RRGGBB' hex string, or null to reset to palette.
 */
export async function patchStrand(strandId, { color = undefined, notes = undefined } = {}) {
  return mutate(req =>
    req('PATCH', `/design/strand/${strandId}`, { color, notes })
  )
}

export async function patchOverhang(overhangId, { sequence = undefined, label = undefined } = {}) {
  const body = {}
  if (sequence !== undefined) body.sequence = sequence
  if (label    !== undefined) body.label    = label
  return mutate(req =>
    req('PATCH', `/design/overhang/${encodeURIComponent(overhangId)}`, body)
  )
}

/**
 * Apply the same color to multiple strands in a single atomic request.
 * color: '#RRGGBB' hex string, or null to reset to palette.
 */
export async function patchStrandsColor(strandIds, color) {
  return mutate(req =>
    req('PATCH', '/design/strands/colors', { strand_ids: strandIds, color })
  )
}

/**
 * Resize one or more strand ends by a shared delta_bp.
 * entries: [{ strand_id, helix_id, end: '5p'|'3p', delta_bp }]
 */
export async function resizeStrandEnds(entries) {
  return mutate(async req => {
    const json = await req('POST', '/design/strand-end-resize', { entries })
    // Log every strand that touches the affected helices so we can see nicks.
    if (json?.design) {
      const affectedIds = new Set(entries.map(e => e.helix_id))
      console.group('%c[API /strand-end-resize response]', 'color:cyan')
      console.log('sent entries:', entries)
      for (const hid of affectedIds) {
        const h = json.design.helices?.find(x => x.id === hid)
        if (!h) { console.log(`  helix ${hid}: NOT FOUND in response`); continue }
        console.log(`  helix ${hid}  bp_start=${h.bp_start}  length_bp=${h.length_bp}`)
        const doms = (json.design.strands ?? []).flatMap(s =>
          s.domains
            .filter(d => d.helix_id === hid)
            .map(d => ({
              strand: s.id.slice(0,16),
              type: s.strand_type,
              dir: d.direction,
              start_bp: d.start_bp,
              end_bp: d.end_bp,
              range: `[${Math.min(d.start_bp,d.end_bp)}..${Math.max(d.start_bp,d.end_bp)}]`,
            }))
        )
        console.table(doms)
      }
      console.groupEnd()
    }
    return json
  })
}

/**
 * Insert or remove a single loop/skip at a bp position.
 * delta: +1 = loop (insertion), -1 = skip (deletion), 0 = remove existing
 */
export async function insertLoopSkip(helixId, bpIndex, delta) {
  return mutate(req => req('POST', '/design/loop-skip/insert', {
    helix_id: helixId,
    bp_index: bpIndex,
    delta,
  }))
}

/** Create a new blank design, replacing the current one. */
export async function createDesign(name = 'Untitled', latticeType = 'HONEYCOMB') {
  return mutate(req => req('POST', '/design', { name, lattice_type: latticeType }))
}

/** Import a NADOC JSON string, replacing the current design. */
export async function importDesign(content) {
  return mutate(req => req('POST', '/design/import', { content }))
}

/** Shift all helix grid positions so min row = 0, min col = 0. */
export async function centerDesign() {
  return mutate(req => req('POST', '/design/center'))
}

/** Import a caDNAno JSON string, replacing the current design. */
export async function importCadnanoDesign(content) {
  return mutate(req => req('POST', '/design/import/cadnano', { content }))
}

/** Import a scadnano .sc JSON string, replacing the current design. */
export async function importScadnanoDesign(content) {
  return mutate(req => req('POST', '/design/import/scadnano', { content }))
}

/** Import a PDB file containing DNA, replacing the current design. */
export async function importPdbDesign(content, merge = false) {
  return mutate(req => req('POST', '/design/import/pdb', { content, merge }))
}

/** Download the current design as a .nadoc file. */
export async function exportDesign() {
  const r = await fetch('/api/design/export')
  if (!r.ok) return false
  const cd   = r.headers.get('Content-Disposition') ?? ''
  const m    = cd.match(/filename="([^"]+)"/)
  const name = m ? m[1] : 'design.nadoc'
  const blob = await r.blob()
  const url  = URL.createObjectURL(blob)
  const a = Object.assign(document.createElement('a'), { href: url, download: name })
  document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url)
  return true
}

/** Download the current design as a caDNAno JSON file. */
export async function exportCadnano() {
  const r = await fetch('/api/design/export/cadnano')
  if (!r.ok) return false
  const cd   = r.headers.get('Content-Disposition') ?? ''
  const m    = cd.match(/filename="([^"]+)"/)
  const name = m ? m[1] : 'design.json'
  const blob = await r.blob()
  const url  = URL.createObjectURL(blob)
  const a = Object.assign(document.createElement('a'), { href: url, download: name })
  document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url)
  return true
}

/** Download the staple/scaffold sequences as a CSV file. */
export async function exportSequenceCsv() {
  const r = await fetch('/api/design/export/sequence-csv')
  if (!r.ok) return false
  const cd   = r.headers.get('Content-Disposition') ?? ''
  const m    = cd.match(/filename="?([^"]+)"?/)
  const name = m ? m[1] : 'sequences.csv'
  const blob = await r.blob()
  const url  = URL.createObjectURL(blob)
  const a = Object.assign(document.createElement('a'), { href: url, download: name })
  document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url)
  return true
}

/** Place all valid staple crossovers automatically. */
export async function addAutoCrossover() {
  return mutate(req => req('POST', '/design/crossovers/auto'))
}

/** Break the scaffold at canonical nicking points. */
export async function addAutoBreak(opts = {}) {
  return mutate(req => req('POST', '/design/auto-break', opts))
}

/** Merge short staple fragments across nicks. */
export async function addAutoMerge() {
  return mutate(req => req('POST', '/design/auto-merge'))
}

/** Extend the near scaffold end by lengthBp. */
export async function scaffoldExtrudeNear(lengthBp = 10) {
  return mutate(req => req('POST', '/design/scaffold-extrude-near', { length_bp: lengthBp }))
}

/** Extend the far scaffold end by lengthBp. */
export async function scaffoldExtrudeFar(lengthBp = 10) {
  return mutate(req => req('POST', '/design/scaffold-extrude-far', { length_bp: lengthBp }))
}

/** Route a seamless (looped) scaffold. */
export async function autoScaffoldSeamless(opts = {}) {
  const { nickHelixId = null, nickOffset = 7, minEndMargin = 9 } = opts
  return mutate(req => req('POST', '/design/auto-scaffold-seamless', {
    nick_helix_id: nickHelixId, nick_offset: nickOffset, min_end_margin: minEndMargin,
  }))
}

/** Route a jointed scaffold. */
export async function jointedScaffold(opts = {}) {
  const { mode = 'end_to_end', nickOffset = 7, minEndMargin = 9 } = opts
  return mutate(req => req('POST', '/design/jointed-scaffold', {
    mode, nick_offset: nickOffset, min_end_margin: minEndMargin,
  }))
}

/**
 * Assign a scaffold sequence by name or custom string.
 * Returns raw JSON (not synced to store) — caller reads padded_nt etc. first.
 */
export async function assignScaffoldSequence(scaffoldName = 'M13mp18', opts = {}) {
  const { customSequence = null, strandId = null } = opts
  return _request('POST', '/design/assign-scaffold-sequence', {
    scaffold_name:   scaffoldName,
    custom_sequence: customSequence || null,
    strand_id:       strandId || null,
  })
}

/** Apply scaffold sequence to design store after assignScaffoldSequence call. */
export async function syncScaffoldSequenceResponse(json) {
  if (json?.design) {
    editorStore.setState({ design: json.design })
    nadocBroadcast.emit('design-changed')
  }
  return json
}

/** Derive complementary staple sequences from the scaffold sequence. */
export async function assignStapleSequences() {
  return mutate(req => req('POST', '/design/assign-staple-sequences'))
}

/** Apply all deformations and update staple routing. */
export async function applyAllDeformations() {
  return mutate(req => req('POST', '/design/apply-all-deformations'))
}

/**
 * Revert the last mutation.
 * Returns the restored design, or null if nothing to undo (404 is silent — not an error).
 */
export async function undoDesign() {
  editorStore.setState({ loading: true })
  try {
    const r = await fetch(`${BASE}/design/undo`, { method: 'POST' })
    editorStore.setState({ loading: false })
    if (r.status === 404) return null          // stack empty — silent
    const json = await r.json().catch(() => null)
    if (!r.ok) return null
    if (json?.design) {
      editorStore.setState({ design: json.design })
      nadocBroadcast.emit('design-changed')
    }
    return json
  } catch (err) {
    editorStore.setState({ loading: false })
    return null
  }
}

/**
 * Re-apply the last undone mutation.
 * Returns the restored design, or null if nothing to redo (404 is silent — not an error).
 */
export async function redoDesign() {
  editorStore.setState({ loading: true })
  try {
    const r = await fetch(`${BASE}/design/redo`, { method: 'POST' })
    editorStore.setState({ loading: false })
    if (r.status === 404) return null          // stack empty — silent
    const json = await r.json().catch(() => null)
    if (!r.ok) return null
    if (json?.design) {
      editorStore.setState({ design: json.design })
      nadocBroadcast.emit('design-changed')
    }
    return json
  } catch (err) {
    editorStore.setState({ loading: false })
    return null
  }
}
