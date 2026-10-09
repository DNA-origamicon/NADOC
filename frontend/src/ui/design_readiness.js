/** Shared presentation for the 3D and pathview design-readiness indicator.
 * Hosts own report fetching, command availability, shortcuts, and subscriptions.
 * Mount inside a positioned viewport so the badge follows its sidebar layout.
 */

let nextPanelId = 0

/** Integrity can subtract one point; simulation is a separate next step. */
export function designReadinessSummary(report) {
  const total = Math.max(0, Math.trunc(Number(report?.total_steps) || 0))
  const completed = Math.max(0, Math.min(total, Math.trunc(Number(report?.completed_steps) || 0)))
  const penalty = report?.integrity_penalty === -1 ? -1 : 0
  const score = completed + penalty
  const complete = total > 0 && completed === total && penalty === 0
  const state = complete && report?.state === 'ready' && report?.simulation?.complete === true
    ? 'ready' : complete ? 'simulation_recommended' : 'incomplete'
  return {
    state,
    completed,
    total,
    score,
    penalty,
    fraction: total ? Math.max(0, score) / total : 0,
    label: !total && penalty ? 'Integrity issue' : `${score}/${total} readiness`,
    caption: state === 'ready' ? 'Simulation complete' : state === 'simulation_recommended' ? 'Sim recommended' : '',
  }
}

/**
 * @param {{host:HTMLElement,onAction?:(action:string,step:object)=>unknown}} options
 * Reports follow GET /design/readiness; hosts may add hotkey/blocked/blocked_reason.
 * The supplied host must be positioned. CSS offsets are --design-readiness-top,
 * --design-readiness-right and --design-readiness-left (all default to 12px).
 */
export function initDesignReadiness({ host, onAction, onDismiss } = {}) {
  if (!host) throw new TypeError('Design readiness needs a viewport host.')
  const doc = host.ownerDocument
  const win = doc.defaultView
  const panelId = `design-readiness-panel-${++nextPanelId}`
  const listeners = []
  let disposed = false
  let suppressed = false
  let userDismissed = false
  let explicitlyShown = false
  let contentVisible = false
  let isOpen = false
  let pinned = false
  let pointerInside = false
  let dismissed = false
  let closeTimer = null
  let actionGeneration = 0

  function element(tag, className, text) {
    const node = doc.createElement(tag)
    node.className = className
    if (text != null) node.textContent = text
    return node
  }
  function listen(node, type, handler, options) {
    node.addEventListener(type, handler, options)
    listeners.push(() => node.removeEventListener(type, handler, options))
  }

  const root = element('div', 'design-readiness')
  root.dataset.role = 'design-readiness'
  root.hidden = true
  const trigger = element('button', 'design-readiness__trigger')
  trigger.dataset.role = 'readiness-trigger'
  trigger.type = 'button'
  trigger.setAttribute('aria-expanded', 'false')
  trigger.setAttribute('aria-controls', panelId)
  const ring = doc.createElementNS('http://www.w3.org/2000/svg', 'svg')
  ring.setAttribute('viewBox', '0 0 36 36')
  ring.setAttribute('class', 'design-readiness__ring')
  ring.setAttribute('aria-hidden', 'true')
  for (const kind of ['track', 'progress']) {
    const circle = doc.createElementNS('http://www.w3.org/2000/svg', 'circle')
    circle.setAttribute('cx', '18')
    circle.setAttribute('cy', '18')
    circle.setAttribute('r', '14')
    circle.setAttribute('pathLength', '100')
    circle.setAttribute('class', `design-readiness__${kind}`)
    ring.append(circle)
  }
  const progress = ring.lastElementChild
  const text = element('span', 'design-readiness__text')
  const count = element('span', 'design-readiness__count')
  const caption = element('span', 'design-readiness__caption')
  text.append(count, caption)
  trigger.append(ring, text)

  // Padding belongs to the hover surface: crossing the visual gap never closes it.
  const popover = element('div', 'design-readiness__popover')
  popover.id = panelId
  popover.hidden = true
  const panel = element('section', 'design-readiness__panel')
  panel.setAttribute('aria-label', 'Design readiness')
  const heading = element('div', 'design-readiness__heading', 'Design readiness')
  const summaryText = element('p', 'design-readiness__summary')
  const rows = element('ul', 'design-readiness__steps')
  const simulationHost = element('div', 'design-readiness__simulation')
  const limitationsHost = element('div', 'design-readiness__limitations')
  const actionError = element('p', 'design-readiness__error')
  actionError.hidden = true
  actionError.setAttribute('role', 'status')
  panel.append(heading, summaryText, rows, simulationHost, limitationsHost, actionError)
  popover.append(panel)
  const dismissButton = element('button', 'design-readiness__dismiss', '×')
  dismissButton.type = 'button'
  dismissButton.setAttribute('aria-label', 'Dismiss design readiness')
  dismissButton.title = 'Dismiss design readiness'
  listen(dismissButton, 'click', event => {
    event.stopPropagation()
    userDismissed = true
    explicitlyShown = false
    applyVisibility()
    onDismiss?.()
  })
  root.append(trigger, dismissButton, popover)
  host.append(root)

  function cancelClose() {
    if (closeTimer !== null) win.clearTimeout(closeTimer)
    closeTimer = null
  }
  function open() {
    if (disposed || root.hidden || dismissed) return
    cancelClose()
    isOpen = true
    popover.hidden = false
    trigger.setAttribute('aria-expanded', 'true')
  }
  function close(returnFocus = false) {
    cancelClose()
    pinned = false
    dismissed = true
    isOpen = false
    popover.hidden = true
    trigger.setAttribute('aria-expanded', 'false')
    if (returnFocus && root.contains(doc.activeElement)) trigger.focus()
  }
  function scheduleClose() {
    cancelClose()
    closeTimer = win.setTimeout(() => {
      closeTimer = null
      if (!pinned && !pointerInside && !root.contains(doc.activeElement)) close()
    }, 160)
  }

  listen(root, 'pointerenter', () => { pointerInside = true; dismissed = false; open() })
  listen(root, 'pointerleave', () => { pointerInside = false; scheduleClose() })
  listen(root, 'focusin', event => {
    if (!root.contains(event.relatedTarget)) dismissed = false
    open()
  })
  listen(root, 'focusout', scheduleClose)
  listen(trigger, 'click', event => {
    event.stopPropagation()
    if (pinned) close()
    else { dismissed = false; pinned = true; open() }
  })
  listen(root, 'pointerdown', event => event.stopPropagation())
  listen(root, 'click', event => event.stopPropagation())
  listen(root, 'wheel', event => event.stopPropagation(), { passive: true })
  listen(root, 'keydown', event => {
    // Button activation, Tab navigation, and scrolling belong to this control.
    event.stopPropagation()
    if (event.key === 'Escape') { event.preventDefault(); close(true) }
  })
  listen(doc, 'pointerdown', event => {
    if (isOpen && !root.contains(event.target)) close()
  })
  listen(doc, 'keydown', event => {
    if (isOpen && event.key === 'Escape') { event.preventDefault(); close(true) }
  })

  function setBadge(state, label, sublabel, fraction) {
    contentVisible = state !== 'ready' || explicitlyShown
    applyVisibility()
    root.dataset.state = state
    count.textContent = label
    caption.textContent = sublabel
    caption.hidden = !sublabel
    progress.setAttribute('stroke-dasharray', `${fraction * 100} 100`)
    progress.style.opacity = fraction ? '1' : '0'
    trigger.setAttribute('aria-label', `Design readiness: ${label}${sublabel ? `; ${sublabel}` : ''}`)
  }

  function applyVisibility() {
    root.hidden = suppressed || userDismissed || !contentVisible
    if (root.hidden) close()
  }

  function setSuppressed(value) {
    if (disposed) return
    suppressed = !!value
    applyVisibility()
  }

  function renderStep(step, { simulation = false } = {}) {
    const integrity = step.id === 'topology'
    const applicable = step.applicable !== false
    const complete = applicable && step.complete === true
    const actionable = applicable && !complete && !!step.action && typeof onAction === 'function'
    const item = element(simulation ? 'div' : 'li', 'design-readiness__step')
    item.dataset.stepId = step.id || 'simulation'
    item.dataset.complete = String(complete)
    if (!applicable) item.classList.add('design-readiness__step--na')
    const body = element(actionable ? 'button' : 'div', 'design-readiness__step-body')
    if (actionable) {
      body.type = 'button'
      body.disabled = !!step.blocked
      body.dataset.action = step.action
      body.addEventListener('click', async () => {
        close(true)
        actionError.hidden = true
        const generation = ++actionGeneration
        try { await onAction(step.action, step) } catch (error) {
          if (disposed || generation !== actionGeneration) return
          actionError.textContent = error?.message || 'Unable to open this step.'
          actionError.hidden = false
          dismissed = false
          pinned = true
          open()
        }
      })
    }
    const marker = element('span', 'design-readiness__marker', !applicable ? '–' : integrity ? '!' : complete ? '✓' : simulation ? '↗' : '○')
    marker.setAttribute('aria-hidden', 'true')
    const content = element('span', 'design-readiness__step-content')
    const line = element('span', 'design-readiness__step-line')
    line.append(element('span', 'design-readiness__step-label', step.label || (simulation ? 'Fine / production simulation' : step.id)))
    const status = !applicable ? 'Not required' : integrity ? '−1 point' : complete ? 'Complete' : simulation ? 'Recommended' : 'Missing'
    line.append(element('span', 'design-readiness__step-state', status))
    content.append(line)
    if (step.detail) content.append(element('span', 'design-readiness__detail', step.detail))
    if (step.blocked) content.append(element('span', 'design-readiness__detail', step.blocked_reason || 'Unavailable in this view.'))
    body.append(marker, content)
    if (applicable && !step.blocked && step.hotkey) body.append(element('kbd', 'design-readiness__hotkey', step.hotkey))
    item.append(body)
    if (step.issues?.length) {
      const issues = element('details', 'design-readiness__issues')
      issues.append(element('summary', '', `${step.issues.length} issue${step.issues.length === 1 ? '' : 's'}`))
      const list = element('ul', '')
      for (const issue of step.issues) {
        const message = typeof issue === 'string' ? issue : issue?.message || issue?.detail || 'Review this design issue.'
        list.append(element('li', '', message))
      }
      issues.append(list)
      item.append(issues)
    }
    return item
  }

  function resetContents() {
    actionGeneration += 1
    actionError.hidden = true
    rows.replaceChildren()
    simulationHost.replaceChildren()
    simulationHost.hidden = true
    limitationsHost.replaceChildren()
    limitationsHost.hidden = true
  }

  function setReport(report) {
    if (disposed) return
    if (!report || report.available === false) {
      close()
      contentVisible = false
      applyVisibility()
      resetContents()
      return
    }
    const focusedAction = popover.contains(doc.activeElement) ? doc.activeElement.dataset?.action : null
    resetContents()
    const summary = designReadinessSummary(report)
    root.removeAttribute('aria-busy')
    setBadge(summary.state, summary.label, summary.caption, summary.fraction)
    summaryText.textContent = summary.state === 'ready'
      ? 'Standard steps complete; a matching fine or production simulation is complete.'
      : summary.state === 'simulation_recommended'
        ? 'Standard steps complete. A fine or production simulation is recommended.'
        : summary.penalty
          ? `${summary.completed}/${summary.total} steps complete. Resolve the design integrity issues to remove the 1-point penalty.`
          : 'Complete the missing steps to prepare this design.'
    for (const step of report.steps || []) {
      if (step.id === 'topology' && (step.complete || step.applicable === false)) continue
      rows.append(renderStep(step))
    }
    if (report.simulation) {
      simulationHost.hidden = false
      simulationHost.append(renderStep(report.simulation, { simulation: true }))
    }
    if (report.limitations?.length) {
      limitationsHost.hidden = false
      for (const limitation of report.limitations) limitationsHost.append(element('p', 'design-readiness__limitation', limitation))
    }
    if (focusedAction && isOpen) {
      const replacement = [...popover.querySelectorAll('button[data-action]')].find(button => button.dataset.action === focusedAction && !button.disabled)
      ;(replacement || trigger).focus()
    }
  }

  function setLoading() {
    if (disposed) return
    resetContents()
    root.setAttribute('aria-busy', 'true')
    setBadge('loading', 'Checking…', '', 0)
    summaryText.textContent = 'Checking the current design…'
  }

  function setError(message = 'Unable to check the current design.') {
    if (disposed) return
    resetContents()
    root.removeAttribute('aria-busy')
    setBadge('unavailable', 'Check unavailable', '', 0)
    summaryText.textContent = message
  }

  function dispose() {
    if (disposed) return
    disposed = true
    actionGeneration += 1
    cancelClose()
    for (const remove of listeners) remove()
    root.remove()
  }

  function reveal() {
    dismissed = false
    pinned = true
    open()
  }

  function focusStep(id) {
    reveal()
    const item = [...rows.children, ...simulationHost.children].find(row => row.dataset.stepId === id)
    const target = item?.querySelector('button:not(:disabled)') || trigger
    target.focus()
    item?.scrollIntoView?.({ block: 'nearest' })
  }

  function show() {
    userDismissed = false
    explicitlyShown = true
    applyVisibility()
  }

  function resetVisibility() {
    userDismissed = false
    explicitlyShown = false
  }

  return { show, resetVisibility, setReport, setLoading, setError, setSuppressed, open: reveal, focusStep, dispose }
}
