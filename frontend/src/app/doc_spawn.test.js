import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { spaceHasContent, initDocSpawn } from './doc_spawn.js'
import { createMockStore } from '../test-helpers/mock_store.js'

describe('spaceHasContent (pure)', () => {
  it('empty state → false', () => {
    expect(spaceHasContent({})).toBe(false)
    expect(spaceHasContent({ currentDesign: null, currentAssembly: null })).toBe(false)
  })

  it('design with helices → true', () => {
    expect(spaceHasContent({ currentDesign: { helices: [{}] } })).toBe(true)
  })

  it('design with strands → true', () => {
    expect(spaceHasContent({ currentDesign: { strands: [{}] } })).toBe(true)
  })

  it('design with feature_log entries → true', () => {
    expect(spaceHasContent({ currentDesign: { feature_log: [{}] } })).toBe(true)
  })

  it('design present but completely empty → false', () => {
    expect(spaceHasContent({ currentDesign: { helices: [], strands: [], feature_log: [] } })).toBe(false)
  })

  it('assembly with instances → true', () => {
    expect(spaceHasContent({ currentAssembly: { instances: [{}] } })).toBe(true)
  })

  it('assembly with feature_log entries → true', () => {
    expect(spaceHasContent({ currentAssembly: { feature_log: [{}] } })).toBe(true)
  })

  it('assembly present but empty → false', () => {
    expect(spaceHasContent({ currentAssembly: { instances: [], feature_log: [] } })).toBe(false)
  })
})

describe('initDocSpawn (factory)', () => {
  let openSpy
  beforeEach(() => {
    openSpy = vi.spyOn(window, 'open').mockImplementation(() => null)
  })
  afterEach(() => {
    openSpy.mockRestore()
  })

  it('spaceHasContent reads from the store', () => {
    const store = createMockStore({ currentDesign: { helices: [{}] } })
    const { spaceHasContent: has } = initDocSpawn({ store, mintDocId: vi.fn() })
    expect(has()).toBe(true)
    store.setState({ currentDesign: { helices: [] } })
    expect(has()).toBe(false)
  })

  it('spawnDocTabIfBusy on an empty space → false, no mint, no window.open', async () => {
    const store = createMockStore({})
    const mintDocId = vi.fn()
    const { spawnDocTabIfBusy } = initDocSpawn({ store, mintDocId })
    expect(await spawnDocTabIfBusy('new=assembly')).toBe(false)
    expect(mintDocId).not.toHaveBeenCalled()
    expect(openSpy).not.toHaveBeenCalled()
  })

  it('busy space → mints id, opens encoded tab, returns true', async () => {
    const store = createMockStore({ currentDesign: { strands: [{}] } })
    const mintDocId = vi.fn().mockResolvedValue('abc 123')
    const { spawnDocTabIfBusy } = initDocSpawn({ store, mintDocId })
    expect(await spawnDocTabIfBusy('new=assembly')).toBe(true)
    expect(mintDocId).toHaveBeenCalledOnce()
    expect(openSpy).toHaveBeenCalledWith('/?doc=abc%20123&new=assembly', 'nadoc-doc-abc 123')
  })

  it('busy space but mint fails → false, no window.open', async () => {
    const store = createMockStore({ currentAssembly: { instances: [{}] } })
    const mintDocId = vi.fn().mockResolvedValue(null)
    const { spawnDocTabIfBusy } = initDocSpawn({ store, mintDocId })
    expect(await spawnDocTabIfBusy('new=assembly')).toBe(false)
    expect(openSpy).not.toHaveBeenCalled()
  })
})
