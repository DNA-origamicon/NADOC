/**
 * Regression pin for the strand spreadsheet's context menu.
 *
 * The menu used to arm `document.addEventListener('pointerdown', _removeCtxMenu,
 * {once:true})` with NO containment check, so a real pointerdown ON AN ITEM
 * detached the menu before mouseup — the item's `click` then fired on a
 * disconnected node and its action never ran. Every item in that menu ("Clear
 * sequence", "Set binder sequence…", "Go to strand", and now "Edit sequence…")
 * was dead to a real mouse; only a synthetic `el.click()` worked. Found while
 * verifying the sequence editor in the running app.
 *
 * ⚠ jsdom CANNOT reproduce the original failure: it dispatches a `click` to a
 * detached node just fine, so the handler still runs there. Proven in a real
 * browser instead (Playwright, "Clear sequence" on the fixture design): before
 * the fix 25 sequenced strands → 25 after (item never fired); after the fix
 * 25 → 24. What IS pinned below in jsdom is the same root cause's other half —
 * `{once: true}` meant an inside press CONSUMED the listener, so the menu could
 * no longer be dismissed by a later outside click. That test fails against the
 * old code; the "real pointerdown+click" one does not, and is kept only as a
 * wiring check.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mountIds } from '../test-helpers/factory_dom.js'
import { createMockStore } from '../test-helpers/mock_store.js'

vi.mock('../api/client.js', () => new Proxy({}, {
  get: () => vi.fn(async () => ({})),
}))
vi.mock('./toast.js', () => ({ showToast: vi.fn() }))
vi.mock('../state/store.js', () => ({ pushGroupUndo: vi.fn() }))

import { initSpreadsheet, getStapleColorOrder } from './spreadsheet.js'
import { STAPLE_PALETTE, buildStapleColorMap, _resetStapleColorPins }
  from '../scene/helix_renderer/palette.js'

const DESIGN = {
  helices: [{ id: 'h0', loop_skips: [] }],
  overhangs: [],
  extensions: [],
  crossovers: [],
  strands: [
    { id: 'scaf', strand_type: 'scaffold', sequence: 'AAAACCCC',
      domains: [{ helix_id: 'h0', start_bp: 0, end_bp: 7, direction: 'FORWARD' }] },
    { id: 'stap', strand_type: 'staple', sequence: 'GGGGTTTT',
      domains: [{ helix_id: 'h0', start_bp: 7, end_bp: 0, direction: 'REVERSE' }] },
  ],
}

function mount() {
  return mountIds({
    'spreadsheet-panel': 'div', 'spreadsheet-body': 'div',
    'spreadsheet-thead-row': 'tr', 'spreadsheet-tbody': 'tbody',
    'spreadsheet-col-toggles': 'div', 'sheet-edge': 'div', 'sheet-toggle': 'button',
  })
}

/** Right-click a cell the way a browser does: contextmenu, then the menu appears. */
function rightClick(el) {
  el.dispatchEvent(new MouseEvent('contextmenu', {
    bubbles: true, cancelable: true, clientX: 10, clientY: 10,
  }))
}

/** Press on an element the way a real mouse does: pointerdown, then click. */
function realClick(el) {
  el.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }))
  el.dispatchEvent(new MouseEvent('click', { bubbles: true }))
}

let store
beforeEach(() => {
  vi.clearAllMocks()
  vi.useFakeTimers()
  // The panel persists its open/closed state; without this the 2nd test's
  // toggle() would CLOSE it and the table would never render.
  localStorage.clear()
  // Seed EMPTY: the panel only rebuilds when `currentDesign` changes identity,
  // so the design must arrive via setState after init.
  store = createMockStore({ currentDesign: null })
})

function openSheet(opts = {}) {
  mount()
  const sheet = initSpreadsheet(store, { goToStrand: vi.fn(), ...opts })
  sheet.toggle()                                   // _rebuildTable no-ops while closed
  store.setState({ currentDesign: DESIGN })
  vi.runOnlyPendingTimers()
  return sheet
}

function sequenceCellOf(rowIndex) {
  const rows = document.querySelectorAll('#spreadsheet-tbody tr')
  return rows[rowIndex]?.querySelector('td[data-col="sequence"]')
}

describe('Base-selection synchronization', () => {
  it('scrolls to the owning strand and highlights selected letters while open', () => {
    const scrollIntoView = vi.fn()
    Element.prototype.scrollIntoView = scrollIntoView
    openSheet()
    store.setState({
      currentGeometry: [
        { helix_id: 'h0', bp_index: 6, direction: 'REVERSE', strand_id: 'stap' },
        { helix_id: 'h0', bp_index: 4, direction: 'REVERSE', strand_id: 'stap' },
      ],
      selection: { items: [
        { kind: 'base', key: 'h0:6:REVERSE' },
        { kind: 'base', key: 'h0:4:REVERSE' },
      ] },
    })
    const row = document.querySelector('tr[data-strand-id="stap"]')
    expect(row.classList.contains('sheet-selected')).toBe(true)
    expect([...row.querySelectorAll('.sheet-seq-selected-base')].map(el => el.textContent)).toEqual(['G', 'G'])
    expect(scrollIntoView).toHaveBeenCalled()

    store.setState({ selection: { items: [] } })
    expect(document.querySelector('.sheet-seq-selected-base')).toBeNull()
  })

  it('does not render or scroll for base selection while collapsed', () => {
    mount()
    initSpreadsheet(store)
    const scrollIntoView = vi.fn()
    Element.prototype.scrollIntoView = scrollIntoView
    store.setState({ currentDesign: DESIGN, currentGeometry: [
      { helix_id: 'h0', bp_index: 6, direction: 'REVERSE', strand_id: 'stap' },
    ], selection: { items: [{ kind: 'base', key: 'h0:6:REVERSE' }] } })
    expect(document.querySelector('.sheet-seq-selected-base')).toBeNull()
    expect(scrollIntoView).not.toHaveBeenCalled()
  })
})

describe('Sequence-cell context menu', () => {
  it('renders an "Edit sequence…" item when a handler is supplied', () => {
    openSheet({ onEditSequence: vi.fn() })
    rightClick(sequenceCellOf(1))
    const labels = [...document.querySelectorAll('.ctx-item')].map(e => e.textContent)
    expect(labels).toContain('Edit sequence…')
  })

  it('hides the item when no handler is supplied', () => {
    openSheet()
    rightClick(sequenceCellOf(1))
    const labels = [...document.querySelectorAll('.ctx-item')].map(e => e.textContent)
    expect(labels).not.toContain('Edit sequence…')
  })

  // Wiring check only — see the ⚠ note at the top: this passes against the old
  // code too, because jsdom still dispatches click to a detached node.
  it('routes the item to onEditSequence with the row strand id', () => {
    const onEditSequence = vi.fn()
    openSheet({ onEditSequence })
    rightClick(sequenceCellOf(1))
    vi.runOnlyPendingTimers()          // arms the outside-dismiss listener

    const item = [...document.querySelectorAll('.ctx-item')]
      .find(e => e.textContent === 'Edit sequence…')
    realClick(item)

    expect(onEditSequence).toHaveBeenCalledWith('stap')
  })

  it('still dismisses on a pointerdown OUTSIDE the menu', () => {
    openSheet({ onEditSequence: vi.fn() })
    rightClick(sequenceCellOf(1))
    vi.runOnlyPendingTimers()
    expect(document.querySelector('.ctx-menu')).toBeTruthy()

    document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }))
    expect(document.querySelector('.ctx-menu')).toBeNull()
  })

  it('closes the menu once an item has run', () => {
    openSheet({ onEditSequence: vi.fn() })
    rightClick(sequenceCellOf(1))
    vi.runOnlyPendingTimers()
    const item = [...document.querySelectorAll('.ctx-item')]
      .find(e => e.textContent === 'Edit sequence…')
    realClick(item)
    expect(document.querySelector('.ctx-menu')).toBeNull()
  })

  it('re-arms dismissal for the next menu (the listener is not consumed)', () => {
    openSheet({ onEditSequence: vi.fn() })
    rightClick(sequenceCellOf(1))
    vi.runOnlyPendingTimers()
    // Press inside — menu survives, and the listener must still be live.
    document.querySelector('.ctx-item')
      .dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }))
    expect(document.querySelector('.ctx-menu')).toBeTruthy()
    document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }))
    expect(document.querySelector('.ctx-menu')).toBeNull()
  })
})

describe('Strand display IDs', () => {
  it('adds a fixed ID column using short type-specific ordinals', () => {
    openSheet()
    const headers = [...document.querySelectorAll('#spreadsheet-thead-row th')]
      .map(cell => cell.textContent)
    expect(headers[0]).toBe('ID')
    const ids = [...document.querySelectorAll('#spreadsheet-tbody td[data-col="id"]')]
      .map(cell => cell.textContent)
    expect(ids).toEqual(['X1', 'S1'])
  })
})

/**
 * This file used to declare its OWN `STAPLE_PALETTE` with entirely different colours
 * (an editor syntax theme) under a comment claiming it mirrored helix_renderer. Because
 * `paletteColor` is the last-resort fallback in `effectiveColor`, every staple arriving
 * with `color === null` — the normal case; Full Autostaple stamps no colour — was painted
 * one hue in the spreadsheet and a different one in the 3D view (index 1: green vs yellow;
 * index 3: blue vs orange). `getStapleColorOrder` feeds `exportSequenceXlsx`, so the wrong
 * hues also reached the exported oligo order sheet.
 *
 * These assertions fail against the old code: it returned '#98c379' for index 1.
 */
describe('Staple colour fallback uses the canonical shared palette', () => {
  const asHex = (rgb) => '#' + rgb.toString(16).padStart(6, '0')

  it('colours an uncoloured staple from scene/helix_renderer/palette.js by array index', () => {
    // DESIGN.strands = [scaffold (idx 0), staple (idx 1)]; neither carries `color`.
    const { strandColors } = getStapleColorOrder({ currentDesign: DESIGN })
    expect(strandColors.stap).toBe(asHex(STAPLE_PALETTE[1]))
    expect(strandColors.stap).toBe('#ffd93d')          // literal pin: the 3D view's hue
  })

  it('excludes the scaffold and never emits the old syntax-theme colours', () => {
    const { strandColors, strandOrder } = getStapleColorOrder({ currentDesign: DESIGN })
    expect(strandOrder).toEqual(['stap'])
    expect(strandColors.scaf).toBeUndefined()
    const retired = ['#e06c75', '#98c379', '#d19a66', '#61afef']
    expect(retired).not.toContain(strandColors.stap)
  })

  it('still honours an explicit per-strand colour override', () => {
    const { strandColors } = getStapleColorOrder({
      currentDesign: DESIGN,
      strandColors: { stap: 0x123456 },
    })
    expect(strandColors.stap).toBe('#123456')
  })
})

/**
 * The OTHER half of the same bug (TD-02, 2026-07-31). Matching STAPLE_PALETTE only
 * fixed the colour LIST. The ASSIGNMENT still diverged: the 3D view pins a palette
 * slot per strand.id for the life of the design (`buildStapleColorMap`), while this
 * file re-derived `strandIndex % 12` — at three call sites, with three different
 * indexings (staples-only array position, `design.strands` position, sorted-row
 * position). So any edit that reshuffles `design.strands` (nick, forced-ligation
 * delete → fragments appended) silently recoloured untouched staples in the panel
 * and in the exported .xlsx while 3D kept them put.
 *
 * The first test below fails against the pre-fix code (index-based: s1 moves from
 * slot 1 to slot 2 when a strand is inserted ahead of it).
 */
describe('Staple palette ASSIGNMENT follows the 3D view, not the array index', () => {
  const asHex = (rgb) => '#' + rgb.toString(16).padStart(6, '0')
  const dom   = () => [{ helix_id: 'h0', start_bp: 0, end_bp: 7, direction: 'FORWARD' }]
  const mkDesign = (strands) => ({
    id: 'drift-design', helices: [{ id: 'h0', loop_skips: [] }],
    overhangs: [], extensions: [], crossovers: [], strands,
  })
  const SCAF = { id: 'scaf', strand_type: 'scaffold', domains: dom() }
  const S1   = { id: 's1',   strand_type: 'staple',   domains: dom() }
  const S2   = { id: 's2',   strand_type: 'staple',   domains: dom() }
  const GEO  = [
    { strand_id: 'scaf', strand_type: 'scaffold' },
    { strand_id: 's1',   strand_type: 'staple' },
    { strand_id: 's2',   strand_type: 'staple' },
  ]

  beforeEach(() => { _resetStapleColorPins() })

  it('a mutation that reshuffles design.strands does not recolour untouched staples', () => {
    const before = getStapleColorOrder({
      currentDesign: mkDesign([SCAF, S1, S2]), currentGeometry: GEO,
    })
    expect(before.strandColors.s1).toBe(asHex(STAPLE_PALETTE[1]))
    expect(before.strandColors.s2).toBe(asHex(STAPLE_PALETTE[2]))

    // An edit inserts a fragment ahead of s1 — every later staple's array index shifts.
    const S0 = { id: 's0', strand_type: 'staple', domains: dom() }
    const after = getStapleColorOrder({
      currentDesign:   mkDesign([SCAF, S0, S1, S2]),
      currentGeometry: [...GEO, { strand_id: 's0', strand_type: 'staple' }],
    })
    expect(after.strandColors.s1).toBe(before.strandColors.s1)
    expect(after.strandColors.s2).toBe(before.strandColors.s2)
  })

  it('the exported colours ARE the renderer\'s pinned map, entry for entry', () => {
    const design = mkDesign([SCAF, S1, S2])
    const pinned = buildStapleColorMap(GEO, design)
    const { strandColors } = getStapleColorOrder({ currentDesign: design, currentGeometry: GEO })
    expect(pinned.size).toBe(2)
    for (const [sid, hex] of pinned) expect(strandColors[sid]).toBe(asHex(hex))
  })

  it('falls back to the array index when there is no geometry to pin against', () => {
    const { strandColors } = getStapleColorOrder({ currentDesign: mkDesign([SCAF, S1, S2]) })
    expect(strandColors.s1).toBe(asHex(STAPLE_PALETTE[1]))
    expect(strandColors.s2).toBe(asHex(STAPLE_PALETTE[2]))
  })
})
