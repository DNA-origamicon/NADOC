import { createSharedAnnotationOccupancy } from './shared_annotation_occupancy.js'
import * as THREE from 'three'
import { initAnnotationOverlay } from '../scene/annotation_overlay.js'
import { CALLOUT_TYPES, MAX_TEXT_LENGTH, SIZE_RANGE, TRANSPARENCY_RANGE } from '../scene/annotation_model.js'
import { isAnnotationIcon } from '../scene/annotation_icons.js'

export function validateSharedAnnotations(entries, root) {
  if (entries == null) return
  const fail = () => { throw new Error('Invalid shared annotations') }
  if (!Array.isArray(entries) || entries.length > 1000) fail()
  const nodes = new Map(), ids = new Set()
  const visit = node => { nodes.set(node.uuid, node); node.children.forEach(visit) }
  visit(root)
  const fields = new Set(['id', 'text', 'icon', 'calloutType', 'color', 'size', 'transparency', 'manual', 'screenPos', 'targets'])
  for (const e of entries) {
    if (!e || typeof e !== 'object' || Object.keys(e).some(k => !fields.has(k)) ||
        typeof e.id !== 'string' || !e.id.length || e.id.length > 256 || ids.has(e.id) ||
        typeof e.text !== 'string' || e.text.length > MAX_TEXT_LENGTH ||
        (e.icon !== null && !isAnnotationIcon(e.icon)) || !CALLOUT_TYPES.some(t => t.key === e.calloutType) ||
        typeof e.color !== 'string' || !/^#[0-9a-f]{6}$/i.test(e.color) ||
        !Number.isFinite(e.size) || e.size < SIZE_RANGE.min || e.size > SIZE_RANGE.max ||
        !Number.isFinite(e.transparency) || e.transparency < TRANSPARENCY_RANGE.min || e.transparency > TRANSPARENCY_RANGE.max ||
        typeof e.manual !== 'boolean' || (e.screenPos !== null && (!e.screenPos || !['x', 'y'].every(k => Number.isFinite(e.screenPos[k]) && e.screenPos[k] >= 0 && e.screenPos[k] <= 1))) ||
        !Array.isArray(e.targets) || e.targets.length > 4096 || e.targets.some(id => !['Points', 'Sprite'].includes(nodes.get(id)?.type))) fail()
    ids.add(e.id)
  }
}

/** Reuse callout layout with guest camera projection and the shared render buffers. */
export function mountSharedAnnotations({ current, container, runtime }) {
  const entries = (current.data.view?.annotations ?? []).map(e => ({ ...e, visible: true, refs: [], manual: false, screenPos: null }))
  if (!entries.length) return { dispose() {} }
  const objects = new Map()
  current.scene.traverse(o => objects.set(o.uuid, o))
  return initAnnotationOverlay({
    container, document: container.ownerDocument, scene: current.scene, getCamera: () => runtime.camera,
    controller: { list: () => entries, isEnabled: () => true, subscribe: () => () => {} }, readOnly: true,
    addFrameCallback: runtime.addFrameCallback, removeFrameCallback: runtime.removeFrameCallback,
    // Guest cameras differ from the host; auto-layout against guest geometry.
    // Update matrices once per overlay frame, before resolving any annotation.
    getEntries: () => { current.scene.updateMatrixWorld(true); return [] },
    getOccluders: createSharedAnnotationOccupancy(current.scene),
    resolveSharedPoints: entry => {
      const points = []
      for (const id of entry.targets) {
        const object = objects.get(id)
        if (object?.isPoints) {
          const position = object.geometry.attributes.position
          for (let i = 0; i < position.count; i++) points.push(new THREE.Vector3().fromBufferAttribute(position, i).applyMatrix4(object.matrixWorld))
        } else if (object?.isSprite) points.push(object.getWorldPosition(new THREE.Vector3()))
      }
      return points
    },
  })
}
