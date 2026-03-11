/**
 * Validation report panel — live display of the ValidationReport.
 *
 * Subscribes to store.validationReport and renders color-coded rows into
 * #validation-report-content.
 */

import { store } from '../state/store.js'

export function initValidationReportPanel() {
  const content = document.getElementById('validation-report-content')
  if (!content) return

  function _render(report) {
    if (!report) {
      content.innerHTML = '<span class="dim">No validation data.</span>'
      return
    }

    const rows = report.results.map(r => `
      <div class="vr-row ${r.ok ? 'vr-ok' : 'vr-fail'}">
        <span class="vr-icon">${r.ok ? '✓' : '✗'}</span>
        <span class="vr-msg">${r.message}</span>
      </div>
    `).join('')

    const summary = report.passed
      ? '<div class="vr-summary vr-ok-summary">All checks passed</div>'
      : '<div class="vr-summary vr-fail-summary">Validation failed</div>'

    content.innerHTML = summary + rows
  }

  _render(store.getState().validationReport)

  store.subscribe((newState, prevState) => {
    if (newState.validationReport !== prevState.validationReport) {
      _render(newState.validationReport)
    }
  })
}
