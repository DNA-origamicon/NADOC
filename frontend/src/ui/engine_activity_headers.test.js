// @vitest-environment jsdom
import { describe, it, expect, beforeEach } from 'vitest'
import { initEngineActivityHeaders } from './engine_activity_headers.js'

/** Build the five engine section headers the way index.html does. */
function buildHeaders(doc) {
  const ids = [
    'oxdna-jobs-heading', 'lammps-jobs-heading', 'mrdna-jobs-heading',
    'cando-jobs-heading', 'md-jobs-panel-heading',
  ]
  for (const id of ids) {
    const h2 = doc.createElement('h2')
    h2.id = id
    const title = doc.createElement('span')
    title.textContent = 'Engine'
    const arrow = doc.createElement('span')
    arrow.className = 'icon'
    h2.append(title, arrow)
    doc.body.appendChild(h2)
  }
}

const spinner = (doc, engine) => doc.querySelector(`[data-engine-spinner="${engine}"]`)

describe('initEngineActivityHeaders', () => {
  beforeEach(() => { document.body.innerHTML = '' })

  it('inserts one hidden spinner into each engine header title', () => {
    buildHeaders(document)
    initEngineActivityHeaders({ fetchActiveJobs: async () => [], doc: document, intervalMs: 999999 })
    for (const e of ['oxdna', 'lammps', 'mrdna', 'cando', 'md']) {
      const sp = spinner(document, e)
      expect(sp).toBeTruthy()
      expect(sp.classList.contains('nadoc-spinner')).toBe(true)
      // lives inside the title span, not the arrow span
      expect(sp.parentElement.querySelector('.icon')).toBeNull()
      expect(sp.hidden).toBe(true)
    }
  })

  it('shows the spinner only for engines with a busy job', async () => {
    buildHeaders(document)
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
    expect(spinner(document, 'lammps').hidden).toBe(true)
    expect(spinner(document, 'mrdna').hidden).toBe(true)
  })

  it('hides a spinner again once its engine goes idle', async () => {
    buildHeaders(document)
    let jobs = [{ engine: 'lammps', status: 'running' }]
    const api = initEngineActivityHeaders({
      doc: document, intervalMs: 999999, fetchActiveJobs: async () => jobs,
    })
    await api.refresh()
    expect(spinner(document, 'lammps').hidden).toBe(false)
    jobs = []
    await api.refresh()
    expect(spinner(document, 'lammps').hidden).toBe(true)
  })

  it('does not throw when a header is missing from the DOM', async () => {
    // only build the oxdna header
    const h2 = document.createElement('h2')
    h2.id = 'oxdna-jobs-heading'
    h2.appendChild(document.createElement('span'))
    document.body.appendChild(h2)
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
