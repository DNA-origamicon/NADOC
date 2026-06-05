/**
 * New Part modal — extracted from main.js (stateful factory).
 *
 * The "New Part" dialog (File → New Part, the Ctrl+O-less new-design path) and
 * its create flow: build the lazy createModal once, open it with an
 * unsaved-changes warning, and on Create reset the editor, create the design,
 * and persist it to the workspace so auto-save has a path.
 *
 * Lifecycle-spine touchpoints (`resetForNewDesign` / `setFileName` /
 * `hideWelcome` / `setWorkspacePath` / `setFileHandle`) and the multi-document
 * spawn guard (`spawnDocTabIfBusy`) stay in main() and are injected — this
 * module owns only the dialog + its create flow. Opened from the File menu
 * (wired here) and from the boot-doc-action path (main.js calls openModal()).
 */
import { createModal } from './primitives/modal.js'
import { createButton } from './primitives/button.js'

/**
 * Sanitize a part name into a safe workspace file stem (kept char class +
 * trimmed, falling back to 'untitled'). Pure. (Was the inline expression in
 * _onCreateClicked.)
 */
export function sanitizeWorkspaceStem(name) {
  return name.replace(/[^a-zA-Z0-9-_ ]/g, '_').trim() || 'untitled'
}

/**
 * @param {object} deps
 * @param {object} deps.store
 * @param {object} deps.api
 * @param {object} deps.workspace
 * @param {() => void} deps.resetForNewDesign
 * @param {(name: string|null) => void} deps.setFileName
 * @param {() => void} deps.hideWelcome
 * @param {(path: string|null) => void} deps.setWorkspacePath
 * @param {(handle: any) => void} deps.setFileHandle
 * @param {() => (object|null)} deps.getLibraryPanel  lazy (libraryPanel is wired later)
 * @param {(actionQuery: string) => Promise<boolean>} deps.spawnDocTabIfBusy
 * @returns {{ openModal: () => void }}
 */
export function initNewDesignModal({
  store, api, workspace,
  resetForNewDesign, setFileName, hideWelcome, setWorkspacePath, setFileHandle,
  getLibraryPanel, spawnDocTabIfBusy,
}) {
  let _newDesignModalCtrl = null   // { open, close, ... } from createModal
  let _newDesignBody      = null   // detached body element with form fields

  function _buildNewDesignModalOnce() {
    if (_newDesignModalCtrl) return
    _newDesignBody = document.getElementById('new-design-modal-body')
    if (!_newDesignBody) return
    _newDesignBody.removeAttribute('hidden')

    const cancelBtn = createButton({
      label: 'Cancel',
      variant: 'default',
      onClick: () => _newDesignModalCtrl.close(),
    })
    const createBtn = createButton({
      label: 'Create',
      variant: 'primary',
      onClick: _onCreateClicked,
    })

    _newDesignModalCtrl = createModal({
      title: 'New Part',
      size: 'sm',
      body: _newDesignBody,
      actions: [cancelBtn, createBtn],
    })

    // Enter in the name input commits.
    const nameInput = _newDesignBody.querySelector('#new-design-name')
    nameInput?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); createBtn.click() }
    })
  }

  function openModal() {
    _buildNewDesignModalOnce()
    if (!_newDesignModalCtrl) {
      // HTML body not in the DOM (no template) — fast-create an Untitled part
      // so the menu item never silently fails.
      resetForNewDesign(); setFileHandle(null); workspace.show()
      api.createDesign('Untitled')
      return
    }
    // Show unsaved-changes warning when a design with helices is already loaded
    const hasDesign = !!(store.getState().currentDesign?.helices?.length)
    const warn = _newDesignBody.querySelector('#new-design-unsaved-warn')
    if (warn) warn.style.display = hasDesign ? 'block' : 'none'
    // Clear name field and hide any previous error
    const nameInput = _newDesignBody.querySelector('#new-design-name')
    const nameError = _newDesignBody.querySelector('#new-design-name-error')
    if (nameInput) { nameInput.value = ''; nameInput.style.borderColor = '' }
    if (nameError) nameError.style.display = 'none'
    _newDesignModalCtrl.open()
    setTimeout(() => nameInput?.focus(), 50)
  }

  async function _onCreateClicked() {
    const nameInput = _newDesignBody.querySelector('#new-design-name')
    const nameError = _newDesignBody.querySelector('#new-design-name-error')
    const name      = nameInput?.value.trim() ?? ''
    if (!name) {
      if (nameInput) nameInput.style.borderColor = '#f85149'
      if (nameError) nameError.style.display = 'block'
      nameInput?.focus()
      return
    }
    const checked = _newDesignBody.querySelector('input[name="new-lattice-type"]:checked')
    const lattice = checked?.value ?? 'HONEYCOMB'
    _newDesignModalCtrl.close()
    resetForNewDesign()
    setFileHandle(null)
    setFileName(name)
    hideWelcome()
    workspace.show(lattice)
    await api.createDesign(name, lattice)
    // Save to workspace immediately so auto-save has a target path
    const safeStem = sanitizeWorkspaceStem(name)
    const wsResult = await api.uploadLibraryFile(
      JSON.stringify(store.getState().currentDesign), `${safeStem}.nadoc`,
    )
    if (wsResult?.path) {
      setWorkspacePath(wsResult.path)
      getLibraryPanel()?.refresh()
    }
  }

  document.getElementById('menu-file-new')?.addEventListener('click', async () => {
    if (await spawnDocTabIfBusy('new=part')) return
    openModal()
  })

  return { openModal }
}
