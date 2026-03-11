/**
 * Properties panel — shows selected object details in the right panel.
 *
 * Subscribes to store.selectedObject and renders into #properties-content.
 */

import { store } from '../state/store.js'
import * as api from '../api/client.js'

export function initPropertiesPanel() {
  const content = document.getElementById('properties-content')
  if (!content) return

  function _fmt(arr) {
    return arr.map(v => Number(v.toFixed(4))).join(', ')
  }

  function _render(selectedObject) {
    if (!selectedObject) {
      content.innerHTML = '<span class="dim">Click a backbone bead to select.</span>'
      return
    }

    const nuc = selectedObject.data

    // Find the helix from the current design for its metadata.
    const design = store.getState().currentDesign
    const helix  = design?.helices?.find(h => h.id === nuc.helix_id)

    const scaffoldTag = nuc.is_scaffold
      ? '<span class="tag tag-scaffold">scaffold</span>'
      : '<span class="tag tag-staple">staple</span>'

    const endTag = nuc.is_five_prime
      ? "<span class=\"tag tag-end\">5′ end</span>"
      : nuc.is_three_prime
        ? "<span class=\"tag tag-end\">3′ end</span>"
        : ''

    content.innerHTML = `
      <div class="prop-row">
        <span class="prop-label">helix</span>
        <span class="prop-val">${nuc.helix_id}</span>
      </div>
      <div class="prop-row">
        <span class="prop-label">bp</span>
        <span class="prop-val">${nuc.bp_index}</span>
        <span class="prop-label" style="margin-left:8px">dir</span>
        <span class="prop-val">${nuc.direction}</span>
      </div>
      <div class="prop-row">
        <span class="prop-label">strand</span>
        <span class="prop-val">${nuc.strand_id ?? '—'}</span>
        ${scaffoldTag} ${endTag}
      </div>
      <div class="prop-row">
        <span class="prop-label">backbone</span>
        <span class="prop-val mono">[${_fmt(nuc.backbone_position)}]</span>
      </div>
      <div class="prop-row">
        <span class="prop-label">base&nbsp;&nbsp;&nbsp;</span>
        <span class="prop-val mono">[${_fmt(nuc.base_position)}]</span>
      </div>
      ${helix ? `
      <div class="prop-row" style="margin-top:6px; border-top:1px solid #21262d; padding-top:6px">
        <span class="prop-label">helix len</span>
        <span class="prop-val">${helix.length_bp} bp</span>
      </div>
      <button class="danger-btn" id="delete-helix-btn">Delete helix</button>
      ` : ''}
    `

    const delBtn = content.querySelector('#delete-helix-btn')
    if (delBtn) {
      delBtn.addEventListener('click', async () => {
        const r = await api.deleteHelix(nuc.helix_id)
        if (!r) {
          const err = store.getState().lastError
          alert(`Cannot delete helix: ${err?.message}`)
        } else {
          store.setState({ selectedObject: null })
        }
      })
    }
  }

  // Initial render
  _render(store.getState().selectedObject)

  // Subscribe
  store.subscribe((newState, prevState) => {
    if (newState.selectedObject !== prevState.selectedObject) {
      _render(newState.selectedObject)
    }
  })
}
