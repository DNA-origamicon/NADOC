import * as THREE from 'three'
import { updateSelectionTint } from '../scene/selection_tint.js'
import { validateSelectionUpdate } from './selection_update.js'
import { validateSelectionPing } from './selection_ping_protocol.js'
import { mountSelectionPing } from './selection_ping.js'

export function validateSharedSelection(value, root) {
  if (value == null) return
  const fail = () => { throw new Error('Invalid presenter selection') }
  if (typeof value.label !== 'string' || value.label.length > 500 || !Number.isSafeInteger(value.revision) || value.revision < 0 || typeof value.target !== 'string' ||
      Object.keys(value).some(k => !['label', 'revision', 'target', 'ping'].includes(k))) fail()
  let target
  const visit = node => { if (node.uuid === value.target) target = node; node.children.forEach(visit) }; visit(root)
  if (target?.type !== 'Points') fail()
  if (value.ping != null && (typeof value.ping.id !== 'string' || !/^[a-zA-Z0-9-]{1,64}$/.test(value.ping.id) || !Number.isSafeInteger(value.ping.createdAt) || value.ping.createdAt < 0 || Object.keys(value.ping).some(k => !['id', 'createdAt'].includes(k)))) fail()
}

export function mountSharedSelection({ container, runtime }) {
  const label = container.ownerDocument.createElement('div'); label.className = 'shared-selection-label'; label.hidden = true; label.setAttribute('role', 'status'); container.append(label)
  let target = null, identity = null, currentScene = null, updateId = null, overlay = null
  let tinted = new Map(), objects = new Map()
  function clearOverlay() {
    if (overlay) {
      overlay.removeFromParent()
      overlay.traverse(o => { o.geometry?.dispose(); o.material?.dispose() })
      overlay = null
    }
    tinted = new Map(); objects = new Map(); updateId = null
  }
  const effect = mountSelectionPing({ container, getCamera: () => runtime.camera, getTarget: () => target })
  runtime.addFrameCallback?.(effect.update)
  return { update(current) {
    clearOverlay(); currentScene = current?.scene ?? null
    currentScene?.traverse(o => {
      objects.set(o.uuid, o)
      const attr = o.geometry?.attributes.instanceSelection
      if (!o.isMesh || !attr) return
      const ids = new Set()
      if (o.isInstancedMesh) { for (let i = 0; i < o.count; i++) if (attr.getX(i)) ids.add(i) }
      else if (attr.array.some(v => v !== 0)) ids.add(0)
      if (ids.size) tinted.set(o, ids)
    })
    const selection = current?.data.view?.selection
    const nextIdentity = selection ? `${selection.target}:${selection.revision}` : null
    if (nextIdentity !== identity) effect.clear()
    identity = nextIdentity; target = selection ? current.scene.getObjectByProperty('uuid', selection.target) : null
    label.hidden = !selection; label.textContent = selection ? `Presenter selected: ${selection.label}` : ''
    effect.play(selection?.ping)
  }, receiveSelection(value) {
    if (!currentScene || value?.id === updateId) return
    try { value = validateSelectionUpdate(value) } catch { return }
    // Resolve every target before changing any pixels. A stale/invalid packet
    // must not clear an otherwise valid selection.
    const next = new Map()
    for (const tint of value.tints) {
      const mesh = objects.get(tint.target), attr = mesh?.geometry?.attributes.instanceSelection
      if (!mesh?.isMesh || !attr || tint.ids.some(i => mesh.isInstancedMesh ? i >= mesh.count : i !== 0)) return
      next.set(mesh, new Set(tint.ids))
    }
    if (!overlay) {
      overlay = new THREE.Group(); overlay.name = 'Shared selection overlay'
      const cloud = new THREE.Points(new THREE.BufferGeometry(), new THREE.PointsMaterial({ color: 0xffd166, size: .65, transparent: true, opacity: .65, depthTest: false, depthWrite: false }))
      cloud.renderOrder = 1250; cloud.frustumCulled = false; cloud.raycast = () => {}
      const corners = new THREE.LineSegments(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: 0x38ff6b, depthTest: true, depthWrite: false }))
      corners.frustumCulled = false; overlay.add(cloud, corners); runtime.scene.add(overlay)
      if (target) target.visible = false
      const oldCorners = currentScene.getObjectByName('clusterSelectionCorners')
      if (oldCorners) oldCorners.visible = false
    }
    for (const mesh of new Set([...tinted.keys(), ...next.keys()])) updateSelectionTint(mesh, tinted.get(mesh) ?? new Set(), next.get(mesh) ?? new Set())
    tinted = next
    const [cloud, corners] = overlay.children
    for (const [object, positions] of [[cloud, value.points], [corners, value.corners]]) {
      const attr = object.geometry.attributes.position
      if (attr?.array.length === positions.length) { attr.array.set(positions); attr.needsUpdate = true }
      else { object.geometry.dispose(); object.geometry = new THREE.BufferGeometry(); object.geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3)) }
      object.visible = positions.length > 0
    }
    const selection = value.selection, nextIdentity = selection ? `${selection.target}:${selection.revision}` : null
    if (identity !== nextIdentity) effect.clear()
    identity = nextIdentity; target = selection ? cloud : null; updateId = value.id
    label.hidden = !selection; label.textContent = selection ? `Presenter selected: ${selection.label}` : ''
    effect.play(selection?.ping)
  }, receivePing(value) {
    try { value = validateSelectionPing(value) } catch { return }
    if (identity === `${value.target}:${value.selectionRevision}` && target) effect.play(value.ping)
  }, dispose() { runtime.removeFrameCallback?.(effect.update); effect.dispose(); clearOverlay(); label.remove() } }
}
