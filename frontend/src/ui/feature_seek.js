/** Two-phase navigation; preview is display-only, editing resumes after commit. */
export function createFeatureSeekFeedback(thumb, panel, store) {
  const ring = document.createElement('span')
  ring.className = 'feature-seek-readiness'
  ring.setAttribute('role', 'status')
  ring.style.cssText = 'position:absolute;inset:-6px;border:2px solid #30363d;border-top-color:#58a6ff;border-radius:50%;pointer-events:none;display:none'
  thumb.append(ring)
  let animation
  const blockEditing = event => {
    // Keep the rail usable so a newer stage can replace a pending seek. Other
    // tools must not act on the old editable scene behind the visual preview.
    if (event.target?.closest?.('#fl-rail')) return
    event.preventDefault()
    event.stopImmediatePropagation()
  }
  return {
    setBusy(busy, error = null) {
      panel.setAttribute('aria-busy', String(busy))
      ring.style.display = busy ? '' : 'none'
      thumb.dataset.readiness = error ? 'error' : busy ? 'loading' : 'ready'
      thumb.title = error ? 'Could not load editable content. Scrub to a stage to retry.'
        : busy ? 'Helix-path preview — loading editable detail' : 'Ready to edit'
      ring.style.borderTopColor = error ? '#f85149' : '#58a6ff'
      ring.setAttribute('aria-label', error ? 'Editing unavailable. Scrub to retry.' : busy ? 'Loading editable stage' : 'Ready to edit')
      animation?.cancel()
      if (busy && !error) animation = ring.animate?.([{ transform: 'rotate(0deg)' }, { transform: 'rotate(360deg)' }], { duration: 850, iterations: Infinity })
      store.setState?.({ featureSeekPending: busy })
      for (const type of ['pointerdown', 'click', 'contextmenu', 'keydown']) {
        window[busy ? 'addEventListener' : 'removeEventListener'](type, blockEditing, true)
      }
    },
  }
}

export async function seekWithPreview({ api, position, subPosition, showPreview, isSuperseded = () => false }) {
  let clearPreview
  let commitStarted = false
  const designId = api.currentDesignId?.()
  try {
    const preview = showPreview && api.previewFeatures
      ? await api.previewFeatures(position, subPosition) : null
    if (isSuperseded() || (designId && api.currentDesignId() !== designId)) return null
    if (preview) {
      clearPreview = showPreview(preview)
      // Let the simplified scene paint before starting the editable response.
      // The timeout also permits navigation in a background browser tab.
      await new Promise(resolve => {
        const timer = setTimeout(resolve, 50)
        requestAnimationFrame(() => requestAnimationFrame(() => { clearTimeout(timer); resolve() }))
      })
    }
    if (isSuperseded() || (designId && api.currentDesignId() !== designId)) return null
    commitStarted = true
    const result = await api.seekFeatures(position, subPosition, preview ? {
      preview_token: preview.preview_token,
    } : {})
    if (!result) throw new Error(api.lastErrorMessage?.() || 'Could not load the selected stage')
    return result
  } catch (error) {
    // A dropped response can follow a successful server commit. Reconcile the
    // real editable state before releasing the edit lock. If recovery fails,
    // keep editing locked, but leave the rail usable for another attempt.
    if (commitStarted && (!designId || api.currentDesignId?.() === designId)) {
      try {
        if (!await api.getDesign?.() || !await api.getGeometry?.()) error.editingUnavailable = true
      } catch { error.editingUnavailable = true }
    }
    throw error
  } finally {
    clearPreview?.()
  }
}
