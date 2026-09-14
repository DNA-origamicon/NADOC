/** Ideal Kuhn-chain PEG surrogate. Lengths nm, fields V/nm, energy kBT.
 * Pivot Metropolis samples equilibrium configurations, NOT physical dynamics.
 * See docs/peg_testing.md for assumptions and validation targets.
 */
export const PEG_DEFAULTS = Object.freeze({ segments: 24, kuhn: 0.7, temperature: 300,
  field: 0.03, charge: 0, screening: 0, wall: true, chains: 64, seed: 173 })
export const ELEMENTARY_FORCE = 160.2176634 // pN per e per V/nm
export const KB = 0.01380649 // pN nm / K

export function validatePegParameters(p) {
  for (const key of ['segments', 'kuhn', 'temperature', 'field', 'charge', 'screening', 'chains', 'seed']) {
    if (!Number.isFinite(p[key])) throw new Error(`Invalid PEG parameter: ${key}`)
  }
  if (!Number.isInteger(p.segments) || p.segments < 2 || p.segments > 64 ||
      !Number.isInteger(p.chains) || p.chains < 1 || p.chains > 256 ||
      p.kuhn < 0.2 || p.kuhn > 2 || p.temperature < 250 || p.temperature > 400 ||
      Math.abs(p.field) > 0.2 || Math.abs(p.charge) > 2 || p.screening < 0 ||
      (p.screening > 0 && !p.wall)) throw new Error('PEG parameters outside playground limits')
  return p
}

export function endpointEnergy(z, p) {
  const a = p.charge * p.field * ELEMENTARY_FORCE / (KB * p.temperature)
  // E(z)=E0 exp(-z/lambda); U(z)=q E0 lambda exp(-z/lambda).
  return p.screening > 0 ? a * p.screening * Math.exp(-z / p.screening) : -a * z
}

export function langevin(x) {
  if (Math.abs(x) < 1e-3) return x / 3 - x ** 3 / 45 + 2 * x ** 5 / 945
  return 1 / Math.tanh(x) - 1 / x
}

export function freeChainExtension(p) {
  return p.segments * p.kuhn * langevin(p.charge * p.field * ELEMENTARY_FORCE * p.kuhn / (KB * p.temperature))
}

/** Independent transfer-integral reference: each segment has uniform z increment
 * on [-b,b]. Discard paths crossing the wall, then weight their terminal height
 * by exp(-U/kBT). Midpoint quadrature with half-weight window endpoints.
 * This is a numerical ideal-chain reference, not atomistic PEG validation.
 */
export function heightReference(p, cellsPerSegment = 24) {
  const dz = p.kuhn / cellsPerSegment
  const bins = p.segments * cellsPerSegment * (p.wall ? 1 : 2)
  const lower = p.wall ? 0 : -p.segments * p.kuhn
  const heights = Float64Array.from({ length: bins }, (_, i) => lower + (i + 0.5) * dz)
  let probability = Float64Array.from(heights, z => Math.abs(z) < p.kuhn ? 1 : 0)
  const normalize = a => { const sum = a.reduce((s, v) => s + v, 0); for (let i = 0; i < a.length; i++) a[i] /= sum }
  normalize(probability)
  for (let step = 1; step < p.segments; step++) {
    const next = new Float64Array(bins)
    for (let i = 0; i < bins; i++) {
      const lo = i - cellsPerSegment, hi = i + cellsPerSegment
      // Direct summation preserves the rare stretched tails that become
      // dominant under large forces (prefix subtraction cancels them away).
      for (let j = Math.max(0, lo); j <= Math.min(bins - 1, hi); j++) {
        next[i] += probability[j] * (j === lo || j === hi ? 0.5 : 1)
      }
    }
    normalize(next)
    probability = next
  }
  const logWeights = Float64Array.from(heights, (z, i) => Math.log(probability[i]) - endpointEnergy(z, p))
  const shift = Math.max(...logWeights)
  for (let i = 0; i < bins; i++) probability[i] = Math.exp(logWeights[i] - shift)
  normalize(probability)
  return { heights, probability, dz, mean: heights.reduce((s, z, i) => s + z * probability[i], 0) }
}

// Integer hash also used in the GPU shader; each proposal is determined by
// (seed, sweep, chain). All beads in a chain must share exactly one proposal.
export function pegRandom(seed) {
  let state = seed >>> 0
  return () => {
    state = (state + 0x9e3779b9) >>> 0
    let x = state
    x = Math.imul(x ^ (x >>> 16), 0x21f0aaad) >>> 0
    x = Math.imul(x ^ (x >>> 15), 0x735a2d97) >>> 0
    x = (x ^ (x >>> 15)) >>> 0
    return (x >>> 8) / 16777216
  }
}

export function initialPegState(p) {
  validatePegParameters(p)
  const data = new Float32Array((p.segments + 1) * p.chains * 4)
  // Extended initial state: explicitly reported as burn-in in the playground.
  for (let c = 0; c < p.chains; c++) for (let j = 0; j <= p.segments; j++) {
    const i = (c * (p.segments + 1) + j) * 4
    data[i + 2] = j * p.kuhn
    data[i + 3] = 1
  }
  return data
}

export function pivotStep(data, p, sweep) {
  const width = p.segments + 1
  let accepted = 0
  for (let c = 0; c < p.chains; c++) {
    const random = pegRandom((p.seed + Math.imul(sweep, 747796405) + Math.imul(c, 2891336453)) >>> 0)
    const joint = Math.floor(random() * p.segments)
    const az = 2 * random() - 1, phi = 2 * Math.PI * random(), angle = (2 * random() - 1) * Math.PI
    const radius = Math.sqrt(1 - az * az), axis = [radius * Math.cos(phi), radius * Math.sin(phi), az]
    const cosine = Math.cos(angle), sine = Math.sin(angle), acceptance = random()
    const start = c * width * 4, pivot = start + joint * 4
    const candidate = new Float32Array((p.segments - joint) * 3)
    let valid = true
    for (let j = joint + 1; j <= p.segments; j++) {
      const i = start + j * 4, k = (j - joint - 1) * 3
      const v = [data[i] - data[pivot], data[i + 1] - data[pivot + 1], data[i + 2] - data[pivot + 2]]
      const dot = axis.reduce((s, a, d) => s + a * v[d], 0)
      for (let d = 0; d < 3; d++) candidate[k + d] = data[pivot + d] + v[d] * cosine +
        (axis[(d + 1) % 3] * v[(d + 2) % 3] - axis[(d + 2) % 3] * v[(d + 1) % 3]) * sine + axis[d] * dot * (1 - cosine)
      if (p.wall && candidate[k + 2] < 0) valid = false
    }
    const oldZ = data[start + p.segments * 4 + 2], newZ = candidate[candidate.length - 1]
    if (valid && Math.log(Math.max(acceptance, 1e-30)) < Math.min(0, endpointEnergy(oldZ, p) - endpointEnergy(newZ, p))) {
      accepted++
      for (let j = joint + 1; j <= p.segments; j++) for (let d = 0; d < 3; d++) data[start + j * 4 + d] = candidate[(j - joint - 1) * 3 + d]
    }
  }
  return accepted
}

export function pegMetrics(data, p) {
  const ends = [], width = p.segments + 1
  let meanR2 = 0, maxBondError = 0, minZ = Infinity
  for (let c = 0; c < p.chains; c++) {
    const end = (c * width + p.segments) * 4
    ends.push(data[end + 2])
    meanR2 += data[end] ** 2 + data[end + 1] ** 2 + data[end + 2] ** 2
    for (let j = 0; j < width; j++) {
      const i = (c * width + j) * 4
      minZ = Math.min(minZ, data[i + 2])
      if (j) maxBondError = Math.max(maxBondError, Math.abs(Math.hypot(data[i] - data[i - 4], data[i + 1] - data[i - 3], data[i + 2] - data[i - 2]) - p.kuhn))
    }
  }
  return { ends, meanHeight: ends.reduce((a, b) => a + b, 0) / p.chains, meanR2: meanR2 / p.chains, maxBondError, minZ }
}
