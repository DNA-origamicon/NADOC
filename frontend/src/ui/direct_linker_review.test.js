import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { gunzipSync } from 'node:zlib'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import * as THREE from 'three'
import { mountGeometryReview } from './direct_linker_review.js'

const evidence = JSON.parse(gunzipSync(readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'geometry_review_data/direct-linker.json.gz'))))
const nativeEvidence = JSON.parse(gunzipSync(readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'geometry_review_data/direct-native.json.gz'))))
let host, content, viewers
beforeEach(() => { host = document.createElement('div'); document.body.append(host); viewers = [] })
afterEach(() => { content?.dispose(); content = null; host.remove() })
function viewerFactory(host, id, bundle) {
  const v = { bundle, camera: new THREE.PerspectiveCamera(42, 1, .001, 1000),
    controls: { target: new THREE.Vector3(), update: vi.fn(), addEventListener: vi.fn() },
    dispose: vi.fn(), fit: vi.fn(), setRepresentation: vi.fn(), isRendered: () => true }
  v.camera.position.set(8, 6, 12)
  viewers.push(v); return v
}

it('shows full context, original root lengths, exact defects and qualification limits', () => {
  const before = JSON.stringify(evidence)
  content = mountGeometryReview(host, evidence, { viewerFactory })
  expect(content.isRendered()).toBe(true)
  expect(viewers[0].bundle.current.atoms).toHaveLength(400)
  expect(host.querySelector('[data-ref="roots"]').textContent).toContain('0.527230')
  expect(host.querySelector('[data-ref="bonds"]').textContent).toContain('C5′'.replace('′', "'"))
  expect(host.querySelector('[data-ref="limits"]').textContent).toContain('unqualified')
  expect(host.querySelector('[data-ref="construction"]').children).toHaveLength(5)
  const select = host.querySelector('[aria-label="candidate representation"]')
  select.value = 'full'; select.dispatchEvent(new Event('change'))
  expect(viewers[1].setRepresentation).toHaveBeenCalledWith('full')
  host.querySelector('[data-ref="focus"]').click()
  expect(viewers[1].camera.position.toArray()).toEqual(viewers[0].camera.position.toArray())
  const builder = host.querySelector('[aria-label="Atom builder"]')
  builder.value = 'export'; builder.dispatchEvent(new Event('change'))
  expect(viewers.slice(0, 4).every(v => v.dispose.mock.calls.length === 1)).toBe(true)
  expect(viewers[4].bundle.current.atoms).toEqual(evidence.export_models.current.atoms)
  expect(viewers[4].bundle.displacement).toEqual(evidence.export_models.displacement)
  expect(host.querySelector('[data-ref="roots"]').textContent).toContain('0.535730')
  expect(JSON.stringify(evidence)).toBe(before)
})

it('keeps the native unreachable case distinct from the feasible imported fixture', () => {
  content = mountGeometryReview(host, evidence.controls.native, { viewerFactory })
  expect(host.querySelector('[data-ref="fit"]').textContent).toContain('still refuses')
  expect(host.querySelector('[data-ref="construction"]').textContent).toContain('F2: Extrude 2')
  expect(host.querySelector('[data-ref="sweep"]').textContent).toBe('')
  expect(viewers[0].bundle.current.atoms.length).toBeGreaterThan(400)
})

it('shows the complete reachable native duplex and its advisory contacts in both builders', () => {
  content = mountGeometryReview(host, nativeEvidence, { viewerFactory })
  expect(viewers[0].bundle.current.atoms).toHaveLength(11920)
  expect(viewers[1].bundle.candidate.atoms).toHaveLength(11920)
  expect(host.querySelector('[data-ref="context"]').textContent).toContain('rigid duplex placement')
  expect(host.querySelector('[data-ref="roots"]').textContent).toContain('7.558952')
  expect(host.querySelector('[data-ref="roots"]').textContent).toContain('0.186511')
  expect(host.querySelector('[data-ref="fit"]').textContent).toContain('71 clash pairs')
  expect(host.querySelector('[data-ref="fit"]').textContent).toContain('15 ring piercings')
  expect(host.querySelector('[data-ref="defects"]').textContent).toContain('PIERCING')
  expect(host.querySelector('[data-ref="construction"]').textContent).toContain('no authored row or production verification receipt')
  expect(host.querySelector('[data-ref="sweep"]').textContent).toContain('36 local-linker phase settings')
  host.querySelector('[data-ref="focus"]').click()
  const { camera, controls } = viewers[0]
  camera.lookAt(controls.target); camera.updateMatrixWorld()
  for (const side of ['current', 'candidate']) {
    for (const serial of nativeEvidence.junctions.viewer[1].roots[side].serials) {
      const atom = nativeEvidence[side].atoms[serial]
      const projected = new THREE.Vector3(atom.x, atom.y, atom.z).project(camera)
      expect(Math.abs(projected.x)).toBeLessThan(1)
      expect(Math.abs(projected.y)).toBeLessThan(1)
    }
  }
  const select = host.querySelector('[aria-label="candidate representation"]')
  select.value = 'full'; select.dispatchEvent(new Event('change'))
  expect(viewers[1].setRepresentation).toHaveBeenCalledWith('full')
  const builder = host.querySelector('[aria-label="Atom builder"]')
  builder.value = 'export'; builder.dispatchEvent(new Event('change'))
  expect(host.querySelector('[data-ref="roots"]').textContent).toContain('0.217004')
  expect(viewers[4].bundle.candidate.atoms).toEqual(nativeEvidence.export_models.candidate.atoms)
})

it('cleans up earlier viewers if WebGL initialization fails', () => {
  expect(() => mountGeometryReview(host, evidence, { viewerFactory: (...args) => {
    if (viewers.length === 2) throw new Error('WebGL unavailable')
    return viewerFactory(...args)
  } })).toThrow('WebGL unavailable')
  expect(viewers.every(v => v.dispose.mock.calls.length === 1)).toBe(true)
  expect(host.children).toHaveLength(0)
})
