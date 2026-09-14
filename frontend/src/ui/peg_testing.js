import { createModal } from './primitives/modal.js'
import { createPegTrajectoryView } from '../scene/peg_trajectory.js'
import { frameCoordinates, frameLabel } from './peg_playback.js'
import './peg_testing.css'

/** Completed simulation viewer. Dependencies permit lifecycle tests without WebGL. */
export function showPegTesting({ onClose = () => {}, fetchData = (...args) => fetch(...args),
  createView = createPegTrajectoryView } = {}) {
  const body = document.createElement('div')
  body.innerHTML = `
    <p>Recorded oxDNA PEG simulations at 294 K. <b>N counts ethylene oxide repeats</b>; one bead represents one repeat.</p>
    <div class="peg-layout">
      <div class="peg-controls">
        <label>PEG length<select data-peg="n" disabled aria-label="PEG length"></select></label>
        <label>Completed simulation<select data-peg="run" disabled aria-label="Completed simulation"></select></label>
        <div class="peg-note" data-peg="condition"></div>
        <div class="peg-note" data-peg="verdict"></div>
        <p class="peg-note">Colors distinguish chains; orange beads mark chain ends. Drag to orbit; scroll to zoom.</p>
        <p class="peg-note">Single chains are centered to remove translation. Bulk chains are made whole and placed in their periodic box.</p>
      </div>
      <div>
        <div class="peg-view" data-peg="view" aria-label="Recorded PEG trajectory"></div>
        <div class="peg-backend" data-peg="status" role="status">Loading completed simulations…</div>
        <div class="peg-actions">
          <button data-peg="play" disabled aria-label="Play trajectory">Play</button>
          <button data-peg="start" disabled>First frame</button>
          <label>Playback speed <select data-peg="speed" aria-label="Playback speed"><option value="6">6 frames/s</option><option value="12" selected>12 frames/s</option><option value="24">24 frames/s</option></select></label>
        </div>
        <label class="peg-timeline">Saved frame <output data-peg="frame">—</output>
          <input data-peg="slider" aria-label="Trajectory frame" type="range" min="0" max="0" value="0" step="1" disabled>
        </label>
        <div class="peg-stats">
          <div>Allocation progress<strong data-peg="time">—</strong></div>
          <div>Snapshot RMS Rg<strong data-peg="rg">—</strong></div>
          <div>Chain count<strong data-peg="chains">—</strong></div>
        </div>
        <p class="peg-note" data-peg="sampling"></p>
        <p class="peg-note">These are subsampled saved frames, without interpolation. Playback speed is for viewing. Completion does not imply equilibrium or successful validation.</p>
      </div>
    </div>`
  const get = name => body.querySelector(`[data-peg="${name}"]`)
  let view, animation, entries = [], selected, buffer, index = 0, playing = false
  let disposed = false, lastTick = 0, request = 0, trajectoryAbort
  const manifestAbort = new AbortController()
  const modal = createModal({ title: 'PEG testing · completed simulations', size: 'xl', className: 'peg-testing', body,
    onClose: () => {
      disposed = true; request++
      manifestAbort.abort(); trajectoryAbort?.abort()
      cancelAnimationFrame(animation); view?.dispose(); buffer = null
      onClose()
    },
  })
  modal.open()
  function pause() {
    playing = false
    get('play').textContent = 'Play'; get('play').setAttribute('aria-label', 'Play trajectory')
  }
  function showFrame(next) {
    index = Math.max(0, Math.min(selected.frames - 1, next))
    view.setFrame(frameCoordinates(buffer, selected, index))
    get('slider').value = String(index)
    get('frame').textContent = `${index + 1} / ${selected.frames}`
    get('time').textContent = frameLabel(selected, index)
    get('rg').textContent = `${selected.rmsRgNm[index].toFixed(3)} nm`
  }
  async function loadRun() {
    const token = ++request
    trajectoryAbort?.abort(); trajectoryAbort = new AbortController()
    pause(); buffer = null
    for (const name of ['play', 'start', 'slider']) get(name).disabled = true
    get('status').textContent = 'Loading recorded trajectory…'
    for (const name of ['condition', 'verdict', 'sampling']) get(name).textContent = ''
    const entry = entries.find(row => row.id === get('run').value)
    try {
      const response = await fetchData(entry.url, { signal: trajectoryAbort.signal })
      if (!response.ok) throw new Error(`Trajectory unavailable (${response.status})`)
      const data = new Float32Array(await response.arrayBuffer())
      if (disposed || token !== request) return
      frameCoordinates(data, entry, 0)
      if (!data.every(Number.isFinite)) throw new Error('Trajectory contains invalid coordinates')
      selected = entry; buffer = data
      view.load(entry); get('slider').max = String(entry.frames - 1)
      get('condition').textContent = `${entry.kind} · N${entry.n} · ${entry.temperature} K · replica ${entry.replica}${entry.pressureKpa != null ? ` · ${entry.pressureKpa} kPa` : ''}`
      get('verdict').textContent = entry.validationPassed
        ? 'Completed · cohort passes its bounded validation checks.'
        : 'Completed · cohort validation remains unresolved.'
      get('status').textContent = 'Recorded trajectory ready · paused'
      get('chains').textContent = entry.chains.toLocaleString()
      get('sampling').textContent = `${entry.frames} displayed frames of ${entry.availableFrames.toLocaleString()} saved. Time/steps are local to this allocation. Snapshot Rg is not an equilibrium estimate.`
      showFrame(0)
      for (const name of ['play', 'start', 'slider']) get(name).disabled = false
    } catch (error) {
      if (disposed || token !== request || error.name === 'AbortError') return
      get('status').textContent = `Cannot load trajectory: ${error.message}`
    }
  }
  function selectLength() {
    pause()
    const options = entries.filter(row => row.n === Number(get('n').value))
    get('run').replaceChildren(...options.map(row => new Option(row.label, row.id)))
    get('run').disabled = options.length === 0
    if (options.length) void loadRun()
  }
  get('n').addEventListener('change', selectLength)
  get('run').addEventListener('change', loadRun)
  get('play').addEventListener('click', () => {
    if (!buffer) return
    if (playing) { pause(); get('status').textContent = 'Recorded trajectory ready · paused'; return }
    if (index === selected.frames - 1) showFrame(0)
    playing = true; lastTick = performance.now()
    get('play').textContent = 'Pause'; get('play').setAttribute('aria-label', 'Pause trajectory')
    get('status').textContent = 'Playing recorded trajectory'
  })
  get('slider').addEventListener('input', () => {
    if (!buffer) return
    pause(); showFrame(Number(get('slider').value)); get('status').textContent = 'Recorded trajectory ready · paused'
  })
  get('start').addEventListener('click', () => {
    if (!buffer) return
    pause(); showFrame(0); get('status').textContent = 'Recorded trajectory ready · paused'
  })
  function animate(now) {
    if (disposed) return
    animation = requestAnimationFrame(animate)
    if (document.hidden) { lastTick = now; return }
    if (playing && buffer && now - lastTick >= 1000 / Number(get('speed').value)) {
      showFrame(index + 1); lastTick = now
      if (index === selected.frames - 1) { pause(); get('status').textContent = 'End of recorded trajectory' }
    }
    view.render()
  }
  async function initialize() {
    try {
      view = createView(get('view'))
      animation = requestAnimationFrame(animate)
      const response = await fetchData('/peg-trajectories/manifest.json', { signal: manifestAbort.signal, cache: 'no-store' })
      if (!response.ok) throw new Error('Completed simulation catalog is unavailable. Export the recorded trajectories first.')
      const manifest = await response.json()
      if (disposed) return
      if (manifest.version !== 1 || !Array.isArray(manifest.entries)) throw new Error('Invalid simulation catalog')
      entries = manifest.entries.filter(row => row.completed)
      const lengths = [...new Set(entries.map(row => row.n))].sort((a, b) => a - b)
      get('n').replaceChildren(...lengths.map(n => new Option(`N${n} · ${n} repeats`, String(n))))
      if (!lengths.length) { get('status').textContent = 'No completed trajectories are available.'; return }
      get('n').disabled = false
      get('n').value = String(lengths.includes(36) ? 36 : lengths[0])
      selectLength()
    } catch (error) {
      if (!disposed && error.name !== 'AbortError') get('status').textContent = `Cannot open viewer: ${error.message}`
    }
  }
  void initialize()
  return modal
}
