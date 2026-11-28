import { afterEach, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { assemblyPatternView, createAssemblyPatternHost } from './assembly_pattern_host.js'
import { initLinearPatternPanel } from './linear_pattern_panel.js'
import { initCircularPatternPanel } from './circular_pattern_panel.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { createAssemblyPattern } from '../api/client.js'
vi.mock('../api/client.js', () => ({ createAssemblyPattern: vi.fn().mockResolvedValue({}),
  refreshAssemblyPatternContext: async () => true, assemblyPatternRevision: () => 1, capturePatternContext: vi.fn(), createLinearPattern: vi.fn(), createCircularPattern: vi.fn() }))
const source = { helices: [{ id: 'h1', length_bp: 21 }, { id: 'h2', length_bp: 21 }] }
const assembly = { id: 'assembly', instances: [{ id: 'a', name: 'Whole origami', source: { design: source } }], feature_log: [{ id: 'f1' }] }
const renderer = { getInstanceDesign: () => source, getInstanceBackboneEntries: () => ({
  nucleotides: [{ backbone_position: [0, 0, 0] }, { backbone_position: [2, 0, 0] }],
  matrixWorld: new THREE.Matrix4().makeTranslation(10, 20, 30),
}) }
afterEach(() => { window.dispatchEvent(new Event('nadoc:document-reset')); document.body.innerHTML = ''; vi.clearAllMocks() })
it('previews the whole posed origami and counts all helices without changing its source', () => {
  const view = assemblyPatternView({ currentAssembly: assembly }, renderer)
  expect(view.currentGeometry.map(n => n.backbone_position)).toEqual([[10, 20, 30], [12, 20, 30]])
  expect(view.currentDesign.helices[0].length_bp).toBe(42)
  expect(source.helices).toHaveLength(2)
})
it('rejects a draft after the assembly changes', () => {
  const store = createMockStore({ assemblyActive: true, currentAssembly: assembly })
  const host = createAssemblyPatternHost({ store, getAssemblyRenderer: () => renderer, kind: 'linear-pattern' })
  const context = host.capture(host.store.getState())
  store.setState({ currentAssembly: { ...assembly } })
  expect(() => host.commit({ cluster_ids: ['a'] }, context)).toThrow(/changed/)
})
for (const kind of ['linear', 'circular']) it(`${kind} uses shared controls, previews, commits whole instances and cancels cleanly`, async () => {
  document.body.innerHTML = `<div id="${kind}-pattern-panel"></div><canvas></canvas>`
  const store = createMockStore({ assemblyActive: true, currentAssembly: assembly })
  const scene = new THREE.Scene()
  const init = kind === 'linear' ? initLinearPatternPanel : initCircularPatternPanel
  const tool = init({ store, scene, getAssemblyRenderer: () => renderer, showToast: vi.fn(),
    canvas: document.querySelector('canvas'), getCamera: () => new THREE.PerspectiveCamera(),
    getControls: () => ({}), addFrameCallback: vi.fn(), removeFrameCallback: vi.fn() })
  await tool.open()
  expect(document.querySelector('.cp-panel-body')).not.toBeNull()
  expect(scene.getObjectByName(`${kind}PatternPreview`)).toBeDefined()
  const confirm = [...document.querySelectorAll('button')].find(b => b.textContent === 'Confirm')
  expect(confirm.disabled).toBe(false)
  confirm.click(); await Promise.resolve(); await Promise.resolve()
  expect(createAssemblyPattern).toHaveBeenCalledWith(`${kind}-pattern`, expect.objectContaining({ instance_ids: ['a'], expected_assembly_id: 'assembly' }))
  tool.close()
  expect(scene.getObjectByName(`${kind}PatternPreview`)).toBeUndefined()
})
it('keeps consistent lattice snapping in the rotated assembly frame', () => {
  const design = { lattice_type: 'SQUARE', helices: [{ id: 'h', length_bp: 20, grid_pos: [0, 0], axis_start: [0, 0, 0], axis_end: [0, 0, 10] }] }
  const matrix = new THREE.Matrix4().makeRotationY(Math.PI / 2).setPosition(10, 20, 30)
  const posed = { ...assembly, instances: [{ ...assembly.instances[0], transform: { values: matrix.clone().transpose().toArray() } }] }
  const preview = assemblyPatternView({ currentAssembly: posed }, {
    getInstanceDesign: () => design,
    getInstanceBackboneEntries: () => ({ nucleotides: [{ backbone_position: [0, 0, 0] }, { backbone_position: [0, 0, 10] }],
      helixAxes: { h: { start: [0, 0, 0], end: [0, 0, 10] } }, matrixWorld: new THREE.Matrix4() }),
  })
  const frame = preview.currentDesign.cluster_transforms[0].patternLattice
  expect(frame.normal.x).toBeCloseTo(1)
  expect(frame.normal.z).toBeCloseTo(0)
  expect(frame.origin.x).toBeCloseTo(-5)
  expect(preview.currentGeometry[0].backbone_position).toEqual([10, 20, 30])
})
it('waits for all source geometry before offering targets or totals', () => {
  const view = assemblyPatternView({ currentAssembly: { ...assembly, instances: [...assembly.instances, { id: 'missing' }] } }, {
    ...renderer, getInstanceBackboneEntries: id => id === 'missing' ? { entries: [] } : renderer.getInstanceBackboneEntries(),
  })
  expect(view.currentDesign.cluster_transforms).toEqual([])
  expect(view.currentGeometry).toEqual([])
})
