import { EM_DEFAULTS, loadEMSettings, saveEMSettings } from './em_settings.js'
import { initEMSimulation } from './em_simulation.js'
import * as THREE from 'three'
import { createEMFieldOverlay } from '../scene/em_field.js'
import { nanoparticlePoseMatrix } from '../scene/nanoparticle_display.js'
import './em_analysis.css'

/** Capture optical inputs in the actual scene frame, including hidden particles. */
export function captureEMParticles({ state, nanoparticleSubsystem, assemblyRenderer }) {
  let particles
  if (state.assemblyActive) {
    particles = []
    for (const instance of state.currentAssembly?.instances ?? []) {
      const design = assemblyRenderer.getInstanceDesign(instance.id)
      const matrix = assemblyRenderer.getLiveTransform(instance.id)
      if (!design || !matrix) throw new Error('Wait for all assembly instances to finish loading.')
      for (const particle of design.nanoparticles ?? []) {
        const pos = new THREE.Vector3().setFromMatrixPosition(nanoparticlePoseMatrix(particle)).applyMatrix4(matrix)
        particles.push({ ...particle, id: `${instance.id}:${particle.id}`, pos })
      }
    }
  } else {
    particles = nanoparticleSubsystem.getQuenchingParticles()
  }
  if (particles.some(p => p.kind !== 'gold_nanosphere')) throw new Error('This experimental model supports gold spheres only; other particle materials cannot be silently omitted.')
  if (particles.length < 1 || particles.length > 4) throw new Error('Load a design containing one to four gold nanospheres.')
  return particles.map(p => ({ id: p.id, diameter_nm: p.diameter_nm,
    center_nm: [p.pos.x, p.pos.y, p.pos.z] }))
}

export function initEMAnalysis({ scene, store, nanoparticleSubsystem, assemblyRenderer, api,
  addFrameCallback, removeFrameCallback, camera = null, controls = null, overlayFactory = createEMFieldOverlay, simulationDisplays = null }) {
  let panel = null, overlay = null, result = null, controller = null, generation = 0, signature = null
  let interval = null, started = 0, lastCheck = 0
  const button = document.getElementById('menu-tools-em-analysis')
  const capture = () => captureEMParticles({ state: store.getState(), nanoparticleSubsystem, assemblyRenderer })
  const fingerprint = () => JSON.stringify([store.getState().currentDesign?.id, store.getState().currentAssembly?.id,
    store.getState().assemblyActive, capture()])
  const status = text => { if (panel) panel.querySelector('[data-status]').textContent = text }
  function cancel(message = 'Cancelled.') {
    generation++; controller?.abort(); controller = null
    clearInterval(interval); interval = null
    if (panel) { panel.querySelector('[data-bare-retry]').hidden = true; panel.querySelector('[data-run]').disabled = false; panel.querySelector('[data-cancel]').disabled = true }
    status(message)
  }
  function invalidate() {
    cancel('Particle configuration changed. Recalculate the field map.')
    result = null; signature = null; overlay?.clear()
    if (panel) panel.querySelector('[data-download]').disabled = true
  }
  function check() {
    if (!panel || !signature || performance.now() - lastCheck < 250) return
    lastCheck = performance.now()
    try { if (fingerprint() !== signature) invalidate() } catch { invalidate() }
  }
  function redraw() {
    if (!result || !panel) return
    overlay.show(result, { mode: panel.querySelector('[data-mode]').value,
      slice: Number(panel.querySelector('[data-slice]').value), minimum: Number(panel.querySelector('[data-minimum]').value),
      maximum: 100, dotSize: Number(panel.querySelector('[data-dot-size]').value) })
  }
  async function run() {
    cancel('Preparing current particle snapshot…')
    overlay.clear(); result = null; panel.querySelector('[data-download]').disabled = true
    const current = generation
    try {
      const particles = capture()
      signature = fingerprint()
      const payload = { particles, resolution: Number(panel.querySelector('[data-resolution]').value),
        polarization: panel.querySelector('[data-polarization]').value,
        solver: panel.querySelector('[data-solver]').value,
        sampling: panel.querySelector('[data-sampling]').value,
        shell: { model: panel.querySelector('[data-shell]').value,
          oligo_length_nt: Number(panel.querySelector('[data-oligo-length]').value),
          persistence_length_nm: Number(panel.querySelector('[data-persistence]').value),
          thickness_nm: Number(panel.querySelector('[data-thickness]').value),
          refractive_index: Number(panel.querySelector('[data-shell-index]').value) } }
      controller = new AbortController()
      panel.querySelector('[data-run]').disabled = true; panel.querySelector('[data-cancel]').disabled = false
      started = performance.now()
      const update = () => status(`Solving 520 nm field · ${((performance.now() - started) / 1000).toFixed(0)} s elapsed`)
      update(); interval = setInterval(update, 1000)
      let requestError = null
      const next = await api._request('POST', '/em-analysis/solve', payload,
        { signal: controller.signal, timeoutMs: 190000, suppressBusy: true, protectedRetry: false,
          onError: (status, detail) => {
            requestError = api.errorDetailToMessage?.(detail)
              ?? (typeof detail === 'string' ? detail : detail?.message || `EM analysis failed (HTTP ${status}).`)
          } })
      if (generation !== current || !panel) return
      if (fingerprint() !== signature) { invalidate(); return }
      if (!next) throw new Error(requestError || 'The EM request ended without a result. Try Calculate again.')
      result = next
      clearInterval(interval); interval = null; controller = null
      panel.querySelector('[data-run]').disabled = false; panel.querySelector('[data-cancel]').disabled = true
      panel.querySelector('[data-download]').disabled = false
      status(`${particles.length} sphere(s) · minimum gap ${next.gap_nm === null ? 'n/a' : next.gap_nm.toFixed(2) + ' nm'}\n` +
        `${next.dna_shell ? 'DNA shell: ' + next.dna_shell.thickness_nm.toFixed(2) + ' nm, n=' + next.dna_shell.refractive_index + ' (' + next.dna_shell.model + ')\n' : ''}` +
        `Sampled peak ${next.peak_intensity.toFixed(2)}× intensity · ${next.elapsed_seconds.toFixed(2)} s solver time\n` +
        `Multipole order ${next.multipole_order}; probe change ${(100 * next.probe_relative_error).toFixed(3)}%. ` +
        (next.sampling?.layout === 'octree'
          ? `Adaptive samples: ${next.sampling.sample_count}; cell widths ${next.sampling.minimum_cell_width_nm.toFixed(2)}–${next.sampling.maximum_cell_width_nm.toFixed(2)} nm. ${next.sampling.gap_refined_cells ?? 0} close-gap cells refined ×4.${next.sampling.budget_limited ? ' Sample budget reached; increase quality to refine further.' : ''}\n`
          : 'Grid spacing ' + next.upper_nm.map((v, i) => ((v - next.lower_nm[i]) / (next.shape[i] - 1)).toFixed(2)).join(' × ') + ' nm.\n') +
        (next.sampling?.field_refinement ? `Field refinement: ${next.sampling.field_refinement.rounds} passes, ${next.sampling.field_refinement.refined_cells} cells refined.${next.sampling.field_refinement.limit_reached ? ' Refinement limit reached; unresolved variation remains.' : ''}\n` : '') +
        `E direction: ${next.polarization_world.map(v => v.toFixed(3)).join(', ')}; k: ${next.propagation_world.map(v => v.toFixed(3)).join(', ')}`)
      redraw()
    } catch (error) {
      if (generation === current && panel) {
        cancel(error.message || 'EM analysis failed.')
        panel.querySelector('[data-bare-retry]').hidden = !error.message?.includes('DNA dielectric shells overlap or touch')
      }
    }
  }
  function frameMap() {
    if (!result || !camera || !controls) return
    const center = new THREE.Vector3(...result.origin_nm)
    for (let i = 0; i < 3; i++) center.addScaledVector(new THREE.Vector3(...result.basis[i]), (result.lower_nm[i] + result.upper_nm[i]) / 2)
    const radius = Math.hypot(...result.upper_nm.map((v, i) => v - result.lower_nm[i])) / 2
    const direction = camera.position.clone().sub(controls.target).normalize()
    if (!direction.lengthSq()) direction.set(1, 1, 1).normalize()
    const halfAngle = Math.atan(Math.tan(THREE.MathUtils.degToRad(camera.fov || 45) / 2) * Math.min(1, camera.aspect || 1))
    camera.position.copy(center).addScaledVector(direction, radius / Math.sin(halfAngle) * 1.2)
    controls.target.copy(center); controls.update()
  }
  function persist() {
    if (!panel) return
    saveEMSettings(Object.fromEntries(Object.keys(EM_DEFAULTS).map(key => [key, panel.querySelector(`[data-${key}]`).value])))
  }
  function close() {
    persist()
    cancel(); removeFrameCallback?.(check); overlay?.dispose(); overlay = null
    panel?.remove(); panel = null; result = null; signature = null; button?.focus()
  }
  function open(settingsOnly = false) {
    const configure = () => {
      for (const key of ['run','frame']) panel.querySelector(`[data-${key}]`).parentElement.hidden = settingsOnly === true
      if (settingsOnly === true) status('These settings apply to the EM visualization. Close this panel to return to the simulation.')
    }
    if (panel) { configure(); return panel.querySelector('[data-solver]').focus() }
    overlay = overlayFactory(scene)
    panel = document.createElement('section'); panel.id = 'em-analysis-panel'
    panel.setAttribute('role', 'region'); panel.setAttribute('aria-label', 'EM analysis')
    panel.innerHTML = `<header><strong>EM analysis</strong><button data-close aria-label="Close EM analysis">×</button></header>
      <p>520 nm plane wave in water (n = 1.333). Coupled, full-wave gold spheres.</p>
      <label>Solver<select data-solver><option value="multipole">Full multipole Maxwell · optimized</option><option value="multipole_reference">Full multipole Maxwell · reference evaluation</option></select></label>
      <label>Optical DNA coating<select data-shell><option value="ssdna_wlc">Full coverage · length-based ssDNA estimate</option><option value="manual">Full coverage · specified thickness</option><option value="none">Bare spheres · original model</option></select></label>
      <p>Optical coverage is independent of explicitly modeled conjugates. These common shell settings apply to every particle.</p>
      <label>Conjugated oligo length (nt)<input data-oligo-length type="number" min="1" max="200" step="1" value="20"></label>
      <label>ssDNA persistence length (nm)<input data-persistence type="number" min="0.1" max="10" step="0.1" value="2.5"></label>
      <label>Specified radial shell thickness (nm)<input data-thickness type="number" min="0" max="100" step="0.1" value="2.5"></label>
      <label>Effective shell refractive index<input data-shell-index type="number" min="1" max="2.5" step="0.01" value="1.7"></label>
      <p data-shell-estimate></p>
      <label>Electric-field polarization<select data-polarization><option value="parallel">Along first particle pair</option><option value="perpendicular">Across first particle pair</option></select></label>
      <label>Sampling<select data-sampling><option value="field_adaptive">Adaptive · field variation and hotspots</option><option value="adaptive">Adaptive · near particle surfaces</option><option value="uniform">Uniform grid</option></select></label>
      <label>Sampling quality / budget<select data-resolution><option value="25">Preview · 15,625 + adaptive refinement</option><option value="33" selected>Standard · 35,937 + adaptive refinement</option><option value="49">Fine · 117,649 + adaptive refinement</option></select></label>
      <div class="em-actions"><button data-run>Calculate 520 nm map</button><button data-cancel disabled>Cancel</button></div>
      <button data-bare-retry hidden>Calculate without DNA coating</button>
      <p data-status role="status" aria-live="polite">Uses the current particle positions, including hidden gold. Calculate to begin.</p>
      <label>Display<select data-mode><option value="volume">3D field cloud</option><option value="xy">XY slice</option><option value="xz">XZ slice</option><option value="yz">YZ slice</option></select></label>
      <label>Sampling dot size: <output data-dot-size-value>3 px</output><input data-dot-size type="range" min="1" max="12" step="0.5" value="3"></label>
      <label>Slice position<input data-slice type="range" min="0" max="1" step="0.02" value="0.5"></label>
      <label>Cloud minimum intensity enhancement<input data-minimum type="number" min="0" max="1000" step="0.5" value="1.5"></label>
      <div class="em-legend"></div><div class="em-scale"><span>0.1×</span><span>1×</span><span>10×</span><span>≥100×</span></div>
      <p>Log color scale: |E<sub>total</sub>|² / |E<sub>incident</sub>|². Pink arrow: E polarization. Cyan: propagation. Slice axes follow the particle pair; XY contains the pair and E. Adaptive slices show center samples from cells intersecting the selected plane. Point density indicates sampling effort, not field strength; use color for intensity.</p>
      <details><summary>Model scope and numerical limits</summary><p>Bulk Johnson–Christy gold in water. Optional full-coverage dielectric DNA shells include fields within the shell; origami bodies and substrates are excluded. The length-based model uses the worm-like-chain RMS size with 0.59 nm/nt as an effective radial-size proxy, not a calibrated optical thickness. Persistence length depends on salt and sequence; 2.5 nm is a poly-T pure-water literature value. Shell n=1.7 is an adjustable literature starting point, not universal for hydrated DNA. Overlapping shells are rejected; compression and interpenetration require another dielectric geometry model. This is a static snapshot, not a trajectory average or fluorescence prediction. Diameters 5–100 nm; metal gaps ≥2 nm. Metal interiors are masked. A 1% multipole probe check does not certify grid convergence; compare resolutions before interpreting a peak.</p></details>
      <div class="em-actions"><button data-frame>Frame map</button><button data-download disabled>Download field + inputs</button><button data-copy>Copy details</button></div>`
    const saved = loadEMSettings()
    for (const key of Object.keys(EM_DEFAULTS)) panel.querySelector(`[data-${key}]`).value = saved[key]
    panel.querySelector('[data-dot-size-value]').textContent = `${saved['dot-size']} px`
    panel.addEventListener('input', persist)
    panel.addEventListener('change', persist)
    document.body.append(panel)
    panel.addEventListener('keydown', event => { event.stopPropagation(); if (event.key === 'Escape') close() })
    panel.querySelector('[data-close]').onclick = close
    panel.querySelector('[data-run]').onclick = run
    panel.querySelector('[data-frame]').onclick = frameMap
    panel.querySelector('[data-cancel]').onclick = () => cancel()
    panel.querySelector('[data-bare-retry]').onclick = () => {
      panel.querySelector('[data-shell]').value = 'none'
      persist()
      shellControls()
      run()
    }
    for (const selector of ['[data-mode]', '[data-slice]', '[data-minimum]']) panel.querySelector(selector).oninput = redraw
    panel.querySelector('[data-dot-size]').oninput = () => {
      panel.querySelector('[data-dot-size-value]').textContent = `${panel.querySelector('[data-dot-size]').value} px`
      redraw()
    }
    function shellControls() {
      const model = panel.querySelector('[data-shell]').value
      const length = Number(panel.querySelector('[data-oligo-length]').value) * .59
      const lp = Number(panel.querySelector('[data-persistence]').value)
      const thickness = model === 'none' ? 0 : model === 'manual' ? Number(panel.querySelector('[data-thickness]').value)
        : Math.sqrt(2 * lp * length + 2 * lp * lp * Math.expm1(-length / lp))
      panel.querySelector('[data-shell-estimate]').textContent = `Radial shell thickness: ${thickness.toFixed(2)} nm. Length estimate is not an optical calibration.`
      for (const name of ['oligo-length', 'persistence']) panel.querySelector(`[data-${name}]`).disabled = model !== 'ssdna_wlc'
      panel.querySelector('[data-thickness]').disabled = model !== 'manual'
      panel.querySelector('[data-shell-index]').disabled = model === 'none'
    }
    shellControls()
    for (const selector of ['[data-sampling]', '[data-resolution]', '[data-polarization]', '[data-solver]', '[data-shell]',
      '[data-oligo-length]', '[data-persistence]', '[data-thickness]', '[data-shell-index]']) {
      panel.querySelector(selector).onchange = () => { shellControls(); invalidate() }
    }
    panel.querySelector('[data-copy]').onclick = async () => {
      try { await navigator.clipboard.writeText(`EM analysis · POST /api/em-analysis/solve\n${panel.querySelector('[data-status]').textContent}\n${location.href}`) }
      catch { status('Clipboard unavailable. Select the result text to copy it.') }
    }
    panel.querySelector('[data-download]').onclick = () => {
      if (!result) return
      const url = URL.createObjectURL(new Blob([JSON.stringify(result)], { type: 'application/json' }))
      const a = document.createElement('a'); a.href = url; a.download = 'em-analysis-520nm.json'; a.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    }
    configure()
    addFrameCallback?.(check)
    panel.querySelector('[data-run]').focus()
  }
  const simulation = simulationDisplays ? initEMSimulation({ scene, api, store, capture, openSettings:() => open(true),
    displays:simulationDisplays, addFrameCallback, removeFrameCallback,
    captureSimulation:() => captureEMParticles({ state:{}, nanoparticleSubsystem }) }) : null
  button?.addEventListener('click', open)
  return { open, close, dispose() { simulation?.dispose(); close(); button?.removeEventListener('click', open) } }
}
