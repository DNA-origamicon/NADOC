// @vitest-environment node
import { afterEach, expect, it, vi } from 'vitest'
import * as THREE from 'three'
const lookup = vi.hoisted(() => ({ listeners: [], ensure: vi.fn(async () => null), stop: vi.fn() }))
vi.mock('./ssdna_fjc.js', () => ({ fjcChainBetween: () => null, isLoaded: () => false,
  ensureLoaded: lookup.ensure, onLoaded: fn => { lookup.listeners.push(fn); return lookup.stop } }))
import { initFlexibleArcs } from './flexible_arcs.js'
import { initOverhangLinkArcs } from './overhang_link_arcs.js'
import { store } from '../state/store.js'

const owned = []
afterEach(() => { for (const owner of owned.splice(0)) owner.dispose(); vi.restoreAllMocks(); lookup.listeners.length = 0; lookup.ensure.mockClear(); lookup.stop.mockClear() })
function state(design) {
  const unsubscribe = vi.fn(), subscribe = vi.fn(() => unsubscribe)
  return { getState: () => ({ currentDesign: design, coloringMode: 'strand', showReferenceGeometry: true }), subscribe, unsubscribe }
}
function flexible() {
  const design = { cluster_transforms: [], strands: [{ id: 's', domains: [{ helix_id: 'a' }, { helix_id: 'b' }] }],
    flexible_connections: [{ id: 'connection', cluster_a_id: 'p1', cluster_b_id: 'p2', n_ss_bases: 2, contour_length_nm: 5,
      anchor_a: { strand_id: 's', domain_index: 0, bp_index: 0, direction: 'FORWARD' },
      anchor_b: { strand_id: 's', domain_index: 1, bp_index: 0, direction: 'FORWARD' }, segment_bead_keys: [] }] }
  const renderer = { getBackboneEntries: () => ['a', 'b'].map((helix_id, i) => ({
    nuc: { helix_id, bp_index: 0, direction: 'FORWARD' }, pos: new THREE.Vector3(i * 3, 0, 0) })) }
  return { design, renderer }
}
function linker() {
  const design = { strands: [], cluster_transforms: [], overhang_connections: [{ id: 'c', linker_type: 'ss',
    overhang_a_id: 'a', overhang_b_id: 'b', overhang_a_attach: 'free_end', overhang_b_attach: 'free_end', length_value: 3, length_unit: 'bp' }] }
  const records = ['a', 'b'].map((overhang_id, i) => ({ overhang_id, helix_id: overhang_id, bp_index: 0,
    direction: 'FORWARD', backbone_position: [i * 3, 0, 0], is_five_prime: true }))
  return { design, records }
}
it('isolates flexible panes and releases subscriptions and each owned geometry exactly once', () => {
  const { design, renderer } = flexible(), local = state(design), scene = new THREE.Scene()
  vi.spyOn(store, 'getState').mockImplementation(() => { throw new Error('live store access') })
  const a = initFlexibleArcs(scene, renderer, () => ({}), { storeRef: local })
  const b = initFlexibleArcs(scene, renderer, () => ({}), { storeRef: local }); owned.push(a, b)
  a.rebuild(design); b.rebuild(design)
  const aGeometry = a.group.getObjectByName('flexSegmentBeads').geometry
  const bGeometry = b.group.getObjectByName('flexSegmentBeads').geometry
  const disposeA = vi.spyOn(aGeometry, 'dispose'), disposeB = vi.spyOn(bGeometry, 'dispose')
  expect(aGeometry).not.toBe(bGeometry)
  a.rebuild(design); expect(disposeA).not.toHaveBeenCalled()
  a.dispose(); a.dispose(); expect(disposeA).toHaveBeenCalledOnce(); expect(disposeB).not.toHaveBeenCalled()
  b.rebuild(design); expect(b.group.getObjectByName('flexSegmentBeads').count).toBe(2)
  b.dispose(); expect(disposeB).toHaveBeenCalledOnce(); expect(local.unsubscribe).toHaveBeenCalledTimes(2)
})
it('private static linker rendering neither fetches nor subscribes to future lookup/global state', () => {
  const { design, records } = linker(), local = state(design)
  vi.spyOn(store, 'getState').mockImplementation(() => { throw new Error('live store access') })
  const owner = initOverhangLinkArcs(new THREE.Scene(), { storeRef: local, staticLookup: true }); owned.push(owner)
  owner.rebuild(design, records)
  expect(owner.group.getObjectByName('overhangSsLinkerBeads').count).toBe(3)
  expect(owner.group.userData.linkerLookup).toBe('native-bezier-fallback')
  expect(lookup.ensure).not.toHaveBeenCalled(); expect(lookup.listeners).toHaveLength(0)
  owner.dispose(); expect(local.unsubscribe).toHaveBeenCalledOnce()
})
it('legacy lookup completion cannot rebuild a disposed linker owner or retain its design', () => {
  const { design, records } = linker(), local = state(design), scene = new THREE.Scene()
  const owner = initOverhangLinkArcs(scene, { storeRef: local }); owned.push(owner)
  owner.rebuild(design, records); expect(lookup.ensure).toHaveBeenCalledOnce()
  const late = lookup.listeners[0]
  owner.dispose(); late(); owner.rebuild(design, records)
  expect(owner.group.children).toHaveLength(0); expect(scene.children).toHaveLength(0)
  expect(lookup.stop).toHaveBeenCalledOnce(); expect(local.unsubscribe).toHaveBeenCalledOnce()
})
