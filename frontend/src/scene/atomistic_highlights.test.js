import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import { initAtomisticRenderer } from './atomistic_renderer.js'
import { atomSelectionForState } from './atom_surface_display.js'

const design = {
  strands: [{ id: 's', domains: [{ helix_id: 'h', start_bp: 0, end_bp: 1, direction: 'FORWARD', overhang_id: 'oh' }] }],
  overhangs: [{ id: 'oh', strand_id: 's' }],
  extensions: [{ id: 'e', strand_id: 'other', end: 'three_prime' }],
  cluster_transforms: [{ id: 'cluster', helix_ids: ['h'], domain_ids: [{ strand_id: 's', domain_index: 0 }] }],
  group_organization: { version: 1, groups: [{ id: 'group', helix_ids: ['h'] }] },
}
const refs = [
  ['strand', { kind: 'strand', id: 's' }],
  ['domain', { kind: 'domain', strandId: 's', domainIndex: 0 }],
  ['base', { kind: 'base', key: 'h:0:FORWARD' }],
  ['end', { kind: 'end', key: 'h:0:FORWARD' }],
  ['overhang', { kind: 'overhang', id: 'oh' }],
  ['cluster', { kind: 'cluster', id: 'cluster' }],
  ['group', { kind: 'part_group', id: 'group' }],
]
function setup(mode) {
  const scene = new THREE.Scene(), ar = initAtomisticRenderer(scene)
  ar.setMode(mode)
  ar.update({ atoms: [
    { serial: 0, element: 'C', helix_id: 'h', bp_index: 0, direction: 'FORWARD', strand_id: 's', x: 0, y: 0, z: 0 },
    { serial: 1, element: 'C', helix_id: 'h', bp_index: 0, direction: 'FORWARD', strand_id: 's', x: .1, y: 0, z: 0 },
    { serial: 2, element: 'C', helix_id: 'h', bp_index: 1, direction: 'FORWARD', strand_id: 's', x: .2, y: 0, z: 0 },
    { serial: 3, element: 'C', helix_id: 'other', bp_index: 0, direction: 'FORWARD', strand_id: 'other', extension_id: 'e', x: 1, y: 0, z: 0 },
  ], bonds: [[0, 1], [1, 2]] })
  const atomMesh = ar.selectionAtomEntries([{ helix_id: 'h', bp_index: 0, direction: 'FORWARD' }])[0].instMesh
  const bondMesh = scene.children.find(m => m.name === 'atomBonds')
  const selected = (mesh, i) => ar.selectionHighlightEntries().some(e => e.instMesh === mesh && e.id === i)
  const select = ref => ar.highlight(atomSelectionForState({ currentDesign: design, selection: { items: [ref] } }))
  return { ar, scene, atomMesh, bondMesh, selected, select }
}
describe.each(['vdw', 'ballstick', 'stick'])('%s native highlights', mode => {
  it.each(refs)('%s outlines actual atoms/bonds without changing their colours or geometry', (_, ref) => {
    const f = setup(mode)
    const before = f.atomMesh.instanceMatrix.array.slice()
    const colors = f.atomMesh.instanceColor.array.slice()
    const bondColors = f.bondMesh?.instanceColor.array.slice()
    f.select(ref)
    expect(f.selected(f.atomMesh, 0)).toBe(mode !== 'stick')
    expect(f.selected(f.atomMesh, 3)).toBe(false)
    expect(f.atomMesh.instanceMatrix.array).toEqual(before)
    expect(f.atomMesh.instanceColor.array).toEqual(colors)
    expect(f.bondMesh?.instanceColor.array).toEqual(bondColors)
    if (f.bondMesh) expect(f.selected(f.bondMesh, 0)).toBe(true)
    expect(f.scene.children.some(m => m.name === 'selectionGlow')).toBe(false)
    f.ar.highlight(null)
    expect(f.selected(f.atomMesh, 0)).toBe(false)
    f.ar.dispose()
  })
  it('extension selection stays on that extension', () => {
    const f = setup(mode); f.select({ kind: 'extension', id: 'e' })
    expect(f.selected(f.atomMesh, 3)).toBe(mode !== 'stick')
    expect(f.selected(f.atomMesh, 0)).toBe(false)
    f.ar.dispose()
  })
})
it('selects a bond cylinder without highlighting endpoint spheres or unrelated intra-residue bonds', () => {
  const f = setup('ballstick')
  f.select({ kind: 'bond', fromKey: 'h:0:FORWARD', toKey: 'h:1:FORWARD', strandId: 's' })
  expect(f.selected(f.bondMesh, 1)).toBe(true)
  expect(f.selected(f.bondMesh, 0)).toBe(false)
  expect(f.selected(f.atomMesh, 0)).toBe(false)
  f.ar.dispose()
})
it('Stick group outlines use only displayed cylinders, never private sphere proxies', () => {
  const f = setup('stick')
  const entries = f.ar.selectionAtomEntries([{ helix_id: 'h', bp_index: 0, direction: 'FORWARD' }], { includeBonds: true, renderedOnly: true })
  expect(entries.length).toBeGreaterThan(0)
  expect(entries.every(e => e.instMesh === f.bondMesh && e.instMesh.parent)).toBe(true)
  f.ar.dispose()
})

it('VDW highlights only the actual endpoint atoms of a selected connection', () => {
  const f = setup('vdw')
  f.select({ kind: 'bond', fromKey: 'h:0:FORWARD', toKey: 'h:1:FORWARD' })
  expect(f.bondMesh).toBeUndefined()
  expect(f.selected(f.atomMesh, 0)).toBe(false)
  expect(f.selected(f.atomMesh, 1)).toBe(true)
  expect(f.selected(f.atomMesh, 2)).toBe(true)
  f.ar.dispose()
})

it('rebinds selection after an equal-size frame rebuild and representation switches', () => {
  const f = setup('ballstick'); f.select({ kind: 'strand', id: 's' })
  const first = f.ar.selectionHighlightEntries()
  f.ar.setMode('stick')
  expect(f.ar.selectionHighlightEntries().every(e => e.instMesh.name === 'atomBonds')).toBe(true)
  f.ar.setMode('ballstick')
  expect(f.ar.selectionHighlightEntries().some(e => e.instMesh.name === 'atomSpheres')).toBe(true)
  f.ar.setVdwScale(1.2)
  const rebuilt = f.ar.selectionHighlightEntries()
  expect(rebuilt.length).toBe(first.length)
  expect(rebuilt.every(e => e.instMesh.parent && !first.some(old => old.instMesh === e.instMesh))).toBe(true)
  f.ar.setMode('off')
  expect(f.ar.selectionHighlightEntries()).toEqual([])
  f.ar.dispose()
})

it('announces same-size mesh replacement so group bounds can rebind their sources', () => {
  const f = setup('ballstick')
  let rebuilds = 0
  const listener = () => { rebuilds++ }
  window.addEventListener('nadoc:atomistic-rebuilt', listener)
  try {
    f.ar.setVdwScale(1.2)
    expect(rebuilds).toBe(1)
    f.select({ kind: 'strand', id: 's' })
    expect(rebuilds).toBe(1)
  } finally { window.removeEventListener('nadoc:atomistic-rebuilt', listener); f.ar.dispose() }
})
