import { expect, it } from 'vitest'
import { decodeDnaComparisonRecords, decodeDnaComparisonRecordsCopy, visitDnaComparisonScalars } from './part_dna_comparison_codec.js'
import { dnaComponent } from '../test-helpers/part_dna_comparison.js'

it('copying decode equals structuredClone of the decoded rows and shares nothing', () => {
  const rows = dnaComponent().nucleotides
  const copied = decodeDnaComparisonRecordsCopy(rows)
  expect(copied).toEqual(structuredClone(decodeDnaComparisonRecords(rows)))
  copied[0].backbone_position[0] = 99
  copied[0].helical_site.axis_point[0] = 99
  copied[0].helical_site.azimuth_rad = 99
  expect(rows[0][4][0]).not.toBe(99)
  expect(rows[0][9].axis_point[0]).not.toBe(99)
  expect(rows[0][9].azimuth_rad).not.toBe(99)
})

it('copying decode refuses malformed transport like the plain decoder', () => {
  expect(() => decodeDnaComparisonRecordsCopy([[1, 2]])).toThrow(/fixed-row/)
  expect(() => decodeDnaComparisonRecordsCopy({})).toThrow(/compact native DNA transport/)
  expect(() => decodeDnaComparisonRecordsCopy('rows')).toThrow(/allowance/)
})

// Test-side packer mirroring backend pack_records_compact (little-endian float64).
import { COMPACT_ENCODING, DNA_RECORD_COLUMNS, SCALAR_COLUMNS } from './part_dna_comparison_codec.js'
import { validateDeformationPreviewComponent } from './part_dna_comparison_model.js'
function compact(rows) {
  const records = decodeDnaComparisonRecords(rows), values = []
  for (const r of records) {
    for (const f of ['backbone_position', 'base_position', 'base_normal', 'axis_tangent', 'slab_position', 'slab_quaternion']) values.push(...r[f])
    const s = r.helical_site
    values.push(...s.axis_point, ...s.radial_hat, s.azimuth_rad, s.groove_offset_rad, s.phase_roll_rad)
  }
  const bytes = new Uint8Array(new Float64Array(values).buffer)
  let binary = ''; for (const b of bytes) binary += String.fromCharCode(b)
  return { encoding: COMPACT_ENCODING, count: records.length, rows: records.map(r => SCALAR_COLUMNS.map(c => r[c])), f64: btoa(binary) }
}

it('compact float64 transport decodes to exactly the row records', () => {
  const rows = dnaComponent().nucleotides
  expect(decodeDnaComparisonRecords(compact(rows))).toEqual(decodeDnaComparisonRecords(rows))
  expect(decodeDnaComparisonRecordsCopy(compact(rows))).toEqual(decodeDnaComparisonRecords(rows))
  expect(Object.keys(decodeDnaComparisonRecords(compact(rows))[0])).toEqual([...DNA_RECORD_COLUMNS])
})

it('the layer takes the validator decode once, then decodes afresh', () => {
  const value = compact(dnaComponent().nucleotides)
  const validated = decodeDnaComparisonRecords(value)
  expect(decodeDnaComparisonRecordsCopy(value)).toBe(validated)
  const again = decodeDnaComparisonRecordsCopy(value)
  expect(again).not.toBe(validated); expect(again).toEqual(validated)
})

it('refuses malformed compact transport', () => {
  const good = compact(dnaComponent().nucleotides)
  for (const bad of [{ ...good, encoding: 'other' }, { ...good, count: good.count + 1 }, { ...good, f64: good.f64.slice(8) },
    { ...good, rows: good.rows.map(r => r.slice(1)) }, { ...good, extra: 1 }, { ...good, f64: '!!!' }])
    expect(() => decodeDnaComparisonRecords(bad)).toThrow(/compact native DNA transport/)
})

it('preview v3 requires the compact block and v2 the rows', () => {
  const v2 = { ...dnaComponent(), component_kind: 'deformation-preview-dna', component_version: 2 }
  delete v2.component_version; v2.component_version = 2
  const v3 = { ...v2, component_version: 3, nucleotides: compact(v2.nucleotides) }
  expect(validateDeformationPreviewComponent(v3)).toBe(v3)
  expect(() => validateDeformationPreviewComponent({ ...v3, nucleotides: v2.nucleotides })).toThrow(/version/)
  expect(() => validateDeformationPreviewComponent({ ...v2, nucleotides: v3.nucleotides })).toThrow(/version/)
})

it('rejects every nonfinite compact coordinate and site angle before constructing records', () => {
  const good = compact(dnaComponent().nucleotides)
  for (let index = 0; index < 28; index++) for (const invalid of [NaN, Infinity, -Infinity]) {
    const bytes = Uint8Array.from(atob(good.f64), c => c.charCodeAt(0))
    new DataView(bytes.buffer).setFloat64(index * 8, invalid, true)
    const bad = { ...good, f64: btoa(String.fromCharCode(...bytes)) }
    const component = { ...dnaComponent(), component_kind: 'deformation-preview-dna', component_version: 3, nucleotides: bad }
    expect(() => validateDeformationPreviewComponent(component)).toThrow(/nonfinite/)
    expect(() => decodeDnaComparisonRecordsCopy(bad)).toThrow(/nonfinite/)
  }
})

it('reuses exact inventories without allocating coordinate arrays and preserves native values', () => {
  const rows = dnaComponent().nucleotides
  const spare = decodeDnaComparisonRecordsCopy(compact(rows))
  const positions = spare.map(r => r.backbone_position)
  const sites = spare.map(r => r.helical_site.axis_point)
  const changed = structuredClone(rows)
  for (const row of changed) {
    row[4][0] += 12.25
    row[9].axis_point[2] -= 3.5
    row[9].phase_roll_rad += 0.75
  }
  const packet = compact(changed)
  visitDnaComparisonScalars(packet, () => {})
  expect(decodeDnaComparisonRecordsCopy(packet, spare)).toBe(spare)
  expect(spare).toEqual(decodeDnaComparisonRecords(changed))
  spare.forEach((r, i) => {
    expect(r.backbone_position).toBe(positions[i])
    expect(r.helical_site.axis_point).toBe(sites[i])
  })
})

it('leaves the spare untouched on inventory mismatch or nonfinite coordinates', () => {
  const packet = compact(dnaComponent().nucleotides)
  const spare = decodeDnaComparisonRecordsCopy(packet)
  const original = structuredClone(spare)
  const changed = structuredClone(packet)
  changed.rows[0][SCALAR_COLUMNS.indexOf('is_reference')] = !spare[0].is_reference
  expect(decodeDnaComparisonRecordsCopy(changed, spare)).not.toBe(spare)
  expect(spare).toEqual(original)
  const bytes = Uint8Array.from(atob(packet.f64), c => c.charCodeAt(0))
  new DataView(bytes.buffer).setFloat64(bytes.length - 8, NaN, true)
  expect(() => decodeDnaComparisonRecordsCopy({ ...packet, f64: btoa(String.fromCharCode(...bytes)) }, spare)).toThrow(/nonfinite/)
  expect(spare).toEqual(original)
})

it('scalar validation supersedes an earlier decoded packet', () => {
  const packet = compact(dnaComponent().nucleotides)
  const old = decodeDnaComparisonRecords(packet)
  packet.rows[0][SCALAR_COLUMNS.indexOf('is_reference')] = !old[0].is_reference
  visitDnaComparisonScalars(packet, () => {})
  expect(decodeDnaComparisonRecordsCopy(packet)[0].is_reference).toBe(!old[0].is_reference)
  expect(() => visitDnaComparisonScalars(null, () => {})).toThrow(/compact native DNA transport/)
})
