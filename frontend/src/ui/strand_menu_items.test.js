import { describe, it, expect, vi } from 'vitest'
import { buildStrandMenuItems, dropEdgeSeparators } from './strand_menu_items.js'

const ALL = () => ({
  onSetReference: vi.fn(),
  onConvertToBinder: vi.fn(),
  onConvertToScaffold: vi.fn(),
  onEditSequence: vi.fn(),
  onAssignScaffoldSequence: vi.fn(),
  onEditExtensions: vi.fn(),
})

const labels = (items) => items.filter(i => !i.type).map(i => i.label)

describe('buildStrandMenuItems — visibility', () => {
  it('returns nothing when no strand is selected', () => {
    expect(buildStrandMenuItems({ strandIds: [] }, ALL())).toEqual([])
  })

  it('offers the hand-edit sequence dialog for a staple, not the scaffold modal', () => {
    const h = ALL()
    const items = buildStrandMenuItems({ strandIds: ['s1'], strandType: 'staple' }, h)
    expect(labels(items)).toContain('Edit sequence…')
    items.find(i => i.label === 'Edit sequence…').onClick()
    expect(h.onEditSequence).toHaveBeenCalledWith('s1')
    expect(h.onAssignScaffoldSequence).not.toHaveBeenCalled()
  })

  it('routes a scaffold to the scaffold-sequence modal instead', () => {
    const h = ALL()
    const items = buildStrandMenuItems({ strandIds: ['sc'], strandType: 'scaffold' }, h)
    items.find(i => i.label === 'Edit sequence…').onClick()
    expect(h.onAssignScaffoldSequence).toHaveBeenCalledWith('sc')
    expect(h.onEditSequence).not.toHaveBeenCalled()
  })

  it('uses the SAME label for both, so the two editors cannot drift', () => {
    const h = ALL()
    const staple = labels(buildStrandMenuItems({ strandIds: ['s'], strandType: 'staple' }, h))
    const scaf   = labels(buildStrandMenuItems({ strandIds: ['s'], strandType: 'scaffold' }, h))
    expect(staple.filter(l => l === 'Edit sequence…')).toHaveLength(1)
    expect(scaf.filter(l => l === 'Edit sequence…')).toHaveLength(1)
  })

  it('hides "Edit sequence…" for a reference scaffold', () => {
    const items = buildStrandMenuItems(
      { strandIds: ['sc'], strandType: 'scaffold', allReference: true }, ALL())
    expect(labels(items)).not.toContain('Edit sequence…')
  })

  it('hides the single-strand items for a multi-selection', () => {
    const items = buildStrandMenuItems({ strandIds: ['a', 'b'], strandType: 'staple' }, ALL())
    expect(labels(items)).not.toContain('Edit sequence…')
    expect(labels(items)).not.toContain('Convert to OH binding strand')
    expect(labels(items)).toContain('Make Reference')      // still applies to all
    expect(labels(items)).toContain('Edit extensions…')
  })

  it('offers "Convert to OH binding strand" only for a single scaffold', () => {
    const h = ALL()
    expect(labels(buildStrandMenuItems({ strandIds: ['s'], strandType: 'scaffold' }, h)))
      .toContain('Convert to OH binding strand')
    expect(labels(buildStrandMenuItems({ strandIds: ['s'], strandType: 'staple' }, h)))
      .not.toContain('Convert to OH binding strand')
  })

  it('offers "Convert to scaffold" only for a single OH binder', () => {
    const h = ALL()
    expect(labels(buildStrandMenuItems({ strandIds: ['s'], strandType: 'oh_binder' }, h)))
      .toContain('Convert to scaffold')
    expect(labels(buildStrandMenuItems({ strandIds: ['s'], strandType: 'staple' }, h)))
      .not.toContain('Convert to scaffold')
  })

  it('an OH binder still gets the hand-edit dialog', () => {
    expect(labels(buildStrandMenuItems({ strandIds: ['s'], strandType: 'oh_binder' }, ALL())))
      .toContain('Edit sequence…')
  })

  it('omits every item whose handler was not supplied', () => {
    const items = buildStrandMenuItems({ strandIds: ['s'], strandType: 'staple' }, {})
    expect(items).toEqual([])
  })

  it('shows only what a partial handler bag implements', () => {
    const items = buildStrandMenuItems(
      { strandIds: ['s'], strandType: 'staple' }, { onEditSequence: vi.fn() })
    expect(labels(items)).toEqual(['Edit sequence…'])
  })
})

describe('buildStrandMenuItems — reference toggle', () => {
  it('reads "Make Reference" when the selection is active', () => {
    const h = ALL()
    const items = buildStrandMenuItems({ strandIds: ['a', 'b'], allReference: false }, h)
    items.find(i => i.label === 'Make Reference').onClick()
    expect(h.onSetReference).toHaveBeenCalledWith(['a', 'b'], true)
  })

  it('reads "Make Active" when every selected strand is reference', () => {
    const h = ALL()
    const items = buildStrandMenuItems({ strandIds: ['a'], allReference: true }, h)
    items.find(i => i.label === 'Make Active').onClick()
    expect(h.onSetReference).toHaveBeenCalledWith(['a'], false)
  })

  it('offers both bulk actions when active and reference strands are selected', () => {
    const h = ALL()
    const items = buildStrandMenuItems({
      strandIds: ['active', 'reference'],
      allReference: false,
      anyReference: true,
    }, h)
    expect(labels(items)).toEqual(expect.arrayContaining(['Make Reference', 'Make Active']))

    items.find(i => i.label === 'Make Reference').onClick()
    items.find(i => i.label === 'Make Active').onClick()
    expect(h.onSetReference).toHaveBeenNthCalledWith(1, ['active', 'reference'], true)
    expect(h.onSetReference).toHaveBeenNthCalledWith(2, ['active', 'reference'], false)
  })
})

describe('buildStrandMenuItems — separators', () => {
  it('never emits a leading or trailing separator', () => {
    const items = buildStrandMenuItems(
      { strandIds: ['s'], strandType: 'staple' }, { onEditExtensions: vi.fn() })
    expect(items[0].type).not.toBe('separator')
    expect(items[items.length - 1].type).not.toBe('separator')
  })

  it('passes extensions the whole selection', () => {
    const h = ALL()
    const items = buildStrandMenuItems({ strandIds: ['a', 'b'] }, h)
    items.find(i => i.label === 'Edit extensions…').onClick()
    expect(h.onEditExtensions).toHaveBeenCalledWith(['a', 'b'])
  })
})

describe('dropEdgeSeparators', () => {
  it('collapses runs and trims both edges', () => {
    const sep = { type: 'separator' }
    const a = { label: 'a' }, b = { label: 'b' }
    expect(dropEdgeSeparators([sep, a, sep, sep, b, sep])).toEqual([a, sep, b])
  })
  it('tolerates an empty list', () => {
    expect(dropEdgeSeparators([])).toEqual([])
    expect(dropEdgeSeparators(undefined)).toEqual([])
  })
})
