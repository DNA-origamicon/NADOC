import { beforeEach, expect, it, vi } from 'vitest'
vi.mock('./import_origami_options.js', () => ({ chooseOrigamiImportOptions: vi.fn(), importRelaxationMessage: () => null }))
vi.mock('./toast.js', () => ({ showToast: vi.fn() }))
import { chooseOrigamiImportOptions } from './import_origami_options.js'
import { importRecentDesign } from './import_recent_design.js'
beforeEach(() => vi.clearAllMocks())
it.each(['cadnano', 'scadnano'])('recent %s forwards the selected option', async type => {
  chooseOrigamiImportOptions.mockResolvedValue({ relaxOrigami: true })
  const api = { importCadnanoDesign: vi.fn(async () => ({})), importScadnanoDesign: vi.fn(async () => ({})) }
  const beforeImport = vi.fn()
  await importRecentDesign({ type, content: 'source' }, { api, beforeImport })
  expect(beforeImport).toHaveBeenCalledOnce()
  expect((type === 'cadnano' ? api.importCadnanoDesign : api.importScadnanoDesign).mock.calls[0].at(-1)).toEqual({ relaxOrigami: true })
})
it('cancel keeps the existing document', async () => {
  chooseOrigamiImportOptions.mockResolvedValue(null)
  const beforeImport = vi.fn()
  expect(await importRecentDesign({ type: 'cadnano' }, { api: {}, beforeImport })).toEqual({ cancelled: true })
  expect(beforeImport).not.toHaveBeenCalled()
})
it('native files reopen without a relaxation prompt', async () => {
  const api = { importDesign: vi.fn(async () => ({})) }
  await importRecentDesign({ content: 'native' }, { api, beforeImport: vi.fn() })
  expect(chooseOrigamiImportOptions).not.toHaveBeenCalled()
  expect(api.importDesign).toHaveBeenCalledWith('native')
})
