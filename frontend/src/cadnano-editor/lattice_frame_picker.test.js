// @vitest-environment jsdom
import { it, expect, vi } from 'vitest'
import { frameOptions, helicesInFrame, framePlane, createLatticeFramePicker } from './lattice_frame_picker.js'
const design = { lattice_frames: [{ id:'a',plane:'XY',placement_cluster_id:'ca' },{ id:'b',plane:'XZ',placement_cluster_id:'cb' }],
  cluster_transforms:[{id:'ca',name:'First'},{id:'cb',name:'Second'}],
  helices:[{id:'h1',grid_pos:[0,0],lattice_frame_id:'a'},{id:'h2',grid_pos:[0,0],lattice_frame_id:'b'}] }
it('keeps same-cell helices distinct and names their planes', () => {
  expect(helicesInFrame(design,'a').map(h=>h.id)).toEqual(['h1'])
  expect(helicesInFrame(design,'b').map(h=>h.id)).toEqual(['h2'])
  expect(framePlane(design,'b')).toBe('XZ')
  expect(frameOptions(design).map(f=>f.label)).toEqual(['1: First · XY','2: Second · XZ'])
  expect(frameOptions({helices:[{id:'old'}]})).toEqual([{id:'',label:'Original lattice'}])
})
it('preserves selection on refresh and recovers when a frame disappears', () => {
  const host=document.createElement('div'), changed=vi.fn()
  const picker=createLatticeFramePicker(host,changed)
  picker.update(design)
  const select=host.querySelector('select')
  expect(picker.frameId()).toBe('a')
  select.value='b';select.dispatchEvent(new Event('change'))
  expect(changed).toHaveBeenCalledOnce()
  picker.update(design);expect(picker.frameId()).toBe('b')
  picker.update({...design,lattice_frames:design.lattice_frames.slice(0,1)})
  expect(picker.frameId()).toBe('a')
})
