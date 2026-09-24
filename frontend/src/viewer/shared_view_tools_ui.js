import { VIEW_TOOLS } from './shared_view_tools.js'
import './shared_view_tools.css'

/** Read-only legend: geometry remains the authoritative host-rendered overlay. */
export function mountSharedViewTools(parent) {
  const doc = parent.ownerDocument, root = doc.createElement('aside')
  root.className = 'shared-view-tools'; root.setAttribute('aria-label', 'Shared view tools'); root.hidden = true
  parent.append(root)
  return { update(value, visualization = null) {
    root.replaceChildren(); root.hidden = !visualization && (!value || !Object.keys(VIEW_TOOLS).some(k => value[k]))
    if (root.hidden) return
    if (visualization) {
      const heading = doc.createElement('strong')
      heading.textContent = `${{ oxdna: 'oxDNA', namd: 'NAMD', lammps: 'LAMMPS' }[visualization.engine]} · ${visualization.mode}`
      const job = doc.createElement('div'); job.textContent = visualization.jobName
      const date = doc.createElement('div')
      date.textContent = visualization.runDate ? `Run: ${new Date(visualization.runDate).toLocaleString(undefined, { timeZoneName: 'short' })}` : 'Run date unavailable'
      root.append(heading, job, date)
    }
    value ??= {}
    const active = doc.createElement('div'); active.className = 'shared-view-tools-active'
    active.textContent = Object.entries(VIEW_TOOLS).filter(([k]) => value[k]).map(([, label]) => label).join(' · ')
    root.append(active)
    if (value.lengthHeatmap) {
      const length = doc.createElement('div'); length.className = 'shared-length-legend'
      length.innerHTML = '<strong>Strand length (nt)</strong><div class="shared-length-gradient"></div><div class="shared-length-ticks"><span>≤14</span><span>37</span><span>60+</span></div>'
      root.append(length)
    }
    if (value.loopSkips) {
      const legend = doc.createElement('div'); legend.textContent = 'Orange rings: loops · Red crosses: skips'; root.append(legend)
    }
    if (value.clashes) {
      const clashes = doc.createElement('div'); clashes.className = 'shared-clash-legend'
      clashes.textContent = value.clashCount == null ? 'Clash report pending' : `${value.clashCount} ${value.clashCount === 1 ? 'clash' : 'clashes'}`
      root.append(clashes)
    }
  }, dispose() { root.remove() } }
}
