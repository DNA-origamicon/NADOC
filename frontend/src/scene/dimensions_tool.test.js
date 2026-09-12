import * as THREE from 'three'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('three/addons/controls/TransformControls.js', () => ({
  TransformControls: class extends THREE.EventDispatcher {
    constructor() { super(); this.helper = new THREE.Group() }
    attach(object) { this.object = object }
    detach() { this.object = null }
    getHelper() { return this.helper }
    setMode() {}
    setSpace() {}
    setSize() {}
    dispose() {}
  },
}))

import { dimensionDistance, initDimensionsTool } from './dimensions_tool.js'

function markup() {
  document.body.innerHTML = `
    <div id="dimensions-section">
      <h2 id="dimensions-heading" tabindex="0"><span></span><span id="dimensions-arrow"></span></h2>
      <div id="dimensions-body"><div id="dimensions-hint"></div>
        <span id="dimensions-record-wrap"><button id="dimensions-record">Measure</button></span>
        <button id="dimensions-clear"></button>
        <div id="dimensions-list"></div>
      </div>
    </div>`
}

function makeStore(assemblyActive = false) {
  let state = { assemblyActive, unfoldActive: false, selection: { items: [] } }
  const listeners = []
  return {
    getState: () => state,
    setAssembly(value) {
      const prev = state
      state = { ...state, assemblyActive: value }
      listeners.forEach(fn => fn(state, prev))
    },
    setSelection(items) {
      const prev = state
      state = { ...state, selection: { items } }
      listeners.forEach(fn => fn(state, prev))
    },
    subscribe(fn) { listeners.push(fn); return () => listeners.splice(listeners.indexOf(fn), 1) },
  }
}

function makeSelection(store) {
  let bases = []
  return {
    getSelectedIndividualBases: () => bases.map(base => ({
      key: `${base.nuc.helix_id}:${base.nuc.bp_index}:${base.nuc.direction}`,
      nuc: base.nuc,
      pos: base.entry.pos.clone(),
    })),
    clearSelectedIndividualBases: vi.fn(() => {
      bases = []
      store.setSelection([])
    }),
    fire(next, kind = 'base') {
      bases = next
      store.setSelection(next.map(base => ({
        kind,
        key: `${base.nuc.helix_id}:${base.nuc.bp_index}:${base.nuc.direction}`,
      })))
    },
  }
}

function setup({ assembly = false } = {}) {
  markup()
  localStorage.clear()
  const scene = new THREE.Scene()
  const store = makeStore(assembly)
  const selectionManager = makeSelection(store)
  let sidebarListener = null
  const rightSidebar = {
    open: vi.fn(),
    onChange(fn) { sidebarListener = fn; return () => { sidebarListener = null } },
    change(activeTab, openPanels) { sidebarListener?.({ activeTab, openPanels, collapsed: false }) },
  }
  const controls = { target: new THREE.Vector3(), enabled: true }
  const box = new THREE.Box3(new THREE.Vector3(-5, -2, -1), new THREE.Vector3(5, 2, 1))
  const tool = initDimensionsTool({
    scene, camera: new THREE.PerspectiveCamera(), canvas: document.createElement('canvas'),
    controls, store, selectionManager, rightSidebar,
    assemblyRenderer: { getBoundingBox: () => box.clone() },
  })
  return { tool, scene, store, selectionManager, rightSidebar }
}

const bead = (x, y, z, bp) => ({
  entry: { pos: new THREE.Vector3(x, y, z) },
  nuc: { helix_id: 'helix-a', strand_id: 'strand-a', bp_index: bp, direction: 'forward' },
})

beforeEach(() => {
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
})

describe('Dimensions tool', () => {
  it('opens the Properties tab and expands its persistent card', () => {
    const { tool, rightSidebar } = setup()
    expect(tool.isActive()).toBe(false)
    tool.open()
    expect(rightSidebar.open).toHaveBeenCalledWith('properties')
    expect(tool.isActive()).toBe(true)
    expect(document.getElementById('dimensions-body').style.display).toBe('')
    expect(localStorage.getItem('nadoc.leftSidebar.sections.v1')).toContain('dimensions-section')
  })

  it('does not draw a part dimension until exactly two selected bases are measured', () => {
    const { tool, scene, selectionManager } = setup()
    tool.open()
    selectionManager.fire([bead(0, 0, 0, 4), bead(3, 4, 0, 9)])
    expect(tool.getMeasurements()).toHaveLength(0)
    expect(document.getElementById('dimensions-record').disabled).toBe(false)
    let lines = 0
    scene.traverse(object => { if (object.isLine) lines++ })
    expect(lines).toBe(0)

    expect(tool.record()).toBe(true)
    expect(tool.getMeasurements()).toHaveLength(1)
    expect(tool.getMeasurements()[0].name).toBe('Dimension 1')
    expect(tool.getMeasurements()[0].distance).toBe(5)
    lines = 0
    scene.traverse(object => { if (object.isLine) lines++ })
    expect(lines).toBe(1)
  })

  it('resolves two Ends selections through the same individual-base route', () => {
    const { tool, selectionManager } = setup()
    tool.open()
    selectionManager.fire([bead(0, 0, 0, 4), bead(0, 0, 6, 9)], 'end')

    expect(document.getElementById('dimensions-record').disabled).toBe(false)
    expect(tool.record()).toBe(true)
    expect(tool.getMeasurements()[0].distance).toBe(6)
  })

  it('keeps Measure disabled with guidance unless exactly two bases are selected', () => {
    const { tool, selectionManager } = setup()
    tool.open()
    const button = document.getElementById('dimensions-record')
    const wrapper = document.getElementById('dimensions-record-wrap')

    expect(button.textContent).toBe('Measure')
    expect(button.disabled).toBe(true)
    expect(button.style.pointerEvents).toBe('none')
    expect(wrapper.title).toBe('You must first select exactly two bases.')
    selectionManager.fire([bead(0, 0, 0, 1)])
    expect(button.disabled).toBe(true)
    expect(wrapper.title).toBe('You must first select exactly two bases.')

    selectionManager.fire([bead(0, 0, 0, 1), bead(1, 0, 0, 2), bead(2, 0, 0, 3)])
    expect(button.disabled).toBe(true)
    expect(wrapper.title).toBe('You must first select exactly two bases.')

    selectionManager.fire([bead(0, 0, 0, 1), bead(1, 0, 0, 2)])
    expect(button.disabled).toBe(false)
    expect(button.style.pointerEvents).toBe('')
    expect(wrapper.title).toBe('')
  })

  it('collapses and drops pending base endpoints when another sidebar tab opens', () => {
    const { tool, selectionManager, rightSidebar } = setup()
    tool.open()
    selectionManager.fire([bead(0, 0, 0, 4), bead(3, 4, 0, 9)])
    expect(document.getElementById('dimensions-record').disabled).toBe(false)
    rightSidebar.change('visualization', ['properties', 'visualization'])
    expect(tool.isActive()).toBe(true)
    expect(document.getElementById('dimensions-record').disabled).toBe(false)
    rightSidebar.change('visualization', ['visualization'])
    expect(tool.isActive()).toBe(false)
    expect(document.getElementById('dimensions-body').style.display).toBe('none')
    expect(document.getElementById('dimensions-record').disabled).toBe(true)
  })

  it('creates two movable endpoints and a live dimension for assemblies', () => {
    const { tool, scene } = setup({ assembly: true })
    tool.open()
    expect(scene.children.filter(object => object.userData.isDimensionGizmo)).toHaveLength(2)
    expect(tool.getMeasurements()).toHaveLength(1)
    expect(tool.getMeasurements()[0].distance).toBe(4)
  })

  it('removes an unrecorded assembly line when the card closes', () => {
    const { tool, scene } = setup({ assembly: true })
    tool.open()
    expect(tool.getMeasurements()).toHaveLength(1)
    tool.close()
    expect(tool.getMeasurements()).toHaveLength(0)
    let lines = 0
    scene.traverse(object => { if (object.isLine) lines++ })
    expect(lines).toBe(0)
  })

  it('keeps only recorded assembly lines after Clear/close lifecycle changes', () => {
    const { tool, scene } = setup({ assembly: true })
    tool.open()
    tool.record()
    expect(tool.getMeasurements()).toHaveLength(2) // live + frozen record
    tool.close()
    expect(tool.getMeasurements()).toHaveLength(1)
    expect(tool.getMeasurements()[0].name).toBe('Dimension 1')

    tool.open()
    tool.clear()
    tool.close()
    expect(tool.getMeasurements()).toHaveLength(0)
    let lines = 0
    scene.traverse(object => { if (object.isLine) lines++ })
    expect(lines).toBe(0)
  })

  it('shows, hides, deletes, and clears recorded dimensions independently', () => {
    const { tool, selectionManager } = setup()
    tool.open()
    selectionManager.fire([bead(0, 0, 0, 1), bead(1, 0, 0, 2)])
    tool.record()
    selectionManager.fire([bead(0, 0, 0, 3), bead(2, 0, 0, 4)])
    tool.record()
    expect(tool.getMeasurements()).toHaveLength(2)

    document.querySelector('.dimensions-row [aria-label="Hide dimension"]').click()
    expect(tool.getMeasurements().some(item => !item.visible)).toBe(true)
    document.querySelector('.dimensions-row [aria-label="Delete dimension"]').click()
    expect(tool.getMeasurements()).toHaveLength(1)
    document.getElementById('dimensions-clear').click()
    expect(tool.getMeasurements()).toHaveLength(0)
  })
})

describe('dimensionDistance', () => {
  it('returns Euclidean distance in world units (nm)', () => {
    expect(dimensionDistance(new THREE.Vector3(0, 0, 0), new THREE.Vector3(2, 3, 6))).toBe(7)
  })
})
