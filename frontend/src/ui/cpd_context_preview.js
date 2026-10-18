import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'

/** Actual selected molecular context, using one coordinate set for preview/commit. */
export function createCpdContextPreview(host) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
  renderer.setClearColor(0x0d1117)
  renderer.domElement.setAttribute('aria-label', '3D CPD selection preview')
  renderer.domElement.style.cssText = 'width:100%;height:360px;display:block;touch-action:none'
  host.append(renderer.domElement)
  const scene = new THREE.Scene()
  scene.add(new THREE.AmbientLight(0xffffff, 2))
  const light = new THREE.DirectionalLight(0xffffff, 3)
  light.position.set(4, 6, 8); scene.add(light)
  const camera = new THREE.PerspectiveCamera(40, 1, .01, 1000)
  const controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = false
  let group = null, data = null, before = false
  const render = () => renderer.render(scene, camera)
  controls.addEventListener('change', render)
  function resize() {
    const width = Math.max(host.clientWidth, 300)
    renderer.setSize(width, 360, false); camera.aspect = width / 360
    camera.updateProjectionMatrix(); render()
  }
  const observer = new ResizeObserver(resize); observer.observe(host)
  function clear() {
    if (!group) return
    group.traverse(o => { o.geometry?.dispose(); o.material?.dispose() })
    scene.remove(group)
  }
  function draw(fit = false) {
    clear(); group = new THREE.Group(); scene.add(group)
    const points = (before ? data.original_positions : data.positions).map(p => new THREE.Vector3(...p))
    const strands = [...new Set(data.strand_ids)]
    const colors = [0x58a6ff, 0xf0b45e, 0xbda0ff]
    points.forEach((p, i) => {
      const color = data.selected[i] ? ({ N: 0x7777ff, O: 0xff6666, C: 0xccccdd }[data.elements[i]] ?? 0xdddddd)
        : colors[strands.indexOf(data.strand_ids[i]) % colors.length]
      const atom = new THREE.Mesh(new THREE.SphereGeometry(data.selected[i] ? .055 : .035, 12, 8), new THREE.MeshStandardMaterial({ color }))
      atom.position.copy(p); group.add(atom)
    })
    const cross = new Set(data.crosslinks.map(b => [...b].sort((a, b) => a - b).join(':')))
    for (const [a, b] of data.bonds) {
      const isCross = cross.has([a, b].sort((a, b) => a - b).join(':'))
      if (before && isCross) continue
      const delta = points[b].clone().sub(points[a]), length = delta.length()
      const bond = new THREE.Mesh(new THREE.CylinderGeometry(isCross ? .025 : .012, isCross ? .025 : .012, length, 8),
        new THREE.MeshStandardMaterial({ color: isCross ? 0xff4fd8 : 0x778899 }))
      bond.position.copy(points[a]).add(points[b]).multiplyScalar(.5)
      bond.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), delta.normalize())
      group.add(bond)
    }
    if (fit) {
      const box = new THREE.Box3().setFromPoints(points), center = box.getCenter(new THREE.Vector3())
      const radius = Math.max(box.getSize(new THREE.Vector3()).length() / 2, .5)
      controls.target.copy(center)
      camera.position.copy(center).add(new THREE.Vector3(1, .65, 1.5).normalize().multiplyScalar(radius * 2.8))
      camera.far = Math.max(1000, radius * 10); camera.updateProjectionMatrix(); controls.update()
    }
    resize()
  }
  return {
    setData(value) { data = value; draw(true) },
    setBefore(value) { before = value; if (data) draw() },
    dispose() { observer.disconnect(); controls.dispose(); clear(); renderer.dispose(); renderer.domElement.remove() },
  }
}
