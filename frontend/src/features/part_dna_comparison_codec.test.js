import { expect, it } from 'vitest'
import { decodeDnaComparisonRecords, decodeDnaComparisonRecordsCopy } from './part_dna_comparison_codec.js'
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
