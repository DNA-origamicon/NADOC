// @vitest-environment jsdom
import { describe, it, expect, vi } from 'vitest'
import * as THREE from 'three'

import { initHairpinDimerMarkers } from './hairpin_dimer_markers.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { LINKER, makeDesign, makeReport, makeWarningReport } from '../test-helpers/hairpin_dimer_fixture.js'

function rect(el, r) { el.getBoundingClientRect = () => ({ left: r[0], top: r[1], width: r[2], height: r[3], right: r[0] + r[2], bottom: r[1] + r[3] }) }

function setup({ report = makeReport(), lookup = null } = {}) {
  document.body.innerHTML = '<div id="area"><canvas id="c"></canvas></div>'
  const host = document.getElementById('area'), canvas = document.getElementById('c')
  rect(host, [0, 0, 800, 600]); rect(canvas, [0, 0, 800, 600])
  const camera = new THREE.PerspectiveCamera(45, 800 / 600, 0.1, 1000)
  camera.position.set(0, 0, 50); camera.lookAt(0, 0, 0); camera.updateMatrixWorld(); camera.updateProjectionMatrix()
  // Overhang A's beads sit at x = +5 nm, the linker's at x = -5 nm.
  const geometry = makeDesign().strands.flatMap(s => s.domains.flatMap(d => {
    const lo = Math.min(d.start_bp, d.end_bp), hi = Math.max(d.start_bp, d.end_bp)
    return Array.from({ length: hi - lo + 1 }, (_, i) => ({
      helix_id: d.helix_id, bp_index: lo + i, direction: d.direction, strand_id: s.id,
      backbone_position: [s.id === 's_a' ? 5 : -5, 0, 0],
    }))
  }))
  const store = createMockStore({ currentDesign: makeDesign(), currentGeometry: geometry, hairpinDimerReport: report, assemblyActive: false })
  const onOpen = vi.fn()
  const markers = initHairpinDimerMarkers({
    store, host, camera, canvas, onOpen,
    getHelixCtrl: () => (lookup ? { lookupEntry: lookup } : null),
  })
  const els = () => [...host.querySelectorAll('.hd-3d-marker')]
  return { store, markers, onOpen, els, camera }
}

const tx = el => Number(/translate\((-?[\d.]+)px/.exec(el.style.transform)?.[1])

describe('3D hairpin/dimer markers', () => {
  it('puts one clickable ⚠ over each flagged strand, projected from its beads', () => {
    const { markers, els, onOpen } = setup()
    expect(els()).toHaveLength(2)
    markers.refresh()
    const byStrand = Object.fromEntries(els().map(e => [e.dataset.strandId, e]))
    expect(tx(byStrand.s_a)).toBeGreaterThan(400)          // +x → right of centre
    expect(tx(byStrand[LINKER])).toBeLessThan(400)
    expect(byStrand.s_a.title).toContain('hairpin Tm 96.6 °C')
    byStrand.s_a.click()
    expect(onOpen).toHaveBeenCalledWith('s_a', 'OH-A')
  })

  it('red ⚠ above 50 °C, amber between 30 and 50 °C', () => {
    const red = setup()
    expect(red.els().every(e => e.classList.contains('hd-3d-marker--critical'))).toBe(true)
    expect(red.els()[0].style.color).toBe('rgb(248, 81, 73)')
    const amber = setup({ report: makeWarningReport() })
    expect(amber.els().map(e => e.className)).toEqual(['hd-3d-marker hd-3d-marker--warning'])
    expect(amber.els()[0].style.color).toBe('rgb(245, 166, 35)')
  })

  it('follows live bead positions (views / transforms) over the static geometry', () => {
    const live = new THREE.Vector3(-20, 0, 0)
    const { markers, els } = setup({ lookup: k => (k.startsWith('h_a:') ? { pos: live } : null) })
    markers.refresh()
    const a = els().find(e => e.dataset.strandId === 's_a')
    expect(tx(a)).toBeLessThan(400)                         // moved to the live position
  })

  it('hides behind the camera and clears when the checker is off or in assembly mode', () => {
    const { store, markers, els, camera } = setup()
    markers.refresh()
    expect(els().every(e => e.style.visibility === 'visible')).toBe(true)
    camera.position.set(0, 0, -50); camera.lookAt(0, 0, -100); camera.updateMatrixWorld()
    markers.refresh()
    expect(els().every(e => e.style.visibility === 'hidden')).toBe(true)
    store.setState({ hairpinDimerReport: null })
    expect(els()).toHaveLength(0)
    store.setState({ hairpinDimerReport: makeReport(), assemblyActive: true })
    expect(els()).toHaveLength(0)
    markers.destroy()
    expect(document.querySelector('.hd-3d-layer')).toBeNull()
  })
})
