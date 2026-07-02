import { describe, it, expect } from 'vitest'
import { exportChoiceFiles } from './metric_export_modal.js'

describe('exportChoiceFiles', () => {
  it('maps a choice to the artefacts to emit', () => {
    expect(exportChoiceFiles({ png: true, data: true })).toEqual(['png', 'data'])
    expect(exportChoiceFiles({ png: true, data: false })).toEqual(['png'])
    expect(exportChoiceFiles({ png: false, data: true })).toEqual(['data'])
    expect(exportChoiceFiles({ png: false, data: false })).toEqual([])
    expect(exportChoiceFiles(null)).toEqual([])
  })
})
