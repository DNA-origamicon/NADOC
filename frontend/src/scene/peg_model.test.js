import { describe, expect, it } from 'vitest'
import { PEG_DEFAULTS, KB, ELEMENTARY_FORCE, endpointEnergy, freeChainExtension, heightReference,
  initialPegState, pivotStep, pegMetrics, validatePegParameters } from './peg_model.js'

function sample(overrides) {
  const p = { ...PEG_DEFAULTS, segments: 8, chains: 128, ...overrides }
  const data = initialPegState(p)
  let mean = 0, r2 = 0, count = 0
  for (let step = 1; step <= 3000; step++) {
    pivotStep(data, p, step)
    if (step > 1000 && step % 25 === 0) {
      const metrics = pegMetrics(data, p)
      mean += metrics.meanHeight; r2 += metrics.meanR2; count++
    }
  }
  return { p, data, mean: mean / count, r2: r2 / count, metrics: pegMetrics(data, p) }
}

describe('PEG ideal-chain statistical mechanics', () => {
  it('uses consistent electrostatic units and screening force sign', () => {
    const p = { ...PEG_DEFAULTS, charge: 1, screening: 2 }
    const h = 1e-5, z = 1
    const force = -(endpointEnergy(z + h, p) - endpointEnergy(z - h, p)) / (2 * h)
    expect(force).toBeCloseTo(ELEMENTARY_FORCE * p.field * Math.exp(-z / 2) / (KB * p.temperature), 8)
    expect(endpointEnergy(100, { ...p, charge: 0 })).toBe(0)
  })

  it('independent quadrature agrees with exact Langevin extension for both polarities', () => {
    for (const field of [0, 0.03, -0.03, 0.1]) {
      const p = { ...PEG_DEFAULTS, wall: false, charge: 1, field }
      expect(Math.abs(heightReference(p).mean - freeChainExtension(p))).toBeLessThan(0.02)
    }
  })

  it('preserves finite probabilities at the largest permitted force and chain length', () => {
    const p = { ...PEG_DEFAULTS, segments: 64, kuhn: 2, charge: 2, field: 0.2, temperature: 250 }
    const ref = heightReference(p)
    expect(ref.probability.every(Number.isFinite)).toBe(true)
    expect(ref.mean).toBeGreaterThan(0.9 * p.segments * p.kuhn)
    expect(ref.mean).toBeLessThan(p.segments * p.kuhn)
  })

  it('neutral trajectories are identical at reversed fields with the same seed', () => {
    const p = { ...PEG_DEFAULTS, segments: 8, chains: 8 }
    const a = initialPegState(p), b = initialPegState(p)
    for (let k = 1; k <= 100; k++) { pivotStep(a, p, k); pivotStep(b, { ...p, field: -p.field }, k) }
    expect(a).toEqual(b)
  })

  it('samples the exact zero-field free-chain second moment', () => {
    const result = sample({ wall: false, field: 0 })
    expect(Math.abs(result.mean)).toBeLessThan(0.09)
    expect(Math.abs(result.r2 - result.p.segments * result.p.kuhn ** 2)).toBeLessThan(0.15)
  })

  it('samples the exact force-extension curve while preserving every bond and anchor', () => {
    const result = sample({ wall: false, charge: 1 })
    expect(Math.abs(result.mean - freeChainExtension(result.p))).toBeLessThan(0.1)
    expect(result.metrics.maxBondError).toBeLessThan(0.001)
    for (let c = 0; c < result.p.chains; c++) expect(Array.from(result.data.slice(c * 9 * 4, c * 9 * 4 + 3))).toEqual([0, 0, 0])
  })

  it('matches the wall-conditioned reference for screened and reversed fields', () => {
    for (const overrides of [{ charge: 1, screening: 2 }, { charge: 1, field: -0.03 }]) {
      const result = sample(overrides)
      expect(Math.abs(result.mean - heightReference(result.p, 48).mean)).toBeLessThan(0.1)
      expect(result.metrics.minZ).toBeGreaterThanOrEqual(0)
      expect(result.metrics.maxBondError).toBeLessThan(0.001)
    }
  })

  it('rejects invalid sizes, nonfinite fields, and screening below an absent wall', () => {
    for (const override of [{ segments: 1000 }, { field: NaN }, { wall: false, screening: 2 }]) {
      expect(() => validatePegParameters({ ...PEG_DEFAULTS, ...override })).toThrow()
    }
  })
})
