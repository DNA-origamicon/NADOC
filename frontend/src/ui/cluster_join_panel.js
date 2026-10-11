/** Native Join controls use the shared non-modal CAD tool popup. */
import { createToolPopup } from './tool_popup.js'

export function createClusterJoinPanel({ onApply, onReset, onCancel, onParameters, onRefresh } = {}) {
  const panel = document.createElement('div')
  panel.id = 'cluster-join-panel'
  panel.className = 'panel-section'
  panel.style.display = 'none'
  panel.innerHTML = `<h2>Join clusters</h2>
    <p class="tool-picking-hint" data-join-step>Choose a fixed attachment point.</p>
    <fieldset class="tool-section"><legend>Attachment points</legend>
      <p class="tool-help" data-join-fixed>Fixed: not selected</p>
      <p class="tool-help" data-join-moving>Moving: not selected</p>
      <p class="tool-help">Hover near a cluster to reveal its scaffold side and end sites. The second cluster moves as a whole.</p>
    </fieldset>
    <fieldset class="tool-section"><legend>Placement</legend>
      <div class="def-row"><label for="cluster-join-gap">Gap</label><input id="cluster-join-gap" name="gap_nm" aria-label="Join gap (nm)" type="number" min="0.3" max="10" step="0.1" value="0.8"><span class="unit">nm</span></div>
      <div class="def-row"><label for="cluster-join-roll">Roll</label><input id="cluster-join-roll" name="roll_deg" aria-label="Join roll (degrees)" type="number" min="-180" max="180" step="1" value="0"><span class="unit">°</span></div>
      <div class="def-row"><label for="cluster-join-tilt">Tilt</label><input id="cluster-join-tilt" name="tilt_deg" aria-label="Join tilt (degrees)" type="number" min="-60" max="60" step="1" value="0"><span class="unit">°</span></div>
      <p class="tool-help">Roll and tilt adjust the moving cluster relative to the selected attachment normals.</p>
    </fieldset>
    <p class="tool-help" data-join-status role="status" aria-live="polite"></p>
    <p class="tool-help" data-join-report></p>
    <details data-join-details hidden><summary>Cluster eligibility</summary><ul class="tool-scroll-list"></ul></details>
    <div class="def-btn-row"><button class="def-btn" data-join-refresh type="button">Refresh sites</button><button class="def-btn" data-join-reset type="button">Reset picks</button></div>
    <div class="def-btn-row"><button class="def-btn" data-join-cancel type="button">Cancel</button><button class="def-btn primary" data-join-apply type="button" disabled>Apply join</button></div>`
  const popup = createToolPopup({ panel, title: 'Join clusters', onClose: onCancel })
  panel.querySelector('[data-join-apply]').addEventListener('click', () => onApply?.())
  panel.querySelector('[data-join-reset]').addEventListener('click', () => onReset?.())
  panel.querySelector('[data-join-cancel]').addEventListener('click', () => onCancel?.())
  panel.querySelector('[data-join-refresh]').addEventListener('click', () => onRefresh?.())
  for (const input of panel.querySelectorAll('input')) input.addEventListener('input', () => {
    const params = Object.fromEntries([...panel.querySelectorAll('input')].map(field => [field.name, field.value === '' ? NaN : Number(field.value)]))
    onParameters?.(params)
  })
  panel.addEventListener('keydown', event => { if (event.key !== 'Escape') event.stopPropagation() })
  return {
    panel, root: popup.root,
    show: () => popup.show(), hide: () => popup.hide(),
    render({ first, second, clusters = [], loading = false, applying = false, previewLoading = false, needsResync = false, status = '', canApply = false, preview = null, params }) {
      const label = site => {
        if (!site) return 'not selected'
        const name = clusters.find(cluster => cluster.cluster_id === site.cluster_id)?.name || site.cluster_id
        return `${name} · ${site.kind} · ${site.from?.helix_id || ''}${site.from?.bp_index != null ? ` / bp ${site.from.bp_index}` : ''}`
      }
      panel.querySelector('[data-join-fixed]').textContent = `Fixed: ${label(first)}`
      panel.querySelector('[data-join-moving]').textContent = `Moving: ${label(second)}`
      panel.querySelector('[data-join-step]').textContent = applying ? 'Joining the selected clusters…' : !first ? '1 · Choose the fixed attachment point.' : !second ? '2 · Choose a point on the moving cluster.' : '3 · Review the pose and scaffold bridges, then Apply join.'
      panel.querySelector('[data-join-status]').textContent = status
      panel.querySelector('[data-join-apply]').disabled = !canApply || applying || previewLoading || loading
      panel.querySelector('[data-join-apply]').textContent = applying ? 'Joining…' : 'Apply join'
      panel.querySelector('[data-join-reset]').disabled = applying || (!first && !second)
      panel.querySelector('[data-join-cancel]').disabled = applying
      panel.querySelector('[data-join-refresh]').disabled = applying || loading
      panel.querySelector('[data-join-refresh]').textContent = needsResync ? 'Refresh design' : 'Refresh sites'
      for (const input of panel.querySelectorAll('input')) {
        input.disabled = applying
        if (params && document.activeElement !== input && Number.isFinite(params[input.name])) input.value = String(params[input.name])
      }
      panel.querySelector('[data-join-report]').textContent = preview?.valid
        ? `${preview.scaffold_count_before} → ${preview.scaffold_count_after} scaffold paths · ${preview.bridges?.length ?? 0} directed bridges${Number.isFinite(preview.added_connector_nt) ? ` · +${preview.added_connector_nt} connector nt` : ''}${preview.warnings?.length ? ` · ${preview.warnings.join(' · ')}` : ''}` : ''
      const excluded = clusters.filter(cluster => !cluster.eligible)
      const details = panel.querySelector('[data-join-details]')
      details.hidden = !excluded.length
      details.querySelector('ul').replaceChildren(...excluded.map(cluster => {
        const item = document.createElement('li'); item.textContent = `${cluster.name || cluster.cluster_id}: ${cluster.reason || 'No valid attachment sites.'}`; return item
      }))
    },
    dispose: () => popup.dispose(),
  }
}
