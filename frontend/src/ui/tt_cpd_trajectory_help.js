/** Help ▸ TT-CPD Model Trajectories — gate-aware NAMD trajectory viewer. */

import { createModal } from './primitives/modal.js'
import { createButton } from './primitives/button.js'
import { el } from './primitives/dom.js'

const COLORS = { H: '#d8dee9', C: '#657bff', N: '#58a6ff', O: '#f85149', P: '#d29922' }

export function trajectoryDurationPs(trajectory) {
  const frames = trajectory?.frames?.length ?? 0
  if (frames < 2) return 0
  return (frames - 1) * Number(trajectory.stride_steps ?? 1) * Number(trajectory.timestep_fs ?? 0) / 1000
}

export function projectTrajectoryFrame(frame, width, height, angle = 0) {
  if (!Array.isArray(frame) || frame.length === 0) return []
  const rotated = frame.map(([x, y, z]) => [
    x * Math.cos(angle) + z * Math.sin(angle),
    y,
    -x * Math.sin(angle) + z * Math.cos(angle),
  ])
  const center = rotated.reduce((sum, xyz) => sum.map((v, i) => v + xyz[i]), [0, 0, 0]).map(v => v / rotated.length)
  const centered = rotated.map(xyz => xyz.map((v, i) => v - center[i]))
  const radius = Math.max(1, ...centered.map(([x, y]) => Math.hypot(x, y)))
  const scale = Math.min(width, height) * 0.42 / radius
  return centered.map(([x, y, z]) => [width / 2 + x * scale, height / 2 - y * scale, z])
}

function _draw(canvas, trajectory, frameIndex, angle) {
  const context = canvas.getContext?.('2d')
  if (!context) return
  const width = canvas.width
  const height = canvas.height
  context.clearRect(0, 0, width, height)
  context.fillStyle = '#0d1117'
  context.fillRect(0, 0, width, height)
  const points = projectTrajectoryFrame(trajectory.frames[frameIndex], width, height, angle)
  context.strokeStyle = '#8b949e'
  context.lineWidth = 2
  for (const [a, b] of trajectory.bonds ?? []) {
    if (!points[a] || !points[b]) continue
    context.beginPath()
    context.moveTo(points[a][0], points[a][1])
    context.lineTo(points[b][0], points[b][1])
    context.stroke()
  }
  const order = points.map((point, index) => [point[2], index]).sort((a, b) => a[0] - b[0])
  for (const [, index] of order) {
    const element = trajectory.elements[index] ?? 'C'
    context.beginPath()
    context.fillStyle = COLORS[element] ?? '#a5d6ff'
    context.arc(points[index][0], points[index][1], element === 'H' ? 3 : 6, 0, Math.PI * 2)
    context.fill()
  }
}

function _gateSummary(product) {
  if (product.help_trajectory?.available) return 'Released, validated NAMD model trajectory available'
  return product.help_trajectory?.reason || `Waiting for ${product.next_gate || 'release evidence'}`
}

export async function showTTCpdTrajectoryHelp({ api }) {
  const body = el('div', { attrs: { style: 'min-height:380px' } })
  body.append(el('div', { text: 'Loading TT-CPD capability registry…', attrs: { style: 'color:#8b949e;font-size:12px' } }))
  let animation = null
  let playing = false
  let trajectory = null
  let frameIndex = 0
  const modal = createModal({
    title: 'TT-CPD model trajectories',
    size: 'xl',
    body,
    actions: [createButton({ label: 'Close', variant: 'primary', onClick: () => modal.close() })],
    onClose: () => {
      playing = false
      if (animation != null) cancelAnimationFrame(animation)
    },
  })
  modal.open()

  let catalog
  try {
    catalog = await api.getPhotoproductCatalog()
  } catch (error) {
    body.replaceChildren(el('div', {
      text: `Could not load TT-CPD capabilities: ${error?.message ?? error}`,
      attrs: { style: 'color:#f85149;font-size:12px' },
    }))
    return modal
  }
  if (!catalog?.products) {
    body.replaceChildren(el('div', {
      text: 'Could not load TT-CPD capabilities.',
      attrs: { style: 'color:#f85149;font-size:12px' },
    }))
    return modal
  }

  body.innerHTML = ''
  body.append(el('p', {
    text: 'These are the eight ordered DNA-level product states, not the six aglycone products recovered after hydrolysis and not KIMMDY reactant propensity. An isomer remains visibly gated until a hash-verified trajectory and its real NAMD smoke test exist.',
    attrs: { style: 'margin:0 0 10px;color:#8b949e;font-size:12px;line-height:1.45' },
  }))
  const layout = el('div', { attrs: { style: 'display:grid;grid-template-columns:minmax(180px,0.7fr) minmax(360px,1.5fr);gap:12px' } })
  const choices = el('div', { attrs: { role: 'list', style: 'display:flex;flex-direction:column;gap:6px' } })
  const viewer = el('div', { attrs: { style: 'border:1px solid #30363d;border-radius:6px;padding:10px;background:#0d1117' } })
  const message = el('div', { text: 'Select a TT-CPD stereoisomer.', attrs: { 'data-cpd-trajectory-message': '', style: 'color:#8b949e;font-size:12px;margin-bottom:8px' } })
  const canvas = el('canvas', { attrs: { width: 640, height: 360, style: 'display:none;width:100%;aspect-ratio:16/9;background:#0d1117' } })
  const controls = el('div', { attrs: { style: 'display:none;align-items:center;gap:8px;margin-top:8px' } })
  const play = createButton({ label: 'Play', onClick: () => {
    if (!trajectory) return
    playing = !playing
    play.textContent = playing ? 'Pause' : 'Play'
    if (playing) tick()
  } })
  const slider = el('input', { attrs: { type: 'range', min: 0, max: 0, value: 0, step: 1, style: 'flex:1' }, on: { input: () => {
    frameIndex = Number(slider.value)
    _draw(canvas, trajectory, frameIndex, 0.25)
    updateReadout()
  } } })
  const readout = el('span', { attrs: { style: 'min-width:100px;text-align:right;color:#c9d1d9;font:11px var(--font-mono,monospace)' } })
  controls.append(play, slider, readout)
  viewer.append(message, canvas, controls)
  layout.append(choices, viewer)
  body.append(layout)

  function updateReadout() {
    if (!trajectory) { readout.textContent = ''; return }
    const time = frameIndex * Number(trajectory.stride_steps ?? 1) * Number(trajectory.timestep_fs ?? 0) / 1000
    readout.textContent = `${time.toFixed(3)} / ${trajectoryDurationPs(trajectory).toFixed(3)} ps`
  }

  let last = 0
  function tick(timestamp = 0) {
    if (!playing || !trajectory) return
    if (timestamp - last >= 80) {
      frameIndex = (frameIndex + 1) % trajectory.frames.length
      slider.value = String(frameIndex)
      _draw(canvas, trajectory, frameIndex, timestamp / 2200)
      updateReadout()
      last = timestamp
    }
    animation = requestAnimationFrame(tick)
  }

  async function select(product, button) {
    for (const node of choices.children) node.setAttribute('aria-current', node === button ? 'true' : 'false')
    playing = false
    play.textContent = 'Play'
    trajectory = null
    canvas.style.display = 'none'
    controls.style.display = 'none'
    message.textContent = _gateSummary(product)
    message.style.color = product.help_trajectory?.available ? '#d29922' : '#8b949e'
    if (!product.help_trajectory?.available) return
    message.textContent = 'Loading verified trajectory…'
    try {
      trajectory = await api.getPhotoproductModelTrajectory(product.id)
      if (!trajectory?.frames?.length) throw new Error('backend returned no trajectory frames')
      frameIndex = 0
      slider.max = String(trajectory.frames.length - 1)
      slider.value = '0'
      canvas.style.display = 'block'
      controls.style.display = 'flex'
      message.textContent = `${product.label} · ${trajectory.frames.length} frames · ${trajectory.provenance?.engine ?? 'NAMD'}`
      message.style.color = '#3fb950'
      _draw(canvas, trajectory, 0, 0.25)
      updateReadout()
    } catch (error) {
      trajectory = null
      message.textContent = `Trajectory rejected: ${error?.message ?? error}`
      message.style.color = '#f85149'
    }
  }

  for (const product of catalog.products ?? []) {
    if (product.product !== 'TT-CPD') continue
    const available = product.help_trajectory?.available === true
    const button = el('button', {
      attrs: {
        type: 'button', role: 'listitem', 'data-product-id': product.id,
        style: `text-align:left;padding:8px;border:1px solid ${available ? '#238636' : '#30363d'};border-radius:5px;background:#161b22;color:#c9d1d9;cursor:pointer`,
        title: _gateSummary(product),
      },
      children: [
        el('div', { text: product.label, attrs: { style: 'font-size:12px;font-weight:600' } }),
        el('div', { text: `C5 ${product.structural_class?.ordered_c5_configurations?.join(',') ?? 'configuration pending'} · ${product.structural_class?.double_bond_orientation ?? 'class pending'}`, attrs: { style: 'font-size:10px;color:#8b949e;margin-top:2px' } }),
        el('div', { text: available ? 'released trajectory ready' : `gated · ${product.next_gate ?? 'evidence'}`, attrs: { style: `font-size:10px;color:${available ? '#3fb950' : '#8b949e'};margin-top:2px` } }),
      ],
    })
    button.addEventListener('click', () => select(product, button))
    choices.append(button)
  }
  choices.querySelector('button')?.click()
  return modal
}
