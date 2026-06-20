import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'
import { initMdEngines } from './md_engines.js'

// A status payload: oxDNA missing (auto-buildable on a GPU box), NAMD missing
// (download), gromacs installed.
function status({ oxdnaInstalled = false } = {}) {
  return {
    gpu: { present: true, names: ['RTX 2080'], toolkit: true, arch: '75' },
    toolchain: { git: true, cmake: true, make: true, cxx: true, nvcc: true },
    engines: {
      oxdna: {
        key: 'oxdna', name: 'oxDNA', purpose: 'CG DNA MD.', installed: oxdnaInstalled,
        path: oxdnaInstalled ? '/home/u/oxDNA/build/bin/oxDNA' : null,
        install: oxdnaInstalled ? null : {
          method: 'auto', can_auto: true, target: 'CUDA',
          commands: ['git clone …', 'make …'], downloads: [], doc: 'docs/oxdna_setup.md',
          missing_prereqs: [], note: 'GPU build',
        },
      },
      namd: {
        key: 'namd', name: 'NAMD 3', purpose: 'All-atom MD.', installed: false, path: null,
        install: {
          method: 'download', can_auto: false, target: 'CUDA', commands: ['tar xf …'],
          downloads: [{ label: 'NAMD download', url: 'https://www.ks.uiuc.edu/Research/namd/' }],
          doc: 'docs/namd_setup.md', missing_prereqs: [], note: 'register + license',
        },
      },
      gromacs: { key: 'gromacs', name: 'GROMACS', purpose: 'Solvation.', installed: true, path: '/usr/bin/gmx', install: null },
      oxdna_anm: { key: 'oxdna_anm', name: 'ANM-oxDNA', purpose: 'Protein fork.', installed: false, required_note: 'Only for proteins.', install: { method: 'auto', can_auto: true, target: 'CUDA', commands: ['x'], downloads: [], missing_prereqs: [] } },
      psfgen: { key: 'psfgen', name: 'psfgen', purpose: 'Topology.', installed: false, required_note: 'Bundled with NAMD; installing NAMD provides it.', install: { method: 'download', can_auto: false, commands: [], downloads: [] } },
      dnanalysis: { key: 'dnanalysis', name: 'DNAnalysis', purpose: 'Health.', installed: true, path: '/o/DNAnalysis', install: null },
    },
    sections: {
      oxdna: { required: ['oxdna'], ready: oxdnaInstalled, missing: oxdnaInstalled ? [] : ['oxdna'] },
      md: { required: ['namd', 'gromacs'], ready: false, missing: ['namd'] },
    },
  }
}

function makeApi(payload, scan = { candidates: [], best: null }) {
  return {
    enginesStatus: vi.fn().mockResolvedValue(payload),
    scanNamdDownload: vi.fn().mockResolvedValue(scan),
  }
}

function openModalRoot() {
  return document.querySelector('.modal__overlay')
}

beforeEach(() => mountIds({ 'oxdna-jobs-body': 'div', 'md-panel-body': 'div' }))
afterEach(() => { clearDom(); document.body.querySelectorAll('.modal__overlay').forEach(n => n.remove()) })

describe('initMdEngines — sidebar gates', () => {
  it('shows a gate for a not-ready section and hides it for a ready one', async () => {
    const eng = initMdEngines({ api: makeApi(status({ oxdnaInstalled: false })) })
    eng.mountSidebarGates()
    await eng.refresh()

    const oxGate = document.getElementById('engines-gate-oxdna')
    const mdGate = document.getElementById('engines-gate-md')
    expect(oxGate.style.display).toBe('')            // oxdna missing → shown
    expect(oxGate.textContent).toMatch(/oxDNA is not installed/)
    expect(mdGate.style.display).toBe('')            // md missing namd → shown
    expect(mdGate.textContent).toMatch(/NAMD 3 is not installed/)
  })

  it('hides the gate once the section becomes ready', async () => {
    const eng = initMdEngines({ api: makeApi(status({ oxdnaInstalled: true })) })
    eng.mountSidebarGates()
    await eng.refresh()
    expect(document.getElementById('engines-gate-oxdna').style.display).toBe('none')
  })
})

describe('initMdEngines — status modal', () => {
  it('lists engines with install actions and a re-check', async () => {
    const api = makeApi(status())
    const eng = initMdEngines({ api })
    await eng.showStatusModal()

    const root = openModalRoot()
    expect(root).toBeTruthy()
    expect(root.textContent).toMatch(/oxDNA/)
    expect(root.textContent).toMatch(/GPU detected \(RTX 2080\)/)
    // installed engine shows ✓; missing shows an action button
    expect(root.textContent).toMatch(/✓ installed/)
    const buttons = [...root.querySelectorAll('button')].map(b => b.textContent)
    expect(buttons).toContain('Install (CUDA)')   // oxdna auto
    expect(buttons).toContain('Download…')         // namd download
    expect(buttons).toContain('Re-check')
  })

  it('download engine opens an instructions popup with the link, not an auto build', async () => {
    const api = makeApi(status())
    const eng = initMdEngines({ api })
    await eng.showStatusModal()
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null)

    const dlBtn = [...document.querySelectorAll('.modal__overlay button')].find(b => b.textContent === 'Download…')
    dlBtn.click()

    // a second modal (instructions) is now present, with the NAMD link button
    const instr = [...document.querySelectorAll('.modal__overlay')].pop()
    expect(instr.textContent).toMatch(/register \+ license/)
    const link = [...instr.querySelectorAll('button')].find(b => /NAMD download/.test(b.textContent))
    expect(link).toBeTruthy()
    link.click()
    expect(openSpy).toHaveBeenCalledWith('https://www.ks.uiuc.edu/Research/namd/', '_blank', 'noopener')
    openSpy.mockRestore()
  })

  it('download popup offers "check download & install" and reports a found file', async () => {
    const found = {
      candidates: [{ filename: 'NAMD_3.0.2_Linux-x86_64-multicore-CUDA.tar.gz', build: 'CUDA', path: '/home/u/Downloads/NAMD.tar.gz', warning: '' }],
      best: { filename: 'NAMD_3.0.2_Linux-x86_64-multicore-CUDA.tar.gz', build: 'CUDA', path: '/home/u/Downloads/NAMD.tar.gz', warning: '' },
    }
    const api = makeApi(status(), found)
    const eng = initMdEngines({ api })
    await eng.showStatusModal()
    ;[...document.querySelectorAll('.modal__overlay button')].find(b => b.textContent === 'Download…').click()

    // let the async scan resolve
    await Promise.resolve(); await Promise.resolve()

    const instr = [...document.querySelectorAll('.modal__overlay')].pop()
    expect(api.scanNamdDownload).toHaveBeenCalled()
    expect(instr.textContent).toMatch(/Already downloaded it\?/)
    expect(instr.textContent).toMatch(/Found NAMD_3.0.2.*CUDA build/)
    const pathInput = instr.querySelector('input[type="text"]')
    expect(pathInput.value).toBe('/home/u/Downloads/NAMD.tar.gz')
    expect([...instr.querySelectorAll('button')].some(b => b.textContent === 'Check & install')).toBe(true)
  })
})
