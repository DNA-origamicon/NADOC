/** Shared presentation for jobs whose external storage is unavailable. */
export function storageUnavailable(job) {
  return job?.storage_available === false
}

export function storageUnavailableMessage(job) {
  return `Simulation storage is unavailable. Connect or mount the drive at ${job?.archive_path || 'its saved location'} to enable visualization.`
}

export function gateStorageVisualization(job, controls) {
  const unavailable = storageUnavailable(job)
  for (const control of controls) {
    if (!control) continue
    const label = control.closest('label')
    if (label?.dataset.storageTitle !== undefined) {
      label.title = label.dataset.storageTitle
      delete label.dataset.storageTitle
    }
    if (!unavailable) continue
    control.disabled = true
    if (label) {
      label.dataset.storageTitle = label.title || ''
      label.title = storageUnavailableMessage(job)
      label.style.opacity = '0.5'
      label.style.cursor = 'not-allowed'
    }
  }
  return unavailable
}

export function disconnectedStorageIcon(path, doc = document) {
  const icon = doc.createElement('span')
  icon.dataset.storageUnavailable = 'true'
  icon.title = storageUnavailableMessage({ archive_path: path })
  icon.setAttribute('aria-label', icon.title)
  icon.setAttribute('role', 'img')
  icon.tabIndex = 0
  icon.style.cssText = 'display:inline-flex;flex:0 0 18px;width:18px;height:18px;align-items:center'
  icon.innerHTML = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" aria-hidden="true"><rect x="3" y="2" width="14" height="19" rx="2" fill="#263342" stroke="#aab7c4" stroke-width="1.5"/><path d="M6 5h8M6 17h5M6 19h5" stroke="#aab7c4" stroke-width="1.5"/><circle cx="16" cy="16" r="6.5" fill="#18212b" stroke="#f85149" stroke-width="2"/><path d="m11.5 20.5 9-9" stroke="#f85149" stroke-width="2"/></svg>'
  icon.addEventListener('click', event => event.stopPropagation())
  return icon
}
