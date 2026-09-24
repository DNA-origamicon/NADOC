import { it, expect, afterEach, vi } from 'vitest'
import * as THREE from 'three'
import { captureViewTools, validateViewTools } from './shared_view_tools.js'
import { mountSharedViewTools } from './shared_view_tools_ui.js'
import { broadcastFingerprint } from './broadcast_fingerprint.js'
import { prepareScene, loadPreparedScene } from './prepared_scene.js'
import { initLoopSkipHighlight } from '../scene/loop_skip_highlight.js'
afterEach(() => { document.body.innerHTML = '' })
const camera = { position: [0, 0, 10], target: [0, 0, 0], up: [0, 1, 0], fov: 55, orbitMode: 'orbit' }
it('captures toggle state and legends and detects count-only changes for live sharing', () => {
  document.body.innerHTML = '<button class="vt-btn active" data-vt="lengthHeatmap"></button><button class="vt-btn active" data-vt="clashes"></button><div id="clash-legend" class="visible"><span id="clash-legend-text">2 clashes</span></div>'
  const scene = new THREE.Scene(), first = captureViewTools(document)
  expect(first.lengthHeatmap).toBe(true); expect(first.sequences).toBe(false); expect(first.clashCount).toBe(2)
  validateViewTools(first)
  const ui = mountSharedViewTools(document.body); ui.update(first)
  expect(document.querySelector('.shared-length-ticks').textContent).toBe('≤143760+')
  expect(document.querySelector('.shared-clash-legend').textContent).toBe('2 clashes')
  document.getElementById('clash-legend-text').textContent = '0 clashes'
  const second = captureViewTools(document)
  expect(broadcastFingerprint({ scene, view: { viewTools: first } })).not.toBe(broadcastFingerprint({ scene, view: { viewTools: second } }))
  ui.update(second); expect(document.querySelector('.shared-clash-legend').textContent).toBe('0 clashes')
  ui.update(null); expect(document.querySelector('.shared-view-tools').hidden).toBe(true)
  expect(() => validateViewTools({ ...first, clashCount: '<script>' })).toThrow()
  ui.dispose(); expect(document.querySelector('.shared-view-tools')).toBeNull()
})
it('round-trips loops/skips, overhang arrows and clash glows with on/off changes', async () => {
  const canvas = vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ createRadialGradient: () => ({ addColorStop() {} }), fillRect() {} })
  const { createGlowLayer } = await import('../scene/glow_layer.js')
  canvas.mockRestore()
  const scene = new THREE.Scene(), loops = initLoopSkipHighlight(scene)
  loops.rebuild({ helices: [{ id: 'h1', axis_start: { x: 0, y: 0, z: 0 }, axis_end: { x: 0, y: 0, z: 3.4 }, length_bp: 10, bp_start: 0, loop_skips: [{ bp_index: 1, delta: 1 }, { bp_index: 2, delta: -1 }] }] }, [], {})
  loops.setVisible(true)
  const arrow = new THREE.ArrowHelper(new THREE.Vector3(1, 0, 0), new THREE.Vector3(2, 3, 4), 2)
  arrow.name = 'overhang-arrow'; scene.add(arrow)
  const glow = createGlowLayer(scene, 0xff0000, 1, 'clashes'); glow.setEntries([{ pos: new THREE.Vector3(1, 2, 3) }])
  const guest = await loadPreparedScene(prepareScene({ scene, camera }))
  expect(guest.scene.children[0].children).toHaveLength(3)
  expect(guest.scene.getObjectByName('overhang-arrow').children).toHaveLength(2)
  expect(guest.scene.getObjectByName('clashes').count).toBe(1)
  expect(guest.scene.getObjectByName('clashes').material.blending).toBe(THREE.AdditiveBlending)
  loops.setVisible(false); arrow.visible = false; glow.clear()
  const off = await loadPreparedScene(prepareScene({ scene, camera }))
  expect(off.scene.children).toHaveLength(1); expect(off.scene.children[0].count).toBe(0)
  guest.dispose(); off.dispose(); loops.dispose(); glow.dispose()
})

it('preserves strand-length heatmap colors and their legend in a guest package', async () => {
  const { buildLengthHeatmapColors } = await import('../ui/view_tool_buttons.js')
  const colors = buildLengthHeatmapColors([14, 37, 60].map(n => ({ id: String(n), strand_type: 'staple', domains: [{ start_bp: 0, end_bp: n }] })))
  const scene = new THREE.Scene(), mesh = new THREE.InstancedMesh(new THREE.SphereGeometry(.1), new THREE.MeshBasicMaterial(), 3)
  ;[...colors.values()].forEach((color, i) => mesh.setColorAt(i, new THREE.Color(color)))
  scene.add(mesh)
  document.body.innerHTML = '<button class="vt-btn active" data-vt="lengthHeatmap"></button>'
  const guest = await loadPreparedScene(prepareScene({ scene, camera, view: { viewTools: captureViewTools(document) } }))
  expect(new Set(colors.values()).size).toBe(3)
  expect(guest.scene.children[0].instanceColor.array).toEqual(mesh.instanceColor.array)
  expect(guest.data.view.viewTools.lengthHeatmap).toBe(true)
  guest.dispose(); mesh.geometry.dispose(); mesh.material.dispose()
})
