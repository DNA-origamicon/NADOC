import { afterEach, expect, it, vi } from 'vitest'
vi.mock('./import_origami_options.js', () => ({ chooseOrigamiImportOptions: vi.fn(), importRelaxationMessage: () => null }))
vi.mock('./file_browser.js', () => ({ openFileBrowser: vi.fn() }))
vi.mock('./toast.js', () => ({ showToast: vi.fn() }))
import { chooseOrigamiImportOptions } from './import_origami_options.js'
import { openFileBrowser } from './file_browser.js'
import { initImportMenu } from './import_menu.js'
afterEach(() => { vi.restoreAllMocks(); vi.clearAllMocks(); document.body.replaceChildren() })
function setup() {
  vi.spyOn(HTMLInputElement.prototype, 'click').mockImplementation(function () {
    Object.defineProperty(this, 'files', { value: [{ name: 'source.sc', text: async () => '{}' }] })
    this.onchange()
  })
  const api = { importCadnanoDesign: vi.fn(async () => ({ relaxation: { status: 'applied' } })),
    importScadnanoDesign: vi.fn(async () => ({ relaxation: { status: 'applied' } })),
    addRecentFile: vi.fn(), saveDesignAs: vi.fn(async () => ({})), deleteCluster: vi.fn() }
  const deps = { api, store: { getState: () => ({ currentDesign: { metadata: { name: 'source' }, cluster_transforms: [{ id: 'body' }] } }) },
    resetForNewDesign: vi.fn(), showWelcome: vi.fn(), hideWelcome: vi.fn(), renderRecentMenu: vi.fn(),
    setFileHandle: vi.fn(), setWorkspacePath: vi.fn(), setFileName: vi.fn(), setSyncStatus: vi.fn() }
  return { deps, menu: initImportMenu(deps) }
}
it.each(['Cadnano', 'Scadnano'])('library %s import forwards opt-in and retains fitted clusters', async format => {
  chooseOrigamiImportOptions.mockResolvedValue({ relaxOrigami: true })
  openFileBrowser.mockResolvedValue({ path: 'result.nadoc', name: 'result', includeClusters: false })
  const { deps, menu } = setup()
  await menu[`import${format}WithAutodetection`]()
  const call = deps.api[`import${format}Design`].mock.calls[0]
  expect(call.at(-1)).toEqual({ relaxOrigami: true })
  expect(deps.api.deleteCluster).not.toHaveBeenCalled()
  expect(openFileBrowser.mock.calls[0][0].autodetection).toBeNull()
  expect(deps.api.saveDesignAs).toHaveBeenCalled()
})
it('cancelling options preserves the current document', async () => {
  chooseOrigamiImportOptions.mockResolvedValue(null)
  const { deps, menu } = setup()
  await menu.importCadnanoWithAutodetection()
  expect(deps.resetForNewDesign).not.toHaveBeenCalled()
  expect(deps.api.importCadnanoDesign).not.toHaveBeenCalled()
})
