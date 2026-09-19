import { describe, it, expect, vi } from 'vitest'
import { createAnnotationController } from './annotation_controller.js'
import { annotationToWire, legacyStorageKeyFor, normalizeAnnotation } from './annotation_model.js'

const manualTimers = () => {
  const queue = []
  return { setTimer: fn => { queue.push(fn); return queue.length }, clearTimer: () => { queue.length = 0 }, run: () => queue.splice(0).forEach(fn => fn()) }
}
const memory = () => { const d = new Map(); return { d, getItem: k => d.get(k) ?? null, setItem: (k, v) => d.set(k, v), removeItem: k => d.delete(k) } }
const wireOf = (o = {}) => annotationToWire(normalizeAnnotation({ text: 'saved', ...o }))
const make = (over = {}) => {
  const t = manualTimers(), commit = vi.fn(async () => {})
  const c = createAnnotationController({ commit, legacyStorage: memory(), ...t, ...over })
  return { c, t, commit }
}
const design = (annotations = [], extra = {}) => ({ id: 'd1', annotations, annotations_enabled: true, ...extra })

describe('hydration from the design (the .nadoc is the source of truth)', () => {
  it('loads saved annotations and the global switch when a design opens', () => {
    const { c } = make()
    c.syncFromDesign(design([wireOf({ id: 'a', screenPos: { x: 0.3, y: 0.4 }, manual: true })], { annotations_enabled: false }))
    expect(c.list()).toHaveLength(1)
    expect(c.list()[0]).toMatchObject({ id: 'a', text: 'saved', manual: true, screenPos: { x: 0.3, y: 0.4 } })
    expect(c.isEnabled()).toBe(false)
  })
  it('an old file with no annotation fields opens empty and enabled', () => {
    const { c } = make()
    c.syncFromDesign({ id: 'old' })
    expect(c.list()).toEqual([]); expect(c.isEnabled()).toBe(true)
  })
  it('switching designs replaces the list and clears when no part is active', () => {
    const { c } = make()
    const events = []; c.subscribe(e => events.push(e.type))
    c.syncFromDesign(design([wireOf({ id: 'a' })]))
    c.syncFromDesign({ id: 'd2', annotations: [] })
    expect(c.list()).toEqual([])
    c.syncFromDesign(design([wireOf({ id: 'a' })]))
    c.syncFromDesign(null)
    expect(c.list()).toEqual([]); expect(c.getDesignId()).toBeNull()
    expect(events.filter(e => e === 'reset').length).toBeGreaterThanOrEqual(3)
  })
  it('follows an external change (undo/redo, another tab, reload) when nothing is pending', () => {
    const { c } = make()
    c.syncFromDesign(design([wireOf({ id: 'a' })]))
    c.syncFromDesign(design([wireOf({ id: 'a' }), wireOf({ id: 'b' })]))
    expect(c.list().map(e => e.id)).toEqual(['a', 'b'])
  })
  it('an unrelated design update with identical annotations is silent', () => {
    const { c } = make()
    c.syncFromDesign(design([wireOf({ id: 'a' })]))
    const fn = vi.fn(); c.subscribe(fn)
    c.syncFromDesign(design([wireOf({ id: 'a' })]))   // new array, same content
    expect(fn).not.toHaveBeenCalled()
  })
})

describe('committing edits', () => {
  it('debounces edits into one commit carrying the wire format and the switch', async () => {
    const { c, t, commit } = make()
    c.syncFromDesign(design())
    const a = c.add({ text: 'x' })
    c.update(a.id, { text: 'xy' })
    c.setEnabled(false)
    expect(commit).not.toHaveBeenCalled()
    t.run()
    await Promise.resolve()
    expect(commit).toHaveBeenCalledTimes(1)
    const arg = commit.mock.calls[0][0]
    expect(arg).toMatchObject({ designId: 'd1', enabled: false })
    expect(arg.annotations[0]).toMatchObject({ id: a.id, text: 'xy', callout_type: 'elbow' })
    expect(c.getCommitted().annotations).toBe(arg.annotations)
  })
  it('never lets an incoming design overwrite unsent or in-flight local edits', async () => {
    let release
    const { c, t } = make({ commit: () => new Promise(r => { release = r }) })
    c.syncFromDesign(design([wireOf({ id: 'a' })]))
    c.update('a', { text: 'typing' })
    c.syncFromDesign(design([wireOf({ id: 'a', text: 'stale from server' })]))   // unsent
    expect(c.get('a').text).toBe('typing')
    t.run(); await Promise.resolve()                                            // now in flight
    c.syncFromDesign(design([wireOf({ id: 'a', text: 'stale from server' })]))
    expect(c.get('a').text).toBe('typing')
    release(); await new Promise(r => setTimeout(r))
    expect(c.hasPendingEdits()).toBe(false)
  })
  it('drops unsent edits on a design switch instead of writing them into the new design', async () => {
    const { c, t, commit } = make()
    c.syncFromDesign(design())
    c.add({ text: 'for d1' })
    c.syncFromDesign({ id: 'd2', annotations: [] })
    t.run(); await Promise.resolve()
    expect(commit).not.toHaveBeenCalled()
    expect(c.list()).toEqual([])
  })
  it('a failed commit stays local and is retried by the next edit', async () => {
    const commit = vi.fn().mockRejectedValueOnce(new Error('net')).mockResolvedValue()
    const { c, t } = make({ commit })
    c.syncFromDesign(design())
    const a = c.add({ text: 'x' })
    t.run(); await new Promise(r => setTimeout(r))
    expect(c.hasPendingEdits()).toBe(true)
    c.update(a.id, { text: 'y' })
    t.run(); await new Promise(r => setTimeout(r))
    expect(commit).toHaveBeenCalledTimes(2)
    expect(c.hasPendingEdits()).toBe(false)
  })
  it('crud, normalisation and events', () => {
    const { c } = make()
    c.syncFromDesign(design())
    const events = []; c.subscribe(e => events.push([e.type, e.structural]))
    const a = c.add({ text: 'hello' })
    c.update(a.id, { size: 99 })
    c.update(a.id, { refs: [{ kind: 'strand', id: 's' }] })
    c.setEnabled(false); c.setEnabled(false)
    expect(c.get(a.id).size).toBe(2.5)
    expect(events).toEqual([['add', true], ['update', false], ['update', true], ['enabled', false]])
    expect(c.remove(a.id)).toBe(true); expect(c.remove('nope')).toBe(false)
    expect(c.update('nope', {})).toBeNull()
  })
  it('does not commit when no design is active', async () => {
    const { c, t, commit } = make()
    c.add({ text: 'orphan' })
    t.run(); await Promise.resolve()
    expect(commit).not.toHaveBeenCalled()
  })
})

describe('migration of annotations saved in browser storage before they lived in the file', () => {
  it('adopts them once into an annotation-less design, commits, and clears the old key', async () => {
    const legacyStorage = memory()
    legacyStorage.setItem(legacyStorageKeyFor('d1'), JSON.stringify({ version: 1, entries: [normalizeAnnotation({ id: 'old', text: 'legacy' })] }))
    const { c, t, commit } = make({ legacyStorage })
    c.syncFromDesign(design())
    expect(c.list().map(e => e.text)).toEqual(['legacy'])
    expect(legacyStorage.d.has(legacyStorageKeyFor('d1'))).toBe(false)
    t.run(); await Promise.resolve()
    expect(commit.mock.calls[0][0].annotations[0].id).toBe('old')
  })
  it('never overrides annotations already in the file', () => {
    const legacyStorage = memory()
    legacyStorage.setItem(legacyStorageKeyFor('d1'), JSON.stringify({ entries: [normalizeAnnotation({ text: 'legacy' })] }))
    const { c } = make({ legacyStorage })
    c.syncFromDesign(design([wireOf({ id: 'a' })]))
    expect(c.list().map(e => e.id)).toEqual(['a'])
  })
})
