import { expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { initDesignRenderer } from './design_renderer.js'
import { initUnfoldView } from './unfold_view.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { store } from '../state/store.js'
vi.mock('../state/store.js', () => ({ store: { getState: vi.fn(), subscribe: vi.fn(), setState: vi.fn() } }))

const nucleotide = (helix, x, copy = 0) => ({ helix_id: helix, bp_index: 0, direction: 'FORWARD', copy_k: copy,
  strand_id: 's', strand_type: 'staple', domain_index: helix === 'a' ? 0 : 1,
  backbone_position: [x,0,0], base_position: [x-.5,0,0],
  placement_source: 'native-full-o5-v1', slab_position: [x-.33,0,0], slab_quaternion: [0,Math.SQRT1_2,Math.SQRT1_2,0],
  base_normal: [-1,0,0], axis_tangent: [0,0,1] })

it('real bead, slab and connection buffers share simulation, visibility, transforms and rebuild ownership', () => {
  const geometry = [nucleotide('a',1), nucleotide('b',5)]
  const design = { id:'display-test', helices:[], crossovers:[], forced_ligations:[], extensions:[], overhangs:[], deformations:[],
    strands:[{id:'s',strand_type:'staple',domains:[{helix_id:'a',start_bp:0,end_bp:0,direction:'FORWARD'},{helix_id:'b',start_bp:0,end_bp:0,direction:'FORWARD'}]}] }
  const state = createMockStore({currentDesign:design,currentGeometry:geometry,strandColors:{},strandGroups:[],loopStrandIds:[],currentHelixAxes:{},unfoldSpacing:3})
  store.getState.mockImplementation(state.getState); store.subscribe.mockImplementation(state.subscribe)
  const scene = new THREE.Scene(), renderer = initDesignRenderer(scene,state)
  const view = initUnfoldView(scene,renderer)
  view.refreshExternalGeometry()
  const line = () => view.getArcRoot().children[0].geometry.attributes.position
  const ends = () => {const p=line();return [new THREE.Vector3().fromBufferAttribute(p,0),new THREE.Vector3().fromBufferAttribute(p,p.count-1)]}
  const assertAttached = () => {
    const displayed = renderer.getBackboneEntries().map(e=>e.pos)
    for (const endpoint of ends()) expect(Math.min(...displayed.map(p=>p.distanceTo(endpoint)))).toBeLessThan(1e-6)
  }
  try {
    assertAttached()
    renderer.applyFemPositions(geometry.map(n=>({...n,backbone_position:n.backbone_position.map(v=>v+10),nx:-1,ny:0,nz:0})),2)
    assertAttached(); expect(ends()[0].x).toBe(21)
    view.refreshArcVisibility(); view.setHiddenNucs(new Set()); assertAttached(); expect(ends()[0].x).toBe(21)
    renderer.setDesignVisible(false); expect(view.getArcRoot().parent.visible).toBe(false)
    renderer.setDesignVisible(true); view.refreshArcVisibility(); assertAttached()
    // Source-generation rebuild reattaches to the new live entries, not stale refs.
    renderer.setExtraNucleotides([nucleotide('cap0',50)])
    view.refreshArcVisibility(); assertAttached(); expect(ends()[0].x).toBe(21)
    renderer.applyFemPositions(null); assertAttached(); expect(ends()[0].x).toBe(1)
    renderer.applyUnfoldOffsets(new Map([['a',new THREE.Vector3(0,8,0)],['b',new THREE.Vector3(0,-4,0)]]), .5)
    assertAttached()
    expect(ends()[0].y).toBe(4)
    const ctrl=renderer.getHelixCtrl(), target={helix_id:'a',bp_index:0,direction:'FORWARD'}
    const info=ctrl.residueTransformInfo(target)
    ctrl.applyResidueTransformMatrix(info,new THREE.Matrix4().makeTranslation(3,4,5))
    assertAttached(); view.refreshArcVisibility(); assertAttached()
    expect(geometry[0].backbone_position).toEqual([1,0,0])
  } finally { view.dispose(); renderer.dispose() }
})

it('insert producers publish partial frames and preserve explicit residue previews through refresh', () => {
  const geometry = [nucleotide('a', 1), { ...nucleotide('b', 5), direction: 'REVERSE' }]
  const design = { id: 'insert-test', helices: [], extensions: [], overhangs: [], deformations: [], forced_ligations: [],
    crossovers: [{ id: 'xo', extra_bases: 'TT', half_a: {helix_id:'a',index:0,strand:'FORWARD'}, half_b:{helix_id:'b',index:0,strand:'REVERSE'} }],
    strands:[{id:'s',strand_type:'staple',domains:geometry.map(n=>({helix_id:n.helix_id,start_bp:0,end_bp:0,direction:n.direction}))}] }
  const state = createMockStore({currentDesign:design,currentGeometry:geometry,strandColors:{},strandGroups:[],loopStrandIds:[],currentHelixAxes:{}})
  const renderer = initDesignRenderer(new THREE.Scene(), state), frame = renderer.getDisplayGeometry()
  const target = k => ({helix_id:'__xb__',crossover_id:'xo',k})
  const site = k => ({helix_id:'__xb__',bp_index:'xo',direction:k})
  const position = k => renderer.xoverResidueInfo(target(k)).centroid
  try {
    expect(renderer.getXoverBeadEntries()).toHaveLength(2)
    const info = renderer.xoverResidueInfo(target(0))
    renderer.applyXoverResidueMatrix(info, new THREE.Matrix4().makeTranslation(3,4,5))
    expect(position(0).distanceTo(info.centroid.clone().add(new THREE.Vector3(3,4,5)))).toBeLessThan(1e-6)
    frame.invalidate('visibility')
    expect(frame.position(site(0)).distanceTo(position(0))).toBeLessThan(1e-6)
    renderer.applyXoverResidueMatrix(info, new THREE.Matrix4())
    expect(position(0).distanceTo(info.centroid)).toBeLessThan(1e-6)
    renderer.applyFemPositions([0,1].map(k=>({...site(k),backbone_position:[50+k,1,2],nx:1,ny:0,nz:0})))
    expect(position(1).x).toBe(51)
    renderer.applyFemPositions([{...site(0),backbone_position:[80,1,2],nx:1,ny:0,nz:0}])
    expect(position(0).x).toBe(80)
    expect(position(1).x).toBeLessThan(10)
    expect(frame.position(site(1)).distanceTo(position(1))).toBeLessThan(1e-6)
    renderer.applyFemPositions(null)
    expect(position(0).distanceTo(info.centroid)).toBeLessThan(1e-6)
  } finally { renderer.dispose() }
})

it('loop copies and extension sites keep exact frame identity in real mesh buffers', () => {
  const geometry = [nucleotide('a',1), nucleotide('a',2,1), nucleotide('__ext_tail',8)]
  const design = {id:'copy-test',helices:[],crossovers:[],forced_ligations:[],extensions:[],overhangs:[],deformations:[],strands:[]}
  const state = createMockStore({currentDesign:design,currentGeometry:geometry,strandColors:{},strandGroups:[],loopStrandIds:[],currentHelixAxes:{}})
  const renderer = initDesignRenderer(new THREE.Scene(),state)
  try {
    renderer.applyFemPositions([
      {...geometry[0],copy:0,backbone_position:[11,0,0]},
      {...geometry[1],copy:1,backbone_position:[22,0,0]},
      {...geometry[2],copy:0,backbone_position:[38,0,0]},
    ],2)
    const frame = renderer.getDisplayGeometry(), m = new THREE.Matrix4()
    const check = expected => {
      for (const [i,n] of geometry.entries()) expect(frame.position(n).x).toBe(expected[i])
      for (const e of renderer.getBackboneEntries()) {
        e.instMesh.getMatrixAt(e.id,m)
        const n = {...e.nuc,copy_k:e._copy??0}
        expect(new THREE.Vector3().setFromMatrixPosition(m).distanceTo(frame.position(n))).toBeLessThan(1e-6)
      }
    }
    check([21,42,68])
    renderer.applyFemPositions([{...geometry[1],copy:1,backbone_position:[32,0,0]}])
    check([1,32,8])
    renderer.applyFemPositions(null)
    check([1,2,8])
  } finally { renderer.dispose() }
})
