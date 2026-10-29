/** Read-only, demand-rendered native molecular layers for the isolated review. */
import * as THREE from '../frontend/node_modules/three/build/three.module.js'
import { OrbitControls } from '../frontend/node_modules/three/examples/jsm/controls/OrbitControls.js'
import { initAtomisticRenderer } from '../frontend/src/scene/atomistic_renderer.js'
import { buildHelixObjects, buildStapleColorMap } from '../frontend/src/scene/helix_renderer.js'
import { buildCrossoverConnections } from '../frontend/src/scene/crossover_connections.js'
import { filterAuditAtomData } from '../frontend/src/ui/molecular_placement_audit.js'

const key = a => `${a.strand_id}:${a.helix_id}:${a.bp_index}:${a.direction}`
function disposeTree(root) {
  root.traverse(node => {
    if (!node.geometry?.userData?.shared) node.geometry?.dispose()
    for (const material of [node.material].flat().filter(Boolean)) material.dispose()
  })
  root.removeFromParent()
}
function tint(root, color, opacity) {
  root.traverse(node => {
    if (node.isInstancedMesh) {
      for (let i=0; i<node.count; i++) node.setColorAt(i, new THREE.Color(color))
      if (node.instanceColor) node.instanceColor.needsUpdate = true
    }
    for (const material of [node.material].flat().filter(Boolean)) {
      material.color?.setHex(color)
      material.transparent = opacity < 1
      material.opacity = opacity
      material.depthWrite = opacity >= 1
    }
  })
}

export function createAttachmentReviewViewer(host, id, bundle, representation) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true })
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5))
  renderer.setClearColor(0x0d1117)
  host.append(renderer.domElement)
  const scene = new THREE.Scene()
  scene.add(new THREE.HemisphereLight(0xffffff, 0x263241, 1.2))
  const light = new THREE.DirectionalLight(0xffffff, 1.8)
  light.position.set(4, 7, 6); scene.add(light)
  const camera = new THREE.PerspectiveCamera(42, 1, 0.001, 10000)
  const controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = false
  let pending = null, layers = [], alive = true, requested = 0, completed = 0
  const markers = new THREE.Group()
  scene.add(markers)
  function render() {
    requested++
    if (pending !== null || !alive) return
    pending = requestAnimationFrame(() => {
      pending = null
      renderer.render(scene, camera)
      // This static review renders only on interaction. Finish the requested
      // frame so readiness includes GPU completion on software renderers too.
      renderer.getContext().finish()
      completed = requested
    })
  }
  function line(points, color, closed=false) {
    const geometry = new THREE.BufferGeometry().setFromPoints(points.map(p => new THREE.Vector3(...p)))
    const material = new THREE.LineBasicMaterial({ color, depthTest:false })
    const object = closed ? new THREE.LineLoop(geometry, material) : new THREE.Line(geometry, material)
    object.renderOrder=20; markers.add(object)
  }
  function diagnostics(side) {
    const data = bundle[side]
    const xyz = i => { const a = data.atoms[i]; return [a.x,a.y,a.z] }
    const color = side === 'current' ? 0x52c7ff : 0xff72ca
    for (const hit of data.diagnostics.clashes) line(hit.serials.map(xyz), color)
    for (const hit of data.diagnostics.piercing.pierced) {
      line(hit.bond_serials.map(xyz), color)
      line(hit.ring_serials.map(xyz), color, true)
    }
    for (const hit of data.diagnostics.bonds.overstretched) line(hit.serials.map(xyz), 0xffa657)
  }
  function layer(side, serials=null, ghost=false) {
    const design = bundle[`${side}_design`], data=bundle[side]
    let root, dispose
    if (representation === 'full') {
      const keys = serials && new Set(serials.map(i => key(data.atoms[i])))
      const geometry = keys ? data.nucleotides.filter(n => keys.has(key(n))) : data.nucleotides
      const custom = Object.fromEntries(bundle.strand_colors)
      const ctrl = buildHelixObjects(geometry, design, scene, custom, [], {}, 'full', { axisMeshes:false })
      ctrl.setMode('normal')
      const xovers = buildCrossoverConnections(design, geometry, buildStapleColorMap(geometry, design), custom)
      if (xovers) ctrl.root.add(xovers.group)
      root=ctrl.root; dispose=()=>disposeTree(root)
    } else {
      root = new THREE.Group(); scene.add(root)
      const atoms = initAtomisticRenderer(root)
      atoms.setMode('ballstick')
      atoms.update(serials ? filterAuditAtomData(data, serials) : data)
      atoms.setColorMode('strand', bundle.strand_colors)
      dispose=()=>{atoms.dispose(); root.removeFromParent()}
    }
    if (id === 'difference' || id === 'defects') tint(root, side === 'current' ? 0x2f81f7 : 0xff4da6, ghost ? 0.4 : 0.9)
    layers.push(dispose)
  }
  function rebuild(next=representation) {
    representation=next
    for (const dispose of layers) dispose()
    layers=[]
    while (markers.children.length) disposeTree(markers.children[0])
    if (id === 'current' || id === 'candidate') { layer(id); diagnostics(id) }
    else {
      const affected=bundle.affected_atom_serials
      layer('current', id === 'defects' ? [...new Set([...affected,...bundle.defect_atom_serials.current])] : null, true)
      layer('candidate', id === 'defects' ? [...new Set([...affected,...bundle.defect_atom_serials.candidate])] : affected)
      diagnostics('current'); diagnostics('candidate')
      if (id === 'difference') for (const row of bundle.displacement.vectors) line([row.from,row.to],0xffd33d)
    }
    render()
  }
  function fit() {
    const box = new THREE.Box3()
    for (const side of ['current','candidate']) for (const a of bundle[side].atoms) box.expandByPoint(new THREE.Vector3(a.x,a.y,a.z))
    const center=box.getCenter(new THREE.Vector3()), radius=Math.max(box.getSize(new THREE.Vector3()).length()/2,0.8)
    controls.target.copy(center)
    camera.position.copy(center).add(new THREE.Vector3(radius*1.35,radius*.9,radius*1.8))
    camera.near=Math.max(radius/1000,.001); camera.far=Math.max(radius*50,100)
    camera.updateProjectionMatrix(); controls.update(); render()
  }
  function resize() {
    renderer.setSize(host.clientWidth,host.clientHeight)
    camera.aspect=host.clientWidth/host.clientHeight; camera.updateProjectionMatrix(); render()
  }
  const observer=new ResizeObserver(resize); observer.observe(host)
  controls.addEventListener('change',render)
  resize(); rebuild(); fit()
  return {camera, controls, fit, setRepresentation:rebuild,
    isRendered:()=>completed>0 && completed===requested, dispose() {
    alive=false; cancelAnimationFrame(pending); observer.disconnect(); controls.dispose()
    for (const dispose of layers) dispose()
    while (markers.children.length) disposeTree(markers.children[0])
    renderer.dispose(); renderer.forceContextLoss(); renderer.domElement.remove()
  }}
}
