import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { reverseComplement, overhangLabel, ssdnaHelixFrames } from './conjugate_manager_logic.js'
import { THIOL_SCHEMES, sliderCount, countSliderStep, manualStrandCount, conjugationSummary } from './nanoparticle_conjugate_logic.js'

const BORDER = '#30363d', BG = '#161b22', DIM = '#8b949e', TEXT = '#c9d1d9', CYAN = '#39c0ff'
const BEAD_RADIUS = 0.10, CONE_RADIUS = 0.075
const SLAB = { length: 0.30, width: 0.06, thickness: 0.70, offset: 0.45 }
const Y_HAT = new THREE.Vector3(0, 1, 0)

export function initNanoparticleConjugateManager({ api, store } = {}) {
  let ctx = null
  function close() {
    if (!ctx) return
    cancelAnimationFrame(ctx.raf)
    window.removeEventListener('keydown', ctx.onKey, true); window.removeEventListener('resize', ctx.resize)
    ctx.controls.dispose(); ctx.renderer.dispose(); ctx.overlay.remove(); ctx = null
  }

  async function open(nanoparticleId) {
    close()
    const design = store.getState().currentDesign
    const particle = design?.nanoparticles?.find(p => p.id === nanoparticleId)
    if (!particle) throw new Error('Nanoparticle not found')
    const existing = (await api.getNanoparticleConjugation(nanoparticleId))?.conjugations?.[0]
    const overhangs = (design?.overhangs ?? []).filter(o => !o.auxiliary_endpoint)
    const overlay = document.createElement('div'); overlay.id = 'nanoparticle-conjugate-overlay'
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:9000;display:flex;align-items:center;justify-content:center;'
    const win = document.createElement('div')
    win.style.cssText = `background:${BG};border:1px solid ${BORDER};border-radius:8px;padding:16px;width:960px;height:600px;max-width:96vw;max-height:90vh;display:flex;flex-direction:column;font-family:monospace;color:#e6e6e6;`
    const header = document.createElement('div'); header.style.cssText = 'display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;flex:0 0 auto;'
    header.innerHTML = '<div style="font-size:15px;font-weight:600">Conjugate Manager — thiol-oligo to gold nanoparticle</div><button id="np-conj-x" style="background:none;border:none;color:#8b949e;font-size:20px;cursor:pointer;padding:0 4px">×</button>'
    const body = document.createElement('div'); body.style.cssText = 'flex:1;display:flex;gap:14px;min-height:0;'
    const left = document.createElement('div'); left.style.cssText = 'flex:0 0 230px;display:flex;flex-direction:column;min-height:0;'
    const preview = document.createElement('div'); preview.id = 'np-conjugate-preview'; preview.style.cssText = `flex:1;position:relative;min-width:0;border:1px solid ${BORDER};border-radius:4px;overflow:hidden;`
    const canvas = document.createElement('canvas'); canvas.style.cssText = 'width:100%;height:100%;display:block;'; preview.appendChild(canvas)
    const hint = document.createElement('div'); hint.textContent = 'Drag to orbit · wheel to zoom · right-drag to pan'; hint.style.cssText = `position:absolute;left:8px;bottom:6px;color:${DIM};font-size:10px;pointer-events:none`; preview.appendChild(hint)
    const right = document.createElement('div'); right.style.cssText = 'flex:0 0 230px;display:flex;flex-direction:column;min-height:0;'
    body.append(left, preview, right); win.append(header, body); overlay.appendChild(win); document.body.appendChild(overlay)

    left.innerHTML = `<div style="font-size:12px;color:${DIM};text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px">Overhangs</div>
      <div id="np-conj-overhangs" style="flex:1;min-height:80px;overflow-y:auto;border:1px solid ${BORDER};border-radius:4px;margin-bottom:10px"></div>
      <label style="font-size:12px;color:${TEXT};display:block;margin-bottom:3px">ssDNA handle</label>
      <input id="np-conj-sequence" readonly placeholder="select an overhang" style="width:100%;box-sizing:border-box;background:#0d1117;border:1px solid ${BORDER};border-radius:4px;color:${CYAN};font-family:monospace;font-size:12px;padding:5px 7px;margin-bottom:10px">
      <div style="font-size:12px;color:${TEXT};margin-bottom:10px">Thiol modification &nbsp;<label style="margin-right:8px"><input type="radio" name="np-thiol-end" value="5p" checked> 5′ end</label><label><input type="radio" name="np-thiol-end" value="3p"> 3′ end</label></div>
      <button id="np-conj-create-handle" disabled style="width:100%;background:#1f6feb;color:#fff;border:none;border-radius:5px;padding:8px;cursor:pointer;font-size:13px">Create ssDNA handle</button>
      <div id="np-conj-status" style="font-size:11px;color:${DIM};margin:8px 0;min-height:28px"></div>`
    right.innerHTML = `<div style="font-size:12px;color:${DIM};text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px">Surface coverage</div>
      <label style="font-size:12px;color:${TEXT}">Thiol scheme<select id="np-conj-scheme" style="display:block;width:100%;box-sizing:border-box;background:#0d1117;border:1px solid ${BORDER};border-radius:4px;color:${TEXT};padding:5px;margin:4px 0 10px"></select></label>
      <label style="font-size:12px;color:${TEXT}">Density<input id="np-conj-density" type="range" min="0" max="8" step="1" style="display:block;width:100%;margin-top:7px"></label>
      <div style="display:flex;justify-content:space-between;color:${DIM};font-size:9px"><span>1</span><span>2</span><span>3</span><span>5</span><span>10</span><span>25%</span><span>50%</span><span>75%</span><span>100%</span></div>
      <label style="font-size:12px;color:${TEXT};margin-top:10px"><input id="np-conj-count" type="number" min="1" max="10000" style="width:72px;background:#0d1117;border:1px solid ${BORDER};border-radius:4px;color:${TEXT};padding:4px"> strands</label>
      <div id="np-conj-summary" style="font-size:11px;color:${DIM};line-height:1.55;margin-top:12px"></div><div id="np-conj-error" style="font-size:11px;color:#ff7b72;min-height:28px;margin-top:8px"></div>
      <div style="display:flex;gap:8px;margin-top:auto"><button id="np-conj-cancel" style="flex:1;background:#21262d;color:${TEXT};border:1px solid ${BORDER};border-radius:5px;padding:8px;cursor:pointer;font-size:13px">Cancel</button><button id="np-conj-apply" disabled style="flex:1;background:#238636;color:#fff;border:none;border-radius:5px;padding:8px;cursor:pointer;font-size:13px">Apply</button></div>
      <button id="np-conj-remove" style="margin-top:8px;background:#21262d;color:${TEXT};border:1px solid ${BORDER};border-radius:5px;padding:6px;cursor:pointer">Remove conjugation</button>`

    const list = left.querySelector('#np-conj-overhangs'), sequence = left.querySelector('#np-conj-sequence')
    const createHandle = left.querySelector('#np-conj-create-handle'), status = left.querySelector('#np-conj-status')
    const apply = right.querySelector('#np-conj-apply'), scheme = right.querySelector('#np-conj-scheme')
    const range = right.querySelector('#np-conj-density'), count = right.querySelector('#np-conj-count')
    if (!overhangs.length) list.innerHTML = '<div style="padding:14px;font-size:11px;color:#6e7681;text-align:center">No overhangs in this design.</div>'
    THIOL_SCHEMES.forEach(([value, label]) => scheme.add(new Option(label, value))); scheme.value = existing?.scheme ?? 'direct_thiol'
    let selectedOverhang = null, handleReady = false, estimate = null

    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true }); renderer.setPixelRatio(Math.min(devicePixelRatio, 2))
    const scene = new THREE.Scene(); scene.background = new THREE.Color(0x0d1117)
    scene.add(new THREE.AmbientLight(0xffffff, .6)); const light = new THREE.DirectionalLight(0xffffff, .9); light.position.set(1, 1, 1); scene.add(light)
    const camera = new THREE.PerspectiveCamera(55, 1, .1, 2000); camera.position.set(particle.diameter_nm * .7, particle.diameter_nm * .55, Math.max(18, particle.diameter_nm * 2.8))
    const controls = new OrbitControls(camera, canvas); controls.enableDamping = true; controls.enablePan = true; controls.target.set(0, 0, 0); controls.update()
    scene.add(new THREE.Mesh(new THREE.SphereGeometry(particle.diameter_nm / 2, 48, 32), new THREE.MeshPhysicalMaterial({ color: 0xd4af37, metalness: 1, roughness: .18, clearcoat: .45 })))
    const corona = new THREE.Group(); scene.add(corona)
    function addFullHandle(dir, radius) {
      const start = dir.clone().multiplyScalar(radius + (estimate?.default_spacer_nm ?? .7))
      const d = { x: dir.x, y: dir.y, z: dir.z }
      const frames = ssdnaHelixFrames({ x: start.x, y: start.y, z: start.z }, d, sequence.value.length)
      const beadGeom = new THREE.SphereGeometry(BEAD_RADIUS, 10, 8), coneGeom = new THREE.ConeGeometry(CONE_RADIUS, 1, 8)
      const slabGeom = new THREE.BoxGeometry(SLAB.length, SLAB.width, SLAB.thickness)
      const mat = new THREE.MeshPhongMaterial({ color: 0x39c0ff }), slabMat = new THREE.MeshPhongMaterial({ color: 0x39c0ff, transparent: true, opacity: .9 })
      const attachEnd = left.querySelector('input[name="np-thiol-end"]:checked')?.value ?? '5p'
      frames.forEach((frame, i) => {
        const p = new THREE.Vector3(frame.position.x, frame.position.y, frame.position.z)
        const normalV = new THREE.Vector3(frame.baseNormal.x, frame.baseNormal.y, frame.baseNormal.z)
        const tangential = new THREE.Vector3().crossVectors(dir, normalV).normalize()
        const slabQuat = new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().makeBasis(tangential, dir, normalV))
        const sequenceIndex = attachEnd === '5p' ? i : frames.length - 1 - i
        const bead = new THREE.Mesh(beadGeom, mat); bead.name = 'np-preview-handle-bead'; bead.position.copy(p); bead.userData = { sequenceIndex, attachEnd }; corona.add(bead)
        const slab = new THREE.Mesh(slabGeom, slabMat); slab.name = 'np-preview-handle-slab'; slab.position.copy(p).addScaledVector(normalV, SLAB.offset); slab.quaternion.copy(slabQuat); slab.userData = { sequenceIndex, base: sequence.value[sequenceIndex] }; corona.add(slab)
        if (i < frames.length - 1) {
          const next = frames[i + 1].position
          const delta = new THREE.Vector3(next.x, next.y, next.z).sub(p)
          const length = delta.length()
          const cone = new THREE.Mesh(coneGeom, mat); cone.name = 'np-preview-handle-connector'
          cone.position.copy(p).addScaledVector(delta, .5)
          cone.quaternion.setFromUnitVectors(Y_HAT, delta.normalize())
          cone.scale.set(1, length, 1); corona.add(cone)
        }
      })
    }
    function draw(n) {
      corona.clear(); const golden = Math.PI * (3 - Math.sqrt(5)), radius = particle.diameter_nm / 2
      for (let i = 0; i < n; i++) {
        const y = 1 - 2 * (i + .5) / n, rr = Math.sqrt(Math.max(0, 1 - y*y)), a = golden*i, dir = new THREE.Vector3(rr*Math.cos(a), y, rr*Math.sin(a))
        if (handleReady) addFullHandle(dir, radius)
        else corona.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([dir.clone().multiplyScalar(radius), dir.clone().multiplyScalar(radius + 3)]), new THREE.LineBasicMaterial({ color: 0x39c0ff })))
        const sulfur = new THREE.Mesh(new THREE.SphereGeometry(.18, 10, 7), new THREE.MeshPhongMaterial({ color: 0xffd43b })); sulfur.position.copy(dir).multiplyScalar(radius); corona.add(sulfur)
      }
    }
    function resize() { const w = preview.clientWidth || 1, h = preview.clientHeight || 1; renderer.setSize(w, h, false); camera.aspect = w/h; camera.updateProjectionMatrix() }
    function summary() {
      const n = manualStrandCount(count.value); count.value = n
      const s = conjugationSummary(n, estimate), capacityRange = estimate.estimated_capacity_range?.join('–') ?? s.capacity
      const overCapacity = n > s.capacity
        ? `<br><span style="color:#d29922">Manual count exceeds estimated maximum coverage.</span>` : ''
      right.querySelector('#np-conj-summary').innerHTML = `<b style="color:${TEXT}">${n} strands</b><br>${s.density.toFixed(4)} strands/nm²<br>≈ ${s.spacing.toFixed(2)} nm mean spacing<br>Estimated capacity: ${s.capacity} (${capacityRange})${overCapacity}<br><a href="${estimate.source_url}" target="_blank" rel="noreferrer" style="color:${CYAN}">Literature basis</a>`; draw(n)
    }
    async function refresh(preserve = false) {
      estimate = await api.estimateNanoparticleConjugation(nanoparticleId, scheme.value)
      const n = preserve ? Number(count.value) : (existing?.requested_count ?? 1)
      count.value = manualStrandCount(n); range.value = countSliderStep(Number(count.value), estimate.estimated_capacity); summary()
    }
    overhangs.forEach(ov => {
      const row = document.createElement('div'); row.className = 'ohc-list-row'; row.style.cssText = 'padding:6px 9px;cursor:pointer;font-size:12px;border-bottom:1px solid #21262d;'; row.textContent = overhangLabel(ov)
      row.onclick = () => { selectedOverhang = ov; list.querySelectorAll('.ohc-list-row').forEach(r => r.classList.remove('is-selected')); row.classList.add('is-selected'); sequence.value = reverseComplement(ov.sequence); sequence.placeholder = sequence.value ? '' : '(overhang has no sequence)'; createHandle.disabled = !sequence.value; handleReady = false; apply.disabled = true; count.value = 1; range.value = 0; summary(); status.textContent = '' }
      list.appendChild(row)
    })
    createHandle.onclick = () => { if (!selectedOverhang || !sequence.value) return; handleReady = true; apply.disabled = false; summary(); status.textContent = `${sequence.value.length} nt complementary handle ready for ${selectedOverhang.label || selectedOverhang.id}.` }
    left.querySelectorAll('input[name="np-thiol-end"]').forEach(radio => { radio.onchange = () => { if (handleReady) summary() } })
    scheme.onchange = () => refresh(true); range.oninput = () => { count.value = sliderCount(Number(range.value), estimate.estimated_capacity); summary() }; count.oninput = () => { range.value = countSliderStep(Number(count.value), estimate.estimated_capacity); summary() }
    apply.onclick = async () => {
      const error = right.querySelector('#np-conj-error'); error.textContent = ''; apply.disabled = true
      try {
        const result = await api.putNanoparticleConjugation(nanoparticleId, { scheme: scheme.value, sequence: sequence.value, count: Number(count.value), attach_end: left.querySelector('input[name="np-thiol-end"]:checked')?.value ?? '5p', seed: 1 })
        if (result?.strand_ids?.[0]) await api.bindNanoparticleStrand(nanoparticleId, result.strand_ids[0], selectedOverhang.id)
        close()
      } catch (e) { error.textContent = e?.message ?? String(e); apply.disabled = !handleReady }
    }
    right.querySelector('#np-conj-remove').disabled = !existing; right.querySelector('#np-conj-remove').onclick = async () => { if (existing) await api.deleteNanoparticleConjugation(nanoparticleId); close() }
    right.querySelector('#np-conj-cancel').onclick = close; header.querySelector('#np-conj-x').onclick = close; overlay.onclick = e => { if (e.target === overlay) close() }
    const onKey = e => { if (e.key === 'Escape') { e.stopPropagation(); close() } }; window.addEventListener('keydown', onKey, true); window.addEventListener('resize', resize)
    ctx = { overlay, renderer, scene, camera, controls, raf: 0, resize, onKey }; resize(); await refresh()
    const tick = () => { if (!ctx) return; controls.update(); renderer.render(scene, camera); ctx.raf = requestAnimationFrame(tick) }; ctx.raf = requestAnimationFrame(tick)
  }
  return {
    open, close, isOpen: () => Boolean(ctx),
    previewCamera: () => ctx ? { position: ctx.camera.position.toArray(), target: ctx.controls.target.toArray() } : null,
    fullHandleCensus: () => ctx ? {
      beads: ctx.scene.getObjectsByProperty('name', 'np-preview-handle-bead').length,
      slabs: ctx.scene.getObjectsByProperty('name', 'np-preview-handle-slab').length,
      connectors: ctx.scene.getObjectsByProperty('name', 'np-preview-handle-connector').length,
    } : { beads: 0, slabs: 0, connectors: 0 },
  }
}
