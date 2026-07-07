import { describe, it, expect } from 'vitest'
import {
  ENGINE_ORDER, gpuSummary, actionKind, actionLabel, commandText, statusTone,
  sectionSummary, gateMessage, degradedNote,
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
  it('degraded (installed but CPU-only on a GPU box) offers a rebuild, not "Installed"', () => {
    const e = engine({ installed: true, degraded: true })   // carries an auto CUDA plan
    expect(actionKind(e)).toBe('auto')
    expect(actionLabel(e)).toBe('Rebuild for GPU (CUDA)')
  })
  it('degraded with auto blocked → guided "Enable GPU…"', () => {
    const e = engine({ installed: true, degraded: true,
      install: { method: 'auto', can_auto: false, target: 'CUDA', commands: ['x'] } })
    expect(actionKind(e)).toBe('guided')
    expect(actionLabel(e)).toBe('Enable GPU…')
  })
  it('degraded rebuild wording is overridable by the plan (LAMMPS = CG-DNA, not GPU)', () => {
    const auto = engine({ key: 'lammps_oxdna', installed: true, degraded: true,
      install: { method: 'auto', can_auto: true, target: 'CPU', commands: ['x'],
        degraded_action_label: 'Rebuild with CG-DNA', degraded_guided_label: 'Add CG-DNA…' } })
    expect(actionLabel(auto)).toBe('Rebuild with CG-DNA')       // not "Rebuild for GPU"
    const guided = engine({ key: 'lammps_oxdna', installed: true, degraded: true,
      install: { method: 'auto', can_auto: false, target: 'CPU', commands: ['x'],
        degraded_action_label: 'Rebuild with CG-DNA', degraded_guided_label: 'Add CG-DNA…' } })
    expect(actionLabel(guided)).toBe('Add CG-DNA…')             // not "Enable GPU…"
  })
})

describe('degradedNote', () => {
  it('returns the note only when degraded', () => {
    expect(degradedNote(engine({ installed: true, degraded: true, degraded_note: 'rebuild me' }))).toBe('rebuild me')
    expect(degradedNote(engine({ installed: true, degraded_note: 'x' }))).toBe('')   // not degraded
    expect(degradedNote(engine({ installed: true }))).toBe('')
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
  it('degraded → warn (installed but not full-speed)', () => {
    expect(statusTone(engine({ installed: true, degraded: true }))).toBe('warn')
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

describe('new pipeline engines (mrdna / arbd / cuda)', () => {
  it('ENGINE_ORDER includes the three new rows', () => {
    for (const k of ['mrdna', 'arbd', 'cuda']) expect(ENGINE_ORDER).toContain(k)
  })
  it('mrdna is a one-click auto install', () => {
    const e = { key: 'mrdna', name: 'mrDNA', installed: false,
      install: { method: 'auto', can_auto: true, target: 'CPU', commands: ['./scripts/setup-mrdna.sh'] } }
    expect(actionKind(e)).toBe('auto')
    expect(actionLabel(e)).toBe('Install (CPU)')
  })
  it('arbd is a download', () => {
    const e = { key: 'arbd', name: 'ARBD', installed: false,
      install: { method: 'download', can_auto: false, commands: [] } }
    expect(actionKind(e)).toBe('download')
    expect(actionLabel(e)).toBe('Download…')
  })
  it('cuda is guided', () => {
    const e = { key: 'cuda', name: 'CUDA toolkit', installed: false,
      install: { method: 'guided', can_auto: false, commands: ['sudo apt-get install -y nvidia-cuda-toolkit'] } }
    expect(actionKind(e)).toBe('guided')
    expect(actionLabel(e)).toBe('How to install…')
  })
})
