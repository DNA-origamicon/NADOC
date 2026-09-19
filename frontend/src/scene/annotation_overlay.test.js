import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import * as THREE from 'three'
import { createAnnotationController } from './annotation_controller.js'
import { initAnnotationOverlay } from './annotation_overlay.js'

const nuc = (strand_id, helix_id, bp_index) => ({ strand_id, helix_id, bp_index, direction: 'FORWARD', domain_index: 0 })
const mk = (n, x, y = 0, z = 0) => ({ nuc: n, pos: new THREE.Vector3(x, y, z) })

let container, scene, camera, controller, overlay, entries
const VIEW = { width: 800, height: 600 }

// jsdom has no layout: give callouts a real size so placement/coverage are meaningful.
const sizeDescriptors = {}
beforeEach(() => {
  for (const [prop, value] of [['offsetWidth', 120], ['offsetHeight', 40]]) {
    sizeDescriptors[prop] = Object.getOwnPropertyDescriptor(HTMLElement.prototype, prop)
    Object.defineProperty(HTMLElement.prototype, prop, { configurable: true, get() { return this.classList?.contains('nadoc-anno') ? value : 0 } })
  }
  container = document.createElement('div')
  document.body.append(container)
  scene = new THREE.Scene()
  camera = new THREE.PerspectiveCamera(50, VIEW.width / VIEW.height, 0.1, 1000)
  camera.position.set(0, 0, 20)
  camera.lookAt(0, 0, 0)
  entries = [mk(nuc('s1', 'h0', 0), -2), mk(nuc('s1', 'h0', 1), 0), mk(nuc('s1', 'h0', 2), 2), mk(nuc('s2', 'h1', 0), 0, 3)]
  controller = createAnnotationController()
  controller.syncFromDesign({ id: 'd1', annotations: [] })
  overlay = initAnnotationOverlay({
    container, scene, controller, getCamera: () => camera, getEntries: () => entries,
    getDesign: () => ({}), getViewport: () => VIEW,
  })
})
afterEach(() => {
  overlay.dispose(); container.remove()
  for (const [prop, d] of Object.entries(sizeDescriptors)) { if (d) Object.defineProperty(HTMLElement.prototype, prop, d); else delete HTMLElement.prototype[prop] }
})

const callout = id => container.querySelector(`[data-annotation-id="${id}"]`)
const highlight = id => scene.getObjectByName(`Annotation highlight ${id}`)

describe('annotation overlay', () => {
  it('draws nothing until the entry has text or an icon', () => {
    const a = controller.add({ refs: [{ kind: 'strand', id: 's1' }] })
    overlay.update()
    expect(callout(a.id).hidden).toBe(true)
    expect(highlight(a.id)).toBeUndefined()
    controller.update(a.id, { icon: 'warning' })
    overlay.update()
    expect(callout(a.id).hidden).toBe(false)
    expect(callout(a.id).querySelector('.nadoc-anno__icon svg')).toBeTruthy()
    controller.update(a.id, { icon: null })
    overlay.update()
    expect(callout(a.id).hidden).toBe(true)
    expect(highlight(a.id)).toBeUndefined()
  })

  it('highlights exactly the target beads in the entry colour, above depth', () => {
    const a = controller.add({ text: 'hi', color: '#ff0000', refs: [{ kind: 'strand', id: 's1' }] })
    overlay.update()
    const pts = highlight(a.id)
    expect(pts.geometry.attributes.position.count).toBe(3)
    expect([...pts.geometry.attributes.position.array]).toEqual([-2, 0, 0, 0, 0, 0, 2, 0, 0])
    expect(pts.material.color.getHexString()).toBe('ff0000')
    expect(pts.material.depthTest).toBe(false)
    expect(pts.renderOrder).toBeGreaterThan(1000)
    expect(callout(a.id).style.getPropertyValue('--anno-color')).toBe('#ff0000')
  })

  it('follows live bead positions and draws a leader ending on the projected anchor', () => {
    const a = controller.add({ text: 'hi', refs: [{ kind: 'base', key: 'h1:0:FORWARD' }] })
    overlay.update()
    const rec = overlay.getRecord(a.id)
    const cx = Number(rec.dot.getAttribute('cx')), cy = Number(rec.dot.getAttribute('cy'))
    expect(cx).toBeCloseTo(400, 0)
    expect(cy).toBeLessThan(300)
    entries[3].pos.set(5, 3, 0)
    overlay.update()
    expect(Number(rec.dot.getAttribute('cx'))).toBeGreaterThan(cx)
    expect(rec.line.getAttribute('points').split(' ').length).toBeGreaterThanOrEqual(2)
  })

  it('shows anchorless callouts without a leader or highlight', () => {
    const a = controller.add({ text: 'note' })
    overlay.update()
    expect(callout(a.id).hidden).toBe(false)
    expect(overlay.getRecord(a.id).g.style.display).toBe('none')
    expect(highlight(a.id)).toBeUndefined()
  })

  it('manual mode pins the box, the grip drags it, and it stays put when the camera moves', () => {
    const a = controller.add({ text: 'hi', refs: [{ kind: 'strand', id: 's2' }] })
    overlay.update()
    controller.update(a.id, { manual: true })
    overlay.update()
    const pinned = controller.get(a.id).screenPos
    expect(pinned).toBeTruthy()
    expect(callout(a.id).classList.contains('nadoc-anno--manual')).toBe(true)

    const grip = callout(a.id).querySelector('.nadoc-anno__grip')
    const fire = (type, x, y) => grip.dispatchEvent(new window.MouseEvent(type, { clientX: x, clientY: y, button: 0, bubbles: true }))
    fire('pointerdown', 100, 100)
    fire('pointermove', 300, 250)
    fire('pointerup', 300, 250)
    const moved = controller.get(a.id).screenPos
    expect(moved.x).toBeCloseTo(pinned.x + 200 / VIEW.width, 5)
    expect(moved.y).toBeCloseTo(pinned.y + 150 / VIEW.height, 5)

    overlay.update()
    const before = callout(a.id).style.transform
    camera.position.set(6, 4, 15); camera.lookAt(0, 0, 0)
    overlay.update()
    expect(callout(a.id).style.transform).toBe(before)
    // Pointer moves after release must not drag.
    fire('pointermove', 700, 500)
    expect(controller.get(a.id).screenPos).toEqual(moved)
  })

  it('auto mode keeps the leader on the moving anchor and re-places once the box is on the design', () => {
    const a = controller.add({ text: 'hi', refs: [{ kind: 'base', key: 'h0:2:FORWARD' }] })
    overlay.update()
    const rec = overlay.getRecord(a.id)
    const dot = () => Number(rec.dot.getAttribute('cx'))
    const before = dot()
    camera.position.set(12, 0, 16); camera.lookAt(0, 0, 0)
    overlay.update()
    expect(dot()).not.toBe(before)
    // Fill the view with design beads around wherever the box sits → it must move off them.
    const r = rec.rect
    const cx = r.x + r.w / 2, cy = r.y + r.h / 2
    // A sheet of beads on the view ray through the box centre (~20 units out), spanning the box.
    const near = new THREE.Vector3((cx / VIEW.width) * 2 - 1, -((cy / VIEW.height) * 2 - 1), 0.5).unproject(camera)
    const dir = near.sub(camera.position).normalize()
    const centre = camera.position.clone().addScaledVector(dir, 20)
    const right = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 0)
    const up = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 1)
    for (let i = -12; i <= 12; i++) for (let j = -4; j <= 4; j++) {
      const p = centre.clone().addScaledVector(right, i * 0.2).addScaledVector(up, j * 0.2)
      entries.push(mk(nuc('s3', 'h9', entries.length), p.x, p.y, p.z))
    }
    overlay.update()
    expect(rec.rect.x === r.x && rec.rect.y === r.y).toBe(false)
  })

  it('places an auto callout where it covers none of the projected design', () => {
    // A dense sheet of beads covering the middle of the view.
    entries = []
    for (let x = -4; x <= 4; x += 0.25) for (let y = -3; y <= 3; y += 0.25) entries.push(mk(nuc('s1', 'h0', entries.length), x, y, 0))
    const a = controller.add({ text: 'hello', refs: [{ kind: 'strand', id: 's1' }] })
    overlay.update()
    const rect = overlay.getRecord(a.id).rect
    const project = e => { const p = e.pos.clone().project(camera); return { x: (p.x * 0.5 + 0.5) * VIEW.width, y: (-p.y * 0.5 + 0.5) * VIEW.height } }
    const covered = entries.filter(e => { const p = project(e); return p.x >= rect.x && p.x <= rect.x + rect.w && p.y >= rect.y && p.y <= rect.y + rect.h })
    expect(covered.length).toBe(0)
  })

  it('anchors, highlights and routes around proteins and nanoparticles', () => {
    const spheres = { n1: { x: 3, y: 1, z: 0, radius: 1.5 }, p1: { x: -3, y: -1, z: 0, radius: 2 } }
    overlay.dispose()
    overlay = initAnnotationOverlay({
      container, scene, controller, getCamera: () => camera, getEntries: () => entries, getDesign: () => ({}), getViewport: () => VIEW,
      resolveExternal: ref => spheres[ref.id] ?? null, getOccluders: () => Object.values(spheres),
    })
    const n = controller.add({ text: 'gold', color: '#ffd700', refs: [{ kind: 'nanoparticle', id: 'n1' }] })
    const p = controller.add({ icon: 'info', refs: [{ kind: 'protein', id: 'p1' }] })
    overlay.update()
    for (const [id, s] of [[n.id, spheres.n1], [p.id, spheres.p1]]) {
      const halo = scene.getObjectByProperty('name', `Annotation halo ${id} ${id === n.id ? 'nanoparticle:n1' : 'protein:p1'}`)
      expect(halo.visible).toBe(true)
      expect(halo.position.x).toBe(s.x)
      expect(halo.scale.x).toBeGreaterThan(s.radius * 2)
      expect(halo.material.depthTest).toBe(false)
      const rec = overlay.getRecord(id)
      const proj = new THREE.Vector3(s.x, s.y, s.z).project(camera)
      expect(Number(rec.dot.getAttribute('cx'))).toBeCloseTo((proj.x * 0.5 + 0.5) * VIEW.width, 0)
      expect(rec.g.style.display).toBe('')
    }
    expect(scene.getObjectByName(`Annotation halo ${n.id} nanoparticle:n1`).material.color.getHexString()).toBe('ffd700')
    // A vanished element hides its halo and drops the leader.
    delete spheres.n1
    overlay.update()
    expect(scene.getObjectByName(`Annotation halo ${n.id} nanoparticle:n1`).visible).toBe(false)
    expect(overlay.getRecord(n.id).g.style.display).toBe('none')
    // Removing the entry cleans the halo up.
    controller.remove(p.id)
    overlay.update()
    expect(scene.getObjectByName(`Annotation halo ${p.id} protein:p1`)).toBeUndefined()
  })

  it('applies size and transparency to the callout, leader and highlight', () => {
    const a = controller.add({ text: 'hi', refs: [{ kind: 'strand', id: 's1' }], size: 2, transparency: 0.5 })
    overlay.update()
    expect(callout(a.id).style.opacity).toBe('0.5')
    expect(callout(a.id).querySelector('.nadoc-anno__box').style.fontSize).toBe('26px')
    expect(highlight(a.id).material.opacity).toBeCloseTo(0.425, 5)
  })

  it('hidden entries and disabled overlays draw nothing; removal cleans up', () => {
    const a = controller.add({ text: 'hi', refs: [{ kind: 'strand', id: 's1' }] })
    overlay.update()
    controller.update(a.id, { visible: false })
    overlay.update()
    expect(callout(a.id).hidden).toBe(true)
    expect(highlight(a.id)).toBeUndefined()
    controller.update(a.id, { visible: true })
    overlay.update()
    expect(highlight(a.id)).toBeTruthy()
    overlay.setEnabled(false)
    expect(container.querySelector('.nadoc-anno-layer').hidden).toBe(true)
    expect(scene.getObjectByName('Annotation highlights').visible).toBe(false)
    overlay.setEnabled(true)
    controller.remove(a.id)
    overlay.update()
    expect(callout(a.id)).toBeNull()
    expect(highlight(a.id)).toBeUndefined()
  })

  it('re-resolves the target when the renderer rebuilds its entries', () => {
    const a = controller.add({ text: 'hi', refs: [{ kind: 'strand', id: 's1' }] })
    overlay.update()
    entries = [mk(nuc('s1', 'h0', 0), 9)]
    overlay.update()
    expect(highlight(a.id).geometry.attributes.position.count).toBe(1)
    expect(highlight(a.id).geometry.attributes.position.array[0]).toBe(9)
  })

  it('the global toggle hides callouts and highlights without deleting entries, and shows them again', () => {
    const a = controller.add({ text: 'hi', refs: [{ kind: 'strand', id: 's1' }] })
    overlay.update()
    expect(container.querySelector('.nadoc-anno-layer').hidden).toBe(false)
    controller.setEnabled(false)
    overlay.update()
    expect(container.querySelector('.nadoc-anno-layer').hidden).toBe(true)
    expect(scene.getObjectByName('Annotation highlights').visible).toBe(false)
    expect(controller.list()).toHaveLength(1)
    controller.setEnabled(true)
    overlay.update()
    expect(container.querySelector('.nadoc-anno-layer').hidden).toBe(false)
    expect(scene.getObjectByName('Annotation highlights').visible).toBe(true)
    expect(highlight(a.id)).toBeTruthy()
  })

  it('an annotation-only design change does not rebuild targets', () => {
    let design = { strands: [], cluster_transforms: [] }
    overlay.dispose()
    overlay = initAnnotationOverlay({ container, scene, controller, getCamera: () => camera, getEntries: () => entries, getDesign: () => design, getViewport: () => VIEW })
    const a = controller.add({ text: 'hi', refs: [{ kind: 'strand', id: 's1' }] })
    overlay.update()
    const points = highlight(a.id)
    design = { ...design, annotations: [{ id: 'x' }] }
    overlay.update()
    expect(highlight(a.id)).toBe(points)
    design = { ...design, strands: [{ id: 's1' }] }   // a topology change does rebuild
    overlay.update()
    expect(overlay.getRecord(a.id).design).toBe(design)
  })

  it('leaves no scene objects or DOM behind after dispose', () => {
    controller.add({ text: 'hi', refs: [{ kind: 'strand', id: 's1' }] })
    overlay.update()
    overlay.dispose()
    expect(scene.getObjectByName('Annotation highlights')).toBeUndefined()
    expect(container.querySelector('.nadoc-anno-layer')).toBeNull()
    overlay = initAnnotationOverlay({ container, scene, controller, getCamera: () => camera, getViewport: () => VIEW })
  })
})
