/**
 * Annotation overlay: screen-space callouts (DOM + SVG leaders) plus a 3D
 * optional highlight for each entry's target. Callouts and leaders draw above
 * the scene; target highlights use the cluster-selection glow. Invisible target
 * buffers preserve live anchor positions when publishing a shared view.
 *
 * Read-only with respect to the design: targets are resolved from live
 * backbone entries every frame, nothing is written back (Three-Layer Law).
 */
import * as THREE from 'three'
import { SilhouetteHighlight, registerSilhouetteHighlights } from './silhouette_highlight.js'
import { createGlowLayer } from './glow_layer.js'
import { drawAnnotationCallouts } from './annotation_canvas.js'
import './annotation_overlay.css'
import { annotationIsRenderable } from './annotation_model.js'
import { isExternalRef } from './annotation_external.js'
import { buildOccupancy } from './annotation_occupancy.js'
import { annotationIconMarkup } from './annotation_icons.js'
import { anchorFromPoints, matchTargetEntries, unresolvedBaseKeys } from './annotation_targets.js'
import { layoutCallouts, leaderPoints } from './annotation_layout.js'

const sharedOverlays = new WeakMap()
const exportOverlays = new WeakMap()

export function drawSceneAnnotations(scene, ctx, width, height, camera) {
  exportOverlays.get(scene)?.draw(ctx, width, height, camera)
}

/** Visible callouts only; hidden annotation text and editor selection refs stay local. */
export function captureSceneAnnotations(scene) {
  return sharedOverlays.get(scene)?.() ?? []
}

export function syncSceneAnnotations(scene) { exportOverlays.get(scene)?.update() }

const SVG_NS = 'http://www.w3.org/2000/svg'
const BASE_FONT_PX = 13
const BASE_ICON_PX = 18
const HIGHLIGHT_RENDER_ORDER = 1200
const HALO_SCALE = 3.2          // sprite diameter as a multiple of the sphere radius
const MAX_OCCUPANCY_POINTS = 20000
/** Design fields target resolution reads; an annotation-only design change must not force a rebuild. */
const TARGET_DESIGN_KEYS = ['strands', 'helices', 'cluster_transforms', 'crossovers', 'forced_ligations', 'overhangs', 'extensions', 'nanoparticles', 'protein_attachments']
const sameTargetDesign = (a, b) => a === b || (!!a && !!b && TARGET_DESIGN_KEYS.every(k => a[k] === b[k]))

function glowTexture(document) {
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = 64
  const ctx = canvas.getContext?.('2d')
  if (!ctx) return null
  const grad = ctx.createRadialGradient(32, 32, 0, 32, 32, 32)
  grad.addColorStop(0, 'rgba(255,255,255,1)')
  grad.addColorStop(0.45, 'rgba(255,255,255,0.7)')
  grad.addColorStop(1, 'rgba(255,255,255,0)')
  ctx.fillStyle = grad
  ctx.fillRect(0, 0, 64, 64)
  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.SRGBColorSpace
  return texture
}

export function initAnnotationOverlay({
  document = globalThis.document, container, scene, getCamera, controller,
  getEntries = () => [], getDesign = () => null, resolveBasePosition = () => null,
  resolveSilhouette = (_refs, matched) => matched,
  resolveExternal = () => null, getOccluders = () => [],
  addFrameCallback = null, removeFrameCallback = null, getViewport = null,
  readOnly = false, resolveSharedPoints = null, resolveTargetEntries = null,
}) {
  const root = document.createElement('div')
  root.className = 'nadoc-anno-layer'
  root.setAttribute('aria-hidden', 'true')
  const svg = document.createElementNS(SVG_NS, 'svg')
  svg.setAttribute('class', 'nadoc-anno-leaders')
  root.append(svg)
  container.append(root)

  const group = new THREE.Group()
  group.name = 'Annotation highlights'
  group.userData.setupOnly = true
  scene.add(group)
  const texture = readOnly ? null : glowTexture(document)

  const records = new Map()
  const v = new THREE.Vector3()
  let enabled = true          // part mode (vs assembly)
  let shown = null            // what the layer currently displays

  const viewport = () => getViewport?.() ?? { width: root.clientWidth || 1, height: root.clientHeight || 1 }

  function makeRecord(entry) {
    const el = document.createElement('div')
    el.className = 'nadoc-anno'
    el.dataset.annotationId = entry.id
    const box = document.createElement('div')
    box.className = 'nadoc-anno__box'
    const icon = document.createElement('span')
    icon.className = 'nadoc-anno__icon'
    const text = document.createElement('span')
    text.className = 'nadoc-anno__text'
    const grip = document.createElement('div')
    grip.className = 'nadoc-anno__grip'
    grip.title = 'Drag to place this callout'
    box.append(icon, text)
    if (!readOnly) box.append(grip)
    el.append(box)
    root.append(el)

    const g = document.createElementNS(SVG_NS, 'g')
    const line = document.createElementNS(SVG_NS, 'polyline')
    const dot = document.createElementNS(SVG_NS, 'circle')
    dot.setAttribute('r', '5')
    g.append(line, dot)
    svg.append(g)

    const rec = {
      id: entry.id, el, box, icon, text, grip, g, line, dot,
      size: { w: 0, h: 0 }, rect: null, drag: null, dirty: true,
      src: null, srcLen: -1, design: null, matched: [], extra: [], externalRefs: [], halos: [], glow: null, points: null, pointCount: 0,
      shown: false, styleSig: '', tx: NaN, ty: NaN, hasAnchor: false,
    }
    if (!readOnly) wireDrag(rec)
    records.set(entry.id, rec)
    return rec
  }

  function wireDrag(rec) {
    const { grip, el } = rec
    grip.addEventListener('pointerdown', event => {
      if (event.button != null && event.button !== 0) return
      event.preventDefault()
      event.stopPropagation()
      const base = root.getBoundingClientRect()
      const rect = rec.rect ?? { x: 0, y: 0 }
      rec.drag = { dx: event.clientX - base.left - rect.x, dy: event.clientY - base.top - rect.y }
      grip.setPointerCapture?.(event.pointerId)
      el.classList.add('nadoc-anno--dragging')
    })
    grip.addEventListener('pointermove', event => {
      if (!rec.drag) return
      const base = root.getBoundingClientRect()
      const { width, height } = viewport()
      const x = event.clientX - base.left - rec.drag.dx
      const y = event.clientY - base.top - rec.drag.dy
      controller.update(rec.id, { screenPos: { x: x / width, y: y / height } })
    })
    const end = event => {
      if (!rec.drag) return
      rec.drag = null
      grip.releasePointerCapture?.(event.pointerId)
      el.classList.remove('nadoc-anno--dragging')
    }
    grip.addEventListener('pointerup', end)
    grip.addEventListener('pointercancel', end)
  }

  function disposeHalos(rec) {
    for (const halo of rec.halos) { group.remove(halo); halo.material.dispose() }
    rec.halos = []
  }
  function disposeHighlight(rec) {
    disposeHalos(rec)
    rec.silhouette?.dispose()
    rec.silhouette = null
    rec.glow?.dispose()
    rec.glow = null
    if (!rec.points) return
    group.remove(rec.points)
    rec.points.geometry.dispose()
    rec.points.material.dispose()
    rec.points = null
    rec.pointCount = 0
  }

  function destroyRecord(rec) {
    disposeHighlight(rec)
    rec.el.remove()
    rec.g.remove()
    records.delete(rec.id)
  }

  /** Text/icon/colour/size; re-measures because box size feeds the layout. */
  function syncStyle(rec, entry) {
    const sig = JSON.stringify([entry.text, entry.icon, entry.calloutType, entry.color, entry.size, entry.manual, entry.transparency])
    if (sig === rec.styleSig) return
    rec.styleSig = sig
    const { el, box, icon, text } = rec
    el.className = `nadoc-anno nadoc-anno--${entry.calloutType}${entry.manual ? ' nadoc-anno--manual' : ''}${rec.drag ? ' nadoc-anno--dragging' : ''}`
    el.style.setProperty('--anno-color', entry.color)
    el.style.opacity = String(1 - entry.transparency)
    box.style.fontSize = `${(BASE_FONT_PX * entry.size).toFixed(1)}px`
    text.textContent = entry.text
    icon.innerHTML = annotationIconMarkup(entry.icon, Math.round(BASE_ICON_PX * entry.size))
    icon.hidden = !entry.icon
    rec.line.setAttribute('stroke', entry.color)
    rec.dot.setAttribute('stroke', entry.color)
    rec.g.style.opacity = String(1 - entry.transparency)
    el.hidden = false
    rec.size = { w: el.offsetWidth, h: el.offsetHeight }
    if (rec.points) {
      rec.points.material.color.set(entry.color)
      rec.points.material.opacity = 0
    }
    for (const halo of rec.halos) {
      halo.material.color.set(entry.color)
      halo.material.opacity = entry.highlight && entry.highlightType !== 'silhouette' ? Math.min(1, 0.45 * entry.glowIntensity) : 0
    }
  }

  function rebuildTarget(rec, entry, src, design) {
    rec.dirty = false
    rec.src = src
    rec.srcLen = src.length
    rec.design = design
    rec.matched = resolveTargetEntries?.(entry.refs) ?? matchTargetEntries(entry.refs, design, src)
    rec.extra = unresolvedBaseKeys(entry.refs, rec.matched)
      .map(key => resolveBasePosition(key)).filter(Boolean)
    rec.externalRefs = entry.refs.filter(isExternalRef)
    disposeHalos(rec)
    for (const ref of rec.externalRefs) {
      const halo = new THREE.Sprite(new THREE.SpriteMaterial({
        map: texture, color: entry.color, transparent: true, opacity: 0,
        depthTest: false, depthWrite: false,
      }))
      halo.renderOrder = HIGHLIGHT_RENDER_ORDER - 1
      halo.name = `Annotation halo ${rec.id} ${ref.kind}:${ref.id}`
      halo.visible = false
      rec.halos.push(halo)
      group.add(halo)
    }
    const count = rec.matched.length + rec.extra.length
    if (!count) {
      if (rec.points) { group.remove(rec.points); rec.points.geometry.dispose(); rec.points.material.dispose(); rec.points = null; rec.pointCount = 0 }
      return
    }
    if (!rec.points || rec.pointCount !== count) {
      if (rec.points) { group.remove(rec.points); rec.points.geometry.dispose(); rec.points.material.dispose() }
      const geometry = new THREE.BufferGeometry()
      geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(count * 3), 3))
      const material = new THREE.PointsMaterial({
        // Keep target positions for shared-view callout anchors, without drawing
        // the legacy soft-dot overlay when Highlight target is switched off.
        color: entry.color, size: 1,
        sizeAttenuation: true, transparent: true, opacity: 0,
        depthTest: false, depthWrite: false, alphaTest: 0.01,
      })
      rec.points = new THREE.Points(geometry, material)
      rec.points.frustumCulled = false
      rec.points.renderOrder = HIGHLIGHT_RENDER_ORDER
      rec.points.name = `Annotation highlight ${rec.id}`
      rec.pointCount = count
      group.add(rec.points)
    }
  }

  function writeHighlight(rec) {
    const entry = rec.entry
    if (entry.highlight && entry.highlightType !== 'silhouette' && !readOnly) {
      rec.glow ??= createGlowLayer(group, entry.glowColor, undefined, `Annotation glow ${rec.id}`)
      rec.glow.setStyle(entry.glowColor, entry.glowIntensity)
      rec.glow.setEntries(rec.matched.concat(rec.extra.map(pos => ({ pos }))))
    } else if (rec.glow) { rec.glow.dispose(); rec.glow = null }
    // Only the optional glow renders; points carry shared-view anchor positions.
    if (rec.points) rec.points.visible = !entry.highlight || entry.highlightType === 'silhouette'
    if (rec.points) {
      const attr = rec.points.geometry.attributes.position
      const a = attr.array
      let i = 0
      for (const e of rec.matched) { a[i++] = e.pos.x; a[i++] = e.pos.y; a[i++] = e.pos.z }
      for (const p of rec.extra) { a[i++] = p.x; a[i++] = p.y; a[i++] = p.z }
      attr.needsUpdate = true
    }
    // Proteins / nanoparticles: a halo sized to the element's bounding sphere.
    const spheres = []
    rec.externalRefs.forEach((ref, k) => {
      const sphere = resolveExternal(ref)
      const halo = rec.halos[k]
      if (halo) {
        halo.visible = !!sphere
        halo.material.color.set(entry.highlight ? entry.glowColor : entry.color)
        halo.material.opacity = entry.highlight && entry.highlightType !== 'silhouette' ? Math.min(1, 0.45 * entry.glowIntensity) : 0
        const blending = entry.highlight ? THREE.AdditiveBlending : THREE.NormalBlending
        if (halo.material.blending !== blending) { halo.material.blending = blending; halo.material.needsUpdate = true }
      }
      if (!sphere) return
      spheres.push(sphere)
      if (halo) { halo.position.set(sphere.x, sphere.y, sphere.z); halo.scale.setScalar(sphere.radius * HALO_SCALE) }
    })
    return spheres
  }

  /** World sphere → screen disc (px), or null when behind the camera. */
  function projectSphere(camera, sphere, width, height) {
    v.set(sphere.x, sphere.y, sphere.z).project(camera)
    if (!(v.z > -1 && v.z < 1)) return null
    const cx = (v.x * 0.5 + 0.5) * width, cy = (-v.y * 0.5 + 0.5) * height
    let r
    if (camera.isPerspectiveCamera) {
      const dist = Math.max(1e-3, Math.abs(camera.matrixWorldInverse.elements[2] * sphere.x + camera.matrixWorldInverse.elements[6] * sphere.y
        + camera.matrixWorldInverse.elements[10] * sphere.z + camera.matrixWorldInverse.elements[14]))
      r = sphere.radius * (height / 2) / (Math.tan((camera.fov * Math.PI) / 360) * dist)
    } else {
      r = sphere.radius * height / ((camera.top - camera.bottom) / (camera.zoom || 1))
    }
    return { x: cx, y: cy, r }
  }

  /** Occupancy of the visible design on screen; rebuilt only when something moved. */
  let occCache = { sig: '', occ: null }
  function occupancyFor(camera, src, discsWorld, width, height) {
    const cam = camera.matrixWorld.elements, proj = camera.projectionMatrix.elements
    let sig = `${width}x${height}|${src.length}|${proj[0].toFixed(4)},${proj[5].toFixed(4)}|${cam.map(n => n.toFixed(3)).join(',')}`
    for (let k = 0, step = Math.max(1, Math.floor(src.length / 48)); k < src.length; k += step) {
      const p = src[k].pos
      sig += `|${(p.x + p.y * 3 + p.z * 7).toFixed(2)}`
    }
    for (const d of discsWorld) sig += `|${d.x.toFixed(2)},${d.y.toFixed(2)},${d.z.toFixed(2)},${d.radius.toFixed(2)}`
    if (sig === occCache.sig) return occCache.occ
    const points = []
    const stride = Math.max(1, Math.ceil(src.length / MAX_OCCUPANCY_POINTS))
    for (let k = 0; k < src.length; k += stride) {
      const p = src[k].pos
      v.set(p.x, p.y, p.z).project(camera)
      if (v.z > -1 && v.z < 1) points.push({ x: (v.x * 0.5 + 0.5) * width, y: (-v.y * 0.5 + 0.5) * height })
    }
    const discs = discsWorld.map(d => projectSphere(camera, d, width, height)).filter(Boolean)
    occCache = { sig, occ: buildOccupancy(points, discs, { width, height }) }
    return occCache.occ
  }

  function sync() {
    const list = controller.list()
    const live = new Set(list.map(e => e.id))
    for (const rec of [...records.values()]) if (!live.has(rec.id)) destroyRecord(rec)
    for (const entry of list) {
      const rec = records.get(entry.id) ?? makeRecord(entry)
      rec.entry = entry
      if (annotationIsRenderable(entry)) syncStyle(rec, entry)
      else { rec.el.hidden = true; rec.styleSig = ''; disposeHighlight(rec); rec.dirty = true; rec.g.style.display = 'none' }
    }
  }

  /** Per-frame: resolve anchors, project, lay out, draw. */
  function update(exportView = null, exportCamera = null) {
    // Two independent switches: part mode, and the user's global annotations toggle.
    const on = enabled && controller.isEnabled()
    if (on !== shown) { shown = on; root.hidden = !on; group.visible = on }
    if (!on) return
    const camera = exportCamera ?? getCamera?.()
    if (!camera) return
    const list = controller.list()
    if (records.size !== list.length || list.some(e => records.get(e.id)?.entry !== e)) sync()
    const { width, height } = exportView?.width ? exportView : viewport()
    const src = getEntries() ?? []
    const design = getDesign()
    camera.updateMatrixWorld?.()

    const items = []
    const draw = []
    for (const entry of list) {
      const rec = records.get(entry.id)
      if (!rec || !annotationIsRenderable(entry)) continue
      const liveTargets = resolveTargetEntries?.(entry.refs)
      const stale = (liveTargets != null && liveTargets !== rec.matched) || rec.dirty || !sameTargetDesign(rec.design, design) || (rec.src !== src && (src.length || rec.srcLen))
      if (stale && !resolveSharedPoints) rebuildTarget(rec, entry, src, design)
      const spheres = resolveSharedPoints ? [] : writeHighlight(rec)
      let anchor = null
      const points = resolveSharedPoints ? resolveSharedPoints(entry) : rec.matched.map(e => e.pos).concat(rec.extra, spheres)
      const world = anchorFromPoints(points)
      if (world) {
        v.set(world.x, world.y, world.z).project(camera)
        if (v.z > -1 && v.z < 1) anchor = { x: (v.x * 0.5 + 0.5) * width, y: (-v.y * 0.5 + 0.5) * height }
      }
      rec.hasAnchor = !!anchor
      items.push({
        id: entry.id, size: rec.size, anchor,
        manualRect: entry.manual && entry.screenPos ? { x: entry.screenPos.x * width, y: entry.screenPos.y * height } : null,
      })
      draw.push({ entry, rec, anchor })
    }
    const previous = new Map(draw.filter(d => !d.entry.manual && d.rec.rect).map(d => [d.entry.id, d.rec.rect]))
    const occupancy = occupancyFor(camera, src, getOccluders() ?? [], width, height)
    const rects = layoutCallouts(items, { width, height }, { occupancy, previous })
    for (const { entry, rec, anchor } of draw) {
      const rect = rects.get(entry.id)
      rec.rect = rect
      const tx = Math.round(rect.x), ty = Math.round(rect.y)
      if (tx !== rec.tx || ty !== rec.ty) { rec.el.style.transform = `translate(${tx}px, ${ty}px)`; rec.tx = tx; rec.ty = ty }
      rec.g.style.display = anchor ? '' : 'none'
      if (anchor) {
        const pts = leaderPoints(entry.calloutType, rect, anchor)
        rec.line.setAttribute('points', pts.map(p => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' '))
        rec.dot.setAttribute('cx', anchor.x.toFixed(1))
        rec.dot.setAttribute('cy', anchor.y.toFixed(1))
      }
    }
  }

  const unsubscribe = controller.subscribe(event => {
    if (event.type === 'update' && event.patch) {
      const rec = records.get(event.id)
      if ('refs' in event.patch && rec) rec.dirty = true
      // Switching to manual pins the box where it currently sits.
      if (event.patch.manual === true && rec) {
        const { width, height } = viewport()
        const at = rec.rect ?? { x: 16, y: 16 }
        controller.update(event.id, { screenPos: { x: at.x / width, y: at.y / height } })
      }
    } else for (const rec of records.values()) rec.dirty = true
  })
  function captureShared() {
    update()
    if (!enabled || !controller.isEnabled()) return []
    return controller.list().filter(annotationIsRenderable).map(entry => {
      const rec = records.get(entry.id)
      return { id: entry.id, text: entry.text, icon: entry.icon, calloutType: entry.calloutType,
        color: entry.color, size: entry.size, transparency: entry.transparency,
        manual: entry.manual, screenPos: entry.screenPos,
        targets: [rec?.points, rec?.glow?.getMesh(), ...(rec?.halos ?? [])].filter(o => o?.visible).map(o => o.uuid) }
    })
  }
  function drawExport(ctx, width, height, camera) {
    const live = viewport()
    const scale = Math.min(width / live.width, height / live.height)
    const previousRects = new Map([...records].map(([id, rec]) => [id, rec.rect]))
    try {
      update({ width: width / scale, height: height / scale }, camera)
      if (!enabled || !controller.isEnabled()) return
      drawAnnotationCallouts(ctx, [...records.values()].filter(rec => annotationIsRenderable(rec.entry)), scale)
    } finally {
      // Export layout must not become the next frame's preferred live layout.
      for (const [id, rect] of previousRects) {
        const rec = records.get(id)
        if (rec) rec.rect = rect
      }
      // The photo session restores the live camera before its final sync.
    }
  }
  if (!readOnly) {
    sharedOverlays.set(scene, captureShared)
    exportOverlays.set(scene, { draw: drawExport, update })
  }
  const unregisterSilhouette = readOnly ? () => {} : registerSilhouetteHighlights(scene, (renderer, camera, pixelScale) => {
    if (!enabled || !controller.isEnabled()) return
    for (const rec of records.values()) {
      const entry = rec.entry
      if (!annotationIsRenderable(entry) || !entry.highlight || entry.highlightType !== 'silhouette') continue
      rec.silhouette ??= new SilhouetteHighlight()
      rec.silhouette.render(renderer, camera, resolveSilhouette(entry.refs, rec.matched), entry.glowColor, entry.glowIntensity, pixelScale)
    }
  })
  addFrameCallback?.(update)

  return {
    update, captureShared,
    setEnabled(next) {
      enabled = !!next
      const on = enabled && controller.isEnabled()
      shown = on
      root.hidden = !on
      group.visible = on
    },
    /** Test/debug view of what is currently drawn. */
    getRecord: id => records.get(id) ?? null,
    dispose() {
      if (sharedOverlays.get(scene) === captureShared) sharedOverlays.delete(scene)
      if (exportOverlays.get(scene)?.draw === drawExport) exportOverlays.delete(scene)
      unregisterSilhouette()
      unsubscribe()
      removeFrameCallback?.(update)
      for (const rec of [...records.values()]) destroyRecord(rec)
      scene.remove(group)
      texture?.dispose()
      root.remove()
    },
  }
}
