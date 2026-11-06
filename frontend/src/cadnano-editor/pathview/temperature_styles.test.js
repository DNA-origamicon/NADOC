import { expect, it } from 'vitest'
import { createTemperatureStyles } from './temperature_styles.js'
import { temperatureColor } from '../../scene/staple_temperature_colors.js'
import { domainMeltingTemperature } from '../../scene/staple_temperature.js'
const d = (start, end, direction) => ({ helix_id: 'h', start_bp: start, end_bp: end, direction })
function fixture() { return { helices: [{ id: 'h' }], strands: [
  { id: 'sc', strand_type: 'scaffold', domains: [d(0, 31, 'FORWARD')] },
  { id: 's', strand_type: 'staple', domains: [d(15, 0, 'REVERSE'), d(31, 16, 'REVERSE')], sequence: 'A'.repeat(16) + 'G'.repeat(16) },
] } }
it('uses the shared Celsius palette per domain and uniform whole-staple colors', () => {
  const design = fixture(), original = JSON.stringify(design), styles = createTemperatureStyles()
  styles.prepare(design, 'domain')
  expect(styles.domain(1, 0).color).toBe('#' + temperatureColor(domainMeltingTemperature('A'.repeat(16))).toString(16).padStart(6, '0'))
  expect(styles.domain(1, 0)).not.toEqual(styles.domain(1, 1))
  expect(styles.site(1, { helix_id: 'h', index: 20, strand: 'REVERSE' })).toEqual(styles.domain(1, 1))
  expect(styles.domain(0, 0)).toBeNull()
  expect(styles.strand(1).color).toBe('#808080')
  styles.prepare(design, 'total')
  expect(styles.domain(1, 0)).toEqual(styles.domain(1, 1))
  expect(styles.strand(1)).toEqual(styles.domain(1, 1))
  styles.prepare(design, 'off'); expect(styles.domain(1, 0)).toBeNull()
  expect(JSON.stringify(design)).toBe(original)
})
it('refreshes on edits, with gray for unassigned DNA and no overlay for references', () => {
  const styles = createTemperatureStyles(), design = fixture()
  styles.prepare(design, 'domain')
  const next = { ...design, strands: design.strands.map(s => ({ ...s, sequence: null })) }
  styles.prepare(next, 'domain'); expect(styles.domain(1, 0).color).toBe('#808080')
  styles.prepare({ ...next, strands: next.strands.map(s => ({ ...s, is_reference: true })) }, 'domain')
  expect(styles.domain(1, 0)).toBeNull()
})

it('applies new bounds without replacing the design or losing unknown colors', () => {
  const styles = createTemperatureStyles(), design = fixture()
  styles.prepare(design, 'domain')
  const before = styles.domain(1, 0).color
  styles.prepare(design, 'domain', { lo: 80, hi: 90 })
  expect(styles.domain(1, 0).color).not.toBe(before)
  expect(styles.strand(1).color).toBe('#808080')
})
