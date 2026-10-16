// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { initAssemblyOverhangListPanel } from './assembly_overhang_list_panel.js'
import { initAssemblyOverhangConnectionsPanel, encodeOption } from './assembly_overhang_connections_panel.js'

const design = label => ({ overhangs: [{ id: 'end_5p', label }] })
function instance(id, version = 1, name = id) {
  const row = { id, name, source: { type: 'file', path: 'hinge.nadoc' }, representation: 'cylinders' }
  Object.defineProperty(row, 'geometrySourceKey', { value: `f:/workspace/hinge.nadoc:${version}:` })
  return row
}
const assembly = (instances = [instance('a'), instance('b')]) => ({ id: 'assembly', instances })
const open = () => {
  document.getElementById('right-panel').classList.remove('hidden')
  document.getElementById('right-tab-content-overhangs').hidden = false
  window.dispatchEvent(new CustomEvent('nadoc:right-tab-change'))
}
const row = id => document.querySelector(`.ohc-list-row[data-instance-id="${id}"]`)
const select = side => document.getElementById(`asm-oconn-select-${side}`)

describe('assembly overhang sidebar rendering lifecycle', () => {
  let panels, store, currentDesign, resolver, fetchDesign
  beforeEach(() => {
    document.body.innerHTML = `<div id="right-panel"><div id="right-tab-content-overhangs" hidden>
      <section id="assembly-overhang-panel"><div id="asm-oh-list"></div></section>
      <section id="assembly-oconn-panel"><select id="asm-oconn-select-a"></select>
        <select id="asm-oconn-select-b"></select><div id="asm-oconn-list"></div>
        <input id="asm-oconn-length" value="12"><button id="asm-oconn-generate"></button>
      </section></div></div>`
    localStorage.clear()
    panels = []
    currentDesign = design('Original end')
    resolver = vi.fn(() => currentDesign)
    fetchDesign = vi.fn(async () => ({ design: currentDesign }))
    store = createMockStore({ currentAssembly: assembly(), assemblyOverhangSelection: [] })
  })
  afterEach(() => { panels.forEach(panel => panel.destroy()); document.body.innerHTML = '' })
  function mount(extra = {}) {
    const deps = { store, getInstanceDesign: resolver, fetchInstanceDesign: fetchDesign, ...extra }
    panels = [initAssemblyOverhangListPanel(deps), initAssemblyOverhangConnectionsPanel(deps)]
    panels.forEach(panel => panel.rebuild())
  }

  it('does no source or row work while parked, then opens with current names and selection', () => {
    mount()
    store.setState({ currentAssembly: assembly([instance('a', 1, 'Renamed')]),
      assemblyOverhangSelection: [{ instanceId: 'a', overhangId: 'end_5p' }] })
    expect(resolver).not.toHaveBeenCalled()
    expect(fetchDesign).not.toHaveBeenCalled()
    expect(document.getElementById('asm-oh-list').children).toHaveLength(0)
    expect(select('a').options).toHaveLength(0)
    open()
    expect(document.getElementById('asm-oh-list').textContent).toContain('Renamed')
    expect(row('a').classList.contains('ct-selected-a')).toBe(true)
    expect(select('a').value).toBe(encodeOption('a', 'end_5p'))
    expect(select('a').options).toHaveLength(2)
  })

  it('preserves visible rows and options across representation and pose snapshots', () => {
    mount(); open()
    const originalRow = row('a'), option = select('a').options[1]
    const changed = assembly([instance('a'), instance('b')])
    changed.instances[0].representation = 'full'
    changed.instances[0].transform = { values: [1, 0, 0, 20] }
    store.setState({ currentAssembly: changed })
    expect(row('a')).toBe(originalRow)
    expect(select('a').options[1]).toBe(option)
    expect(fetchDesign).not.toHaveBeenCalled()
  })

  it('keeps two-way ordered selection without replacing dropdown options', () => {
    mount(); open()
    const option = select('b').options[1]
    row('a').click()
    expect(select('a').value).toBe(encodeOption('a', 'end_5p'))
    select('b').value = encodeOption('b', 'end_5p')
    select('b').dispatchEvent(new Event('change'))
    expect(store.getState().assemblyOverhangSelection.map(pick => pick.instanceId)).toEqual(['a', 'b'])
    expect(row('b').classList.contains('ct-selected-b')).toBe(true)
    expect(select('b').options[1]).toBe(option)
    document.getElementById('right-panel').classList.add('hidden')
    store.setState({ assemblyOverhangSelection: [{ instanceId: 'b', overhangId: 'end_5p' }] })
    open()
    expect(row('a').classList.contains('ct-selected-a')).toBe(false)
    expect(row('b').classList.contains('ct-selected-a')).toBe(true)
    expect(select('a').value).toBe(encodeOption('b', 'end_5p'))
  })

  it('refreshes changed source versions, part names, and membership on opening', () => {
    mount(); open()
    document.getElementById('right-tab-content-overhangs').hidden = true
    currentDesign = design('New source end')
    store.setState({ currentAssembly: assembly([instance('a', 2, 'Latest part')]) })
    expect(row('a').textContent).toContain('Original end')
    open()
    expect(row('a').textContent).toContain('New source end')
    expect(row('b')).toBeNull()
    expect(select('a').querySelector('optgroup').label).toBe('Latest part')
    expect(select('a').options[1].textContent).toContain('New source end')
    expect(fetchDesign).not.toHaveBeenCalled()
  })

  it('does not build hidden DOM when source readiness resolves, and renders on reopen', async () => {
    let ready
    const wait = new Promise(resolve => { ready = resolve })
    currentDesign = null
    mount({ waitForAssemblyReady: () => wait }); open()
    document.getElementById('right-tab-content-overhangs').hidden = true
    currentDesign = design('Ready end')
    ready()
    await wait; await Promise.resolve(); await Promise.resolve()
    expect(row('a')).toBeNull()
    expect(fetchDesign).not.toHaveBeenCalled()
    open()
    expect(row('a').textContent).toContain('Ready end')
    expect(select('a').options[1].textContent).toContain('Ready end')
  })

  it('updates connection records while retaining unchanged source options', () => {
    mount(); open()
    const option = select('a').options[1]
    store.setState({ currentAssembly: { ...store.getState().currentAssembly, overhang_connections: [{
      id: 'connection', name: 'New linker', linker_type: 'ds', instance_a_id: 'a', instance_b_id: 'b',
      overhang_a_id: 'end_5p', overhang_b_id: 'end_5p',
    }] } })
    expect(document.getElementById('asm-oconn-list').textContent).toContain('New linker')
    expect(select('a').options[1]).toBe(option)
  })

  it('preserves collapse actions and removes subscriptions on disposal', () => {
    mount(); open()
    const header = document.querySelector('.aohc-part-header')
    header.click()
    expect(row('a')).toBeNull()
    document.querySelector('.aohc-part-header').click()
    expect(row('a')).not.toBeNull()
    panels.forEach(panel => panel.destroy()); panels = []
    const original = row('a')
    store.setState({ currentAssembly: assembly([]) })
    open()
    expect(row('a')).toBe(original)
  })
})
