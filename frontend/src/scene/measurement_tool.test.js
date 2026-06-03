import { describe, it, expect, vi, beforeEach } from 'vitest'
import * as THREE from 'three'
import { initMeasurementTool } from './measurement_tool.js'

// Minimal scene stub that records add/remove.
const makeScene = () => {
  const objects = []
  return {
    objects,
    add: (o) => objects.push(o),
    remove: (o) => { const i = objects.indexOf(o); if (i >= 0) objects.splice(i, 1) },
  }
}

// Selection-manager stub that captures the ctrl-bead listener so tests can fire it.
const makeSelMgr = () => {
  let cb = null
  return { onCtrlBeadsChange: (fn) => { cb = fn }, fire: (beads) => cb?.(beads) }
}

function setup() {
  const scene = makeScene()
  const sel = makeSelMgr()
  const onSelectionHudChange = vi.fn()
  const tool = initMeasurementTool({ scene, selectionManager: sel, onSelectionHudChange })
  return { scene, sel, onSelectionHudChange, tool }
}

const A = () => new THREE.Vector3(0, 0, 0)
const B = () => new THREE.Vector3(3, 4, 0) // 5 units from A

beforeEach(() => { document.body.innerHTML = '' })

describe('show', () => {
  it('adds a line to the scene and a visible readout with the distance', () => {
    const { scene, tool } = setup()
    tool.show(A(), B())
    expect(tool.isActive()).toBe(true)
    expect(scene.objects.some((o) => o.isLine)).toBe(true)
    const box = document.body.querySelector('div')
    expect(box).not.toBeNull()
    expect(box.textContent).toBe('Distance: 5.000 nm')
    expect(box.style.display).toBe('block')
  })

  it('replaces a prior measurement (no stale line accumulates)', () => {
    const { scene, tool } = setup()
    tool.show(A(), B())
    tool.show(A(), new THREE.Vector3(6, 8, 0)) // dist 10
    expect(scene.objects.filter((o) => o.isLine)).toHaveLength(1)
    expect(document.body.querySelector('div').textContent).toBe('Distance: 10.000 nm')
  })
})

describe('clear', () => {
  it('removes the line, hides the box, and deactivates', () => {
    const { scene, tool } = setup()
    tool.show(A(), B())
    tool.clear()
    expect(tool.isActive()).toBe(false)
    expect(scene.objects).toHaveLength(0)
    expect(document.body.querySelector('div').style.display).toBe('none')
  })
})

describe('ctrl-bead subscription', () => {
  it('clears when active and the bead set is no longer a pair', () => {
    const { sel, tool } = setup()
    tool.show(A(), B())
    sel.fire([{}]) // one bead → not a pair
    expect(tool.isActive()).toBe(false)
  })

  it('does NOT clear while exactly two beads remain', () => {
    const { sel, tool } = setup()
    tool.show(A(), B())
    sel.fire([{}, {}])
    expect(tool.isActive()).toBe(true)
  })

  it('refreshes the selection HUD on every change, active or not', () => {
    const { sel, onSelectionHudChange } = setup()
    sel.fire([])
    sel.fire([{}, {}])
    expect(onSelectionHudChange).toHaveBeenCalledTimes(2)
  })
})

describe('dispose', () => {
  it('clears and removes the readout box from the DOM', () => {
    const { tool } = setup()
    tool.show(A(), B())
    tool.dispose()
    expect(tool.isActive()).toBe(false)
    expect(document.body.querySelector('div')).toBeNull()
  })
})
