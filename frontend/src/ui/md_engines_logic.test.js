import { describe, it, expect } from 'vitest'
import {
  gpuSummary, actionKind, actionLabel, commandText, statusTone,
  sectionSummary, gateMessage, namdScanSummary,
} from './md_engines_logic.js'

const engine = (over = {}) => ({
  key: 'oxdna', name: 'oxDNA', installed: false,
  install: { method: 'auto', can_auto: true, target: 'CUDA', commands: ['a', 'b'] },
  ...over,
})

describe('gpuSummary', () => {
  it('no gpu', () => {
    expect(gpuSummary({ present: false })).toMatch(/No CUDA GPU/)
  })
  it('gpu without toolkit steers to installing nvcc', () => {
    const s = gpuSummary({ present: true, names: ['RTX 2080'], toolkit: false })
    expect(s).toMatch(/RTX 2080/)
    expect(s).toMatch(/nvcc/)
  })
  it('gpu with toolkit', () => {
    expect(gpuSummary({ present: true, names: ['RTX'], toolkit: true })).toMatch(/GPU builds available/)
  })
})

describe('actionKind / actionLabel', () => {
  it('installed', () => {
    expect(actionKind(engine({ installed: true }))).toBe('installed')
    expect(actionLabel(engine({ installed: true }))).toBe('Installed')
  })
  it('auto when can_auto', () => {
    expect(actionKind(engine())).toBe('auto')
    expect(actionLabel(engine())).toBe('Install (CUDA)')
  })
  it('auto blocked by missing prereqs falls to guided', () => {
    const e = engine({ install: { method: 'auto', can_auto: false, target: 'CUDA', commands: [] } })
    expect(actionKind(e)).toBe('guided')
    expect(actionLabel(e)).toBe('How to install…')
  })
  it('download', () => {
    const e = engine({ install: { method: 'download', can_auto: false, commands: [] } })
    expect(actionKind(e)).toBe('download')
    expect(actionLabel(e)).toBe('Download…')
  })
})

describe('commandText', () => {
  it('joins commands with newlines', () => {
    expect(commandText(engine())).toBe('a\nb')
  })
  it('empty when no plan', () => {
    expect(commandText(engine({ installed: true, install: null }))).toBe('')
  })
})

describe('statusTone', () => {
  it('installed → ok', () => expect(statusTone(engine({ installed: true }))).toBe('ok'))
  it('missing required → err', () => expect(statusTone(engine())).toBe('err'))
  it('missing bundled → warn', () => {
    expect(statusTone(engine({ required_note: 'Bundled with oxDNA; building oxDNA provides it.' }))).toBe('warn')
  })
})

describe('sectionSummary / gateMessage', () => {
  const status = {
    engines: { namd: { name: 'NAMD 3' }, gromacs: { name: 'GROMACS' } },
    sections: {
      oxdna: { required: ['oxdna'], ready: true, missing: [] },
      md: { required: ['namd', 'gromacs'], ready: false, missing: ['namd', 'gromacs'] },
    },
  }
  it('ready section', () => {
    expect(sectionSummary(status, 'oxdna')).toEqual({ ready: true, missing: [] })
    expect(gateMessage(status, 'oxdna')).toBe('')
  })
  it('not-ready section names the missing engines', () => {
    const s = sectionSummary(status, 'md')
    expect(s.ready).toBe(false)
    expect(s.missing.map(m => m.name)).toEqual(['NAMD 3', 'GROMACS'])
    expect(gateMessage(status, 'md')).toBe('NAMD 3 + GROMACS are not installed.')
  })
  it('missing section key defaults ready', () => {
    expect(sectionSummary({}, 'oxdna')).toEqual({ ready: true, missing: [] })
  })
})

describe('namdScanSummary', () => {
  it('no candidates → not found, guidance message', () => {
    const s = namdScanSummary({ candidates: [], best: null })
    expect(s.found).toBe(false)
    expect(s.path).toBe('')
    expect(s.message).toMatch(/No NAMD download/)
  })
  it('uses best candidate, prefilling path and reporting build', () => {
    const best = { filename: 'NAMD_3.0.2_Linux-x86_64-multicore-CUDA.tar.gz', build: 'CUDA', path: '/home/u/Downloads/x.tar.gz', warning: '' }
    const s = namdScanSummary({ candidates: [best], best })
    expect(s.found).toBe(true)
    expect(s.path).toBe('/home/u/Downloads/x.tar.gz')
    expect(s.message).toMatch(/Found .*CUDA build/)
  })
  it('surfaces a CPU-on-GPU warning', () => {
    const best = { filename: 'NAMD_3.0.2_Linux-x86_64-multicore.tar.gz', build: 'CPU', path: '/d/x.tar.gz', warning: 'This is the CPU build, but RTX 2080 was detected' }
    expect(namdScanSummary({ candidates: [best], best }).message).toMatch(/CPU build, but RTX 2080/)
  })
})
