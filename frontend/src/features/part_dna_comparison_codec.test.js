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
  expect(() => decodeDnaComparisonRecordsCopy({})).toThrow(/allowance/)
})
