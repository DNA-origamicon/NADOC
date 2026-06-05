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
  let _ascTargetStrandId  = null   // strand id passed in from the right-click "Assign Scaffold for strand…" path
  let _ascTotalNt         = 0      // scaffold length captured at open time

  function _ascUpdateWarning() {
    if (!_ascBody) return
    const customSeqEl = _ascBody.querySelector('#asc-custom-seq')
    const warnEl      = _ascBody.querySelector('#asc-warning')
    if (!warnEl) return
    const customRaw = customSeqEl?.value?.replace(/\s/g, '').toUpperCase() ?? ''
    const scaffoldName = _ascBody.querySelector('input[name="asc-scaffold"]:checked')?.value ?? 'M13mp18'
    const text = ascWarningText({
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

    // Wire field events once.
    _ascBody.querySelectorAll('input[name="asc-scaffold"]').forEach(r => r.addEventListener('change', _ascUpdateWarning))
    const customSeqEl = _ascBody.querySelector('#asc-custom-seq')
    customSeqEl?.addEventListener('input', () => {
      const raw = customSeqEl.value.replace(/\s/g, '').toUpperCase()
      const charCountEl = _ascBody.querySelector('#asc-custom-char-count')
      const customErrEl = _ascBody.querySelector('#asc-custom-error')
      if (charCountEl) charCountEl.textContent = `${raw.length} nt`
      const bad = [...new Set(raw.replace(/[ATGCN]/g, ''))]
      if (bad.length > 0) {
        if (customErrEl) { customErrEl.textContent = `Invalid: ${bad.join(', ')}`; customErrEl.style.display = 'inline' }
      } else {
        if (customErrEl) { customErrEl.textContent = ''; customErrEl.style.display = 'none' }
      }
      _ascUpdateWarning()
    })
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
    const scaffoldName = _ascBody.querySelector('input[name="asc-scaffold"]:checked')?.value ?? 'M13mp18'
    const customRaw    = (_ascBody.querySelector('#asc-custom-seq')?.value ?? '').replace(/\s/g, '').toUpperCase()
    const customErrEl  = _ascBody.querySelector('#asc-custom-error')
    const targetStrandId = _ascTargetStrandId

    // Block if custom sequence has invalid characters
    if (customRaw && customErrEl?.textContent) return

    _ascModalCtrl.close()
    _ascTargetStrandId = null   // clear targeting after use

    const label = customRaw ? `custom (${customRaw.length} nt)` : scaffoldName
    showProgress('Assign Scaffold Sequence', `Assigning ${label} sequence…`)
    const json = await api.assignScaffoldSequence(scaffoldName, {
      customSequence: customRaw || null,
      strandId: targetStrandId,
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
    const totalNt = countScaffoldNt(currentDesign)

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
    _ascUpdateWarning()
    _ascModalCtrl.open()
  }

  document.getElementById('menu-seq-assign-scaffold')?.addEventListener('click', () => openModal(null))

  return { openModal }
}
