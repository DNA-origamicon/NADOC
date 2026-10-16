import { describe, expect, it } from 'vitest'
import { validatePartComparisonEnvelope } from './part_comparison_model.js'
import { comparisonBinding, comparisonEnvelope } from '../test-helpers/part_comparison.js'

describe('private comparison envelope', () => {
  it('accepts the complete display projection without turning it into a design or certificate', () => {
    const packet = comparisonEnvelope(), original = JSON.stringify(packet)
    const result = validatePartComparisonEnvelope(packet, comparisonBinding())
    expect(result.published.particles[0].authored_visible).toBe(false)
    expect(result.proposed.particles[0].diameter_nm).toBe(12)
    expect(result.coverage.scientific_qualification).toBe(false)
    expect(result).not.toHaveProperty('design')
    expect(result).not.toHaveProperty('candidate')
    expect(result).not.toHaveProperty('ready')
    expect(JSON.stringify(packet)).toBe(original)
  })

  it.each([
    ['job', packet => { packet.job_id = 'another' }],
    ['design', packet => { packet.design_id = 'another' }],
    ['revision', packet => { packet.source_revision++ }],
    ['draft', packet => { packet.repair_draft.draft_id = 'another' }],
    ['generation', packet => { packet.repair_draft.generation++ }],
    ['version', packet => { packet.projection_version = 2 }],
    ['expired lease', packet => { packet.expires_in_seconds = 0 }],
    ['unbounded lease', packet => { packet.expires_in_seconds = Infinity }],
    ['renewed lease', packet => { packet.expires_in_seconds = 901 }],
    ['scope', packet => { packet.scope = 'dna' }],
    ['incomplete', packet => { packet.coverage.complete = false }],
    ['physical frame', packet => { packet.coverage.excluded_layers = ['presentation'] }],
    ['qualification', packet => { packet.coverage.scientific_qualification = true }],
    ['wrong units', packet => { packet.proposed.units = 'angstrom' }],
    ['missing pane', packet => { delete packet.proposed }],
    ['candidate injection', packet => { packet.candidate = { id: 'part' } }],
    ['hidden family', packet => { packet.published.helices = [{ id: 'omitted' }] }],
  ])('refuses %s before any display allocation', (_label, change) => {
    const packet = comparisonEnvelope(); change(packet)
    expect(() => validatePartComparisonEnvelope(packet, comparisonBinding())).toThrow()
  })

  it.each([
    ['nonfinite coordinate', pane => { pane.proteins[0].atoms[0].x = Infinity }],
    ['negative radius', pane => { pane.particles[0].diameter_nm = -1 }],
    ['oversized diameter', pane => { pane.particles[0].diameter_nm = 1001 }],
    ['invalid pose', pane => { pane.particles[0].pose = [1, 2, 3] }],
    ['nonrigid pose', pane => { pane.particles[0].pose[0] = 4 }],
    ['unbounded ID', pane => { pane.particles[0].id = 'x'.repeat(257) }],
    ['duplicate particle', pane => { pane.particles.push({ ...pane.particles[0] }) }],
    ['misowned protein atom', pane => { pane.proteins[0].atoms[0].helix_id = '__protein__other' }],
    ['empty protein', pane => { pane.proteins[0].atoms = [] }],
    ['bad bounds', pane => { pane.bounds_nm.minimum[0] = Infinity }],
  ])('refuses %s for the entire comparison', (_label, change) => {
    const packet = comparisonEnvelope(); change(packet.proposed)
    expect(() => validatePartComparisonEnvelope(packet, comparisonBinding())).toThrow()
  })

  it('charges the combined placement and atom totals within each pane', () => {
    const packet = comparisonEnvelope(), particle = packet.published.particles[0]
    packet.published.particles = Array.from({ length: 128 }, (_, index) => ({ ...particle, id: `p${index}` }))
    // 128 particles plus the existing protein exceeds the shared placement cap.
    expect(() => validatePartComparisonEnvelope(packet, comparisonBinding())).toThrow()
    packet.published.particles = []
    const atom = packet.published.proteins[0].atoms[0]
    packet.published.proteins[0].atoms = Array.from({ length: 4097 }, (_, index) => ({ ...atom, serial: index }))
    expect(() => validatePartComparisonEnvelope(packet, comparisonBinding())).toThrow()
  })

  it('admits empty geometry and reports unplaced assets without inventing a placement', () => {
    const packet = comparisonEnvelope()
    packet.published = { units: 'nm', particles: [], proteins: [], bounds_nm: null, unplaced_asset_ids: ['unused'] }
    expect(validatePartComparisonEnvelope(packet, comparisonBinding()).published.bounds_nm).toBeNull()
  })
})
