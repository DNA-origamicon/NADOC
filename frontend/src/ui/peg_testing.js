import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { createModal } from './primitives/modal.js'
import { PEG_DEFAULTS, heightReference, freeChainExtension, pegMetrics, validatePegParameters } from '../scene/peg_model.js'
import { createPegSampler } from '../scene/peg_gpu.js'
import './peg_testing.css'

const BURN_IN = 1000

function chainGeometry(p, lines) {
  const uv = [], offsets = [], tips = []
  const side = Math.ceil(Math.sqrt(p.chains)), spacing = 2.5 * Math.sqrt(p.segments) * p.kuhn
  for (let c = 0; c < p.chains; c++) {
    const bead = j => {
      uv.push((j + 0.5) / (p.segments + 1), (c + 0.5) / p.chains)
      offsets.push((c % side - (side - 1) / 2) * spacing, 0, (Math.floor(c / side) - (side - 1) / 2) * spacing)
      tips.push(j === p.segments ? 1 : 0)
    }
    for (let j = 0; j <= p.segments; j++) {
      if (lines) { if (j) { bead(j - 1); bead(j) } }
      else bead(j)
    }
  }
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(new Float32Array(tips.length * 3), 3))
  geometry.setAttribute('beadUV', new THREE.Float32BufferAttribute(uv, 2))
  geometry.setAttribute('anchorOffset', new THREE.Float32BufferAttribute(offsets, 3))
  geometry.setAttribute('tip', new THREE.Float32BufferAttribute(tips, 1))
  return { geometry, span: side * spacing }
}

function chainMaterial(points) {
  return new THREE.ShaderMaterial({
    uniforms: { positions: { value: null } }, transparent: true,
    vertexShader: `uniform sampler2D positions; attribute vec2 beadUV; attribute vec3 anchorOffset; attribute float tip; varying float isTip;
      void main() { vec3 p = texture2D(positions, beadUV).xyz; isTip = tip;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(vec3(p.x, p.z, p.y) + anchorOffset, 1.0);
      gl_PointSize = tip > 0.5 ? 7.0 : 3.0; }`,
    fragmentShader: `varying float isTip; void main() {
      ${points ? 'if (distance(gl_PointCoord, vec2(0.5)) > 0.5) discard;' : ''}
      gl_FragColor = vec4(mix(vec3(0.30,0.83,0.73),vec3(1.0,0.70,0.34),isTip), ${points ? '1.0' : '0.6'}); }`,
  })
}

export function showPegTesting({ onClose = () => {} } = {}) {
  const body = document.createElement('div')
  body.innerHTML = `
    <p>Explore how an electric field changes a tethered chain’s <b>height</b> while its contour length stays fixed. These ideal Kuhn chains are a preliminary PEG surrogate.</p>
    <div class="peg-layout">
      <div class="peg-controls">
        <label>Model / benchmark<select data-peg="preset">
          <option value="neutral">Neutral PEG control</option><option value="charged">PEG with charged terminal group</option>
          <option value="screened">Charged terminal · screened surface</option><option value="free">Free-chain FJC benchmark (no wall)</option>
        </select></label>
        <label>Kuhn segments<select data-peg="segments"><option>8</option><option>16</option><option selected>24</option><option>32</option><option>64</option></select></label>
        <label>Kuhn length (nm; illustrative)<input data-peg="kuhn" type="number" min="0.2" max="2" step="0.05" value="0.7"></label>
        <label>Temperature (K)<input data-peg="temperature" type="number" min="250" max="400" step="5" value="300"></label>
        <label>Field at surface: <output data-peg="field-label">+0.030 V/nm</output><input aria-label="Field at surface" data-peg="field" type="range" min="-0.1" max="0.1" step="0.005" value="0.03"></label>
        <label>Terminal charge (e)<select data-peg="charge"><option value="0">0 · neutral</option><option value="1">+1</option><option value="-1">−1</option></select></label>
        <label>Field profile<select data-peg="profile"><option value="uniform">Uniform E</option><option value="screened">E(z) = E₀ exp(−z/λ)</option></select></label>
        <label>Screening length λ (nm)<input data-peg="screening" type="number" min="0.2" max="20" step="0.2" value="2" disabled></label>
        <label>Compute<select data-peg="compute"><option value="gpu">GPU preferred</option><option value="cpu">CPU reference</option></select></label>
        <p class="peg-note">64 independent grafted chains, spaced apart for viewing. No chain–chain interactions or brush crowding. Gold beads mark free ends. Drag to orbit; scroll to zoom.</p>
      </div>
      <div>
        <div class="peg-view" data-peg="view" aria-label="PEG chain visualization"></div>
        <div class="peg-backend" data-peg="backend" role="status">Initializing…</div>
        <div class="peg-stats">
          <div>Sampled end height<strong data-peg="height">—</strong></div>
          <div>Equilibrium reference<strong data-peg="reference">—</strong></div>
          <div>Fixed contour length<strong data-peg="contour">—</strong></div>
        </div>
        <canvas class="peg-chart" data-peg="chart" width="760" height="155" aria-label="Terminal height distribution: sampled chains and statistical reference"></canvas>
        <div class="peg-note" data-peg="progress" role="status"></div>
        <div class="peg-note" data-peg="physics"></div>
        <div class="peg-actions"><button data-peg="pause">Pause</button><button data-peg="reset">Reset ensemble</button><button data-peg="export">Export samples + model</button></div>
        <p class="peg-note">Monte Carlo moves sample equilibrium; playback is not molecular time. The reference solves the same ideal-chain statistics independently. Agreement checks the sampler, not PEG chemistry.</p>
      </div>
    </div>
    <details><summary>Research, assumptions, and a path to NAMD validation</summary>
      <ul>
        <li><a href="https://pubmed.ncbi.nlm.nih.gov/15352837/" target="_blank" rel="noopener noreferrer">Vemparala et al. (2004)</a> simulated field-induced torsional and orientational switching of short PEG-terminated monolayers on gold at 200 K, using fields up to ±20 V/nm. This is directly relevant precedent, but it does not validate this Kuhn-chain model or long hydrated brushes.</li>
        <li><a href="https://pmc.ncbi.nlm.nih.gov/articles/PMC2937831/" target="_blank" rel="noopener noreferrer">Lee et al. (2009)</a> developed coarse-grained PEG/PEO and studied grafted-chain conformations. Their chemically parameterized model is richer than this ideal-chain baseline.</li>
        <li><a href="https://pmc.ncbi.nlm.nih.gov/articles/PMC10906002/" target="_blank" rel="noopener noreferrer">Smook &amp; de Beer (2024)</a> modeled field-responsive charged brushes using coarse-grained MD. This supports the charged-chain approach, but their system is not neutral PEG.</li>
      </ul>
      <p class="peg-note">Neutral PEG has no net backbone charge. This baseline deliberately gives it no direct qE response; it omits partial-charge torsions, dipoles, polarization, ions, hydration, and electrode chemistry. The charged-terminal model is a functionalized-chain hypothesis, not a claim that ordinary PEG is charged. Positive field points away from the surface. Screening length is an input, not a solved double layer or electrode-voltage conversion.</p>
      <p class="peg-note">Next: compare chain size and height distributions against short explicit-water NAMD PEG runs at zero field; then test both field polarities and charged/neutral end groups with a specified substrate and electrolyte. Fit effective segment length and field coupling on one condition and test held-out lengths and fields. No NAMD PEG validation has been run. High-field conformational chemistry cannot be established by fitting this ideal model.</p>
    </details>`
  const get = name => body.querySelector(`[data-peg="${name}"]`)
  let renderer, controls, observer, sampler, frame = null, scene, camera, chainObjects = []
  let p, reference, paused = false, disposed = false, lastFrame = 0, lastRead = 0, lastSample = 0
  let snapshot, sampleCount = 0, heightSum = 0, histogram = new Array(36).fill(0), records = []
  let resources = []
  const modal = createModal({ title: 'PEG testing', size: 'xl', className: 'peg-testing', body,
    onClose: () => {
      disposed = true
      cancelAnimationFrame(frame)
      observer?.disconnect()
      controls?.dispose()
      sampler?.dispose()
      for (const resource of resources) resource.dispose()
      renderer?.dispose()
      renderer?.forceContextLoss()
      onClose()
    },
  })
  modal.open()

  function parameters() {
    const wall = get('preset').value !== 'free'
    if (!wall) get('profile').value = 'uniform'
    get('profile').disabled = !wall
    get('screening').disabled = get('profile').value !== 'screened'
    return validatePegParameters({ ...PEG_DEFAULTS, wall,
      segments: Number(get('segments').value), kuhn: Number(get('kuhn').value),
      temperature: Number(get('temperature').value), charge: Number(get('charge').value), field: Number(get('field').value),
      screening: get('profile').value === 'screened' ? Number(get('screening').value) : 0,
    })
  }

  function chart() {
    const ctx = get('chart').getContext('2d'), width = 760, height = 155
    if (!ctx) return
    ctx.clearRect(0, 0, width, height)
    const theory = new Array(histogram.length).fill(0)
    const lower = p.wall ? 0 : -p.segments * p.kuhn, range = p.segments * p.kuhn - lower
    reference.heights.forEach((z, i) => { theory[Math.min(theory.length - 1, Math.floor((z - lower) / range * theory.length))] += reference.probability[i] })
    const measured = histogram.map(n => n / Math.max(1, sampleCount))
    const peak = Math.max(...theory, ...measured, 0.01)
    ctx.font = '12px system-ui'
    ctx.fillStyle = '#68dbb9'; ctx.fillText('Bars: sampled end heights', 12, 18)
    ctx.fillStyle = '#ffbe71'; ctx.fillText('Line: statistical reference', 235, 18)
    const plotW = width - 36, base = 129
    measured.forEach((v, i) => { ctx.fillStyle = '#3cb69b'; ctx.fillRect(18 + i / measured.length * plotW, base - v / peak * 95, plotW / measured.length - 2, v / peak * 95) })
    ctx.strokeStyle = '#ffbe71'; ctx.lineWidth = 2; ctx.beginPath()
    theory.forEach((v, i) => { const x = 18 + (i + 0.5) / theory.length * plotW, y = base - v / peak * 95; if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y) }); ctx.stroke()
    ctx.fillStyle = '#b5c5d4'; ctx.fillText(`${lower.toFixed(1)} nm`, 12, 148); ctx.fillText('Terminal height above anchor', 270, 148); ctx.fillText(`${(p.segments * p.kuhn).toFixed(1)} nm`, width - 66, 148)
  }

  function readStats() {
    snapshot = pegMetrics(sampler.read(), p)
    if (!Number.isFinite(snapshot.meanHeight) || snapshot.maxBondError > 0.02 || (p.wall && snapshot.minZ < -0.001)) {
      paused = true
      get('pause').textContent = 'Resume'
      get('progress').textContent = 'Sampler invariant check failed. Reset or select CPU reference.'
      return
    }
    if (sampler.sweeps >= BURN_IN && sampler.sweeps - lastSample >= 100) {
      lastSample = sampler.sweeps
      const lower = p.wall ? 0 : -p.segments * p.kuhn, range = p.segments * p.kuhn - lower
      for (const z of snapshot.ends) { const bin = Math.max(0, Math.min(histogram.length - 1, Math.floor((z - lower) / range * histogram.length))); histogram[bin]++; heightSum += z; sampleCount++ }
      records.push({ sweep: sampler.sweeps, meanHeightNm: snapshot.meanHeight, meanR2Nm2: snapshot.meanR2 })
      if (records.length > 2000) records.shift()
    }
    get('height').textContent = `${(sampleCount ? heightSum / sampleCount : snapshot.meanHeight).toFixed(2)} nm`
    get('progress').textContent = sampler.sweeps < BURN_IN
      ? `Burn-in: ${sampler.sweeps} / ${BURN_IN} proposals per chain. Height is the current snapshot.`
      : `${sampler.sweeps.toLocaleString()} proposals per chain · ${sampleCount.toLocaleString()} end samples (correlated) · max bond error ${snapshot.maxBondError.toExponential(1)} nm`
    chart()
  }

  function rebuild() {
    try {
      p = parameters()
      sampler?.dispose()
      sampler = null
      for (const resource of resources) resource.dispose()
      resources = []
      scene.clear()
      reference = heightReference(p)
      sampler = createPegSampler(renderer, p, { forceCPU: get('compute').value === 'cpu' })
      get('backend').textContent = sampler.backend + (sampler.fallbackReason ? ` (${sampler.fallbackReason})` : '')
      get('backend').dataset.backend = sampler.backend.startsWith('GPU') ? 'gpu' : 'cpu'
      sampleCount = 0; heightSum = 0; lastSample = 0; histogram.fill(0); records = []
      chainObjects = []
      let span = 1
      for (const points of [false, true]) {
        const built = chainGeometry(p, !points), material = chainMaterial(points)
        span = built.span
        const object = points ? new THREE.Points(built.geometry, material) : new THREE.LineSegments(built.geometry, material)
        object.frustumCulled = false
        material.uniforms.positions.value = sampler.texture
        scene.add(object); chainObjects.push(object); resources.push(built.geometry, material)
      }
      if (p.wall) {
        const geometry = new THREE.PlaneGeometry(span, span), material = new THREE.MeshBasicMaterial({ color: '#294256', side: THREE.DoubleSide, transparent: true, opacity: 0.6 })
        const plane = new THREE.Mesh(geometry, material); plane.rotation.x = -Math.PI / 2; plane.position.y = -0.08
        scene.add(plane); resources.push(geometry, material)
      }
      const grid = new THREE.GridHelper(span, 8, '#66849c', '#30465b')
      grid.position.y = -0.09; scene.add(grid); resources.push(grid.geometry, grid.material)
      const fieldSign = Math.sign(p.field) || 1
      const arrow = new THREE.ArrowHelper(new THREE.Vector3(0, fieldSign, 0), new THREE.Vector3(span * 0.49, span * 0.18 - fieldSign * span * 0.07, 0), span * 0.14, '#ffbd72', span * 0.025, span * 0.015)
      arrow.visible = p.field !== 0; scene.add(arrow)
      // ArrowHelper geometry is shared by Three.js; dispose only its materials.
      resources.push(arrow.line.material, arrow.cone.material)
      camera.position.set(span * 0.72, span * 0.65, span * 0.85)
      camera.far = span * 20; camera.updateProjectionMatrix()
      controls.target.set(0, Math.sqrt(p.segments) * p.kuhn / 2, 0); controls.update()
      get('contour').textContent = `${(p.segments * p.kuhn).toFixed(1)} nm`
      get('reference').textContent = `${reference.mean.toFixed(2)} nm`
      get('physics').textContent = p.charge === 0
        ? 'Neutral control: changing E leaves this model’s equilibrium unchanged. Direct dipolar/torsional PEG response is not modeled.'
        : !p.wall ? `No-wall benchmark: exact FJC mean = ${freeChainExtension(p).toFixed(3)} nm; quadrature = ${reference.mean.toFixed(3)} nm. At E = 0, ⟨R²⟩ = ${(p.segments * p.kuhn ** 2).toFixed(2)} nm².`
          : `Terminal force ${p.charge * p.field > 0 ? 'pulls away from' : p.charge * p.field < 0 ? 'pushes toward' : 'is zero at'} the surface${p.screening ? '; it decays with height' : ''}. Ideal-chain reference includes the impenetrable wall.`
      readStats()
    } catch (error) { paused = true; get('pause').textContent = 'Resume'; get('progress').textContent = `Cannot initialize: ${error.message}` }
  }

  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'low-power' })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5))
    renderer.setClearColor('#0b1420')
    get('view').append(renderer.domElement)
    renderer.domElement.addEventListener('webglcontextlost', event => { event.preventDefault(); paused = true; get('progress').textContent = 'Graphics context lost. Close and reopen PEG testing.' })
    scene = new THREE.Scene(); camera = new THREE.PerspectiveCamera(42, 1, 0.1, 2000)
    controls = new OrbitControls(camera, renderer.domElement); controls.enableDamping = true
    observer = new ResizeObserver(() => { const width = get('view').clientWidth, height = get('view').clientHeight; renderer.setSize(width, height); camera.aspect = width / Math.max(1, height); camera.updateProjectionMatrix() })
    observer.observe(get('view'))
    rebuild()
    function animate(now) {
      if (disposed) return
      frame = requestAnimationFrame(animate)
      if (document.hidden || now - lastFrame < 33) return
      lastFrame = now
      if (!paused && sampler) sampler.step(8)
      for (const object of chainObjects) if (sampler) object.material.uniforms.positions.value = sampler.texture
      controls.update(); renderer.render(scene, camera)
      if (!paused && sampler && now - lastRead > 500) { lastRead = now; readStats() }
    }
    frame = requestAnimationFrame(animate)
  } catch (error) {
    get('backend').textContent = 'WebGL unavailable'
    get('progress').textContent = `The playground needs WebGL2 for its 3D view: ${error.message}`
    for (const button of body.querySelectorAll('button')) button.disabled = true
  }

  get('field').addEventListener('input', () => { get('field-label').textContent = `${Number(get('field').value) >= 0 ? '+' : ''}${Number(get('field').value).toFixed(3)} V/nm` })
  for (const input of body.querySelectorAll('select,input')) input.addEventListener('change', () => {
    if (input === get('preset')) {
      get('charge').value = input.value === 'neutral' ? '0' : '1'
      get('profile').value = input.value === 'screened' ? 'screened' : 'uniform'
    } else if ([get('charge'), get('profile')].includes(input) && get('preset').value !== 'free') {
      get('preset').value = get('charge').value === '0' ? 'neutral' : get('profile').value === 'screened' ? 'screened' : 'charged'
    }
    if (renderer && scene) rebuild()
  })
  get('pause').addEventListener('click', () => { paused = !paused; get('pause').textContent = paused ? 'Resume' : 'Pause' })
  get('reset').addEventListener('click', rebuild)
  get('export').addEventListener('click', () => {
    if (!sampler) return
    const payload = { model: 'ideal-PEG-Kuhn-chain-v1', status: 'Uncalibrated PEG surrogate; equilibrium Monte Carlo, not molecular dynamics',
      parameters: p, backend: sampler.backend, proposalsPerChain: sampler.sweeps, burnIn: BURN_IN,
      sampleCount, samplesAreCorrelated: true, meanHeightNm: sampleCount ? heightSum / sampleCount : null,
      histogram, reference: { meanHeightNm: reference.mean, heightsNm: Array.from(reference.heights), probability: Array.from(reference.probability) },
      recentSnapshots: records, coordinatesNmRGBA: Array.from(sampler.read()),
    }
    const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a'); link.href = url; link.download = 'peg-testing.json'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
  })
  return modal
}
