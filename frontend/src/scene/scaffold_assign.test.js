import { describe, it, expect } from 'vitest'
import { ascWarningText, SCAFFOLD_LENGTHS } from './scaffold_assign.js'

describe('SCAFFOLD_LENGTHS', () => {
  it('has the known scaffold lengths', () => {
    expect(SCAFFOLD_LENGTHS.M13mp18).toBe(7249)
    expect(SCAFFOLD_LENGTHS.p8064).toBe(8064)
  })
})

describe('ascWarningText', () => {
  it('warns when a custom sequence is shorter than the scaffold', () => {
    const t = ascWarningText({ customRaw: 'ACGT', totalNt: 10 })
    expect(t).toContain('Custom sequence (4 nt)')
    expect(t).toContain('6 bases will be assigned')
  })
  it('no warning when the custom sequence is long enough', () => {
    expect(ascWarningText({ customRaw: 'A'.repeat(10), totalNt: 10 })).toBeNull()
  })
  it('warns when scaffold exceeds the chosen reference (no custom seq)', () => {
    const t = ascWarningText({ customRaw: '', totalNt: 7300, scaffoldName: 'M13mp18', scaffoldLen: 7249 })
    expect(t).toContain('Scaffold (7300 nt) exceeds M13mp18 (7249 nt)')
    expect(t).toContain("51 bases will be assigned 'N'")
  })
  it('no warning when scaffold fits the reference', () => {
    expect(ascWarningText({ customRaw: '', totalNt: 5000, scaffoldLen: 7249 })).toBeNull()
  })
  it('custom-seq branch ignores scaffold length', () => {
    // Custom present + long enough → null even though scaffold would otherwise warn.
    expect(ascWarningText({ customRaw: 'A'.repeat(9000), totalNt: 8000, scaffoldLen: 100 })).toBeNull()
  })
})
