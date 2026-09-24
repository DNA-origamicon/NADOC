import { it, expect, afterEach } from 'vitest'
import * as THREE from 'three'
import { captureSharedVisualization, validateSharedVisualization } from './shared_visualization.js'
import { mountSharedViewTools } from './shared_view_tools_ui.js'
import { prepareScene, loadPreparedScene } from './prepared_scene.js'
import { liveSceneSignature } from './live_frame_capture.js'
afterEach(() => { document.body.innerHTML = '' })
it('publishes the job label and UTC run date with its visualization and clears on native Off', async () => {
  document.body.innerHTML = '<input type="radio" name="oxdna-viz" value="flex" checked>'
  const job = { id: 'job-1', name: '<b>My run</b>', engine: 'oxdna', createdAt: 1720000000 }
  const visualization = captureSharedVisualization(document, job)
  expect(visualization).toEqual({ engine: 'oxdna', jobId: 'job-1', jobName: '<b>My run</b>', mode: 'Flexibility map (RMSF)', runDate: '2024-07-03T09:46:40.000Z' })
  const scene = new THREE.Scene(), camera = { position: [0,0,20], target: [0,0,0], up: [0,1,0], fov: 55, orbitMode: 'orbit' }
  const guest = await loadPreparedScene(prepareScene({ scene, camera, view: { visualization } }))
  expect(guest.data.view.visualization).toEqual(visualization)
  const ui = mountSharedViewTools(document.body); ui.update({ sequences: true }, guest.data.view.visualization)
  expect(document.querySelector('.shared-view-tools').hidden).toBe(false)
  expect(document.body.textContent).toContain('My run'); expect(document.body.textContent).toContain('Sequences')
  expect(document.querySelector('b')).toBeNull()
  expect(liveSceneSignature({ scene, view: { visualization } })).not.toBe(liveSceneSignature({ scene, view: { visualization: null } }))
  document.querySelector('input').value = 'off'
  expect(captureSharedVisualization(document, job)).toBeNull()
  ui.update({ sequences: true }, null); expect(document.body.textContent).not.toContain('My run')
  expect(document.body.textContent).toContain('Sequences')
  ui.update(null); expect(document.querySelector('.shared-view-tools').hidden).toBe(true)
  ui.dispose(); guest.dispose()
})
it('rejects malformed labels and handles jobs with no recorded date without inventing one', () => {
  document.body.innerHTML = '<input name="md-viz" type="radio" value="ion-paths" checked>'
  const value = captureSharedVisualization(document, { id: 'a', engine: 'namd' })
  expect(value.runDate).toBeNull(); expect(value.jobName).toBe('a')
  expect(() => validateSharedVisualization(value)).not.toThrow()
  for (const invalid of [{ ...value, runDate: 'yesterday' }, { ...value, jobName: 'a'.repeat(201) }, { ...value, engine: 'bad' }, { ...value, secret: 'x' }]) expect(() => validateSharedVisualization(invalid)).toThrow('Invalid shared visualization')
})
