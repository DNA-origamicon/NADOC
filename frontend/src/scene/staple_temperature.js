/** Read-only staple thermodynamics. Model and units: docs/staple_temperature.md. */
import { domainKeys, strandSequenceDisplay } from '../ui/strand_sequence_display.js'
import { baseKey, parseBaseKey } from './base_ref.js'
import { domainJunctions, junctionIndex, strandJunctions } from '../design/strand_junctions.js'

export const CONDITIONS = Object.freeze({ magnesiumM: 0.010, stapleM: 200e-9 })
const R = 8.31447 / 4.184 // cal mol−1 K−1
const NN = {
  AA: [-7.6, -21.3], TT: [-7.6, -21.3], AT: [-7.2, -20.4], TA: [-7.2, -21.3],
  CA: [-8.5, -22.7], TG: [-8.5, -22.7], GT: [-8.4, -22.4], AC: [-8.4, -22.4],
  CT: [-7.8, -21.0], AG: [-7.8, -21.0], GA: [-8.2, -22.2], TC: [-8.2, -22.2],
  CG: [-10.6, -27.2], GC: [-9.8, -24.4], GG: [-8.0, -19.9], CC: [-8.0, -19.9],
}
const complement = { A: 'T', T: 'A', C: 'G', G: 'C' }

/** SantaLucia & Hicks 2004 Table 1: kcal/mol and cal/(mol K). */
export function duplexThermodynamics(sequence) {
  const seq = (sequence ?? '').toUpperCase()
  if (!/^[ACGT]{2,}$/.test(seq)) return null
  let h = 0.2, s = -5.7
  for (const base of [seq[0], seq.at(-1)]) {
    if (base === 'A' || base === 'T') { h += 2.2; s += 6.9 }
  }
  for (let i = 1; i < seq.length; i++) {
    const [dh, ds] = NN[seq.slice(i - 1, i + 1)]
    h += dh; s += ds
  }
  return { h, s }
}

/** Excess-staple duplex Tm; Owczarzy 2008 Eq.16 uses KELVIN, not Celsius. */
export function domainMeltingTemperature(sequence) {
  const thermo = duplexThermodynamics(sequence)
  if (!thermo) return null
  const seq = sequence.toUpperCase(), n = seq.length
  const gc = [...seq].filter(b => b === 'G' || b === 'C').length / n
  const l = Math.log(CONDITIONS.magnesiumM)
  const correction = 3.92e-5 - 9.11e-6 * l + gc * (6.26e-5 + 1.42e-5 * l)
    + (-4.82e-4 + 5.25e-4 * l + 8.31e-5 * l * l) / (2 * (n - 1))
  const kelvin = thermo.h * 1000 / (thermo.s + R * Math.log(CONDITIONS.stapleM))
  return 1 / (1 / kelvin + correction) - 273.15
}

/** pyOrigamiBreak loop entropy: worm-like ssDNA, Gaussian end concentration. */
export function loopClosureEntropy(distanceNt) {
  if (!(distanceNt > 0) || !Number.isFinite(distanceNt)) return null
  const contour = distanceNt * 0.6, persistence = 0.9
  const r2 = 2 * persistence * contour * (1 - persistence / contour * (1 - Math.exp(-contour / persistence)))
  const effectiveM = (3 / (2 * Math.PI * r2 * 1e-18)) ** 1.5 / 6.02e23 / 1000
  return R * Math.log(effectiveM)
}

/** PNAS 2024 Tfold: one concentration term; independent duplex and loop terms. */
export function stapleFoldingTemperature(sequences, loopDistances) {
  if (!sequences.length || loopDistances.length !== sequences.length - 1) return null
  let h = 0, s = R * Math.log(CONDITIONS.stapleM)
  for (const seq of sequences) {
    const thermo = duplexThermodynamics(seq)
    if (!thermo) return null
    h += thermo.h * 1000
    // Dunn 2015 salt entropy, with no unspecified Tris/monovalent contribution.
    s += thermo.s + 0.368 * (seq.length - 1) * Math.log(3.3 * Math.sqrt(CONDITIONS.magnesiumM))
  }
  for (const distance of loopDistances) {
    const entropy = loopClosureEntropy(distance)
    if (entropy == null) return null
    s += entropy
  }
  return h / s - 273.15
}

function partnerKey(key) {
  const p = parseBaseKey(key)
  return baseKey({ ...p, direction: p.direction === 'FORWARD' ? 'REVERSE' : 'FORWARD' }, p.copy)
}

/** Domain sequence offsets use the same loop/skip convention as the spreadsheet. */
export function estimateStapleTemperatures(design) {
  const strands = design?.strands ?? [], index = junctionIndex(design)
  const scaffolds = new Map(), pairing = new Map()
  // Every active scaffold has its own circular contour and independent origin.
  // Inserted scaffold bases contribute to that scaffold's contour length.
  for (const strand of strands.filter(s => s.strand_type === 'scaffold' && !s.is_reference)) {
    const scaffold = { id: strand.id, length: 0 }
    scaffolds.set(strand.id, scaffold)
    for (const run of strandSequenceDisplay(strand, design, undefined, index).runs) {
      run.keys.forEach((key, i) => {
        const partner = { scaffold, position: scaffold.length++, base: run.text[i]?.toUpperCase() }
        // Ambiguous occupancy must not pick whichever scaffold happens to be last.
        pairing.set(key, pairing.has(key) ? null : partner)
      })
    }
  }
  const results = new Map()
  for (const strand of strands) {
    if (strand.strand_type === 'scaffold' || strand.is_reference) continue
    let offset = 0
    const domains = (strand.domains ?? []).map(d => {
      const keys = domainKeys(d, design)
      const sequence = (strand.sequence ?? '').slice(offset, offset + keys.length).toUpperCase()
      offset += keys.length
      const partners = keys.map(k => pairing.get(partnerKey(k)))
      const tail = d.overhang_id != null && d.binds_overhang_id == null
      const unsupported = d.overhang_id != null || d.binds_overhang_id != null
        || [...domainJunctions(d, index).values()].some(j => j.extra_bases?.length)
      const mismatch = partners.some((p, i) => complement[p?.base] && complement[p.base] !== sequence[i])
      const tm = unsupported || mismatch || !partners.every(Boolean) || sequence.length !== keys.length ? null : domainMeltingTemperature(sequence)
      // Only unwrap within one molecule; never join independent scaffold origins.
      const scaffold = partners[0]?.scaffold
      const scaffoldId = scaffold && partners.every(p => p?.scaffold === scaffold) ? scaffold.id : null
      const scaffoldLength = scaffold?.length ?? 0
      let center = null
      if (scaffoldId != null && scaffoldLength) {
        const positions = [partners[0].position]
        for (let i = 1; i < partners.length; i++) {
          let delta = partners[i].position - partners[i - 1].position
          if (delta > scaffoldLength / 2) delta -= scaffoldLength
          if (delta < -scaffoldLength / 2) delta += scaffoldLength
          positions.push(positions.at(-1) + delta)
        }
        const ordered = [...new Set(positions)].sort((a, b) => a - b)
        const contiguous = ordered.length === positions.length && ordered.at(-1) - ordered[0] === ordered.length - 1
        if (contiguous) center = ((positions.reduce((a, b) => a + b, 0) / positions.length) % scaffoldLength + scaffoldLength) % scaffoldLength
      }
      return { keys, sequence, tm, center, scaffoldId, unsupported, tail }
    })
    const bound = domains.filter(d => !d.tail)
    const scaffoldId = bound.length && bound[0].scaffoldId != null
      && bound.every(d => d.scaffoldId === bound[0].scaffoldId) ? bound[0].scaffoldId : null
    const scaffoldLength = scaffolds.get(scaffoldId)?.length ?? 0
    const junctionExtras = strandJunctions(strand, index).some(j => j?.extra_bases?.length)
    // Do not silently fit unsupported linkers, circular staples, or mixed scaffolds.
    const eligible = scaffoldId != null && bound.length && !strandJunctions(strand, index).at(-1) && !junctionExtras
      && domains.every((d, i) => !d.unsupported || (d.tail && (i === 0 || i === domains.length - 1)))
      && bound.every(d => d.tm != null && d.center != null)
    const distances = bound.slice(1).map((d, i) => {
      const distance = Math.abs(d.center - bound[i].center)
      return Math.min(distance, scaffoldLength - distance)
    })
    const total = eligible ? stapleFoldingTemperature(bound.map(d => d.sequence), distances) : null
    results.set(strand.id, { domains, total, scaffoldId })
  }
  return results
}
