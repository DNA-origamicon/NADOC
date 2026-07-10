import { describe, it, expect } from 'vitest'
import {
  statusLineText, recommendationDialogCopy, dialogChoices, translateOxdnaToLammps,
} from './simulate_policy.js'

describe('statusLineText', () => {
  it('GPU free → oxDNA/GPU, fastest', () => {
    const s = statusLineText({
      gpu: { available: true, busy: false }, free_cores: 16,
      recommendation: { engine: 'oxdna', backend: 'CUDA' }, has_proteins: false,
    })
    expect(s).toMatch(/GPU: free/)
    expect(s).toMatch(/16 cores free/)
    expect(s).toMatch(/oxDNA \(GPU\)/)
    expect(s).toMatch(/fastest/)
  })
  it('GPU busy → LAMMPS/CPU fallback, names the holder', () => {
    const s = statusLineText({
      gpu: { available: true, busy: true, holder_name: 'namd3' }, free_cores: 12,
      recommendation: { engine: 'lammps', backend: 'CPU' },
    })
    expect(s).toMatch(/busy \(namd3\)/)
    expect(s).toMatch(/LAMMPS \(CPU\)/)
    expect(s).toMatch(/CPU fallback/)
  })
  it('proteins → required-for-proteins', () => {
    const s = statusLineText({
      gpu: { available: true, busy: false }, free_cores: 8,
      recommendation: { engine: 'oxdna', backend: 'CUDA' }, has_proteins: true,
    })
    expect(s).toMatch(/required for proteins/)
  })
  it('no GPU → unknown, singular core', () => {
    const s = statusLineText({ gpu: { available: false }, free_cores: 1,
      recommendation: { engine: 'oxdna', backend: 'CUDA' } })
    expect(s).toMatch(/GPU: unknown/)
    expect(s).toMatch(/1 core free/)
  })
})

describe('recommendationDialogCopy', () => {
  it('includes hog, ETA, slowdown and cores when known', () => {
    const { title, message } = recommendationDialogCopy({
      hogName: 'namd3', etaSeconds: 425, slowdownFactor: 47, freeCores: 12 })
    expect(title).toMatch(/GPU is busy/)
    expect(message).toMatch(/namd3/)
    expect(message).toMatch(/7m 5s remaining/)
    expect(message).toMatch(/47× slower/)
    expect(message).toMatch(/12 cores/)
  })
  it('says "unknown" when ETA is absent (external hog)', () => {
    const { message } = recommendationDialogCopy({ hogName: 'blender', slowdownFactor: 13, freeCores: 4 })
    expect(message).toMatch(/time remaining unknown/)
  })
})

describe('dialogChoices', () => {
  it('offers cpu (recommended, first) / gpu / cancel', () => {
    const c = dialogChoices()
    expect(c.map((x) => x.value)).toEqual(['cpu', 'gpu', 'cancel'])
    expect(c[0].variant).toBe('success')
    expect(c[1].variant).toBe('danger')
  })
})

describe('translateOxdnaToLammps', () => {
  it('maps steps/salt, sets reduced T + cores, and maps oxDNA forces → LAMMPS shape', () => {
    const p = translateOxdnaToLammps({
      oxdnaForm: { mdRelaxSteps: 5000, salt: 0.3 },
      forces: {
        field: { field_pN: 20, dir: [1, 0, 0], enabled: true },
        surface: { dir: [0, 1, 0], offsetNm: 0.5, stiff: 5 },   // oxDNA shape (offsetNm)
        anchors: [{ kind: 'strand', id: 's1' }],
      },
      freeCores: 12,
    })
    expect(p).toMatchObject({ steps: 5000, salt: 0.3, temperature: 0.1, cores: 12, ranks: 12 })
    expect(p.field).toEqual({ field_pN: 20, dir: [1, 0, 0] })
    expect(p.wall).toEqual({ dir: [0, 1, 0], offset_nm: 0.5, stiff: 5 })   // surface→wall, offsetNm→offset_nm
    expect(p.anchors).toEqual([{ kind: 'strand', id: 's1' }])
  })
  it('drops a zero-magnitude field / zero-stiffness surface / empty anchors', () => {
    const p = translateOxdnaToLammps({
      forces: { field: { field_pN: 0, dir: [1, 0, 0] }, surface: { dir: [0, 1, 0], offsetNm: 0.5, stiff: 0 }, anchors: [] },
    })
    expect(p.field).toBeNull()
    expect(p.wall).toBeNull()
    expect(p.anchors).toBeNull()
  })
  it('applies defaults for empty input', () => {
    const p = translateOxdnaToLammps({})
    expect(p).toMatchObject({ steps: 100000, salt: 0.5, temperature: 0.1, cores: 1 })
  })
})
