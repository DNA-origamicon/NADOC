// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { initPlateView } from './plate_view.js'

const ctx = {
  setTransform: vi.fn(), fillRect: vi.fn(), fillText: vi.fn(), beginPath: vi.fn(),
  arc: vi.fn(), fill: vi.fn(), stroke: vi.fn(), moveTo: vi.fn(), arcTo: vi.fn(),
  closePath: vi.fn(), setLineDash: vi.fn(), lineTo: vi.fn(),
}

// Six staple records stand in for the six helices of the short 6HB fixture. The
// overlaps are intentional: red is s1+s2, while group-A is s1+s3, proving that
// Color and Group transfer the correct unit rather than merely the same count.
function short6hbRecords() {
  return [
    { strandId: 's1', color: '#ff3344', groupId: 'group-A' },
    { strandId: 's2', color: '#ff3344', groupId: 'group-B' },
    { strandId: 's3', color: '#3388ff', groupId: 'group-A' },
    { strandId: 's4', color: '#33aa66', groupId: 'group-B' },
    { strandId: 's5', color: '#aa55dd', groupId: 'group-C' },
    { strandId: 's6', color: '#dd9933', groupId: 'group-C' },
  ].map((s, i) => ({
    ...s, groupOrder: i % 3, lengthNt: 42, hasMod: false, modName: null,
    sequence: 'A'.repeat(42), name: `6HB staple ${i + 1}`,
  }))
}

function initialLayout() {
  return {
    orientation: '8x12', plate_count: 1, tubes: [],
    wells: short6hbRecords().map((s, col) => ({ strand_id: s.strandId, plate: 0, row: 0, col })),
  }
}

function setup(extra = {}) {
  document.body.innerHTML = `
    <div id="wrap"><canvas id="plate"></canvas></div>
    <div id="toolbar"></div><div id="tubes"></div>`
  const canvas = document.getElementById('plate')
  const wrap = document.getElementById('wrap')
  canvas.getContext = () => ctx
  for (const el of [canvas, wrap]) {
    el.getBoundingClientRect = () => ({ left: 0, top: 0, width: 420, height: 320, right: 420, bottom: 320 })
  }
  const saves = []
  const view = initPlateView(canvas, {
    wrapEl: wrap,
    toolbarEl: document.getElementById('toolbar'),
    getTubesContainer: () => document.getElementById('tubes'),
    enableGroupMode: true,
    onSaveLayout: layout => saves.push(layout),
    ...extra,
  })
  view.setData(short6hbRecords(), initialLayout())
  return { canvas, view, saves }
}

function sortedIds(items) {
  return items.map(x => x.strand_id).sort()
}

describe('plate/tube context transfers', () => {
  beforeEach(() => { globalThis.ResizeObserver = undefined })
  afterEach(() => document.querySelectorAll('.context-menu').forEach(el => el.remove()))

  it('round-trips one well through the two right-click menu actions', () => {
    const { canvas, view } = setup()

    // resetView fits a 396x280 one-plate world into the 420x320 canvas. A1's
    // centre is therefore at approximately (52, 70) CSS pixels.
    canvas.dispatchEvent(new MouseEvent('contextmenu', {
      bubbles: true, cancelable: true, clientX: 52, clientY: 70,
    }))
    expect(document.querySelector('.context-menu__item')?.textContent).toBe('Send to tubes')
    document.querySelector('.context-menu__item').click()

    expect(sortedIds(view.getLayout().tubes)).toEqual(['s1'])
    expect(view.getLayout().tubes[0].reason).toBe('manual')
    const tubeRow = document.querySelector('[data-strand-id="s1"]')
    expect(tubeRow.dataset.color).toBe('#ff3344')
    expect(tubeRow.dataset.groupId).toBe('group-A')
    expect(document.querySelector('.plate-tubes-box')).toBeTruthy()
    expect(document.querySelector('.plate-tubes-scroll')).toBeTruthy()

    tubeRow.dispatchEvent(new MouseEvent('contextmenu', {
      bubbles: true, cancelable: true, clientX: 100, clientY: 100,
    }))
    expect(document.querySelector('.context-menu__item')?.textContent).toBe('Send to plates')
    document.querySelector('.context-menu__item').click()

    expect(view.getLayout().tubes).toEqual([])
    expect(view.getLayout().wells).toEqual(initialLayout().wells)
  })

  it('round-trips strand, color, and group units without losing their identities', () => {
    const { view } = setup()

    view.setSelectionMode('staple')
    expect(view.sendToTubes('s1')).toEqual(['s1'])
    expect(view.sendToPlates('s1')).toEqual(['s1'])

    view.setSelectionMode('color')
    expect(view.sendToTubes('s1').sort()).toEqual(['s1', 's2'])
    expect(sortedIds(view.getLayout().tubes)).toEqual(['s1', 's2'])
    expect(view.sendToPlates('s1').sort()).toEqual(['s1', 's2'])

    view.setSelectionMode('group')
    expect(view.sendToTubes('s1').sort()).toEqual(['s1', 's3'])
    expect(sortedIds(view.getLayout().tubes)).toEqual(['s1', 's3'])
    expect(view.sendToPlates('s1').sort()).toEqual(['s1', 's3'])

    expect(view.getLayout().tubes).toEqual([])
    expect(view.getLayout().wells).toEqual(initialLayout().wells)
  })
})

describe('hairpin/self-dimer warnings', () => {
  afterEach(() => { document.body.innerHTML = '' })

  it('badges flagged wells and adds the finding to the hover tooltip', () => {
    const { canvas, view } = setup()
    ctx.moveTo.mockClear()
    view.setWarnings(new Map([['s1', '⚠ Secondary structure with Tm > 30 °C\nOverhang OH-A: hairpin Tm 42.0 °C']]))
    expect(ctx.moveTo).toHaveBeenCalled()             // the ⚠ triangle path
    const layoutBefore = JSON.stringify(view.getLayout())
    // Well A1 (s1) centre: ROWLABEL_W + WELL_PITCH/2 by TITLE_H + HEADER_H + WELL_PITCH/2 at the fitted zoom;
    // hover every point on a grid and look for the tooltip naming s1's finding.
    let tip = null
    for (let y = 0; y < 320 && !tip; y += 4) {
      for (let x = 0; x < 420 && !tip; x += 4) {
        canvas.dispatchEvent(new PointerEvent('pointermove', { clientX: x, clientY: y, bubbles: true }))
        const el = [...document.body.children].find(n => n.textContent?.includes('6HB staple 1'))
        if (el?.style.display !== 'none' && el?.textContent.includes('hairpin Tm 42.0 °C')) tip = el
      }
    }
    expect(tip).toBeTruthy()
    expect(JSON.stringify(view.getLayout())).toBe(layoutBefore)   // no re-pack
  })

  it('a click on the well\'s ⚠ badge opens the structure; the rest of the well does not', () => {
    const warned = []
    const { canvas, view } = setup({ onWarningClick: (sid, name) => warned.push([sid, name]) })
    for (const f of [ctx.setTransform, ctx.moveTo, ctx.lineTo]) f.mockClear()
    view.setWarnings(new Map([['s1', 'hairpin Tm 42.0 °C']]))
    // Recover the badge's screen position from the draw calls: the triangle is the
    // only moveTo followed by lineTo; the last setTransform is the pan/zoom (dpr 1).
    const [z, , , , px, py] = ctx.setTransform.mock.calls.at(-1)
    const at = ctx.moveTo.mock.invocationCallOrder.indexOf(ctx.lineTo.mock.invocationCallOrder[0] - 1)
    const [bx, apex] = ctx.moveTo.mock.calls[at]
    const by = apex + 4.5                                            // triangle centre
    const click = (wx, wy) => canvas.dispatchEvent(new PointerEvent('pointerdown',
      { clientX: px + z * wx, clientY: py + z * wy, button: 0, bubbles: true }))
    click(bx - 12 * 0.72, by + 12 * 0.72)                             // well centre
    expect(warned).toEqual([])
    click(bx, by)
    expect(warned).toEqual([['s1', '6HB staple 1']])
  })

  it('fills the badge amber for a warning and red for a critical finding', () => {
    const fills = []
    const orig = ctx.fill
    ctx.fill = vi.fn(function () { fills.push(this.fillStyle) })
    try {
      const { view } = setup()
      ctx.lineTo.mockClear(); fills.length = 0
      view.setWarnings(new Map([['s1', { text: 'a', level: 'warning' }], ['s2', { text: 'b', level: 'critical' }]]))
      expect(fills).toContain('#d29922')
      expect(fills).toContain('#f85149')
      view.sendToTubes('s2')
      expect(document.querySelector('#tubes .hd-warn-icon--critical')).toBeTruthy()
    } finally {
      ctx.fill = orig
    }
  })

  it('marks flagged tube rows and clears the mark when the warning goes away', () => {
    const warned = []
    const { view } = setup({ onWarningClick: (sid, name) => warned.push([sid, name]) })
    view.sendToTubes('s2')
    view.setWarnings(new Map([['s2', 'Overhang OH-B: self-dimer Tm 35.0 °C']]))
    const icon = document.querySelector('#tubes tr[data-strand-id="s2"] .hd-warn-icon')
    expect(icon?.title).toContain('Overhang OH-B: self-dimer Tm 35.0 °C')
    icon.click()
    expect(warned).toEqual([['s2', '6HB staple 2']])
    view.setWarnings(new Map())
    expect(document.querySelector('#tubes .hd-warn-icon')).toBeNull()
  })
})
