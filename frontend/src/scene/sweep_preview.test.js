import { it, expect, vi } from 'vitest'
import * as THREE from 'three'
import { createSweepPreview } from './sweep_preview.js'

it('raycasts points, translates the selected point in its saved frame, and cleans up controls', () => {
  const canvas = document.createElement('canvas')
  document.body.append(canvas)
  canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 800, height: 600 })
  const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(45, 800 / 600, .1, 1000)
  camera.position.set(0, 0, 40); camera.updateMatrixWorld(true)
  const orbit = { enabled: true }, moved = vi.fn(), selected = vi.fn()
  let preview
  preview = createSweepPreview(scene, { canvas, getCamera: () => camera, getControls: () => orbit,
    onSelect: index => { selected(index); preview.select(index) }, onMove: moved })
  preview.update({ origin_nm: [0,0,0], point_rotation: [[0,-1,0],[1,0,0],[0,0,1]],
    points_nm: [[0,0,0],[0,5,0]], path_nm: [[0,0,0],[0,5,0]], helix_paths_nm: [[[0,0,0],[0,5,0]]] })
  const screen = p => { const v = p.clone().project(camera); return { x: (v.x + 1) * 400, y: (1 - v.y) * 300 } }
  const fire = (type, p, button = 0) => { const event = new MouseEvent(type, { clientX: p.x, clientY: p.y, button, bubbles: true, cancelable: true }); Object.defineProperty(event, 'pointerId', { value: 1 }); canvas.dispatchEvent(event) }
  fire('pointerdown', screen(new THREE.Vector3(0,0,0)))
  expect(selected).toHaveBeenLastCalledWith(0)
  expect(scene.getObjectByName('sweep-point-gizmo').visible).toBe(false)
  fire('pointerdown', screen(new THREE.Vector3(0,5,0)))
  expect(selected).toHaveBeenLastCalledWith(1)
  scene.updateMatrixWorld(true)
  const helper = scene.getObjectByName('sweep-point-gizmo')
  const handles = []
  helper.traverse(o => { if (o.name === 'X' && o.isMesh && o.visible) handles.push(o) })
  const handle = handles[0]
  handle.geometry.computeBoundingBox()
  const center = handle.geometry.boundingBox.getCenter(new THREE.Vector3()).applyMatrix4(handle.matrixWorld)
  const start = screen(center)
  fire('pointerdown', start)
  expect(orbit.enabled).toBe(false)
  fire('pointermove', { x: start.x + 40, y: start.y }, -1)
  fire('pointerup', { x: start.x + 40, y: start.y })
  expect(orbit.enabled).toBe(true)
  expect(moved).toHaveBeenCalled()
  const [index, point] = moved.mock.lastCall
  expect(index).toBe(1)
  expect(point[0]).toBeCloseTo(5, 2)
  expect(point[1]).toBeLessThan(-1)
  preview.clear()
  expect(scene.getObjectByName('sweep-control-points').children).toHaveLength(0)
  expect(helper.visible).toBe(false)
  preview.dispose(); canvas.remove()
  expect(scene.children).toHaveLength(0)
})

it('previews a single-base continuation without invalid tube vertices', () => {
  const scene = new THREE.Scene(), preview = createSweepPreview(scene)
  preview.update({ points_nm: [[0,0,0],[0,0,.1]], path_nm: [[0,0,0],[0,0,.1]], helix_paths_nm: [[[0,0,.1],[0,0,.1]]] })
  scene.traverse(o => { if (o.geometry) expect([...o.geometry.attributes.position.array].every(Number.isFinite)).toBe(true) })
  preview.setPoints([[0,0,0]], 0)
  expect(scene.getObjectByName('sweep-control-points').children).toHaveLength(1)
  preview.dispose()
})

it('draws warning segments and full point-frame arrows, and recovers angles in the starting plane', () => {
  const scene = new THREE.Scene(), preview = createSweepPreview(scene)
  const frame = new THREE.Matrix4().makeRotationFromEuler(new THREE.Euler(Math.PI/12, Math.PI/2, Math.PI/4, 'YXZ'))
  const b = [0,1,2].map(r => [0,1,2].map(c => frame.elements[4*c+r]))
  preview.update({origin_nm:[0,0,0], points_nm:[[0,0,0],[0,0,10]], path_nm:[[0,0,0],[0,0,10]], point_bases:[[[1,0,0],[0,1,0],[0,0,1]],b], feasibility:{warning_segments:[0]}})
  expect(scene.getObjectByName('sweep-curvature-warning').geometry.attributes.position.count).toBe(2)
  expect(scene.getObjectByName('sweep-orientation-arrows').children).toHaveLength(4)
  preview.getOrientation(1).forEach((a,i) => expect(a).toBeCloseTo([15,90,45][i],8))
  preview.clear(); expect(scene.getObjectByName('sweep-curvature-warning')).toBeUndefined()
  preview.dispose()
})

it('switches Tab to free rotation, preserves point position, and shows every oriented cross-section', () => {
  const canvas = document.createElement('canvas'); document.body.append(canvas)
  const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(45, 4/3, .1, 1000)
  camera.position.z = 40; camera.updateMatrixWorld(true)
  const oriented = vi.fn(), moved = vi.fn(), basis = [[1,0,0],[0,1,0],[0,0,1]]
  const preview = createSweepPreview(scene, {canvas, getCamera:()=>camera, onOrient:oriented, onMove:moved})
  preview.update({origin_nm:[0,0,0], points_nm:[[0,0,0],[0,5,0]], path_nm:[[0,0,0],[0,5,0]], point_bases:[basis,basis], cross_section_nm:[[-1.25,0],[1.25,0]]})
  expect(scene.getObjectByName('sweep-cross-sections').children).toHaveLength(2)
  const tab = target => target.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',bubbles:true,cancelable:true}))
  const input = document.createElement('input'); document.body.append(input)
  tab(input); expect(preview.getMode()).toBe('translate')
  tab(canvas); expect(preview.getMode()).toBe('rotate')
  expect(oriented.mock.lastCall[1].every(a => a === 0)).toBe(true)
  const target = scene.getObjectByName('sweep-point-target'), helper = scene.getObjectByName('sweep-point-gizmo')
  // Exercise the real TransformControls change event with an unsnapped frame.
  target.quaternion.setFromEuler(new THREE.Euler(.123,.234,.345,'YXZ'))
  helper.controls.dispatchEvent({type:'objectChange'})
  const angles = oriented.mock.lastCall[1]
  angles.forEach((a,i)=>expect(a).toBeCloseTo(THREE.MathUtils.radToDeg([.123,.234,.345][i])))
  expect(moved).not.toHaveBeenCalled()
  const section = scene.getObjectByName('sweep-cross-section-1')
  expect(section.material.color.toArray()).toEqual([1,.87,.50])
  expect(section.material.opacity).toBe(1)
  const other = scene.getObjectByName('sweep-cross-section-0')
  expect(other.material.color.toArray()).toEqual([.25,.7,.78])
  expect(other.material.opacity).toBe(1)
  expect(section.position.toArray()).toEqual([0,5,0])
  expect(section.quaternion.angleTo(target.quaternion)).toBeCloseTo(0)
  tab(canvas); expect(preview.getMode()).toBe('translate')
  preview.dispose(); canvas.remove(); input.remove()
})

it('replaces only affected helices and warnings, preserving unrelated scene objects and hidden state', () => {
  const scene = new THREE.Scene()
  const original = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial())
  const alreadyHidden = original.clone(); alreadyHidden.visible = false
  const savedWarning = new THREE.Group(); savedWarning.name = 'sweep-warning-icons-saved'
  const affectedWarning = original.clone(); affectedWarning.userData.helixIds = ['swept']; savedWarning.add(affectedWarning)
  const unrelatedWarning = original.clone(); unrelatedWarning.userData.helixIds = ['other']; savedWarning.add(unrelatedWarning)
  scene.add(original, alreadyHidden, savedWarning)
  const setPreviewHelices = vi.fn()
  const preview = createSweepPreview(scene, {setPreviewHelices})
  const data = { points_nm:[[0,0,0],[0,0,10]], path_nm:[[0,0,0],[0,0,10]],
    edit_helix_ids:['swept'], helix_path_ids:['swept','other'], helix_paths_nm:[[[0,0,0],[0,0,10]],[[20,0,0],[20,0,10]]],
    edit_backbones_nm:[[[1,0,0],[1,0,4]], [[1,0,5],[1,0,10]]] }
  preview.update(data)
  expect(original.visible).toBe(true)
  expect(setPreviewHelices).toHaveBeenLastCalledWith(['swept'])
  expect(scene.getObjectByName('sweep-geometry').children.filter(o => o.isMesh)).toHaveLength(1)
  expect(affectedWarning.visible).toBe(false)
  expect(unrelatedWarning.visible).toBe(true)
  expect(scene.getObjectByName('sweep-geometry').children.filter(o => o.name === 'sweep-edited-backbone')).toHaveLength(2)
  preview.update(data)
  preview.clearGeometry()
  expect(original.visible).toBe(true)
  expect(alreadyHidden.visible).toBe(false)
  expect(setPreviewHelices).toHaveBeenLastCalledWith([])
  expect(affectedWarning.visible).toBe(true)
  preview.update(data); preview.dispose()
  expect(original.visible).toBe(true)
  expect(alreadyHidden.visible).toBe(false)
  original.geometry.dispose(); original.material.dispose()
})
