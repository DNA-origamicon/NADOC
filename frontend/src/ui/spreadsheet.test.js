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
import { STAPLE_PALETTE } from '../scene/helix_renderer/palette.js'

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
