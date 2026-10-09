import * as THREE from 'three'
import { STLLoader } from 'three/addons/loaders/STLLoader.js'
import { setReferenceOpacity } from './reference_material.js'
import { TransformControls } from 'three/addons/controls/TransformControls.js'
import { createContextMenu } from '../ui/primitives/context_menu.js'
import { openReferenceColorPopup } from '../ui/reference_color_popup.js'
import { showToast } from '../ui/toast.js'
import { docHeaders } from '../shared/doc_id.js'

export const REFERENCE_COLORS = ['#8da9c4', '#ef8354', '#69b578', '#c792ea', '#ffffff']
export const REFERENCE_OPACITIES = [1, 0.75, 0.5, 0.25]
export function parseReferenceSTL(buffer, nmPerUnit = 1) {
  if (Object.prototype.toString.call(buffer) !== '[object ArrayBuffer]' || buffer.byteLength < 15 || buffer.byteLength > 100 * 1024 * 1024) throw new Error('Invalid STL file size.')
  if (buffer.byteLength >= 84) {
    const count = new DataView(buffer).getUint32(80, true)
    const binarySize = 84 + count * 50
    const ascii = new TextDecoder().decode(buffer.slice(0, 80)).trimStart().startsWith('solid')
    if (binarySize === buffer.byteLength ? count > 1_000_000 : !ascii) throw new Error('Invalid or oversized binary STL.')
  }
  const geometry = new STLLoader().parse(buffer)
  const positions = geometry.getAttribute('position')
  if (!positions || !positions.count || positions.count % 3 || positions.count > 3_000_000 ||
      !Array.from(positions.array).every(Number.isFinite)) {
    geometry.dispose()
    throw new Error('STL must contain finite triangles (maximum one million).')
  }
  geometry.scale(nmPerUnit, nmPerUnit, nmPerUnit)
  geometry.computeBoundingBox()
  if (geometry.boundingBox.getSize(new THREE.Vector3()).length() <= 0) {
    geometry.dispose(); throw new Error('STL has no size.')
  }
  geometry.center()
  geometry.computeVertexNormals()
  geometry.computeBoundingSphere()
  return geometry
}

export function uniformReferenceScale(scale, axis, fallback = 1) {
  const axes = [...(axis || 'XYZ')].filter(letter => 'XYZ'.includes(letter))
  const value = Math.pow(axes.reduce((product, letter) => product * Math.abs(scale[letter.toLowerCase()]), 1), 1 / axes.length)
  return Number.isFinite(value) ? Math.max(1e-6, Math.min(1e6, value)) : fallback
}

// Intentionally outside the document store: these objects never enter NADOC saves.
export function initReferenceModels({ scene, camera, canvas, controls, onImported, onSelected }) {
  const root = new THREE.Group(); root.name = 'Temporary STL references'; scene.add(root)
  const ray = new THREE.Raycaster(), pointer = new THREE.Vector2()
  const tc = new TransformControls(camera, canvas)
  scene.add(tc.getHelper()); tc.enabled = false
  let selected = null, mode = 0, menu = null, down = null, consumed = false, gizmoGesture = false
  let colorPopup = null
  let uniformScale = 1
  let revision = 0, sent = -1, session = null, busy = false, eventSequence = 0
  const changed = () => { revision++ }
  function select(mesh, publishSelection = true) {
    if (selected !== mesh) {
      colorPopup?.close()
      if (publishSelection) changed()
      if (mesh) onSelected?.()
    }
    if (selected) selected.material.emissive.setHex(0)
    selected = mesh
    tc.detach(); tc.enabled = !!mesh
    if (mesh) { mesh.material.emissive.setHex(0x29445a); tc.attach(mesh) }
  }
  function setMode(value) {
    mode = value; tc.setMode(['translate', 'rotate', 'scale'][mode]); tc.setSpace(mode === 2 ? 'local' : 'world')
    tc.showX = tc.showY = tc.showZ = true
  }
  tc.addEventListener('objectChange', () => {
    if (selected && mode === 2) {
      uniformScale = uniformReferenceScale(selected.scale, tc.axis, uniformScale)
      selected.scale.setScalar(uniformScale)
    }
  })
  tc.addEventListener('dragging-changed', e => {
    controls.enabled = !e.value
    if (e.value) uniformScale = selected.scale.x
    else changed()
  })
  function add(geometry, name, source) {
    if (root.children.length >= 64 || root.children.reduce((n, m) => n + m.geometry.attributes.position.count, geometry.attributes.position.count) > 3_000_000) {
      geometry.dispose(); throw new Error('Reference limit: 64 models or one million triangles total.')
    }
    const mesh = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ color: REFERENCE_COLORS[0], side: THREE.DoubleSide, roughness: 0.8 }))
    mesh.name = name; mesh.userData.referenceId = crypto.randomUUID()
    if (source) { mesh.position.copy(source.position); mesh.quaternion.copy(source.quaternion); mesh.scale.copy(source.scale); mesh.material.copy(source.material); mesh.material.emissive.setHex(0) }
    root.add(mesh); select(mesh); setMode(0); changed(); return mesh
  }
  function action(kind) {
    if (!selected) return
    if (kind === 'reset') { selected.position.set(0, 0, 0); selected.quaternion.identity(); selected.scale.setScalar(1) }
    if (kind === 'color') { const i = REFERENCE_COLORS.indexOf('#' + selected.material.color.getHexString()); selected.material.color.set(REFERENCE_COLORS[(i + 1) % REFERENCE_COLORS.length]) }
    if (kind === 'opacity') { const i = REFERENCE_OPACITIES.indexOf(selected.material.opacity); setReferenceOpacity(selected.material, REFERENCE_OPACITIES[(i + 1) % REFERENCE_OPACITIES.length]) }
    if (kind === 'duplicate') {
      try { add(selected.geometry.clone(), selected.name + ' copy', selected) }
      catch (error) { showToast(error.message, { severity: 'error' }) }
    }
    if (kind === 'delete') { const old = selected; select(null); root.remove(old); old.geometry.dispose(); old.material.dispose() }
    changed()
  }
  function editColor() {
    colorPopup?.close()
    const mesh = selected
    if (!mesh) return
    colorPopup = openReferenceColorPopup({
      color: '#' + mesh.material.color.getHexString(), opacity: mesh.material.opacity,
      onChange({ color, opacity }) {
        mesh.material.color.set(color)
        setReferenceOpacity(mesh.material, opacity)
        changed()
      },
      onClose() { colorPopup = null },
    })
  }
  function context(e) {
    menu?.close()
    menu = createContextMenu({ x: e.clientX, y: e.clientY, items: [
      { type: 'header', label: selected.name },
      ...[['reset', 'Reset transforms'], ['color', 'Color…'], ['duplicate', 'Duplicate'], ['delete', 'Delete']].map(([kind, label]) => ({ label, onClick: () => kind === 'color' ? editColor() : action(kind) })),
    ] })
  }
  function hit(e) {
    const r = canvas.getBoundingClientRect(); pointer.set((e.clientX-r.left)/r.width*2-1, -(e.clientY-r.top)/r.height*2+1)
    scene.updateMatrixWorld(true); ray.setFromCamera(pointer, camera)
    return ray.intersectObjects(root.children, false)[0]?.object ?? null
  }
  // Capture reference clicks before molecular picking; leave TransformControls' own handlers intact.
  canvas.addEventListener('pointerdown', e => {
    gizmoGesture = e.button === 0 && !!tc.axis
    down = { x: e.clientX, y: e.clientY, mesh: hit(e) }
    consumed = !!down.mesh && (e.button === 2 || !tc.axis)
    if (consumed) { controls.enabled = false; e.stopImmediatePropagation() }
  }, true)
  canvas.addEventListener('pointerup', e => {
    if (consumed) {
      e.stopImmediatePropagation(); controls.enabled = true; consumed = false
      if (Math.hypot(e.clientX-down.x, e.clientY-down.y) < 5) { select(down.mesh); if (e.button === 2) context(e); else setMode(0) }
    } else if (!tc.dragging && !tc.axis && e.button === 0 && down && Math.hypot(e.clientX-down.x, e.clientY-down.y) < 5 && !hit(e)) select(null)
  }, true)
  canvas.addEventListener('pointerdown', e => { if (gizmoGesture) e.stopImmediatePropagation() })
  canvas.addEventListener('pointerup', e => { if (gizmoGesture) { gizmoGesture = false; e.stopImmediatePropagation() } })
  canvas.addEventListener('pointercancel', () => { consumed = gizmoGesture = false; controls.enabled = true })
  canvas.addEventListener('click', e => { if (hit(e) || tc.axis) e.stopImmediatePropagation() }, true)
  canvas.addEventListener('contextmenu', e => { if (hit(e)) { e.preventDefault(); e.stopImmediatePropagation(); if (!(e.buttons & 2)) { select(hit(e)); context(e) } } }, true)
  window.addEventListener('keydown', e => {
    if (colorPopup?.isOpen()) return
    if (!selected || /INPUT|TEXTAREA|SELECT/.test(e.target?.tagName) || e.target?.isContentEditable) return
    if (e.key === 'Tab') { e.preventDefault(); e.stopImmediatePropagation(); setMode((mode+1)%3) }
    if (e.key === 'Escape') { select(null); menu?.close() }
  }, true)
  const input = document.createElement('input'); input.type = 'file'; input.accept = '.stl'; input.hidden = true
  input.dataset.referenceStl = ''; document.body.append(input)
  input.addEventListener('change', async () => {
    const file = input.files?.[0]; if (!file) return
    try {
      if (file.size > 100 * 1024 * 1024) throw new Error('STL file exceeds 100 MB.')
      const mesh = add(parseReferenceSTL(await file.arrayBuffer()), file.name)
      onImported?.()
      const radius = mesh.geometry.boundingSphere.radius
      const direction = camera.position.clone().sub(controls.target).normalize()
      if (direction.lengthSq() === 0) direction.set(1, 1, 1).normalize()
      controls.target.copy(mesh.position)
      const distance = radius / Math.sin(THREE.MathUtils.degToRad(camera.fov / 2)) * 1.2
      camera.position.copy(mesh.position).addScaledVector(direction, distance)
      camera.far = Math.max(camera.far, distance + radius * 4)
      camera.updateProjectionMatrix(); controls.update()
      showToast('STL reference imported (1 mm → 1 nm). Temporary; not saved in NADOC.')
    } catch (error) { showToast('STL import failed: ' + error.message, { severity: 'error' }) }
    input.value = ''
  })
  document.getElementById('menu-file-import-stl')?.addEventListener('click', () => input.click())
  function snapshot() {
    return root.children.map(mesh => { mesh.updateMatrix(); return { id: mesh.userData.referenceId, vertices: Array.from(mesh.geometry.attributes.position.array), matrix: mesh.matrix.toArray(), color: mesh.material.color.toArray(), opacity: mesh.material.opacity } })
  }
  // Geometry crosses the bridge only after a desktop edit or a fresh VR session.
  async function sync() {
    if (busy) return; busy = true
    try {
      const response = await fetch('/api/vr/references', { headers: docHeaders() })
      if (!response.ok) return
      const state = await response.json()
      if (!state.session) { session = null; return }
      if (session !== state.session) { session = state.session; sent = -1; eventSequence = 0 }
      if (state.event?.sequence > eventSequence && state.event.revision === sent && revision === sent && !tc.dragging) {
        eventSequence = state.event.sequence
        const mesh = root.children.find(m => m.userData.referenceId === state.event.id)
        select(mesh ?? null, false)
        if (mesh && state.event.matrix) new THREE.Matrix4().fromArray(state.event.matrix).decompose(mesh.position, mesh.quaternion, mesh.scale)
        if (mesh && state.event.action) action(state.event.action)
      }
      if (sent !== revision && !tc.dragging) {
        const version = revision
        const result = await fetch('/api/vr/references', { method: 'POST', headers: { ...docHeaders(), 'Content-Type': 'application/json' }, body: JSON.stringify({ revision: version, selected: selected?.userData.referenceId ?? '', models: snapshot() }) })
        if (result.ok) sent = version
      }
    } catch { /* Native VR is optional; desktop references remain usable. */ }
    finally { busy = false }
  }
  const timer = setInterval(sync, 500)
  return { root, select, action, snapshot, get selected() { return selected }, get mode() { return mode }, dispose() { colorPopup?.close(); clearInterval(timer); tc.dispose(); input.remove() } }
}
