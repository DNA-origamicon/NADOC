/** Help ▸ Hull Audit — isolated old/candidate Hull Prism comparison. */
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { _hullGeoForSource } from '../scene/assembly_hull_geometry.js'
import { buildClusteredOccupancyHull, partitionOccupancyGeometry } from '../scene/joint_renderer.js'
import { buildHelixObjects } from '../scene/helix_renderer.js'
import './hull_audit.css'

export function disposeTree(root) {
  root?.traverse(obj => {
    if (!obj.geometry?.userData?.shared) obj.geometry?.dispose?.()
    const mats = Array.isArray(obj.material) ? obj.material : [obj.material]
    for (const mat of mats) { mat?.map?.dispose?.(); mat?.dispose?.() }
  })
  root?.removeFromParent?.()
}

export function hullAuditStats(root) {
  const box = new THREE.Box3(), child = new THREE.Box3()
  let triangles = 0, meshes = 0
  root?.updateMatrixWorld?.(true)
  root?.traverse?.(obj => {
    if (!obj.visible || !obj.isMesh || !obj.geometry?.attributes?.position) return
    meshes++
    triangles += obj.geometry.index
      ? obj.geometry.index.count / 3
      : obj.geometry.attributes.position.count / 3
    if (!obj.geometry.boundingBox) obj.geometry.computeBoundingBox()
    child.copy(obj.geometry.boundingBox).applyMatrix4(obj.matrixWorld)
    box.union(child)
  })
  const size = box.isEmpty() ? new THREE.Vector3() : box.getSize(new THREE.Vector3())
  return { meshes, triangles: Math.round(triangles), size: size.toArray() }
}

export function setHullElementBoundaries(root, visible) {
  let count = 0
  root?.traverse?.(obj => {
    if (obj.userData?.hullElementBoundaries || obj.userData?.hullElementColors) {
      obj.visible = !!visible
      count++
    } else if (obj.userData?.hullUnifiedSurface) {
      obj.visible = !visible
    }
  })
  return count
}

export const partitionAuditGeometry = partitionOccupancyGeometry

export function buildClusteredAuditHull(design, geometry, axes) {
  return buildClusteredOccupancyHull(design, geometry, axes, 1.0)
}

function fit(camera, controls, root) {
  const box = new THREE.Box3().setFromObject(root)
  if (box.isEmpty()) return
  const center = box.getCenter(new THREE.Vector3()), size = box.getSize(new THREE.Vector3())
  const radius = Math.max(size.length() / 2, 1)
  controls.target.copy(center)
  camera.position.copy(center).add(new THREE.Vector3(1, .75, 1).normalize().multiplyScalar(radius * 2.6))
  camera.near = Math.max(.01, radius / 100); camera.far = Math.max(1000, radius * 20)
  camera.updateProjectionMatrix(); controls.update()
}

function makeViewer(host, root) {
  const scene = new THREE.Scene(); scene.background = new THREE.Color(0x0d1117)
  scene.add(root, new THREE.HemisphereLight(0xffffff, 0x263238, 2.1))
  const key = new THREE.DirectionalLight(0xffffff, 2.4); key.position.set(2, 3, 4); scene.add(key)
  const camera = new THREE.PerspectiveCamera(38, 1, .01, 10000)
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false })
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2)); host.appendChild(renderer.domElement)
  const controls = new OrbitControls(camera, renderer.domElement); controls.enableDamping = true
  const resize = () => {
    const w = Math.max(1, host.clientWidth), h = Math.max(1, host.clientHeight)
    renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix()
  }
  const observer = new ResizeObserver(resize); observer.observe(host); resize(); fit(camera, controls, root)
  let alive = true, raf
  const draw = () => { if (!alive) return; controls.update(); renderer.render(scene, camera); raf = requestAnimationFrame(draw) }
  draw()
  return {
    camera, controls, root,
    fit: () => fit(camera, controls, root),
    dispose() { alive = false; cancelAnimationFrame(raf); observer.disconnect(); controls.dispose(); renderer.dispose(); disposeTree(root); renderer.domElement.remove() },
  }
}

export function initHullAudit({ getState, subscribe, setMenuToggle = () => {}, viewerFactory = makeViewer } = {}) {
  const menu = document.getElementById('menu-help-hull-audit')
  const modal = document.createElement('div')
  modal.id = 'hull-audit'; modal.className = 'ha-modal'
  modal.innerHTML = `<div class="ha-header"><div><div class="ha-title">Hull Audit</div>
    <div class="ha-subtitle">Read-only comparison · production hull, candidate minimal envelope, and full geometry reference</div></div>
    <button class="ha-reset" type="button">Reset views</button><button class="ha-close" type="button">Close</button></div>
    <div class="ha-metrics"></div><div class="ha-grid"></div>`
  document.body.appendChild(modal)
  const grid = modal.querySelector('.ha-grid'), metrics = modal.querySelector('.ha-metrics')
  let open = false, viewers = [], syncing = false, refreshQueued = false
  const close = () => {
    open = false; modal.classList.remove('visible'); setMenuToggle('menu-help-hull-audit', false)
    viewers.forEach(v => v.dispose?.()); viewers = []; grid.innerHTML = ''; metrics.innerHTML = ''
    modal.querySelector('.ha-warning')?.remove()
  }
  const sync = source => {
    if (syncing) return
    syncing = true
    for (const v of viewers) if (v !== source) {
      v.camera.position.copy(source.camera.position); v.camera.quaternion.copy(source.camera.quaternion)
      v.controls.target.copy(source.controls.target); v.controls.update()
    }
    syncing = false
  }
  const render = () => {
    const cameraState = viewers[0] ? {
      position: viewers[0].camera.position.clone(), quaternion: viewers[0].camera.quaternion.clone(),
      target: viewers[0].controls.target.clone(),
    } : null
    viewers.forEach(v => v.dispose?.()); viewers = []; grid.innerHTML = ''; metrics.innerHTML = ''
    modal.querySelector('.ha-warning')?.remove()
    const { currentDesign: design, currentGeometry: geometry, currentHelixAxes: axes } = getState?.() ?? {}
    if (!design || !geometry?.length || !axes) {
      grid.innerHTML = '<div class="ha-error">Load a design with generated geometry before opening Hull Audit.</div>'; return
    }
    const oldData = _hullGeoForSource(design, geometry, axes, { forceLegacy: true })
    const oldRoot = new THREE.Group()
    if (oldData?.solid) oldRoot.add(new THREE.Mesh(oldData.solid, new THREE.MeshPhongMaterial({ color: 0x9a9a9a, shininess: 16 })))
    oldData?.markers?.dispose?.()
    const candidate = buildClusteredAuditHull(design, geometry, axes)
    const fullRoot = new THREE.Group()
    const customColors = Object.fromEntries((design.strands ?? []).filter(s => s.color).map(s => [
      s.id, Number.parseInt(String(s.color).replace(/^#/, ''), 16),
    ]))
    const fullCtrl = buildHelixObjects(geometry, design, fullRoot, customColors, [], axes, 'full')
    fullCtrl.setMode?.('normal'); fullCtrl.setAxisArrowsVisible?.(false)
    const defs = [
      { id: 'old', title: 'Old', note: 'Legacy feature-history / scan Hull Prism', root: oldRoot },
      { id: 'candidate', title: 'New', note: 'Imported-design production occupancy envelope', root: candidate ?? new THREE.Group() },
      { id: 'full', title: 'Full reference', note: 'Current detailed representation', root: fullRoot },
    ]
    grid.innerHTML = ''
    for (const def of defs) {
      const panel = document.createElement('section'); panel.className = 'ha-panel'; panel.dataset.panel = def.id
      panel.innerHTML = `<div class="ha-panel-head"><b>${def.title}</b><span>${def.note}</span>${def.id === 'candidate'
        ? '<label class="ha-elements"><input type="checkbox"> Elements</label>' : ''}</div><div class="ha-canvas"></div>`
      grid.appendChild(panel)
      const viewer = viewerFactory(panel.querySelector('.ha-canvas'), def.root); viewers.push(viewer)
      viewer.controls?.addEventListener?.('change', () => sync(viewer))
      panel.querySelector('.ha-elements input')?.addEventListener('change', event => {
        setHullElementBoundaries(def.root, event.target.checked)
      })
    }
    if (!oldData?.solid || !candidate) {
      const warning = document.createElement('div'); warning.className = 'ha-warning'
      warning.textContent = `${!oldData?.solid ? 'Old hull unavailable. ' : ''}${!candidate ? 'Candidate needs lattice helices with dsDNA geometry.' : ''}`
      modal.appendChild(warning)
    }
    if (viewers[0] && viewers[1]) sync(viewers[0])
    if (cameraState) {
      for (const viewer of viewers) {
        viewer.camera.position.copy(cameraState.position); viewer.camera.quaternion.copy(cameraState.quaternion)
        viewer.controls.target.copy(cameraState.target); viewer.controls.update()
      }
    }
    metrics.innerHTML = defs.map(def => {
      const s = hullAuditStats(def.root), dims = s.size.map(n => n.toFixed(1)).join(' × ')
      return `<div><span>${def.title}</span><b>${s.triangles} tris</b><small>${dims} nm</small></div>`
    }).join('')
  }
  const show = () => {
    if (open) { close(); return }
    open = true; modal.classList.add('visible'); setMenuToggle('menu-help-hull-audit', true)
    render()
  }
  menu?.addEventListener('click', show)
  modal.querySelector('.ha-close').addEventListener('click', close)
  modal.querySelector('.ha-reset').addEventListener('click', () => { viewers[0]?.fit?.(); if (viewers[0]) sync(viewers[0]) })
  const key = e => { if (open && e.key === 'Escape') close() }; window.addEventListener('keydown', key)
  const unsubscribe = subscribe?.((next, previous) => {
    if (!open || refreshQueued) return
    const transformsChanged = next.currentDesign?.cluster_transforms !== previous.currentDesign?.cluster_transforms
    if (next.currentGeometry === previous.currentGeometry && next.currentHelixAxes === previous.currentHelixAxes && !transformsChanged) return
    refreshQueued = true
    queueMicrotask(() => { refreshQueued = false; if (open) render() })
  })
  return { show, close, refresh: render, isOpen: () => open, element: modal, dispose() { unsubscribe?.(); close(); menu?.removeEventListener('click', show); window.removeEventListener('keydown', key); modal.remove() } }
}
