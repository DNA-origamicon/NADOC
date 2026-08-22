// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { initPlateView } from './plate_view.js'

const ctx = {
  setTransform: vi.fn(), fillRect: vi.fn(), fillText: vi.fn(), beginPath: vi.fn(),
  arc: vi.fn(), fill: vi.fn(), stroke: vi.fn(), moveTo: vi.fn(), arcTo: vi.fn(),
  closePath: vi.fn(), setLineDash: vi.fn(),
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

function setup() {
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
