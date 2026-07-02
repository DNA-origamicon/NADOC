import { describe, it, expect, vi } from 'vitest'
import { runOverhangGen, reverseComplement } from './overhang_gen.js'

function makeDeps(seqMap, showChoice) {
  const api = {
    // A "new random" sequence for the target (deterministic for the test).
    generateOverhangRandomSequence: vi.fn(async (id) => { seqMap[id] = 'GGGGCCCC' }),
    patchOverhang: vi.fn(async (id, { sequence }) => { seqMap[id] = sequence }),
  }
  return { api, getSeq: (id) => seqMap[id] ?? null, showChoice }
}

describe('reverseComplement', () => {
  it('antiparallel WC, uppercased', () => {
    expect(reverseComplement('AAAC')).toBe('GTTT')
    expect(reverseComplement('acgt')).toBe('ACGT')
    expect(reverseComplement('N')).toBe('N')
  })
})

describe('runOverhangGen', () => {
  it('no partner → generate a random sequence for this overhang', async () => {
    const d = makeDeps({ a: null })
    await runOverhangGen('a', null, d)
    expect(d.api.generateOverhangRandomSequence).toHaveBeenCalledWith('a')
    expect(d.api.patchOverhang).not.toHaveBeenCalled()
  })

  it('all-N counts as unsequenced (partner all-N → still random)', async () => {
    const d = makeDeps({ a: null, b: 'NNNN' })
    await runOverhangGen('a', 'b', d)
    expect(d.api.generateOverhangRandomSequence).toHaveBeenCalledWith('a')
  })

  it('partner sequenced, this empty → fill this with RC(partner)', async () => {
    const d = makeDeps({ a: null, b: 'AAAC' })
    await runOverhangGen('a', 'b', d)
    expect(d.api.patchOverhang).toHaveBeenCalledWith('a', { sequence: 'GTTT' })
    expect(d.api.generateOverhangRandomSequence).not.toHaveBeenCalled()
  })

  it('both sequenced → asks; "rc" sets this = RC(partner)', async () => {
    const d = makeDeps({ a: 'TTTT', b: 'AAAC' }, vi.fn(async () => 'rc'))
    await runOverhangGen('a', 'b', d)
    expect(d.showChoice).toHaveBeenCalled()
    expect(d.api.patchOverhang).toHaveBeenCalledWith('a', { sequence: 'GTTT' })
    expect(d.api.generateOverhangRandomSequence).not.toHaveBeenCalled()
  })

  it('"override" → new random for this overhang only', async () => {
    const d = makeDeps({ a: 'TTTT', b: 'AAAC' }, vi.fn(async () => 'override'))
    await runOverhangGen('a', 'b', d)
    expect(d.api.generateOverhangRandomSequence).toHaveBeenCalledWith('a')
    expect(d.api.patchOverhang).not.toHaveBeenCalled()
  })

  it('"pair" → new random for this + set the partner to its RC', async () => {
    const d = makeDeps({ a: 'TTTT', b: 'AAAC' }, vi.fn(async () => 'pair'))
    await runOverhangGen('a', 'b', d)
    expect(d.api.generateOverhangRandomSequence).toHaveBeenCalledWith('a')
    expect(d.api.patchOverhang).toHaveBeenCalledWith('b', { sequence: reverseComplement('GGGGCCCC') })
  })

  it('cancel (null) → no writes', async () => {
    const d = makeDeps({ a: 'TTTT', b: 'AAAC' }, vi.fn(async () => null))
    await runOverhangGen('a', 'b', d)
    expect(d.api.generateOverhangRandomSequence).not.toHaveBeenCalled()
    expect(d.api.patchOverhang).not.toHaveBeenCalled()
  })

  it('uses the injected (register-aware) rcOfPartner for every RC write', async () => {
    // The panels inject overhangRcOfPartner (paired window RC, toehold preserved).
    // Here we stub it to prove runOverhangGen writes exactly what the effect returns.
    const rcOfPartner = vi.fn((_t, _s) => 'CCCCNNNN')   // e.g. RC of a 4-bp window + preserved 4-bp toehold
    const d = { ...makeDeps({ a: null, b: 'AAACGGGG' }), rcOfPartner }
    await runOverhangGen('a', 'b', d)
    expect(rcOfPartner).toHaveBeenCalledWith('a', 'b')
    expect(d.api.patchOverhang).toHaveBeenCalledWith('a', { sequence: 'CCCCNNNN' })
  })

  it('skips the write when rcOfPartner returns null (no backing domain)', async () => {
    const d = { ...makeDeps({ a: null, b: 'AAAC' }), rcOfPartner: () => null }
    await runOverhangGen('a', 'b', d)
    expect(d.api.patchOverhang).not.toHaveBeenCalled()
  })
})
