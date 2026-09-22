/** Independent of the production wizard's rotational-diffusion override. */
export function mountImageClearanceReview(container, report, submitButton) {
  const data = report || {
    status: 'unknown', requires_override: true,
    detail: 'Periodic-image clearance was not provided. Reopen the review to check it.',
  }
  // Unknown/malformed results must not look like a successful measurement.
  const blocked = !['pass', 'not_applicable'].includes(data.status) || !!data.requires_override
  const heading = document.createElement('strong')
  heading.textContent = 'Periodic-image clearance'
  container.appendChild(heading)
  container.style.cssText = `border:1px solid ${blocked ? '#d29922' : '#30363d'};border-radius:4px;padding:8px;margin-bottom:10px;line-height:1.5`
  const detail = document.createElement('div')
  const gaps = data.axis_gaps_nm
  if (Array.isArray(gaps) && gaps.length === 3 && gaps.every(Number.isFinite)) {
    const measurements = document.createElement('div')
    measurements.textContent = `Envelope gaps X / Y / Z: ${gaps.map(v => v.toFixed(2)).join(' / ')} nm. Recommended minimum: ${Number(data.recommended_gap_nm).toFixed(2)} nm.`
    container.appendChild(measurements)
  }
  detail.textContent = data.detail || 'Clearance could not be verified.'
  container.appendChild(detail)
  if (data.coordinate_source) {
    const source = document.createElement('div')
    source.textContent = `Starting coordinates: ${data.coordinate_source}; cell: ${data.cell_source}.`
    source.style.color = '#8b949e'
    container.appendChild(source)
  }
  let checkbox = null
  if (blocked) {
    const label = document.createElement('label')
    label.style.cssText = 'display:block;margin-top:8px;color:#e3b341;cursor:pointer'
    checkbox = document.createElement('input')
    checkbox.type = 'checkbox'
    checkbox.id = 'mr-allow-small-image-gap'
    label.append(checkbox, document.createTextNode(' Submit anyway — I accept the periodic self-interaction risk.'))
    container.appendChild(label)
    checkbox.addEventListener('change', () => { submitButton.disabled = !checkbox.checked })
  }
  submitButton.disabled = blocked
  return {
    canSubmit: () => !blocked || !!checkbox?.checked,
    overridden: () => blocked && !!checkbox?.checked,
  }
}
