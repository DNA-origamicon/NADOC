// @vitest-environment jsdom
import { describe, it, expect, beforeEach } from 'vitest'
import { initEngineActivityHeaders } from './engine_activity_headers.js'

/** Build the engine-selector TABS the way engine_selector.js does (the busy spinner
 *  now hangs on the tab, not a section header). LAMMPS has no tab. */
function buildTabs(doc) {
  for (const key of ['oxdna', 'mrdna', 'cando', 'namd']) {
    const btn = doc.createElement('button')
    btn.className = 'engine-selector-btn'
    btn.dataset.engine = key
    const lbl = doc.createElement('span')
    lbl.className = 'engine-selector-label'
    lbl.textContent = key
    btn.appendChild(lbl)
    doc.body.appendChild(btn)
  }
}

const spinner = (doc, engine) => doc.querySelector(`[data-engine-spinner="${engine}"]`)

describe('initEngineActivityHeaders', () => {
  beforeEach(() => { document.body.innerHTML = '' })

  it('inserts one hidden spinner into each engine tab (no LAMMPS tab)', () => {
    buildTabs(document)
    initEngineActivityHeaders({ fetchActiveJobs: async () => [], doc: document, intervalMs: 999999 })
    for (const e of ['oxdna', 'mrdna', 'cando', 'md']) {
      const sp = spinner(document, e)
      expect(sp).toBeTruthy()
      expect(sp.classList.contains('nadoc-spinner')).toBe(true)
      expect(sp.closest('.engine-selector-btn')).toBeTruthy()   // lives on the tab
      expect(sp.hidden).toBe(true)
    }
    // 'md' hangs on the 'namd' tab; LAMMPS has no tab → no spinner
    expect(spinner(document, 'md').closest('.engine-selector-btn').dataset.engine).toBe('namd')
    expect(spinner(document, 'lammps')).toBeNull()
  })

  it('shows the spinner only for engines with a busy job', async () => {
    buildTabs(document)
    const api = initEngineActivityHeaders({
      doc: document, intervalMs: 999999,
      fetchActiveJobs: async () => [
        { engine: 'md', status: 'running' },
        { engine: 'cando', status: 'preparing' },
      ],
    })
    await api.refresh()
    expect(spinner(document, 'md').hidden).toBe(false)
    expect(spinner(document, 'cando').hidden).toBe(false)
    expect(spinner(document, 'oxdna').hidden).toBe(true)
    expect(spinner(document, 'mrdna').hidden).toBe(true)
  })

  it('hides a spinner again once its engine goes idle', async () => {
    buildTabs(document)
    let jobs = [{ engine: 'md', status: 'running' }]
    const api = initEngineActivityHeaders({
      doc: document, intervalMs: 999999, fetchActiveJobs: async () => jobs,
    })
    await api.refresh()
    expect(spinner(document, 'md').hidden).toBe(false)
    jobs = []
    await api.refresh()
    expect(spinner(document, 'md').hidden).toBe(true)
  })

  it('does not throw when a tab is missing from the DOM', async () => {
    // only build the oxdna tab
    const btn = document.createElement('button')
    btn.className = 'engine-selector-btn'
    btn.dataset.engine = 'oxdna'
    document.body.appendChild(btn)
    const api = initEngineActivityHeaders({
      doc: document, intervalMs: 999999,
      fetchActiveJobs: async () => [{ engine: 'md', status: 'running' }],
    })
    await api.refresh()
    expect(spinner(document, 'oxdna')).toBeTruthy()
    expect(spinner(document, 'md')).toBeNull()
    api.stop()
  })
})
