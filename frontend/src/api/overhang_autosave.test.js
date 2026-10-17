import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { store } from '../state/store.js'
import { initAutosaveSync } from '../app/lifecycle.js'
import { wasLastDesignSyncTransient } from './client.js'
import {
  generateOverhangRandomSequence, generateSubDomainRandom,
  generateAllOverhangSequences, patchOverhang,
} from './overhang_endpoints.js'

vi.mock('../shared/broadcast.js', () => ({ nadocBroadcast: { emit: vi.fn() } }))

const saveWorkspace = vi.fn(async () => ({}))
const savePart = vi.fn(async () => ({}))
let partContext = null
const generatedDesign = {
  id: 'part', helices: [], strands: [{ id: 's1', sequence: 'ACGT' }],
  overhangs: [{ id: 'oh1', sequence: 'ACGT' }],
}

beforeAll(() => {
  initAutosaveSync({
    store,
    api: { wasLastDesignSyncTransient, saveDesignToWorkspace: saveWorkspace, subscribeLibraryEvents: vi.fn() },
    fileIo: { savePartToAssembly: savePart },
    syncBadge: { setSyncStatus: vi.fn(), syncLog: vi.fn() },
    libraryPanel: { refresh: vi.fn() },
    getPartEditContext: () => partContext,
    getWorkspacePath: () => 'parts/test.nadoc',
    getAssemblyWorkspacePath: () => null,
  })
})

beforeEach(() => {
  vi.useFakeTimers()
  saveWorkspace.mockClear()
  savePart.mockClear()
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: true, status: 200, headers: { get: () => null },
    json: async () => ({
      design: structuredClone(generatedDesign), validation: { loop_strand_ids: [] },
      geometry_unchanged: true, nucleotides: [], helix_axes: [],
      generated_overhang_ids: ['oh1'], generated_count: 1,
    }),
  })))
})

afterEach(() => {
  vi.clearAllTimers()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe.each(['workspace', 'assembly part'])('overhang Gen autosave: %s', (destination) => {
  it.each([
    ['whole overhang', () => generateOverhangRandomSequence('oh1')],
    ['sub-domain', () => generateSubDomainRandom('oh1', 'sd1')],
    ['all overhangs', () => generateAllOverhangSequences()],
    ['Gen reverse complement', () => patchOverhang('oh1', { sequence: 'ACGT' })],
  ])('%s persists the changed design through the normal save path', async (_label, generate) => {
    partContext = destination === 'assembly part' ? { instanceId: 'i1' } : null
    await generate()
    expect(store.getState().currentDesign.overhangs[0].sequence).toBe('ACGT')
    expect(store.getState().currentDesign.strands[0].sequence).toBe('ACGT')
    await vi.advanceTimersByTimeAsync(1500)
    if (partContext) {
      expect(savePart).toHaveBeenCalledExactlyOnceWith({ silent: true })
      expect(saveWorkspace).not.toHaveBeenCalled()
    } else {
      expect(saveWorkspace).toHaveBeenCalledExactlyOnceWith('parts/test.nadoc')
      expect(savePart).not.toHaveBeenCalled()
    }
  })
})
