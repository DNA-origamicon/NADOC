import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { gunzipSync } from 'node:zlib'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import * as THREE from 'three'
import { mountGeometryReview } from './geometry_review_content.js'

const bundle = JSON.parse(gunzipSync(readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'geometry_review_data/platform-attachment.json.gz'))))
let content, host, viewers, disconnect
beforeEach(() => {
  host = document.createElement('div'); document.body.append(host)
  viewers = []; disconnect = vi.fn()
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() { disconnect() } })
})
afterEach(() => { content?.dispose(); content = null; host.remove(); vi.unstubAllGlobals() })
function viewerFactory(host, id) {
  const viewer = { camera: new THREE.PerspectiveCamera(42, 1, .001, 1000),
    controls: { target: new THREE.Vector3(), update: vi.fn(), addEventListener: vi.fn() },
    setRepresentation: vi.fn(), fit: vi.fn(), dispose: vi.fn(), isRendered: () => true }
  viewers.push(viewer)
  return viewer
}

it('shows exact platform evidence and native feature names without changing the evidence', () => {
  const before = JSON.stringify(bundle)
  content = mountGeometryReview(host, bundle, { viewerFactory })
  expect(viewers).toHaveLength(4)
  expect(host.querySelector('[data-ref="metrics"]').textContent).toContain('8 → 6')
  expect(host.querySelector('[data-ref="candidate-rule"]').textContent).toContain('own covalent host strand')
  expect(host.querySelector('[data-ref="features"]').children).toHaveLength(53)
  expect(host.querySelector('[data-ref="features"] li').textContent).toMatch(/^F1:/)
  expect(host.querySelector('[data-ref="features"]').lastChild.textContent).toContain('not saved or applied')
  expect(host.querySelector('[data-ref="defect-list"]').children).toHaveLength(14)
  const select = host.querySelector('[data-ref="candidate-representation"]')
  select.value = 'full'; select.dispatchEvent(new Event('change'))
  expect(viewers[1].setRepresentation).toHaveBeenCalledWith('full')
  host.querySelector('[data-ref="focus"]').click()
  expect(viewers[1].camera.position.toArray()).toEqual(viewers[0].camera.position.toArray())
  expect(JSON.stringify(bundle)).toBe(before)
  content.dispose()
  expect(disconnect).toHaveBeenCalledOnce()
  for (const viewer of viewers) expect(viewer.dispose).toHaveBeenCalledOnce()
  content = null
})

it('shows a pierced control without stale platform claims or construction history', () => {
  content = mountGeometryReview(host, bundle.controls.pierced, { viewerFactory })
  expect(host.querySelector('.gr-notice').textContent).toContain('identical')
  expect(host.querySelector('[data-ref="explanation"]').hidden).toBe(true)
  expect(host.querySelector('[data-ref="features"]').parentElement.hidden).toBe(true)
  expect(host.querySelector('[data-ref="defect-list"]').textContent).toContain('PIERCING')
  expect(host.querySelector('[data-ref="focus"]').hidden).toBe(true)
})

it('releases earlier WebGL viewers if a subsequent viewer cannot initialize', () => {
  expect(() => mountGeometryReview(host, bundle, { viewerFactory: (...args) => {
    if (viewers.length === 2) throw new Error('WebGL unavailable')
    return viewerFactory(...args)
  } })).toThrow('WebGL unavailable')
  expect(disconnect).toHaveBeenCalledOnce()
  for (const viewer of viewers) expect(viewer.dispose).toHaveBeenCalledOnce()
  expect(host.children).toHaveLength(0)
})
