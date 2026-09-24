import { createModal } from './primitives/modal.js'
import { el } from './primitives/dom.js'
import { projectTrajectoryFrame } from './tt_cpd_trajectory_help.js'

/** Rotatable projection of the actual 3D template; no WebGL context needed. */
export function drawCpdPreview(svg, template, angle = 0) {
  svg.replaceChildren()
  if (!template) return
  const points = projectTrajectoryFrame(template.positions, 600, 330, angle)
  const node = (tag, attrs) => {
    const n = document.createElementNS('http://www.w3.org/2000/svg', tag)
    for (const [key, value] of Object.entries(attrs)) n.setAttribute(key, value)
    return n
  }
  for (const [a, b] of template.bonds) {
    const crosslink = template.atom_keys[a].split(':')[0] !== template.atom_keys[b].split(':')[0]
    svg.append(node('line', { x1: points[a][0], y1: points[a][1], x2: points[b][0], y2: points[b][1], stroke: crosslink ? '#ff4fd8' : '#8b949e', 'stroke-width': crosslink ? 5 : 2 }))
  }
  const colors = { C: '#849cff', N: '#58a6ff', O: '#f85149', P: '#d29922', H: '#d8dee9' }
  points.map((p, i) => [p, i]).sort((a, b) => a[0][2] - b[0][2]).forEach(([p, i]) => {
    const element = template.atom_keys[i].split(':')[1][0]
    const atom = node('circle', { cx: p[0], cy: p[1], r: element === 'H' ? 3 : 6, fill: colors[element] ?? '#aaa' })
    const title = node('title', {})
    title.textContent = template.atom_keys[i]
    atom.append(title); svg.append(atom)
  })
}

export async function showCpdConversion({ api, baseKeys }) {
  const keys = [...baseKeys]
  const status = el('p', { text: 'Loading CPD types…', attrs: { role: 'status' } })
  const choices = el('select', { attrs: { 'aria-label': 'CPD type', style: 'width:100%;padding:8px' } })
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
  svg.setAttribute('viewBox', '0 0 600 330')
  svg.setAttribute('aria-label', '3D CPD template preview')
  svg.style.cssText = 'width:100%;background:#0d1117;border-radius:6px'
  const rotation = el('input', { attrs: { type: 'range', min: -180, max: 180, value: 20, 'aria-label': 'Rotate CPD preview', style: 'width:100%' } })
  const convert = el('button', { text: 'Convert to CPD', className: 'primary-btn', attrs: { disabled: true } })
  const body = el('div', { children: [choices, status, svg, el('label', { text: 'Rotate preview', children: [rotation] })] })
  let epoch = 0, template = null, saving = false
  const modal = createModal({ title: 'Convert to CPD', size: 'lg', body, actions: [convert], onClose: () => {
    if (saving) return false
    epoch++
  } })
  modal.open()
  rotation.addEventListener('input', () => drawCpdPreview(svg, template, Number(rotation.value) * Math.PI / 180))
  async function select() {
    const token = ++epoch
    template = null; svg.replaceChildren(); convert.disabled = true
    status.textContent = 'Loading template…'
    try {
      const result = await api.getCpdDesignTemplate(choices.value)
      if (token !== epoch || !modal.isOpen()) return
      if (!result?.positions?.length) throw new Error('CPD template is unavailable.')
      template = result
      status.textContent = result.qualification
      drawCpdPreview(svg, template, Number(rotation.value) * Math.PI / 180)
      convert.disabled = false
    } catch (error) {
      if (token === epoch && modal.isOpen()) status.textContent = error.message
    }
  }
  choices.addEventListener('change', select)
  convert.addEventListener('click', async () => {
    if (!template || saving) return
    saving = true; convert.disabled = true; choices.disabled = true
    status.textContent = 'Converting thymines and relaxing bonds and nearby clashes…'
    try {
      const result = await api.convertExtraBasesToCpd(keys, choices.value)
      if (!result) throw new Error('Conversion failed. Check the current selection and try again.')
      saving = false; modal.close()
    } catch (error) {
      status.textContent = error.message
    } finally {
      saving = false; convert.disabled = false; choices.disabled = false
    }
  })
  try {
    const catalog = await api.getPhotoproductCatalog()
    if (!modal.isOpen()) return modal
    if (!catalog?.products?.length) throw new Error('CPD types could not be loaded.')
    for (const p of catalog.products.filter(p => p.product === 'TT-CPD')) {
      const available = p.simulation_supported === true || p.simulation_ready === true
      choices.append(el('option', { text: `${p.label} · ${available ? (p.simulation_ready ? 'Validated' : 'Preliminary research template') : 'In development'}`, attrs: { value: p.stereochemistry, ...(available ? {} : { disabled: true }) } }))
    }
    const first = [...choices.options].find(o => !o.disabled)
    if (first) { choices.value = first.value; await select() }
    else status.textContent = 'All CPD types are in development. No conversion template is available.'
  } catch (error) {
    if (modal.isOpen()) status.textContent = error.message
  }
  return modal
}
