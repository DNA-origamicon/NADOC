/** Host actions for the shared readiness checklist. Never repairs topology implicitly. */
import { createModal } from './primitives/modal.js'

const COMMANDS = {
  scaffold_routing: { id: 'menu-routing-scaffold-ends', hotkey: '1' },
  staple_routing: { id: 'menu-routing-full-autostaple', hotkey: '2' },
  scaffold_sequence: { id: 'menu-seq-assign-scaffold', hotkey: '5' },
  staple_sequences: { id: 'menu-seq-assign-staples', hotkey: '6' },
}

const HELP = {
  scaffold_routing: 'Choose a scaffold routing mode, then inspect the resulting strand path.',
  staple_routing: 'Full Autostaple assigns sequences and routes staples. Review its result before continuing.',
  scaffold_sequence: 'Assign the intended scaffold sequence using the sequence picker.',
  staple_sequences: 'Assign the scaffold sequence first, then derive complementary staple sequences. Edit unpaired or functional sequences in the strand spreadsheet.',
  validation: 'Inspect the listed strands, helices, or connections in the path view or Properties. Correct each issue and check readiness again. Readiness does not change topology automatically.',
}

function menuBlock(action, document) {
  const button = document?.getElementById(COMMANDS[action]?.id)
  if (!button) return 'This command is unavailable in the current editor.'
  if (button.disabled || button.getAttribute('aria-disabled') === 'true') {
    return 'This command is currently disabled. Finish or cancel the active tool, then try again.'
  }
  return null
}

/** Add host availability without changing the scientific readiness verdict. */
export function readinessActions(report, { document = globalThis.document, assembly = report?.context === 'assembly' } = {}) {
  if (!report) return report
  const decorate = step => {
    if (!step) return step
    const command = COMMANDS[step.action]
    const reason = !assembly && command ? menuBlock(step.action, document) : null
    return {
      ...step,
      hotkey: !assembly && command && !reason ? command.hotkey : null,
      blocked: !!step.blocked || !!reason,
      blocked_reason: step.blocked_reason || reason || null,
    }
  }
  return { ...report, steps: (report.steps ?? []).map(decorate), simulation: decorate(report.simulation) }
}

/**
 * Menu handlers own mutations, progress and cross-tab synchronization. Assembly
 * actions open the owning part editor; simulation actions only reveal controls.
 */
export function createDesignReadinessActions({
  store,
  mode = '3d',
  document = globalThis.document,
  window = globalThis.window,
  getDocId = () => new URL(window.location.href).searchParams.get('doc'),
  broadcast,
  onSimulate,
  openPartEditor,
} = {}) {
  let report = null
  let reportContext = null
  let modal = null
  let disposed = false

  function closeDetails() { modal?.close(); modal = null }

  function node(tag, text) {
    const result = document.createElement(tag)
    if (text != null) result.textContent = text
    return result
  }

  function isAssembly() {
    return !!store?.getState?.().assemblyActive || report?.context === 'assembly'
  }

  function currentDocument() {
    const state = store?.getState?.() ?? {}
    return state.assemblyActive ? state.currentAssembly : (state.currentDesign ?? state.design)
  }

  function assertCurrent(expected = reportContext) {
    if (disposed) throw new Error('The readiness panel has closed.')
    const current = currentDocument()
    if (expected && (current !== expected.document || getDocId() !== expected.docId
      || (expected.id && current?.id !== expected.id))) {
      throw new Error('The open document changed. Refresh readiness before choosing an action.')
    }
  }

  function openPart(target, action, expected = reportContext) {
    assertCurrent(expected)
    if (!target?.instance_id) throw new Error('This issue does not identify an owning part. Refresh readiness and inspect the assembly.')
    const instances = store?.getState?.().currentAssembly?.instances
    if (instances && !instances.some(instance => instance.id === target.instance_id)) {
      throw new Error('This part is no longer in the assembly. Refresh readiness.')
    }
    if (openPartEditor) return openPartEditor(target.instance_id, action)
    const asmDoc = getDocId()
    const params = new URLSearchParams({
      'part-instance': target.instance_id,
      doc: `pe-${asmDoc ?? 'default'}-${target.instance_id}`,
      readiness: action,
    })
    if (asmDoc) params.set('assembly-doc', asmDoc)
    const opened = window.open(`/?${params}`, `nadoc-part-${target.instance_id}`)
    if (!opened) throw new Error('Allow a popup to open the part editor, then try again.')
    opened.focus?.()
    return true
  }

  function details(step, { choosePart = false } = {}) {
    closeDetails()
    // A chooser remains tied to the report that opened it even if a background
    // refresh decorates another report while this modal is still visible.
    const expected = reportContext
    const body = node('div')
    body.dataset.readinessIssues = ''
    body.style.cssText = 'display:grid;gap:12px;max-height:65vh;overflow:auto;overflow-wrap:anywhere'
    body.append(node('p', step?.detail || 'Review the design issues below.'))
    const issues = step?.issues?.length ? step.issues : (report?.issues ?? [])
    if (issues.length) {
      const list = node('ul')
      list.style.cssText = 'margin:0;padding-left:20px;display:grid;gap:8px'
      for (const issue of issues) {
        list.append(node('li', typeof issue === 'string' ? issue : (issue.message ?? issue.detail ?? JSON.stringify(issue))))
      }
      body.append(list)
    }
    body.append(node('p', HELP[step?.action] ?? 'Review the affected part in its editor, then check readiness again.'))
    if (choosePart) {
      body.append(node('p', step.targets?.length
        ? 'Open an affected part to continue. Its editor will show this readiness step before you run the command.'
        : 'This issue belongs to the combined assembly. Inspect its part placement, cross-part connections and linker strands; no single part can be repaired automatically.'))
      for (const target of step.targets ?? []) {
        const row = node('div')
        row.style.cssText = 'display:grid;gap:4px'
        const button = node('button', `Open ${target.name || 'part'}`)
        button.type = 'button'
        button.className = 'panel-action-btn'
        button.addEventListener('click', async () => {
          try { await openPart(target, step.action, expected); closeDetails() }
          catch (error) { errorLine.textContent = error.message }
        })
        row.append(button)
        if (target.detail) row.append(node('span', target.detail))
        body.append(row)
      }
    }
    const errorLine = node('p')
    errorLine.setAttribute('role', 'alert')
    body.append(errorLine)
    const close = node('button', 'Close')
    close.type = 'button'
    close.className = 'panel-action-btn'
    close.addEventListener('click', closeDetails)
    modal = createModal({ title: step?.label || 'Design issues', body, actions: [close], size: 'md' })
    modal.open()
    close.focus()
    return true
  }

  function simulation() {
    if (mode !== 'cadnano') {
      if (onSimulate) return onSimulate()
      if (window.__leftSidebar?.selectTab) return window.__leftSidebar.selectTab('dynamics')
      throw new Error('Simulation controls are not available yet. Open the Simulations sidebar after the editor finishes loading.')
    }
    const docId = getDocId()
    const expected = docId || '__default__'
    try {
      const opener = window.opener
      if (opener && !opener.closed) {
        const url = new URL(opener.location.href)
        const sameOrigin = url.origin === new URL(window.location.href).origin
        const openerDoc = url.searchParams.get('doc')
        const is3dEditor = url.pathname === '/' || url.pathname === '/index.html'
        if (sameOrigin && is3dEditor && (openerDoc || '__default__') === expected) {
          opener.focus()
          if (broadcast?.emit) {
            broadcast.emit('readiness-action', { action: 'simulation', docId: docId === '__default__' ? null : docId })
            return true
          }
          if (opener.__leftSidebar?.selectTab) {
            opener.__leftSidebar.selectTab('dynamics')
            return true
          }
        }
      }
    } catch { /* Closed/cross-origin opener: use an explicitly scoped 3D window. */ }
    // An absent doc query makes the 3D app mint a fresh document. Pin the backend
    // default sentinel too, so standalone cadnano editors retain their document.
    const params = new URLSearchParams({ doc: expected, readiness: 'simulation' })
    const opened = window.open(`/?${params}`, `nadoc-readiness-3d-${expected}`)
    if (!opened) throw new Error('Allow a popup to open this design in 3D, then try again.')
    opened.focus?.()
    return true
  }

  function decorate(nextReport) {
    report = nextReport
    const current = currentDocument()
    const legacyAssemblyId = nextReport?.context === 'assembly'
      && nextReport.design_id === `flat_${current?.id}` ? current.id : nextReport?.design_id
    reportContext = nextReport ? {
      document: current,
      docId: getDocId(),
      id: nextReport.document_id || legacyAssemblyId,
    } : null
    return readinessActions(nextReport, { document, assembly: isAssembly() })
  }

  async function run(action, step = null) {
    assertCurrent()
    const currentStep = step ?? (report?.steps ?? []).find(candidate => candidate.action === action)
      ?? (action === 'simulation' ? report?.simulation : null)
      ?? { action }
    if (currentStep.blocked) throw new Error(currentStep.blocked_reason || 'This action is currently unavailable.')
    if (action === 'simulation') return simulation()
    if (action === 'validation') return details(currentStep, { choosePart: isAssembly() })
    if (!COMMANDS[action]) return details(currentStep)
    if (isAssembly()) {
      const targets = currentStep.targets ?? []
      if (targets.length === 1) return openPart(targets[0], action)
      return details(currentStep, { choosePart: true })
    }
    const reason = menuBlock(action, document)
    if (reason) throw new Error(reason)
    document.getElementById(COMMANDS[action].id).click()
    return true
  }

  return { decorate, run, dispose() { disposed = true; closeDetails() } }
}
