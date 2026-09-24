import { it, expect, vi, afterEach } from 'vitest'
import * as THREE from 'three'
import { initPresentationSelection, resolvePresentationSelection } from './presentation_selection.js'
import { prepareScene, loadPreparedScene, validateScene } from '../viewer/prepared_scene.js'
import { decodeContainer } from '../viewer/package_container.js'
import { mountSharedSelection } from '../viewer/shared_selection.js'
afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); document.body.innerHTML = '' })
const entry = (bp, domain = 0) => ({ pos: new THREE.Vector3(bp, 0, 0), nuc: { helix_id: 'h', bp_index: bp, direction: 'FORWARD', strand_id: 's', domain_index: domain } })
const design = { id: 'part', strands: [{ id: 's', domains: [] }], cluster_transforms: [{ id: 'c', helix_ids: ['h'] }], crossovers: [{ id: 'x', half_a: { helix_id: 'h', index: 0, strand: 'FORWARD' }, half_b: { helix_id: 'h', index: 1, strand: 'FORWARD' } }] }
it.each([
  [{ kind: 'base', key: 'h:0:FORWARD' }, 1], [{ kind: 'end', key: 'h:0:FORWARD' }, 1],
  [{ kind: 'domain', strandId: 's', domainIndex: 0 }, 1], [{ kind: 'strand', id: 's' }, 2],
  [{ kind: 'cluster', id: 'c' }, 2], [{ kind: 'bond', fromKey: 'h:0:FORWARD', toKey: 'h:1:FORWARD' }, 2],
  [{ kind: 'crossover', id: 'x' }, 2], [{ kind: 'protein', id: 'p' }, 7], [{ kind: 'nanoparticle', id: 'n' }, 7],
])('resolves selected %j to displayed targets', (ref, count) => {
  const result = resolvePresentationSelection({ state: { currentDesign: design, selection: { items: [ref] } }, entries: [entry(0), entry(1, 1)], resolveBasePosition: () => null, resolveExternal: ref => ['protein', 'nanoparticle'].includes(ref.kind) ? { x: 8, y: 9, z: 10, radius: 2 } : null })
  expect(result.points).toHaveLength(count)
})
it('resolves nested assembly groups in world coordinates and handles cyclic group input', () => {
  const result = resolvePresentationSelection({ state: { assemblyActive: true, activeGroupId: 'g', currentAssembly: { id: 'a', groups: [{ id: 'g', instance_ids: ['i'], subgroup_ids: ['g'] }] } }, assemblyRenderer: { getInstanceBackboneEntries: () => ({ entries: [entry(1)], matrixWorld: new THREE.Matrix4().makeTranslation(5, 6, 7) }) } })
  expect(result.points[0].toArray()).toEqual([6, 6, 7])
})
it('exports selection, pings by button or period, ignores text entry, and clears on deselection', async () => {
  vi.useFakeTimers(); vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
  const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(55, 1, .1, 1000); camera.position.z = 20
  const container = document.createElement('div'); document.body.append(container)
  container.innerHTML = '<div id="presentation-controls"><button data-end-presentation>End</button></div>'
  const state = { currentDesign: design, selection: { items: [{ kind: 'strand', id: 's' }] } }
  const entries = [entry(0), entry(1)], source = initPresentationSelection({ scene, store: { getState: () => state }, container, getCamera: () => camera,
    addFrameCallback: vi.fn(), removeFrameCallback: vi.fn(), getEntries: () => entries, resolveBasePosition: () => null, getProteinRenderer: () => null, getNanoparticleSubsystem: () => null })
  expect(container.querySelector('[data-selection-ping]').parentElement.id).toBe('presentation-controls')
  expect(container.querySelector('[data-selection-ping]').nextElementSibling.hasAttribute('data-end-presentation')).toBe(true)
  const before = source.capture(); expect(before.label).toContain('Strand')
  const input = document.createElement('input'); container.append(input)
  input.dispatchEvent(new KeyboardEvent('keydown', { key: '.', bubbles: true })); expect(source.capture().ping).toBeNull()
  document.dispatchEvent(new KeyboardEvent('keydown', { key: '.', bubbles: true, cancelable: true })); const ping = source.capture().ping
  expect(ping.id).toBeTruthy(); expect(container.querySelector('.selection-ping').hidden).toBe(false)
  const bytes = prepareScene({ scene, camera: { position: [0,0,20], target: [0,0,0], up: [0,1,0], fov: 55, orbitMode: 'orbit' }, view: { selection: source.capture() } })
  const guest = await loadPreparedScene(bytes), guestContainer = document.createElement('div'); document.body.append(guestContainer)
  const shared = mountSharedSelection({ container: guestContainer, runtime: { camera } }); shared.update(guest)
  expect(guestContainer.textContent).toContain('Presenter selected: Strand')
  expect(guestContainer.querySelector('.selection-ping').hidden).toBe(false)
  await vi.advanceTimersByTimeAsync(2500)
  expect(guestContainer.querySelector('.selection-ping').hidden).toBe(true)
  shared.update(guest); expect(guestContainer.querySelector('.selection-ping').hidden).toBe(true)
  container.querySelector('[data-selection-ping]').click(); expect(source.capture().ping.id).not.toBe(ping.id)
  const bad = decodeContainer(bytes); bad.view.selection.target = 'missing'; expect(() => validateScene(bad)).toThrow('Invalid presenter selection')
  state.selection = { items: [] }; expect(source.capture()).toBeNull(); expect(container.querySelector('[data-selection-ping]').disabled).toBe(true)
  shared.update(null); expect(guestContainer.querySelector('.shared-selection-label').hidden).toBe(true)
  shared.dispose(); guest.dispose(); source.dispose()
})
