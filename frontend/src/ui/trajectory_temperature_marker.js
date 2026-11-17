import '../styles/trajectory_temperature_marker.css'

export function trajectoryMarkerLabel(marker) {
  const stage = `${marker.label || ''}${marker.stage_name ? ` (${marker.stage_name})` : ''}`
  if (!Number.isFinite(marker.temperature_c)) return stage
  const temperature = `${Number(marker.temperature_c.toFixed(6))} °C`
  return `${temperature} — target temperature from frame ${marker.frame + 1} through ${Number.isInteger(marker.end_frame) ? marker.end_frame + 1 : 'the next marker'}. ${stage}`
}

/** A wider hit area keeps thin ticks usable without moving the playback thumb. */
export function createTrajectoryMarker(marker, color, doc = document) {
  const tick = doc.createElement('div')
  tick.className = 'trajectory-stage-marker'
  tick.style.left = `${marker.pct}%`
  tick.style.setProperty('--marker-color', color)
  tick.title = trajectoryMarkerLabel(marker)
  if (Number.isFinite(marker.temperature_c)) {
    tick.dataset.temperatureC = String(marker.temperature_c)
    tick.tabIndex = 0
    tick.setAttribute('role', 'img')
    tick.setAttribute('aria-label', tick.title)
    const tooltip = doc.createElement('span')
    tooltip.className = 'trajectory-temperature-tooltip'
    tooltip.setAttribute('role', 'tooltip')
    tooltip.setAttribute('popover', 'manual')
    tooltip.textContent = tick.title
    tick.append(tooltip)
    const show = () => {
      if (tooltip.showPopover) tooltip.showPopover()
      else tooltip.classList.add('is-visible')
      const bounds = tick.getBoundingClientRect(), box = tooltip.getBoundingClientRect()
      tooltip.style.left = `${Math.max(8, Math.min(bounds.left - box.width / 2, doc.documentElement.clientWidth - box.width - 8))}px`
      tooltip.style.top = `${Math.max(8, bounds.top - box.height - 6)}px`
    }
    const hide = () => {
      if (doc.activeElement === tick || tick.matches(':hover')) return
      if (tooltip.hidePopover) tooltip.hidePopover()
      tooltip.classList.remove('is-visible')
    }
    tick.addEventListener('mouseenter', show)
    tick.addEventListener('focus', show)
    tick.addEventListener('mouseleave', hide)
    tick.addEventListener('blur', hide)
  }
  return tick
}
