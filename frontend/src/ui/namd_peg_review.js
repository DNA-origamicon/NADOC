import * as THREE from 'three'
import './namd_peg_review.css'
import { isPegJob, wholePegCoordinates, pegRmsf, pegWaterIndices } from './namd_peg_visualization.js'
import { pegMoleculeNodes } from '../scene/namd_peg_molecule.js'
import { initPegVizControls } from './namd_peg_viz_controls.js'

export function openPegQualification(job, mode) {
  if (!isPegJob(job)) return false
  window.dispatchEvent(new CustomEvent('nadoc:peg-qualification', { detail: { jobId: job.job_id, mode } }))
  return true
}

/** Render stored atoms/PSF bonds and real recorded coordinates, without changing DNA. */
export function initNamdPegReview({ scene, camera, controls, store, api }) {
  const group = new THREE.Group(); group.name = 'NAMD PEG qualification'; scene.add(group)
  const card = document.createElement('section'); card.className = 'namd-peg-review'; card.hidden = true
  card.setAttribute('aria-label', 'Atomistic PEG qualification review')
  const title = document.createElement('strong'), status = document.createElement('p')
  status.setAttribute('role', 'status')
  const jobs = document.createElement('select'); jobs.setAttribute('aria-label', 'PEG qualification job')
  const stages = document.createElement('select'); stages.setAttribute('aria-label', 'PEG relaxation stage')
  const waterLabel = document.createElement('label'), water = document.createElement('input'); water.type = 'checkbox'
  waterLabel.append(water, ' Show water oxygens')
  const fit = document.createElement('button'); fit.textContent = 'Fit surface'; fit.className = 'btn'
  const play = document.createElement('button'); play.textContent = 'Play'; play.className = 'btn'
  const slider = document.createElement('input'); slider.type = 'range'; slider.min = 0; slider.step = 1
  slider.setAttribute('aria-label', 'PEG trajectory frame')
  const create = document.createElement('button'); create.textContent = 'Create fast relax job'; create.className = 'btn'
  create.title = '25 ps warm-up, then up to 4.8 ns at 4 fs with HMR, NVT walls and PEG-aware skip acceleration. Start with Run in the NAMD jobs list.'
  const refresh = document.createElement('button'); refresh.textContent = 'Refresh frames'; refresh.className = 'btn'
  const frameLabel = document.createElement('span')
  const representationLabel = document.createElement('p')
  const scaleLabel = document.createElement('p'); scaleLabel.className = 'peg-rmsf-scale'; scaleLabel.hidden = true
  card.append(title, status, jobs, stages, waterLabel, fit, play, slider, frameLabel, scaleLabel, representationLabel, create, refresh); document.body.append(card)
  let data = null, initial = null, designId = null, frames = [], index = 0, timer = null, generation = 0
  let representation = 'full'
  let mode = 'traj', liveTimer = null, rmsf = null, selectedJobId = null
  const sidebar = initPegVizControls({ onMode: setMode, onAction: sidebarAction })
  const stopLive = () => { clearTimeout(liveTimer); liveTimer = null }
  const stop = () => { clearInterval(timer); timer = null; play.textContent = 'Play' }
  const clear = () => {
    for (const node of [...group.children]) {
      group.remove(node); node.geometry?.dispose(); node.material?.dispose(); node.dispose?.()
    }
  }
  const fitView = () => {
    if (!data) return
    const box = data.slit.box_nm, center = new THREE.Vector3(...box).multiplyScalar(.5), scale = Math.max(...box)
    controls.target.copy(center); camera.position.copy(center).add(new THREE.Vector3(scale*1.2, -scale*1.4, scale*1.1))
    camera.lookAt(center); camera.updateProjectionMatrix(); controls.update()
  }
  function draw() {
    clear()
    if (!data) return
    const xyz = mode === 'flex' && rmsf ? rmsf.mean : wholePegCoordinates(data,
      mode === 'off' ? data.coordinates_nm : frames[index]?.coordinates_nm || data.coordinates_nm)
    const solvent = sidebar.solvent()
    const waters = new Set(mode !== 'flex' && water.checked ? pegWaterIndices(data, xyz, solvent.shell) : [])
    const peg = new Set(data.peg_indices), anchors = new Set(data.anchor_indices)
    const indices = [], colors = [], bonds = []
    const color = new THREE.Color()
    xyz.forEach((p, i) => {
      if (!peg.has(i) && !waters.has(i)) return
      indices.push(i)
      color.set(anchors.has(i) ? '#ffbf47' : data.elements[i] === 'O' ? (peg.has(i) ? '#ff6655' : '#58a6ff') : data.elements[i] === 'H' ? '#dddddd' : '#a7b1c2')
      if (mode === 'flex' && peg.has(i) && rmsf) color.setHSL((1-rmsf.angstrom[i]/(rmsf.max || 1))*2/3, .85, .55)
      colors.push(color.r, color.g, color.b)
    })
    for (const [a, b] of data.bonds) if (peg.has(a) && peg.has(b)) bonds.push([a, b])
    for (const node of pegMoleculeNodes({ xyz, indices, colors, elements: data.elements, bonds, representation })) group.add(node)
    const box = data.slit.box_nm, inset = data.slit.inset_nm, axis = data.slit.axis ?? 2
    const tangents = [0, 1, 2].filter(a => a !== axis)
    for (const z of [inset, box[axis]-inset]) {
      const plane = new THREE.Mesh(new THREE.PlaneGeometry(box[tangents[0]], box[tangents[1]]), new THREE.MeshBasicMaterial({ color: '#b57bea', transparent: true, opacity: .13, side: THREE.DoubleSide, depthWrite: false }))
      const u = new THREE.Vector3(...[0, 1, 2].map(a => +(a === tangents[0])))
      const v = new THREE.Vector3(...[0, 1, 2].map(a => +(a === tangents[1])))
      plane.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(u, v, u.clone().cross(v)))
      const center = box.map(v => v/2); center[axis] = z
      plane.position.set(...center); group.add(plane)
    }
    const grafts = []
    for (const i of anchors) { const p = [...data.coordinates_nm[i]]; p[axis] = inset; grafts.push(...p, ...xyz[i]) }
    const graftGeometry = new THREE.BufferGeometry(); graftGeometry.setAttribute('position', new THREE.Float32BufferAttribute(grafts, 3))
    group.add(new THREE.LineSegments(graftGeometry, new THREE.LineBasicMaterial({ color: '#ffbf47' })))
    if (solvent.box) {
      const boxGeometry = new THREE.BoxGeometry(...box)
      const geometry = new THREE.EdgesGeometry(boxGeometry); boxGeometry.dispose()
      const cell = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ color: '#58a6ff' }))
      cell.position.set(...box.map(v => v/2)); group.add(cell)
    }
    card.dataset.representation = representation
    representationLabel.textContent = ['vdw', 'ballstick', 'stick', 'beads', 'full'].includes(representation)
      ? `PEG representation: ${representation === 'full' ? 'atoms and bonds' : representation}`
      : 'PEG shown as atoms and bonds. DNA coarse/surface representations do not define a PEG model.'
    water.disabled = mode === 'flex'
    slider.max = Math.max(0, frames.length-1); slider.value = index
    slider.disabled = !frames.length || mode !== 'traj'; play.disabled = frames.length < 2 || mode !== 'traj'
    frameLabel.textContent = mode === 'flex' ? `Mean of ${frames.length} sampled frames · ${data.stage}` : mode !== 'off' && frames.length ? `Frame ${index+1}/${frames.length} · ${data.stage === 'minimize' ? 'iteration' : 'step'} ${frames[index].step}` : 'Initial configuration'
    scaleLabel.hidden = mode !== 'flex' || !rmsf
    scaleLabel.textContent = rmsf ? `PEG atom RMSF: blue 0 → red ${rmsf.max.toFixed(3)} Å · fixed surface frame · ${frames.length}/${data.raw_frames ?? frames.length} frames · relaxation/qualification sampling` : ''
    card.dataset.mode = mode; card.dataset.waterAtoms = waters.size
    sidebar.frame(index, frameLabel.textContent, !!timer, frames.length)
    card.dataset.atoms = data.atoms; card.dataset.frames = frames.length
  }
  function apply(next, resetCamera = true) {
    data = next; frames = next?.frames || []; index = mode === 'display' ? Math.max(0, frames.length-1) : 0; stop()
    rmsf = mode === 'flex' && frames.length >= 2 && next.stage !== 'minimize' ? pegRmsf(next, frames) : null
    if (mode === 'flex' && !rmsf) mode = 'off'
    sidebar.setMode(mode); sidebar.sync(next)
    card.hidden = !next
    if (!next) { clear(); return }
    title.textContent = next.title; status.textContent = next.note
    jobs.replaceChildren(new Option('Initial configuration', ''))
    const jobOptions = new Map([...(initial?.jobs || []), ...(next.jobs || [])].map(job => [job.job_id, job]))
    for (const job of jobOptions.values()) jobs.add(new Option(`${job.stage} · ${job.status || 'completed'}`, job.job_id))
    jobs.value = next.job_id || ''
    stages.replaceChildren(...(next.available_stages || []).map(s => new Option(s, s)))
    stages.hidden = !next.available_stages?.length; stages.value = next.stage || ''
    create.hidden = next.job?.run_kind === 'peg_fast_relax' || next.stage === 'fast relax'
    refresh.disabled = !next.job_id
    draw(); if (resetCamera) fitView()
  }
  async function loadJob(id, segment, resetCamera = true) {
    const token = ++generation; stop(); stopLive(); selectedJobId = id
    if (!id) { apply(initial, false); return }
    status.textContent = 'Loading recorded PEG trajectory…'
    try {
      const result = await api.getPegQualification(id, segment, mode === 'display' ? 1 : 100)
      if (token !== generation) return
      if (!result || result.schema !== 'nadoc.namd_peg_review.v1') throw new Error('PEG trajectory is unavailable.')
      apply(result, resetCamera)
      if (mode === 'display' && ['running', 'queued'].includes(result.job?.status)) {
        liveTimer = setTimeout(() => loadJob(id, undefined, false), 5000)
      }
    } catch (error) {
      if (token !== generation) return
      status.textContent = error.message
      if (mode === 'display') {
        status.textContent += ' · Previous snapshot retained; retrying in 5 s.'
        liveTimer = setTimeout(() => loadJob(id, undefined, false), 5000)
      }
    }
  }
  function setMode(next) {
    mode = next; generation++; stop(); stopLive(); sidebar.setMode(mode)
    if (mode === 'off') { draw(); return }
    if (selectedJobId) void loadJob(selectedJobId, mode === 'display' ? undefined : stages.value || undefined, false)
    else draw()
  }
  function togglePlay() {
    if (timer) { stop(); draw(); return }
    if (frames.length < 2 || mode !== 'traj') return
    play.textContent = 'Pause'; timer = setInterval(() => { index = (index+1)%frames.length; draw() }, 150)
    draw()
  }
  function sidebarAction(action, target) {
    if (action === 'close') { generation++; stop(); stopLive(); selectedJobId = null; apply(null, false); return }
    if (action === 'traj-play') togglePlay()
    else if (action.startsWith('traj-')) {
      stop(); index = action === 'traj-slider' ? Number(target.value) : (index + (action === 'traj-next' ? 1 : -1) + frames.length)%frames.length
      draw()
    } else {
      water.checked = sidebar.solvent().water; draw()
    }
  }
  const onJob = event => {
    mode = ({ trajectory: 'traj', none: 'off' })[event.detail.mode] || event.detail.mode || 'off'
    if (!['off', 'display', 'flex', 'traj'].includes(mode)) mode = 'off'
    sidebar.setMode(mode); loadJob(event.detail.jobId)
  }
  const onState = state => {
    const next = state.currentDesign?.metadata?.namd_peg_review || null
    const id = state.currentDesign?.id || null
    if (id === designId && next === initial) return
    designId = id; initial = next; generation++; selectedJobId = null; stopLive(); mode = 'off'; apply(next)
  }
  create.addEventListener('click', async () => {
    const source = data?.job?.run_kind === 'peg_wall_qualification' ? data.job_id
      : initial?.jobs?.find(j => j.stage === 'resident')?.job_id || initial?.jobs?.[0]?.job_id
    if (!source || create.disabled) return
    create.disabled = true
    try {
      const job = await api.createPegFastRelax(source)
      window.dispatchEvent(new CustomEvent('nadoc:md-job-created', { detail: { jobId: job.job_id, mode } }))
      await loadJob(job.job_id)
      status.textContent = 'Fast relax job created. Use Run in Simulations → NAMD; Stop and Resume use the same job.'
    } catch (error) { status.textContent = error.message }
    finally { create.disabled = false }
  })
  stages.addEventListener('change', () => loadJob(data.job_id, stages.value, false))
  refresh.addEventListener('click', () => { if (data?.job_id) loadJob(data.job_id, mode === 'display' ? undefined : stages.value || undefined, false) })
  jobs.addEventListener('change', () => {
    mode = 'traj'; sidebar.setMode(mode)
    if (jobs.value) window.dispatchEvent(new CustomEvent('nadoc:peg-job-selected', { detail: { jobId: jobs.value } }))
    loadJob(jobs.value)
  })
  water.addEventListener('change', () => { const el = document.getElementById('md-jobs-water-toggle'); if (el) el.checked = water.checked; sidebar.sync(); draw() }); fit.addEventListener('click', fitView)
  slider.addEventListener('input', () => { stop(); index = Number(slider.value); draw() })
  play.addEventListener('click', togglePlay)
  const onRepresentation = event => { representation = event.detail?.representation || 'full'; draw(); sidebar.sync() }
  window.addEventListener('nadoc:representation-change', onRepresentation)
  window.addEventListener('nadoc:peg-qualification', onJob)
  const unsubscribe = store.subscribe(onState); onState(store.getState())
  return { loadJob: (id, segment) => { mode = 'traj'; return loadJob(id, segment) }, setMode, dispose() { generation++; stop(); stopLive(); sidebar.dispose(); unsubscribe?.(); clear(); scene.remove(group); card.remove(); window.removeEventListener('nadoc:peg-qualification', onJob); window.removeEventListener('nadoc:representation-change', onRepresentation) } }
}
