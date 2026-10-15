import { createPartRepairController } from '../features/part_repair_controller.js'
import { cloneRepairInput, resolveRepairFeature, sameRepairContext } from '../features/part_repair_model.js'
import { actionFromRepairField, replacementRepairSource, updateRepairActions } from '../features/part_repair_fields.js'
import { getDocId } from '../shared/doc_id.js'
import { createRepairInputEditor } from './part_repair_input_editor.js'
import { createModal } from './primitives/modal.js'
import { createButton } from './primitives/button.js'
import { el } from './primitives/dom.js'
import './part_repair_panel.css'

const targetKey = target => JSON.stringify([target.feature_id, target.child_id ?? null])
const publishedLabels = { unchecked: 'Published geometry: not checked', checking: 'Checking published geometry',
  verified: 'Published geometry: regenerated successfully', reproduced_import: 'Published geometry: regenerated from pinned imports',
  failed: 'Published geometry: replay did not verify it', stale: 'Published geometry: check is stale' }
const short = value => { const text = typeof value === 'string' ? value : JSON.stringify(value); return text?.length > 180 ? `${text.slice(0, 180)}…` : text }

/** Standard-part host. The controller owns requests; this module owns only the view/edit buffer. */
export function initPartRepairPanel({ store, api, host, isPartContext = () => !store.getState().assemblyActive,
  focusFeature = () => {}, getDocumentId = getDocId, digestSource }) {
  if (!host || !api.partRepairAPI) return null
  const getDesign = () => store.getState().currentDesign
  function getContext() {
    const design = getDesign()
    if (!isPartContext() || !design) return null
    const loadoutId = design.active_loadout_id ?? null
    const loadout = design.loadouts?.find(item => item.id === loadoutId)
    const metadata = store.getState().repairMetadata
    return { docId: getDocumentId(), designId: design.id, loadoutId,
      revision: api.currentRevisionWatermark(), cursor: design.feature_log_cursor ?? -1,
      subCursor: design.feature_log_sub_cursor ?? null, editable: !loadout?.protected && !store.getState().featureSeekPending,
      summary: metadata?.designId === design.id ? metadata.summary : null }
  }
  const controller = createPartRepairController({ api: api.partRepairAPI, getContext,
    subscribeContext: callback => store.subscribe(callback) })
  let modal, latest = controller.getState(), actions = [], dirty = false, lastDraft = null,
    renderedCatalog = null, selectedTarget = null, sourceWork = 0, sourceBusy = false, closing = false,
    localError = '', note = ''
  const pendingFiles = new Map()
  const error = el('p', { className: 'part-repair__error', attrs: { role: 'alert' } })
  const status = el('p', { attrs: { role: 'status', 'aria-live': 'polite' } })
  const issues = el('div', { className: 'part-repair__issues' }), proposal = el('ol', { className: 'part-repair__proposal' })
  const changes = el('p', { className: 'part-repair__muted' })
  const selector = el('select', { attrs: { 'aria-label': 'Feature to repair' } })
  const showError = value => { localError = value?.message ?? String(value); error.textContent = localError }
  const clearNotice = () => { localError = ''; note = ''; error.textContent = '' }
  const actionFor = (field, value) => {
    if (latest.inputs !== renderedCatalog || !renderedCatalog || renderedCatalog.revision !== latest.context?.revision) throw new Error('Inspect the current feature inputs before editing')
    return actionFromRepairField(renderedCatalog, field, value)
  }
  function addChange(field, value) {
    actions = updateRepairActions(actions, actionFor(field, value)); dirty = true
    clearNotice()
    controller.cancel(); renderProposal(); renderState(controller.getState())
  }
  async function sourceAction(field, file, operation, source) {
    const origin = latest.context, work = ++sourceWork
    clearNotice()
    sourceBusy = true; renderState(latest)
    try {
      if (!renderedCatalog?.fields.includes(field)) throw new Error('Inspect the current source input before choosing its file')
      if (operation === 'replace') {
        const descriptor = await replacementRepairSource(field, file, digestSource)
        if (work !== sourceWork || !sameRepairContext(origin, controller.getState().context)) return
        addChange(field, descriptor)
        if (pendingFiles.size >= 64) pendingFiles.clear()
        pendingFiles.set(descriptor.sha256, file)
        note = 'Replacement input prepared. Save the proposal, then upload its selected file.'
      } else {
        if (!latest.draft || dirty) throw new Error('Save the proposal before restoring or staging source bytes')
        if (file.size > field.source_binding.max_size_bytes || file.size !== source.size_bytes) throw new Error('The selected file does not match the named source byte allowance')
        const receipt = await controller.inspectSource({ operation, feature_id: renderedCatalog.feature_id,
          child_id: renderedCatalog.child_id, parameter: field.source_binding.parameter, source })
        if (receipt && work === sourceWork && sameRepairContext(origin, controller.getState().context)) {
          await controller.uploadSource(receipt, file)
        }
      }
    } catch (failure) { if (work === sourceWork) showError(failure) }
    finally { if (work === sourceWork) { sourceBusy = false; renderState(controller.getState()) } }
  }
  const editor = createRepairInputEditor({ onChange: addChange, onError: showError, onSource: sourceAction,
    getSelectedFile: source => pendingFiles.get(source?.sha256),
    onSelect: field => {
      if (!renderedCatalog?.fields.includes(field)) throw new Error('Inspect the current reference input before selecting a replacement')
      return controller.selectReferences({ feature_id: renderedCatalog.feature_id,
        child_id: renderedCatalog.child_id, parameter_path: field.parameter_path,
        expected_old: field.expected_old, limit: field.reference_selection.max_candidates })
    } })
  async function inspectTarget(target, path) {
    try {
      clearNotice()
      const resolved = resolveRepairFeature(getDesign(), target.feature_id, target.child_id)
      selectedTarget = { feature_id: resolved.featureId, child_id: resolved.childId }
      selector.value = targetKey(selectedTarget); focusFeature(resolved)
      const catalog = await controller.inspectInputs(selectedTarget)
      if (catalog && path) editor.focusPath(path)
    } catch (failure) { showError(failure) }
  }
  function rebuildFeatures() {
    selector.replaceChildren(el('option', { text: 'Select a feature', attrs: { value: '' } }))
    for (const [index, entry] of (getDesign()?.feature_log ?? []).entries()) {
      const entries = entry.feature_type === 'routing-cluster' ? (entry.children ?? []).map((child, sub) =>
        ({ label: `F${index + 1}.${sub + 1}: ${child.label ?? child.op_subtype}`, feature_id: entry.id, child_id: child.id }))
        : [{ label: `F${index + 1}: ${entry.label ?? entry.op_kind}`, feature_id: entry.id, child_id: null }]
      for (const target of entries) if (target.feature_id) selector.append(el('option', { text: target.label, attrs: { value: targetKey(target) } }))
    }
    selector.value = selectedTarget ? targetKey(selectedTarget) : ''
  }
  selector.addEventListener('change', () => {
    if (!selector.value) return
    const [feature_id, child_id] = JSON.parse(selector.value)
    void inspectTarget({ feature_id, child_id })
  })
  function renderProposal() {
    proposal.replaceChildren()
    actions.forEach((action, index) => {
      const text = action.action === 'set_input'
        ? `${action.feature_id}${action.child_id ? ` / ${action.child_id}` : ''} — ${JSON.stringify(action.parameter_path)}: ${short(action.expected_old)} → ${short(action.value)}`
        : `${action.feature_id}: numerical contract upgrade (separate molecular review required)`
      const remove = createButton({ label: 'Remove proposed change', size: 'sm', onClick: () => {
        actions = actions.filter((_item, position) => position !== index); dirty = true; controller.cancel(); renderProposal(); renderState(controller.getState())
      } })
      proposal.append(el('li', { children: [el('span', { text }), remove] }))
    })
    if (!actions.length) proposal.append(el('li', { text: 'No proposed input changes. Add a change, then save the proposal.' }))
  }
  async function mutate(operation) {
    clearNotice()
    const target = selectedTarget
    const result = operation === 'save' ? await controller.save(actions)
      : operation === 'rebase' ? await controller.rebase(dirty ? actions : undefined) : await controller.discard()
    if (result) {
      dirty = false; actions = cloneRepairInput(result.draft?.actions ?? []); renderProposal(); renderState(controller.getState())
      if (target && operation !== 'discard') await controller.inspectInputs(target)
    }
  }
  const buttons = {
    check: createButton({ label: 'Check published recipe', size: 'sm', onClick: () => { clearNotice(); return controller.check() } }),
    inspect: createButton({ label: 'Reload saved proposal', size: 'sm', onClick: async () => { clearNotice(); dirty = false; await controller.inspect() } }),
    save: createButton({ label: 'Save proposal', onClick: () => mutate('save') }),
    rebase: createButton({ label: 'Rebase proposal', onClick: () => mutate('rebase') }),
    discard: createButton({ label: 'Discard proposal', variant: 'danger', onClick: () => mutate('discard') }),
    evaluate: createButton({ label: 'Evaluate proposal', onClick: () => { clearNotice(); return controller.evaluate() } }),
    cancel: createButton({ label: 'Cancel evaluation', onClick: () => { clearNotice(); sourceWork++; sourceBusy = false; controller.cancel() } }),
    apply: createButton({ label: 'Apply evaluated proposal', variant: 'primary', onClick: () => { clearNotice(); return controller.apply() } }),
    refresh: createButton({ label: 'Refresh committed result', onClick: () => { clearNotice(); return controller.refreshCommitted() } }),
    resolve: createButton({ label: 'Check publication status', onClick: () => { clearNotice(); return controller.resolvePublication() } }),
  }
  function renderState(next) {
    const previous = latest
    latest = next
    launcher.hidden = !next.context
    launcher.textContent = next.summary ? 'Repair · saved proposal' : 'Check / repair recipe'
    if (!modal?.isOpen() || closing) return
    if (!next.context || (!next.loaded && (previous.loaded || !sameRepairContext(previous.context, next.context)))) {
      selectedTarget = null; modal.close(); return
    }
    const busy = !!next.busy || sourceBusy, current = next.context?.cursor === -1 && next.context?.subCursor == null
    const publicationPending = next.refreshNeeded || !!next.publication
    const editable = next.context?.editable && current && !publicationPending
    status.textContent = `${publishedLabels[next.publishedStatus]}.${next.publication ? (next.publication.outcome === 'pending' ? ' Publication is in progress.' : ' Publication status is unknown; check its status before continuing.') : ''}${next.refreshNeeded ? ` Proposal published at revision ${next.committed.revision}; display refresh is still needed.` : ''}${next.summary ? ` Proposal ${next.summary.generation + 1}: ${next.summary.base_status === 'rebase_required' ? 'explicit rebase required' : 'pending; not a verification result'}.` : ''}${!current ? ' Return to the latest feature to edit or evaluate.' : !next.context?.editable ? ' This loadout is read-only.' : ''}${busy ? ' Working…' : ''}`
    if (next.draft !== lastDraft && !dirty) { lastDraft = next.draft; actions = cloneRepairInput(next.draft?.actions ?? []); renderProposal() }
    error.textContent = next.error?.message ?? localError
    if (next.inputs !== renderedCatalog) { renderedCatalog = next.inputs; editor.render(renderedCatalog, next.draft?.actions ?? []) }
    editor.setSelection(next.selection); editor.setDisabled(busy || !editable)
    selector.disabled = busy || !current || publicationPending
    issues.replaceChildren()
    for (const issue of next.issues) {
      const row = el('div', { children: [el('span', { text: `${issue.code}: ${issue.detail ?? ''}` })] })
      if (issue.feature_id) row.append(createButton({ label: 'Inspect failing input', size: 'sm', disabled: busy,
        onClick: () => inspectTarget(issue, issue.parameter_path) }))
      issues.append(row)
    }
    const changed = next.result?.repair?.authoring_changes?.changed_fields
    if (next.requiresReview) changes.textContent = 'Numerical contract changes need the separate atom and junction comparison review before evaluation or Apply.'
    else if (changed) changes.textContent = `Evaluated changes: ${changed.join(', ') || 'none'}. Visual comparison is not available in this panel.`
    else if (next.result?.repair?.not_evaluated?.length) changes.textContent = `${next.result.repair.not_evaluated.length} later feature(s) were not evaluated after the failure.`
    else changes.textContent = note
    buttons.check.disabled = busy || !current || publicationPending
    buttons.inspect.disabled = busy || publicationPending
    buttons.save.disabled = busy || !editable || !dirty || !actions.length
    buttons.rebase.disabled = busy || !editable || !next.draft || (dirty && !actions.length)
    buttons.discard.disabled = busy || !editable || !next.draft
    buttons.evaluate.disabled = busy || !editable || !next.draft || dirty || next.requiresReview
    buttons.apply.disabled = busy || !editable || !next.ready || dirty || next.requiresReview
    buttons.cancel.disabled = next.busy === 'apply' || (!busy && !next.job)
    buttons.refresh.hidden = !next.refreshNeeded
    buttons.refresh.disabled = busy || !next.refreshNeeded
    buttons.resolve.hidden = !next.publication
    buttons.resolve.disabled = busy || !next.publication
    for (const button of proposal.querySelectorAll('button')) button.disabled = busy || !editable
  }
  const launcher = createButton({ label: 'Check / repair recipe', size: 'sm', onClick: () => open() })
  const body = el('div', { className: 'part-repair', children: [status,
    el('div', { className: 'part-repair__tools', children: [buttons.check, buttons.inspect] }), error, issues,
    el('label', { children: ['Feature inputs', selector] }), editor.root,
    el('h3', { text: 'Proposed input changes' }), proposal, changes] })
  modal = createModal({ title: 'Check and repair part recipe', size: 'lg', body,
    actions: [buttons.save, buttons.rebase, buttons.discard, buttons.evaluate, buttons.cancel, buttons.apply, buttons.refresh, buttons.resolve],
    onClose: () => {
      closing = true
      try { sourceWork++; sourceBusy = false; controller.cancel(); pendingFiles.clear(); dirty = false; clearNotice(); return true }
      finally { closing = false }
    } })
  const unsubscribe = controller.subscribe(renderState)
  const resetView = () => { selectedTarget = null; modal.close() }
  window.addEventListener('nadoc:document-reset', resetView)
  host.append(launcher)
  function open() {
    if (!getContext()) return
    clearNotice(); dirty = false; lastDraft = null; actions = []; renderProposal(); rebuildFeatures(); modal.open(); renderState(controller.getState())
    void controller.inspect()
  }
  return { open, controller, dispose() {
    modal.close(); unsubscribe(); controller.dispose(); launcher.remove(); pendingFiles.clear()
    window.removeEventListener('nadoc:document-reset', resetView)
  } }
}

export function focusPartRepairRow(list, target) {
  for (const row of list.querySelectorAll('.fl-repair-focus')) row.classList.remove('fl-repair-focus')
  const key = `${target.index + 1}${target.subIndex == null ? '' : `.${target.subIndex}`}`
  const row = list.querySelector(`[data-fl-row="${key}"]`)
  row?.classList.add('fl-repair-focus'); row?.scrollIntoView?.({ block: 'nearest' })
}
