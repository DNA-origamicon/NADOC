import { EM_DEFAULTS, loadEMSettings, saveEMSettings, opticalSettings } from './em_settings.js'
import {initEMLegend} from './em_legend.js'
import {loadEMColors} from './em_color_settings.js'
import { initEMSimulation } from './em_simulation.js'
import * as THREE from 'three'
import { createEMFieldOverlay } from '../scene/em_field.js'
import { registerEMExport } from '../scene/em_export.js'
import { nanoparticlePoseMatrix } from '../scene/nanoparticle_display.js'
import {EM_PANEL_HTML, updateEMPanel, prepareEMPanel} from './em_analysis_panel.js'
import {registerEMClear} from '../scene/em_export.js'
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
  rightSidebar = null, addFrameCallback, removeFrameCallback, overlayFactory = createEMFieldOverlay, simulationDisplays = null }) {
  let panel = null, overlay = null, result = null, controller = null, generation = 0, signature = null
  let interval = null, started = 0, lastCheck = 0
  const legend=initEMLegend(scene)
  const button = document.getElementById('menu-tools-em-analysis')
  const railButton=document.querySelector('#right-tab-strip [data-tab="em"]')
  const standalone=()=>configure(false)
  const capture = () => captureEMParticles({ state: store.getState(), nanoparticleSubsystem, assemblyRenderer })
  const fingerprint = () => JSON.stringify([store.getState().currentDesign?.id, store.getState().currentAssembly?.id,
    store.getState().assemblyActive, capture()])
  const status = text => { if (panel) panel.querySelector('[data-status]').textContent = text }
  const unregisterClear = registerEMClear(scene,()=>{invalidate();status('Field cleared. Calculate to begin.')})
  const unregisterExport = registerEMExport(scene, () => {
    if (!panel || (!result && !controller)) return
    if (controller) throw new Error('Wait for the EM calculation to finish before exporting.')
    if (fingerprint() !== signature) { invalidate(); throw new Error('Particle positions changed. Recalculate EM before exporting.') }
    redraw()
  })
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
    if (!panel) return
    updateEMPanel(panel)
    if (!result) return
    overlay.show(result, { mode: panel.querySelector('[data-mode]').value,
      slice: Number(panel.querySelector('[data-slice]').value), minimum: Number(panel.querySelector('[data-minimum]').value),
      ...loadEMColors(), dotSize: Number(panel.querySelector('[data-dot-size]').value), lighting:panel.querySelector('[data-lighting]').value })
  }
  async function run() {
    if([...panel.querySelectorAll('input:not(:disabled)')].some(input=>!input.reportValidity()))return
    cancel('Preparing current particle snapshot…')
    overlay.clear(); result = null; panel.querySelector('[data-download]').disabled = true
    const current = generation
    try {
      const particles = capture()
      signature = fingerprint()
      const payload = { particles, ...opticalSettings(Object.fromEntries(Object.keys(EM_DEFAULTS).map(key=>[key,panel.querySelector(`[data-${key}]`).value]))) }
      controller = new AbortController()
      panel.querySelector('[data-run]').disabled = true; panel.querySelector('[data-cancel]').disabled = false
      started = performance.now()
      const update = () => status(`Solving ${payload.wavelength_nm} nm field · ${((performance.now() - started) / 1000).toFixed(0)} s elapsed`)
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
  function persist() {
    if (!panel) return
    saveEMSettings(Object.fromEntries(Object.keys(EM_DEFAULTS).map(key => [key, panel.querySelector(`[data-${key}]`).value])))
  }
  function close() {
    persist()
    if(rightSidebar){
      for(const item of rightSidebar.getInstances())if(item.type==='em')rightSidebar.close(item.id)
    }else if(panel)panel.hidden=true
    button?.focus()
  }
  function configure(settingsOnly=false){
    if(!panel)return
    for(const key of ['run','download'])panel.querySelector(`[data-${key}]`).parentElement.hidden=settingsOnly===true
    panel.querySelector('[data-clear]').hidden=settingsOnly===true
    if(settingsOnly===true)status('These settings apply to the simulation EM visualization.')
  }
  function open(settingsOnly = false, reveal = true) {
    if (panel) { configure(settingsOnly); panel.hidden=false; rightSidebar?.open('em'); return panel.querySelector('[data-solver]').focus() }
    overlay = overlayFactory(scene)
    panel = document.createElement('section'); panel.id = 'em-analysis-panel'
    panel.setAttribute('role', 'region'); panel.setAttribute('aria-label', 'EM analysis')
    panel.innerHTML = EM_PANEL_HTML
    prepareEMPanel(panel)
    const saved = loadEMSettings()
    for (const key of Object.keys(EM_DEFAULTS)) panel.querySelector(`[data-${key}]`).value = saved[key]
    panel.querySelector('[data-dot-size-value]').textContent = `${saved['dot-size']} px`
    panel.addEventListener('input', persist)
    panel.addEventListener('change', persist)
    const host=document.getElementById('right-tab-content-em')
    ;(host??document.body).append(panel)
    panel.hidden=!host&&!reveal
    if(reveal)rightSidebar?.open('em')
    panel.addEventListener('keydown', event => { event.stopPropagation(); if (event.key === 'Escape') close() })
    panel.querySelector('[data-close]').onclick = close
    panel.querySelector('[data-clear]').onclick = ()=>{invalidate();status('Field cleared. Calculate to begin.')}
    panel.querySelector('[data-run]').onclick = run
    panel.querySelector('[data-cancel]').onclick = () => cancel()
    panel.querySelector('[data-bare-retry]').onclick = () => {
      panel.querySelector('[data-shell]').value = 'none'
      persist()
      shellControls()
      run()
    }
    for (const selector of ['[data-mode]', '[data-slice]', '[data-minimum]', '[data-lighting]']) panel.querySelector(selector).oninput = redraw
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
      panel.querySelector('[data-shell-estimate]').textContent = `Radial shell thickness: ${thickness.toFixed(2)} nm`
      updateEMPanel(panel)
      for (const name of ['oligo-length', 'persistence']) panel.querySelector(`[data-${name}]`).disabled = model !== 'ssdna_wlc'
      panel.querySelector('[data-thickness]').disabled = model !== 'manual'
      panel.querySelector('[data-shell-index]').disabled = model === 'none'
    }
    shellControls()
    for (const selector of ['[data-wavelength]', '[data-sampling]', '[data-resolution]', '[data-polarization]', '[data-solver]', '[data-shell]',
      '[data-oligo-length]', '[data-persistence]', '[data-thickness]', '[data-shell-index]']) {
      panel.querySelector(selector).onchange = () => { shellControls(); invalidate() }
    }
    panel.querySelector('[data-download]').onclick = () => {
      if (!result) return
      const url = URL.createObjectURL(new Blob([JSON.stringify(result)], { type: 'application/json' }))
      const a = document.createElement('a'); a.href = url; a.download = `em-analysis-${result.wavelength_nm ?? 520}nm.json`; a.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    }
    configure(settingsOnly)
    redraw()
    addFrameCallback?.(check)
    if(reveal)panel.querySelector('[data-run]').focus()
  }
  open(false,false)
  window.addEventListener('nadoc:em-colors',redraw)
  const simulation = simulationDisplays ? initEMSimulation({ scene, api, store, capture, openSettings:() => open(true),
    displays:simulationDisplays, addFrameCallback, removeFrameCallback,
    captureSimulation:() => captureEMParticles({ state:{}, nanoparticleSubsystem }) }) : null
  railButton?.addEventListener('click',standalone)
  button?.addEventListener('click', open)
  return { open, close, dispose() { unregisterClear(); unregisterExport(); simulation?.dispose(); cancel(); removeFrameCallback?.(check); overlay?.dispose(); panel?.remove(); panel=null; legend.dispose(); railButton?.removeEventListener('click',standalone); window.removeEventListener('nadoc:em-colors',redraw); button?.removeEventListener('click', open) } }
}
