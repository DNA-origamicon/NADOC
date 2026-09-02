/**
 * Factory tests for the Conjugate Manager modal.
 *
 * The module owns a private THREE scene + WebGL renderer (no WebGL in jsdom), so
 * we mock `three`, OrbitControls, and the atomistic renderer down to the surface
 * the module touches, then assert the observable contract: open() mounts the
 * windowed modal, lists overhangs (left) + numbered conjugation sites (right),
 * selecting an overhang fills the reverse-complement handle, selecting a site
 * highlights its row, and Conjugate renders on the SELECTED site.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

vi.mock('three', () => {
  class V3 {
    constructor(x = 0, y = 0, z = 0) { this.x = x; this.y = y; this.z = z }
    set(x, y, z) { this.x = x; this.y = y; this.z = z; return this }
    setScalar() { return this }
    copy(v) { this.x = v.x; this.y = v.y; this.z = v.z; return this }
    addScaledVector(v, s) { this.x += v.x * s; this.y += v.y * s; this.z += v.z * s; return this }
    crossVectors() { return this }
    normalize() { return this }
    clone() { return new V3(this.x, this.y, this.z) }
  }
  const hex = (v) => { let h = typeof v === 'number' ? v : 0; return { getHex: () => h, setHex: (x) => { h = x } } }
  class Mat { constructor(o = {}) { this.color = hex(o.color); this.emissive = hex(o.emissive) } }
  class Q { setFromUnitVectors() { return this } setFromRotationMatrix() { return this } copy() { return this } }
  class Mesh {
    constructor(geom, mat) { this.geometry = geom; this.material = mat || new Mat(); this.position = new V3(); this.scale = new V3(1, 1, 1); this.quaternion = new Q(); this.userData = {} }
    add() {}
  }
  class Light { constructor() { this.position = new V3() } add() {} }
  return {
    WebGLRenderer: class { setPixelRatio() {} setSize() {} render() {} dispose() {} },
    Scene: class { add() {} remove() {} },
    Color: class {},
    AmbientLight: Light,
    DirectionalLight: Light,
    PerspectiveCamera: class { constructor() { this.position = new V3() } updateProjectionMatrix() {} },
    Group: class { add() {} },
    Mesh,
    MeshPhongMaterial: Mat,
    MeshBasicMaterial: Mat,
    SphereGeometry: class {},
    BoxGeometry: class {},
    ConeGeometry: class {},
    Vector3: V3,
    Quaternion: Q,
    Matrix4: class { makeBasis() { return this } },
    Raycaster: class { setFromCamera() {} intersectObjects() { return [] } },
  }
})
vi.mock('three/addons/controls/OrbitControls.js', () => ({
  OrbitControls: class { constructor() { this.target = { set() {} } } update() {} dispose() {} },
}))
vi.mock('../scene/atomistic_renderer.js', () => ({
  initAtomisticRenderer: () => ({ setMode: vi.fn(), update: vi.fn(), centroidOf: () => ({ x: 0, y: 0, z: 0 }) }),
}))
vi.mock('../shared/doc_id.js', () => ({ docHeaders: () => ({}) }))

import { initConjugateManager } from './conjugate_manager.js'

const CANDIDATES = [
  { res_name: 'LYS', chain_id: 'A', res_seq: 10, chemistry: 'lys', x: 0, y: 0, z: 0 },
  { res_name: 'CYS', chain_id: 'A', res_seq: 22, chemistry: 'cys', x: 1, y: 0, z: 0 },
  { res_name: 'MET', chain_id: 'A', res_seq: 1, chemistry: 'nterm', x: 0, y: 2, z: 0 },
]
const OVERHANGS = [{ id: 'ovhg_1', label: 'A1', sequence: 'ATGC' }, { id: 'ovhg_2', sequence: '' }]

const makeApi = () => ({
  getConjugationCandidates: vi.fn(async () => ({
    asset_id: 'a1', design_revision: 7, candidates: CANDIDATES,
  })),
  conjugateProteinToOverhang: vi.fn(async () => ({ attachment_id: 'att1', binder_strand_id: 'b1' })),
  currentRevisionWatermark: vi.fn(() => 7),
})
const makeStore = (overhangs = OVERHANGS) => ({ getState: () => ({ currentDesign: { overhangs } }) })
const overlayEl = () => document.getElementById('conjugate-manager-overlay')
const btnByText = (t) => [...overlayEl().querySelectorAll('button')].find(b => b.textContent === t)
const conjugateBtn = () => btnByText('Conjugate')
const siteRows = () => [...overlayEl().querySelectorAll('.ohc-list-row')].slice(OVERHANGS.length)

beforeEach(() => {
  globalThis.requestAnimationFrame = vi.fn(() => 1)
  globalThis.cancelAnimationFrame = vi.fn()
  Element.prototype.scrollIntoView = vi.fn()
  globalThis.fetch = vi.fn(async () => ({ ok: true, json: async () => ({ atoms: [{ x: 0, y: 0, z: 0, element: 'N' }] }) }))
})
afterEach(() => { document.body.innerHTML = ''; vi.restoreAllMocks() })

describe('open', () => {
  it('mounts the modal, lists overhangs (left) and numbered sites (right)', async () => {
    const mgr = initConjugateManager({ api: makeApi(), store: makeStore() })
    await mgr.open('a1')
    const overlay = overlayEl()
    expect(overlay).toBeTruthy()
    expect(overlay.textContent).toContain('Conjugation sites (3)')
    // numbered, with residue labels
    expect(overlay.textContent).toContain('1.')
    expect(overlay.textContent).toContain('LYS A:10')
    expect(overlay.textContent).toContain('CYS A:22')
    // overhang list (left)
    expect(overlay.textContent).toContain('A1 (4 nt)')
  })

  it('removes the loading spinner once sites are computed', async () => {
    const mgr = initConjugateManager({ api: makeApi(), store: makeStore() })
    await mgr.open('a1')
    expect(overlayEl().querySelector('.cm-spinner')).toBeNull()
  })

  it('selecting an overhang fills the handle field with the reverse complement', async () => {
    const mgr = initConjugateManager({ api: makeApi(), store: makeStore() })
    await mgr.open('a1')
    const handle = overlayEl().querySelector('input[readonly]')
    expect(conjugateBtn().disabled).toBe(true)
    overlayEl().querySelectorAll('.ohc-list-row')[0].click()   // left list, first overhang ATGC
    expect(handle.value).toBe('GCAT')
    expect(conjugateBtn().disabled).toBe(false)
  })
})

describe('site selection', () => {
  // The right-hand list rows follow the (3) overhang rows in DOM order.
  const siteRows = () => [...overlayEl().querySelectorAll('.ohc-list-row')].slice(OVERHANGS.length)

  it('clicking a site row highlights it', async () => {
    const mgr = initConjugateManager({ api: makeApi(), store: makeStore() })
    await mgr.open('a1')
    const rows = siteRows()
    expect(rows.length).toBe(3)
    rows[1].click()
    expect(rows[1].classList.contains('is-selected')).toBe(true)
    expect(rows[0].classList.contains('is-selected')).toBe(false)
    // selecting another moves the highlight
    rows[2].click()
    expect(rows[2].classList.contains('is-selected')).toBe(true)
    expect(rows[1].classList.contains('is-selected')).toBe(false)
  })

  it('Conjugate renders on the SELECTED site', async () => {
    const mgr = initConjugateManager({ api: makeApi(), store: makeStore() })
    await mgr.open('a1')
    overlayEl().querySelectorAll('.ohc-list-row')[0].click()   // pick overhang (enables Conjugate)
    siteRows()[2].click()                                      // pick site #3 (CYS? -> MET nterm, idx 2)
    conjugateBtn().click()
    expect(overlayEl().textContent).toContain('ssDNA on #3 MET A:1')
  })

  it('Conjugate with no site selected deterministically picks the top-ranked site', async () => {
    const mgr = initConjugateManager({ api: makeApi(), store: makeStore() })
    await mgr.open('a1')
    overlayEl().querySelectorAll('.ohc-list-row')[0].click()
    conjugateBtn().click()
    expect(overlayEl().textContent).toContain('ssDNA on #1')
  })
})

describe('Apply / Cancel', () => {
  it('Apply is disabled until BOTH an overhang and a site are selected', async () => {
    const mgr = initConjugateManager({ api: makeApi(), store: makeStore() })
    await mgr.open('a1')
    expect(btnByText('Apply').disabled).toBe(true)
    overlayEl().querySelectorAll('.ohc-list-row')[0].click()   // overhang only
    expect(btnByText('Apply').disabled).toBe(true)
    siteRows()[1].click()                                      // + a site
    expect(btnByText('Apply').disabled).toBe(false)
  })

  it('Apply commits with the selected overhang/site/azide and closes', async () => {
    const api = makeApi()
    const mgr = initConjugateManager({ api, store: makeStore() })
    await mgr.open('a1')
    overlayEl().querySelectorAll('.ohc-list-row')[0].click()   // overhang ovhg_1
    siteRows()[1].click()                                      // site #2 → CYS, serial-less fixture
    overlayEl().querySelector('input[name="cm-azide"][value="3p"]').click()
    btnByText('Apply').click()
    await Promise.resolve(); await Promise.resolve()
    expect(api.conjugateProteinToOverhang).toHaveBeenCalledWith(
      expect.objectContaining({ assetId: 'a1', overhangId: 'ovhg_1', azideEnd: '3p' }))
    expect(mgr.isOpen()).toBe(false)                            // closed on success
  })

  it('passes the originating placement so conjugation converts it in place', async () => {
    const api = makeApi()
    const mgr = initConjugateManager({ api, store: makeStore() })
    await mgr.open('a1', { sourceAttachmentId: 'free-att-1' })
    overlayEl().querySelectorAll('.ohc-list-row')[0].click()
    siteRows()[0].click()
    btnByText('Apply').click()
    await Promise.resolve(); await Promise.resolve()
    expect(api.conjugateProteinToOverhang).toHaveBeenCalledWith(
      expect.objectContaining({ sourceAttachmentId: 'free-att-1' }))
  })

  it('uses the authoritative revision returned with the candidate snapshot', async () => {
    const api = makeApi()
    api.currentRevisionWatermark.mockReturnValue(99)
    const mgr = initConjugateManager({ api, store: makeStore() })
    await mgr.open('a1', { sourceAttachmentId: 'free-att-1' })
    overlayEl().querySelectorAll('.ohc-list-row')[0].click()
    siteRows()[0].click()
    btnByText('Apply').click()
    await Promise.resolve(); await Promise.resolve()
    expect(api.conjugateProteinToOverhang).toHaveBeenCalledWith(
      expect.objectContaining({ expectedRevision: 7 }))
  })

  it('shows the backend conflict reason when Apply is rejected', async () => {
    const api = makeApi()
    api.conjugateProteinToOverhang.mockResolvedValue(null)
    const store = {
      getState: () => ({
        currentDesign: { overhangs: OVERHANGS },
        lastError: { status: 409, message: 'Design changed while this operation was prepared.' },
      }),
    }
    const mgr = initConjugateManager({ api, store })
    await mgr.open('a1')
    overlayEl().querySelectorAll('.ohc-list-row')[0].click()
    siteRows()[0].click()
    btnByText('Apply').click()
    await Promise.resolve(); await Promise.resolve()
    expect(overlayEl().textContent).toContain(
      'Conjugation failed: Design changed while this operation was prepared.')
  })

  it('Cancel closes without committing', async () => {
    const api = makeApi()
    const mgr = initConjugateManager({ api, store: makeStore() })
    await mgr.open('a1')
    btnByText('Cancel').click()
    expect(mgr.isOpen()).toBe(false)
    expect(api.conjugateProteinToOverhang).not.toHaveBeenCalled()
  })
})

describe('edge cases + teardown', () => {
  it('no overhangs → message; open(null) → no-op', async () => {
    const mgr = initConjugateManager({ api: makeApi(), store: makeStore([]) })
    await mgr.open('a1')
    expect(overlayEl().textContent).toContain('No overhangs in this design.')
    mgr.close()
    await mgr.open(null)
    expect(overlayEl()).toBeNull()
  })

  it('close() and Escape remove the overlay', async () => {
    const mgr = initConjugateManager({ api: makeApi(), store: makeStore() })
    await mgr.open('a1')
    mgr.close()
    expect(overlayEl()).toBeNull()
    await mgr.open('a1')
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(mgr.isOpen()).toBe(false)
  })
})

describe('showConjugateMenu', () => {
  it('includes a supplied protein representation submenu', () => {
    const mgr = initConjugateManager({ api: makeApi(), store: makeStore() })
    const representationItem = document.createElement('div')
    representationItem.textContent = 'Representation'
    mgr.showConjugateMenu({ x: 5, y: 5, assetId: 'a1', representationItem })
    expect(document.getElementById('conjugate-context-menu').textContent).toContain('Representation')
  })

  it('opens the manager for the asset on click', async () => {
    const mgr = initConjugateManager({ api: makeApi(), store: makeStore() })
    mgr.showConjugateMenu({ x: 5, y: 5, assetId: 'a1' })
    const menu = document.getElementById('conjugate-context-menu')
    expect(menu.textContent).toContain('Conjugate protein to ssDNA')
    menu.querySelector('div').click()
    await Promise.resolve(); await Promise.resolve()
    expect(overlayEl()).toBeTruthy()
  })
  it('no-op without an assetId', () => {
    const mgr = initConjugateManager({ api: makeApi(), store: makeStore() })
    mgr.showConjugateMenu({ x: 0, y: 0 })
    expect(document.getElementById('conjugate-context-menu')).toBeNull()
  })
})
