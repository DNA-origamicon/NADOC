import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'
import { initMdEngines } from './md_engines.js'

// A status payload: oxDNA missing (auto-buildable on a GPU box), NAMD missing
// (download), gromacs installed.
function status({ oxdnaInstalled = false, arbdBuilt = false } = {}) {
  return {
    gpu: { present: true, names: ['RTX 2080'], toolkit: true, arch: '75' },
    toolchain: { git: true, cmake: true, make: true, cxx: true, nvcc: true },
    wsl: true,
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
      mrdna: { key: 'mrdna', name: 'mrDNA', purpose: 'CG relax.', installed: false, path: null, install: { method: 'auto', can_auto: true, target: 'CPU', commands: ['./scripts/setup-mrdna.sh'], downloads: [], missing_prereqs: [], note: 'python install' } },
      arbd: { key: 'arbd', name: 'ARBD', purpose: 'GPU BD engine.', installed: false, path: null, required_note: arbdBuilt ? 'Built on the Linux side but not installed yet — finish below.' : 'Needs the CUDA toolkit to build.', install: { method: 'download', can_auto: false, target: 'CUDA', wsl: true, built_path: arbdBuilt ? '/home/u/arbd-src/build/arbd' : null, can_finish_built: arbdBuilt, commands: ['sudo make install'], downloads: [{ label: 'ARBD download (register + accept license)', url: 'https://www.ks.uiuc.edu/Development/Download/download.cgi?PackageName=ARBD' }], doc: 'docs/mrdna_setup.md', missing_prereqs: arbdBuilt ? [] : ['CUDA toolkit (nvcc)'], note: 'download then build' } },
      cuda: { key: 'cuda', name: 'CUDA toolkit', purpose: 'GPU compiler.', installed: false, path: null, install: { method: 'guided', can_auto: false, target: 'CUDA', commands: ['sudo apt-get install -y nvidia-cuda-toolkit'], downloads: [{ label: 'CUDA Toolkit (NVIDIA)', url: 'https://developer.nvidia.com/cuda-downloads' }], doc: 'docs/mrdna_setup.md', missing_prereqs: [], note: 'needs admin password' } },
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

function makeApi(payload, listing = null) {
  const dflt = { cwd: '/mnt/c/Users/joshu/Downloads', parent: '/mnt/c/Users/joshu', error: '', entries: [] }
  return {
    enginesStatus: vi.fn().mockResolvedValue(payload),
    browseFiles: vi.fn().mockResolvedValue(listing || dflt),
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

  it('download popup offers a Browse… folder picker + Check & install', async () => {
    const api = makeApi(status())
    const eng = initMdEngines({ api })
    await eng.showStatusModal()
    ;[...document.querySelectorAll('.modal__overlay button')].find(b => b.textContent === 'Download…').click()

    const instr = [...document.querySelectorAll('.modal__overlay')].pop()
    expect(instr.textContent).toMatch(/Already downloaded it\?/)
    expect(instr.querySelector('input[type="text"]')).toBeTruthy()
    const btns = [...instr.querySelectorAll('button')].map(b => b.textContent)
    expect(btns).toContain('Browse…')
    expect(btns).toContain('Check & install')
  })

  it('Browse… opens the folder navigator (calls browseFiles) and a picked file fills the input', async () => {
    const listing = {
      cwd: '/mnt/c/Users/joshu/Downloads', parent: '/mnt/c/Users/joshu', error: '',
      entries: [
        { name: 'sub', path: '/mnt/c/Users/joshu/Downloads/sub', is_dir: true, size: 0, mtime: 1, matches: false },
        { name: 'NAMD_3.0.2_Linux-x86_64-multicore-CUDA.tar.gz', path: '/mnt/c/Users/joshu/Downloads/NAMD.tar.gz', is_dir: false, size: 2570, mtime: 2, matches: true },
      ],
    }
    const api = makeApi(status(), listing)
    const eng = initMdEngines({ api })
    await eng.showStatusModal()
    ;[...document.querySelectorAll('.modal__overlay button')].find(b => b.textContent === 'Download…').click()
    const instr = [...document.querySelectorAll('.modal__overlay')].pop()
    ;[...instr.querySelectorAll('button')].find(b => b.textContent === 'Browse…').click()
    await Promise.resolve(); await Promise.resolve()

    expect(api.browseFiles).toHaveBeenCalledWith(null, 'namd')   // opens at Downloads, namd highlight
    const picker = [...document.querySelectorAll('.modal__overlay')].pop()
    expect(picker.textContent).toMatch(/NAMD_3.0.2/)
    // click the file row (the clickable one, style cursor:pointer) → picker closes
    // and the install-block input is filled
    const fileRow = [...picker.querySelectorAll('div')].find(d => /NAMD_3.0.2/.test(d.textContent) && (d.getAttribute('style') || '').includes('cursor:pointer'))
    fileRow.click()
    expect(instr.querySelector('input[type="text"]').value).toBe('/mnt/c/Users/joshu/Downloads/NAMD.tar.gz')
  })
})

describe('initMdEngines — mrDNA / ARBD / CUDA rows', () => {
  it('renders the three new pipeline engines with the right actions', async () => {
    const eng = initMdEngines({ api: makeApi(status()) })
    await eng.showStatusModal()
    const root = openModalRoot()
    expect(root.textContent).toMatch(/mrDNA/)
    expect(root.textContent).toMatch(/ARBD/)
    expect(root.textContent).toMatch(/CUDA toolkit/)
    const buttons = [...root.querySelectorAll('button')].map(b => b.textContent)
    expect(buttons).toContain('Install (CPU)')     // mrdna auto
    expect(buttons.filter(b => b === 'Download…').length).toBeGreaterThanOrEqual(2)  // namd + arbd
    expect(buttons).toContain('How to install…')   // cuda guided
  })

  it('ARBD download popup shows the KS link and Browse… opens the picker with kind=arbd', async () => {
    const listing = {
      cwd: '/mnt/c/Users/joshu/Downloads', parent: '/mnt/c/Users/joshu', error: '',
      entries: [{ name: 'arbd-may24-beta.tar.gz', path: '/mnt/c/Users/joshu/Downloads/arbd-may24-beta.tar.gz', is_dir: false, size: 386754, mtime: 9, matches: true }],
    }
    const api = makeApi(status(), listing)
    const eng = initMdEngines({ api })
    await eng.showStatusModal()
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null)

    // the ARBD row's Download… button — two 'Download…' exist now (namd + arbd), so
    // climb each to its engine-row and pick the one that names ARBD.
    const rowOf = (btn) => {
      let n = btn
      while (n) {
        if (n.getAttribute && (n.getAttribute('style') || '').includes('border-bottom:1px solid #21262d')) return n
        n = n.parentElement
      }
      return null
    }
    const arbdBtn = [...document.querySelectorAll('.modal__overlay button')]
      .filter(b => b.textContent === 'Download…')
      .find(b => { const r = rowOf(b); return r && r.textContent.includes('ARBD') })
    arbdBtn.click()

    const instr = [...document.querySelectorAll('.modal__overlay')].pop()
    const link = [...instr.querySelectorAll('button')].find(b => /ARBD download/.test(b.textContent))
    expect(link).toBeTruthy()
    link.click()
    expect(openSpy).toHaveBeenCalledWith('https://www.ks.uiuc.edu/Development/Download/download.cgi?PackageName=ARBD', '_blank', 'noopener')

    // Browse… opens the folder navigator scoped to arbd, then a pick fills the input
    ;[...instr.querySelectorAll('button')].find(b => b.textContent === 'Browse…').click()
    await Promise.resolve(); await Promise.resolve()
    expect(api.browseFiles).toHaveBeenCalledWith(null, 'arbd')
    const picker = [...document.querySelectorAll('.modal__overlay')].pop()
    const fileRow = [...picker.querySelectorAll('div')].find(d => /arbd-may24-beta/.test(d.textContent) && (d.getAttribute('style') || '').includes('cursor:pointer'))
    fileRow.click()
    expect(instr.querySelector('input[type="text"]').value).toBe('/mnt/c/Users/joshu/Downloads/arbd-may24-beta.tar.gz')
    openSpy.mockRestore()
  })

  it('WSL banner shows in the status modal', async () => {
    const eng = initMdEngines({ api: makeApi(status()) })
    await eng.showStatusModal()
    expect(openModalRoot().textContent).toMatch(/Running in WSL/)
  })

  it('ARBD built-but-not-installed offers no-password finish + run-with-password', async () => {
    const api = makeApi(status({ arbdBuilt: true }))
    const eng = initMdEngines({ api })
    await eng.showStatusModal()
    // ARBD row now shows the finish hint in its required_note
    expect(openModalRoot().textContent).toMatch(/not installed yet/)

    // open the ARBD instructions popup
    const rowOf = (btn) => { let n = btn; while (n) { if (n.getAttribute && (n.getAttribute('style') || '').includes('border-bottom:1px solid #21262d')) return n; n = n.parentElement } return null }
    const arbdBtn = [...document.querySelectorAll('.modal__overlay button')]
      .filter(b => b.textContent === 'Download…')
      .find(b => { const r = rowOf(b); return r && r.textContent.includes('ARBD') })
    arbdBtn.click()

    const instr = [...document.querySelectorAll('.modal__overlay')].pop()
    const btns = [...instr.querySelectorAll('button')].map(b => b.textContent)
    expect(btns).toContain('Finish install (no password)')
    expect(btns.some(b => /uses your password/.test(b))).toBe(true)

    // the password path opens a small password prompt
    ;[...instr.querySelectorAll('button')].find(b => /uses your password/.test(b.textContent)).click()
    const pwModal = [...document.querySelectorAll('.modal__overlay')].pop()
    expect(pwModal.querySelector('input[type="password"]')).toBeTruthy()
    expect(pwModal.textContent).toMatch(/not saved/)
  })
})
