/**
 * Assign Scaffold Sequence modal — extracted from main.js (stateful factory).
 *
 * Owns the lazy createModal-based dialog for assigning a reference (M13mp18 /
 * p7560 / p8064) or custom scaffold sequence. The pure cores (`ascWarningText`,
 * `countScaffoldNt`) live in scene/scaffold_assign.js and are unit-tested there.
 *
 * Opened two ways: the Sequencing menu item (wired here) and the scaffold
 * right-click "Assign Scaffold for strand…" path (main.js calls
 * `openModal(strandId)`).
 */
import { scaffoldSequenceChoice, updateScaffoldCustomInput, wireScaffoldCustomInput, validateScaffoldSequenceChoice } from './scaffold_custom_input.js'
import { mountScaffoldSequenceTarget, confirmScaffoldScope } from './scaffold_sequence_target.js'
import { createModal } from './primitives/modal.js'
import { createButton } from './primitives/button.js'
import { showToast } from './toast.js'
import { ascWarningText, SCAFFOLD_LENGTHS, countScaffoldNt } from '../scene/scaffold_assign.js'

/**
 * @param {object} deps
 * @param {object} deps.store
 * @param {object} deps.api
 * @param {(title: string, stage?: string) => void} deps.showProgress
 * @param {() => void} deps.hideProgress
 * @param {() => boolean} deps.getUndefinedHighlightOn
 * @param {() => void} deps.refreshUndefinedHighlight
 * @returns {{ openModal: (targetStrandId?: string|null) => void }}
 */
export function initScaffoldModal({ store, api, showProgress, hideProgress, getUndefinedHighlightOn, refreshUndefinedHighlight }) {
  let _ascModalCtrl       = null
  let _ascBody            = null
  let _ascTargetScope = null
  let _ascTargetStrandId  = null   // strand id passed in from the right-click "Assign Scaffold for strand…" path
  let _ascTotalNt         = 0      // scaffold length captured at open time

  function _ascUpdateWarning() {
    if (!_ascBody) return
    const warnEl      = _ascBody.querySelector('#asc-warning')
    if (!warnEl) return
    const { customRaw, scaffoldName } = scaffoldSequenceChoice(_ascBody)
    const text = scaffoldName === 'custom' && !customRaw ? null : ascWarningText({
      customRaw, totalNt: _ascTotalNt, scaffoldName, scaffoldLen: SCAFFOLD_LENGTHS[scaffoldName] ?? 0,
    })
    if (text) { warnEl.textContent = text; warnEl.style.display = 'block' }
    else warnEl.style.display = 'none'
  }

  function _buildScaffoldModalOnce() {
    if (_ascModalCtrl) return
    _ascBody = document.getElementById('assign-scaffold-modal-body')
    if (!_ascBody) return
    _ascBody.removeAttribute('hidden')

    const cancelBtn = createButton({
      label: 'Cancel',
      variant: 'default',
      onClick: () => { _ascTargetStrandId = null; _ascModalCtrl.close() },
    })
    const applyBtn = createButton({
      label: 'Apply',
      variant: 'primary',
      onClick: _onAscApplyClicked,
    })
    _ascModalCtrl = createModal({
      title: 'Assign Scaffold Sequence',
      size: 'sm',
      body: _ascBody,
      actions: [cancelBtn, applyBtn],
      onClose: () => { _ascTargetStrandId = null },
    })

    wireScaffoldCustomInput(_ascBody, _ascUpdateWarning)
    // Enter on the custom textarea is intentionally a newline; Enter elsewhere
    // commits via the modal's keydown handling.
    _ascBody.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && e.target?.tagName !== 'TEXTAREA') {
        e.preventDefault()
        applyBtn.click()
      }
    })
  }

  async function _onAscApplyClicked() {
    if (!_ascBody) return
    const choice = validateScaffoldSequenceChoice(_ascBody)
    if (!choice) return
    const { scaffoldName, customRaw } = choice
    let targetOptions
    try {
      const scope = _ascTargetScope.read()
      if (!await confirmScaffoldScope(scope)) return
      targetOptions = scope.options
    }
    catch (error) { showToast(error.message, { severity: 'error' }); return }

    _ascModalCtrl.close()
    _ascTargetStrandId = null   // clear targeting after use

    const label = customRaw ? `custom (${customRaw.length} nt)` : scaffoldName
    showProgress('Assign Scaffold Sequence', `Assigning ${label} sequence…`)
    const json = await api.assignScaffoldSequence(scaffoldName, {
      customSequence: customRaw || null,
      ...targetOptions,
    })
    hideProgress()
    if (!json) {
      showToast('Assign scaffold sequence failed: ' + (store.getState().lastError?.message ?? 'unknown'), { severity: 'error' })
      return
    }
    await api.syncScaffoldSequenceResponse(json)
    if (getUndefinedHighlightOn()) refreshUndefinedHighlight()
    const padMsg = json.padded_nt > 0 ? ` (${json.padded_nt} nt padded with N)` : ''
    showToast(`${label} sequence assigned.${padMsg}`)
  }

  function openModal(targetStrandId = null) {
    const { currentDesign } = store.getState()
    if (!currentDesign) { showToast('No design loaded.', { severity: 'error' }); return }

    _ascTargetStrandId = targetStrandId

    // Count scaffold nucleotides, honouring skips (delta=-1 → 0 nt) and
    // loops (delta=+1 → 2 nt), matching the backend _strand_nt_with_skips logic.
    const totalNt = countScaffoldNt(currentDesign, targetStrandId)

    _buildScaffoldModalOnce()
    if (!_ascModalCtrl) return
    const lengthEl     = _ascBody.querySelector('#asc-length-line')
    const customSeqEl  = _ascBody.querySelector('#asc-custom-seq')
    const charCountEl  = _ascBody.querySelector('#asc-custom-char-count')
    const customErrEl  = _ascBody.querySelector('#asc-custom-error')

    // Clear custom textarea and reset error state on (re)open
    if (customSeqEl) { customSeqEl.value = ''; }
    if (charCountEl) charCountEl.textContent = '0 nt'
    if (customErrEl) { customErrEl.textContent = ''; customErrEl.style.display = 'none' }

    lengthEl.textContent = `Scaffold length: ${totalNt} nt`
    _ascTotalNt = totalNt   // remembered for the apply path's warning + 'N' fill
    updateScaffoldCustomInput(_ascBody)
    _ascUpdateWarning()
    _ascTargetScope = mountScaffoldSequenceTarget({ body: _ascBody, design: currentDesign,
      state: store.getState(), explicitStrandId: targetStrandId,
      onChange: nt => { _ascTotalNt = nt; _ascUpdateWarning() },
    })
    _ascModalCtrl.open()
  }

  document.getElementById('menu-seq-assign-scaffold')?.addEventListener('click', () => openModal(null))

  return { openModal }
}
