// Autobreak modal — the routing dialog that runs the simple deterministic
// staple breaker: nick at every major tick, then merge fragments up to 56 nt.
// (The Aksel thermodynamic optimizer was removed.)
import { showToast }                      from './toast.js'
import { showOpProgress, hideOpProgress } from './op_progress.js'
import { createModal }                    from './primitives/modal.js'
import { createButton }                   from './primitives/button.js'

export function initAutobreakModal({ store, api }) {
  let _abModalCtrl = null
  let _abBody      = null

  async function _runAutoBreak3d() {
    _abModalCtrl?.close()
    showOpProgress('Autobreak', 'Running nick planner…')
    const result = await api.addAutoBreak({})
    hideOpProgress()
    if (!result) {
      showToast('Autobreak failed: ' + (store.getState().lastError?.message ?? 'unknown error'), { severity: 'error' })
    } else {
      showToast('Autobreak complete.')
    }
  }

  function _buildOnce() {
    if (_abModalCtrl) return
    _abBody = document.getElementById('autobreak-modal-body')
    if (!_abBody) return
    _abBody.removeAttribute('hidden')
    const cancelBtn = createButton({ label: 'Cancel', variant: 'default', onClick: () => _abModalCtrl.close() })
    const runBtn    = createButton({ label: 'Run Autobreak', variant: 'primary', onClick: _runAutoBreak3d })
    _abModalCtrl = createModal({
      title: 'Autobreak staples',
      size: 'md',
      body: _abBody,
      actions: [cancelBtn, runBtn],
    })
  }

  function openModal() {
    if (!store.getState().currentDesign?.helices?.length) {
      showToast('No design loaded.', { severity: 'error' }); return
    }
    _buildOnce()
    _abModalCtrl?.open()
  }

  document.getElementById('menu-routing-autobreak')?.addEventListener('click', openModal)

  return { openModal }
}
