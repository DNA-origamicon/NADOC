/**
 * CAD-style Dimensions tool.
 *
 * Parts measure the last two nucleotide anchors selected by SelectionManager.
 * Assemblies expose two independent translation gizmos. Recorded dimensions are
 * frozen world-space snapshots while the live dimension remains editable.
 */
import * as THREE from 'three'
import { TransformControls } from 'three/addons/controls/TransformControls.js'
import { getSectionCollapsed, setSectionCollapsed } from '../ui/section_collapse_state.js'
import { icon } from '../ui/primitives/icon.js'

const LIVE_COLOR = 0x00e5ff
const RECORDED_COLOR = 0x58a6ff

export function dimensionDistance(a, b) {
  return a && b ? a.distanceTo(b) : null
}

function _disposeMaterial(material) {
  if (!material) return
  for (const mat of Array.isArray(material) ? material : [material]) {
    mat.map?.dispose?.()
    mat.dispose?.()
  }
}

function _makeLabel(text, color) {
  const canvas = document.createElement('canvas')
  canvas.width = 256
  canvas.height = 64
  const ctx = canvas.getContext?.('2d')
  if (!ctx) return { sprite: null, setText() {}, dispose() {} }
  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.SRGBColorSpace
  const material = new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false })
  const sprite = new THREE.Sprite(material)
  sprite.renderOrder = 1001
  sprite.scale.set(5.6, 1.4, 1)

  function setText(next) {
    ctx.clearRect(0, 0, canvas.width, canvas.height)
    ctx.fillStyle = 'rgba(10,18,30,.88)'
    ctx.strokeStyle = color
    ctx.lineWidth = 2
    ctx.beginPath()
    ctx.roundRect?.(2, 2, 252, 60, 10)
    if (ctx.roundRect) { ctx.fill(); ctx.stroke() }
    else { ctx.fillRect(2, 2, 252, 60); ctx.strokeRect(2, 2, 252, 60) }
    ctx.fillStyle = color
    ctx.font = '600 25px sans-serif'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(next, 128, 33)
    texture.needsUpdate = true
  }
  setText(text)
  return {
    sprite,
    setText,
    dispose() { texture.dispose(); material.dispose() },
  }
}

function _makeVisual(scene, a, b, colorHex) {
  const root = new THREE.Group()
  root.userData.isDimension = true
  const geometry = new THREE.BufferGeometry().setFromPoints([a, b])
  const material = new THREE.LineBasicMaterial({
    color: colorHex, linewidth: 2, depthTest: false, transparent: true, opacity: 0.95,
  })
  const line = new THREE.Line(geometry, material)
  line.renderOrder = 1000
  root.add(line)

  const cssColor = `#${colorHex.toString(16).padStart(6, '0')}`
  const label = _makeLabel(`${a.distanceTo(b).toFixed(3)} nm`, cssColor)
  if (label.sprite) root.add(label.sprite)
  scene.add(root)

  function update(nextA, nextB) {
    const pos = line.geometry.getAttribute('position')
    pos.setXYZ(0, nextA.x, nextA.y, nextA.z)
    pos.setXYZ(1, nextB.x, nextB.y, nextB.z)
    pos.needsUpdate = true
    const distance = nextA.distanceTo(nextB)
    label.sprite?.position.copy(nextA).add(nextB).multiplyScalar(0.5)
    label.setText(`${distance.toFixed(3)} nm`)
    return distance
  }
  update(a, b)

  return {
    root,
    update,
    setVisible(visible) { root.visible = visible },
    dispose() {
      root.parent?.remove(root)
      geometry.dispose()
      material.dispose()
      label.dispose()
    },
  }
}

function _anchorLabel(anchor, fallback) {
  const nuc = anchor?.nuc
  if (!nuc) return fallback
  const strand = nuc.strand_id ? String(nuc.strand_id).slice(0, 12) : 'base'
  return `${strand} · ${nuc.bp_index ?? '?'}${nuc.direction === 'reverse' ? 'R' : 'F'}`
}

export function initDimensionsTool({
  scene, camera, canvas, controls, store, selectionManager, assemblyRenderer, rightSidebar,
}) {
  const section = document.getElementById('dimensions-section')
  const heading = document.getElementById('dimensions-heading')
  const body = document.getElementById('dimensions-body')
  const arrow = document.getElementById('dimensions-arrow')
  const hint = document.getElementById('dimensions-hint')
  const list = document.getElementById('dimensions-list')
  const recordButton = document.getElementById('dimensions-record')
  const clearButton = document.getElementById('dimensions-clear')
  if (!section || !heading || !body || !list) return null

  let collapsed = getSectionCollapsed('right', 'dimensions-section', true)
  let live = null
  let pending = null
  let records = []
  let nextId = 1
  let assemblyHandles = null
  let disposed = false

  function _isAssembly() { return Boolean(store.getState().assemblyActive) }
  function _isPickingBases() {
    const state = store.getState()
    return !collapsed && !state.assemblyActive && !state.unfoldActive
  }

  function _removeLive() {
    live?.visual?.dispose()
    live = null
  }

  function _clearPending() {
    pending = null
  }

  function _setLive(a, b, labels = ['Point A', 'Point B']) {
    if (!a || !b) { _removeLive(); _renderList(); return }
    if (!live) {
      live = {
        id: 'live', name: 'Current', a: a.clone(), b: b.clone(), labels,
        visible: true, visual: _makeVisual(scene, a, b, LIVE_COLOR),
      }
    } else {
      live.a.copy(a); live.b.copy(b); live.labels = labels
      live.visual.update(live.a, live.b)
    }
    _renderList()
  }

  function _removeRecord(id) {
    const index = records.findIndex(record => record.id === id)
    if (index < 0) return
    records[index].visual.dispose()
    records.splice(index, 1)
    _renderList()
  }

  function _toggleVisible(item) {
    item.visible = !item.visible
    item.visual.setVisible(item.visible)
    _renderList()
  }

  function _row(item, isLive = false) {
    const row = document.createElement('div')
    row.className = `dimensions-row${isLive ? ' dimensions-row--live' : ''}`
    row.dataset.dimensionId = String(item.id)

    const main = document.createElement('div')
    main.className = 'dimensions-row__main'
    const name = document.createElement('div')
    name.className = 'dimensions-row__name'
    name.textContent = item.name
    name.title = `${item.labels[0]} → ${item.labels[1]}`
    const value = document.createElement('div')
    value.className = 'dimensions-row__value'
    value.textContent = `${dimensionDistance(item.a, item.b).toFixed(3)} nm`
    main.append(name, value)

    const eye = document.createElement('button')
    eye.type = 'button'
    eye.className = 'dimensions-row__button'
    eye.title = item.visible ? 'Hide dimension' : 'Show dimension'
    eye.setAttribute('aria-label', eye.title)
    eye.appendChild(icon(item.visible ? 'eye' : 'eye-off', { size: 14 }))
    eye.addEventListener('click', () => _toggleVisible(item))

    const remove = document.createElement('button')
    remove.type = 'button'
    remove.className = 'dimensions-row__button dimensions-row__button--delete'
    remove.title = isLive ? 'Clear current dimension' : 'Delete dimension'
    remove.setAttribute('aria-label', remove.title)
    remove.appendChild(icon('x', { size: 14 }))
    remove.addEventListener('click', () => {
      if (isLive) {
        _removeLive()
        if (!_isAssembly()) selectionManager.clearCtrlBeads?.()
        _renderList()
      } else _removeRecord(item.id)
    })
    row.append(main, eye, remove)
    return row
  }

  function _renderList() {
    list.replaceChildren()
    if (live) list.appendChild(_row(live, true))
    for (const record of records) list.appendChild(_row(record))
    if (!live && records.length === 0) {
      const empty = document.createElement('div')
      empty.className = 'dimensions-empty'
      empty.textContent = 'No dimensions recorded.'
      list.appendChild(empty)
    }
    if (recordButton) recordButton.disabled = !(live || pending)
  }

  function _disposeAssemblyHandles() {
    if (!assemblyHandles) return
    // TransformControls.detach()/dispose() may emit a final change event. Clear
    // the authoritative handle state first so that event cannot recreate a live
    // line after Clear or while the card is closing.
    const handles = assemblyHandles
    assemblyHandles = null
    for (const transform of handles.transforms) {
      transform.detach()
      transform.getHelper().parent?.remove(transform.getHelper())
      transform.dispose()
    }
    for (const dummy of handles.dummies) {
      dummy.traverse(child => {
        child.geometry?.dispose?.()
        _disposeMaterial(child.material)
      })
      dummy.parent?.remove(dummy)
    }
    controls.enabled = true
  }

  function _assemblySeedPoints() {
    const box = assemblyRenderer.getBoundingBox?.()
    if (box && !box.isEmpty()) {
      const center = box.getCenter(new THREE.Vector3())
      const size = box.getSize(new THREE.Vector3())
      const half = Math.max(size.x, size.y, size.z, 4) * 0.2
      return [center.clone().add(new THREE.Vector3(-half, 0, 0)), center.clone().add(new THREE.Vector3(half, 0, 0))]
    }
    const center = controls.target?.clone?.() ?? new THREE.Vector3()
    return [center.clone().add(new THREE.Vector3(-2, 0, 0)), center.clone().add(new THREE.Vector3(2, 0, 0))]
  }

  function _createAssemblyHandles() {
    if (assemblyHandles || collapsed || !_isAssembly()) return
    const points = _assemblySeedPoints()
    const dummies = points.map((point, index) => {
      const dummy = new THREE.Object3D()
      dummy.position.copy(point)
      dummy.userData.isDimensionGizmo = true
      const marker = new THREE.Mesh(
        new THREE.SphereGeometry(0.45, 16, 12),
        new THREE.MeshBasicMaterial({ color: index ? 0xffc857 : LIVE_COLOR, depthTest: false }),
      )
      marker.renderOrder = 1002
      dummy.add(marker)
      scene.add(dummy)
      return dummy
    })
    const transforms = dummies.map(dummy => {
      const transform = new TransformControls(camera, canvas)
      transform.setMode('translate')
      transform.setSpace('world')
      transform.setSize(0.72)
      transform.attach(dummy)
      scene.add(transform.getHelper())
      transform.addEventListener('dragging-changed', event => { controls.enabled = !event.value })
      transform.addEventListener('change', () => {
        if (assemblyHandles) _setLive(dummies[0].position, dummies[1].position)
      })
      return transform
    })
    assemblyHandles = { dummies, transforms }
    _setLive(dummies[0].position, dummies[1].position)
  }

  function _syncMode() {
    if (collapsed) {
      _disposeAssemblyHandles()
      _removeLive()
      _clearPending()
      if (!_isAssembly()) selectionManager.clearCtrlBeads?.()
      _renderList()
      return
    }
    if (_isAssembly()) {
      selectionManager.clearCtrlBeads?.()
      _removeLive()
      _createAssemblyHandles()
      if (hint) hint.textContent = 'Drag either endpoint gizmo. Record freezes the current dimension.'
    } else {
      _disposeAssemblyHandles()
      _removeLive()
      _clearPending()
      selectionManager.clearCtrlBeads?.()
      if (hint) hint.textContent = 'Select two individual bases, then click Record to create the dimension.'
    }
    _renderList()
  }

  function _applyCollapse() {
    body.style.display = collapsed ? 'none' : ''
    heading.setAttribute('aria-expanded', String(!collapsed))
    arrow?.classList.toggle('is-collapsed', collapsed)
    setSectionCollapsed('right', 'dimensions-section', collapsed)
    _syncMode()
  }

  function open() {
    rightSidebar?.open?.('properties')
    collapsed = false
    _applyCollapse()
  }

  function close() {
    collapsed = true
    _applyCollapse()
  }

  function record() {
    const source = live ?? pending
    if (!source) return false
    const snapshot = {
      id: nextId++, name: `Dimension ${nextId - 1}`,
      a: source.a.clone(), b: source.b.clone(), labels: [...source.labels], visible: true,
    }
    snapshot.visual = _makeVisual(scene, snapshot.a, snapshot.b, RECORDED_COLOR)
    records.unshift(snapshot)
    if (!_isAssembly()) {
      selectionManager.clearCtrlBeads?.()
      _clearPending()
    }
    _renderList()
    return true
  }

  function clear() {
    _removeLive()
    _clearPending()
    for (const record of records) record.visual.dispose()
    records = []
    selectionManager.clearCtrlBeads?.()
    _renderList()
  }

  function _onHeadingKey(event) {
    if (event.key !== 'Enter' && event.key !== ' ') return
    event.preventDefault()
    collapsed ? open() : close()
  }
  heading.addEventListener('click', () => { collapsed ? open() : close() })
  heading.addEventListener('keydown', _onHeadingKey)
  recordButton?.addEventListener('click', record)
  clearButton?.addEventListener('click', clear)

  selectionManager.onCtrlBeadsChange(beads => {
    if (!_isPickingBases()) return
    const lastTwo = beads.slice(-2)
    if (lastTwo.length !== 2) { _clearPending(); _renderList(); return }
    const a = selectionManager.getCtrlBeadPos(beads.length - 2)
    const b = selectionManager.getCtrlBeadPos(beads.length - 1)
    pending = a && b ? {
      a: a.clone(), b: b.clone(),
      labels: [_anchorLabel(lastTwo[0], 'Base A'), _anchorLabel(lastTwo[1], 'Base B')],
    } : null
    _renderList()
  })

  const unsubscribe = store.subscribe((next, prev) => {
    if (next.assemblyActive !== prev.assemblyActive) _syncMode()
  })
  const unsubscribeSidebar = rightSidebar?.onChange?.(({ activeTab }) => {
    if (activeTab !== 'properties' && !collapsed) close()
  })

  _applyCollapse()
  _renderList()

  return {
    open, close, record, clear,
    isActive: () => !collapsed,
    isPickingBases: _isPickingBases,
    getMeasurements: () => [live, ...records].filter(Boolean).map(item => ({
      id: item.id, name: item.name, distance: dimensionDistance(item.a, item.b), visible: item.visible,
    })),
    getAssemblyEndpoints: () => assemblyHandles?.dummies.map(dummy => dummy.position.toArray()) ?? [],
    setAssemblyEndpoint(index, position) {
      const dummy = assemblyHandles?.dummies[index]
      if (!dummy || !Array.isArray(position) || position.length !== 3) return false
      dummy.position.fromArray(position)
      dummy.updateMatrixWorld(true)
      _setLive(assemblyHandles.dummies[0].position, assemblyHandles.dummies[1].position)
      return true
    },
    dispose() {
      if (disposed) return
      disposed = true
      clear()
      _disposeAssemblyHandles()
      unsubscribe?.()
      unsubscribeSidebar?.()
      heading.removeEventListener('keydown', _onHeadingKey)
    },
  }
}
