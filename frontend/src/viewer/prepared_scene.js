import { hullCutoutShader, applyHullCutouts, validateHullCutouts } from '../scene/hull_volume_cutouts.js'
import { validateSharedOverlay } from './shared_overlay.js'
import { validateSharedVisualization } from './shared_visualization.js'
import { validateSharedSelection } from './shared_selection.js'
import { validateSharedAnnotations } from './shared_annotations.js'
import { validateViewTools } from './shared_view_tools.js'
import * as THREE from 'three'
import { LineSegmentsGeometry } from 'three/addons/lines/LineSegmentsGeometry.js'
import { encodeWideLineMaterial, validateWideLineMaterial, loadWideLineMaterial, restoreWideLine } from './prepared_wide_lines.js'
import { applyInstanceAlphaMaterial, instanceAlphaOnBeforeCompile } from '../scene/instance_alpha.js'
import { encodeContainer, decodeContainer } from './package_container.js'
import { preparedImpostorSpec, makeImpostorPhongMaterial, enableImpostorInstanceAlpha, installSphereImpostorRaycast } from '../scene/impostor_material.js'
import { sectionCapShader } from '../scene/section_cap_material.js'

const MATERIALS = new Set(['MeshBasicMaterial', 'MeshLambertMaterial', 'MeshPhongMaterial', 'MeshStandardMaterial', 'MeshPhysicalMaterial', 'MeshNormalMaterial', 'LineBasicMaterial', 'LineDashedMaterial', 'PointsMaterial', 'SpriteMaterial'])
const COLOR_KEYS = ['color', 'emissive', 'specular', 'sheenColor', 'attenuationColor', 'specularColor']
const NODES = new Set(['Scene', 'Group', 'Object3D', 'Mesh', 'InstancedMesh', 'Line', 'LineSegments', 'LineLoop', 'Points', 'Sprite', 'AmbientLight', 'DirectionalLight', 'HemisphereLight', 'PointLight'])
const finiteVector = (v, n) => Array.isArray(v) && v.length === n && v.every(Number.isFinite)
const fail = message => { throw new Error(message) }

/** Export a frozen display snapshot, including physical positions already on screen.
 * No topology, scientific geometry generation, or editor history is copied/changed.
 * Unsupported shader pipelines fail rather than silently losing their transforms.
 */
export function prepareScene({ scene, camera, navigation = new Float64Array(), title = 'Prepared view', background = '#0d1117', renderer, sourceHash = null, view = null }) {
  if (renderer?.clippingPlanes?.length) fail('Global clipping is not supported by prepared views')
  const geometries = new Map(), materials = new Map(), meta = { textures: {}, images: {} }
  function attribute(a) {
    if (a.isInterleavedBufferAttribute) {
      const array = new a.data.array.constructor(a.count * a.itemSize)
      for (let i = 0; i < a.count; i++) for (let k = 0; k < a.itemSize; k++) array[i * a.itemSize + k] = a.data.array[i * a.data.stride + a.offset + k]
      return { array, itemSize: a.itemSize, normalized: a.normalized, instanced: !!a.data.isInstancedInterleavedBuffer, meshPerAttribute: a.data.meshPerAttribute ?? 1 }
    }
    if (!ArrayBuffer.isView(a.array)) fail('Unsupported geometry attribute')
    return { array: a.array, itemSize: a.itemSize, normalized: a.normalized, instanced: !!a.isInstancedBufferAttribute, meshPerAttribute: a.meshPerAttribute ?? 1 }
  }
  function geometry(g) {
    if (geometries.has(g.uuid)) return g.uuid
    if (g.isInstancedBufferGeometry && !g.isLineSegmentsGeometry) fail('Custom instanced geometry is not supported by this package version')
    if (Object.keys(g.morphAttributes).length) fail('Animated morph geometry is not supported by this package version')
    geometries.set(g.uuid, { uuid: g.uuid, ...(g.isLineSegmentsGeometry ? { wideLine: true, instanceCount: g.instanceCount } : {}), attributes: Object.fromEntries(Object.entries(g.attributes).map(([k, a]) => [k, attribute(a)])),
      index: g.index ? attribute(g.index) : null, groups: g.groups, drawRange: { start: g.drawRange.start, count: Number.isFinite(g.drawRange.count) ? g.drawRange.count : null } })
    return g.uuid
  }
  function material(m) {
    if (materials.has(m.uuid)) return m.uuid
    if (m.colors && Object.entries(m.colors).some(([k, v]) => !COLOR_KEYS.includes(k) || !finiteVector(v, 3))) fail('Invalid material colors')
    if (!MATERIALS.has(m.type) && !m.isLineMaterial) fail(`Unsupported material ${m.type}; this view cannot yet be packaged`)
    const impostor = preparedImpostorSpec(m)
    const alpha = m.onBeforeCompile === instanceAlphaOnBeforeCompile
    const hullCutouts = m.onBeforeCompile === hullCutoutShader ? m.userData.hullCutouts : null
    const sectionCap = m.onBeforeCompile === sectionCapShader
    if (!hullCutouts && !impostor && !alpha && !sectionCap && m.onBeforeCompile !== THREE.Material.prototype.onBeforeCompile) fail(`Custom shader on ${m.name || m.type} is not yet supported; keep using the editor for this view`)
    const data = m.isLineMaterial ? encodeWideLineMaterial(m) : m.toJSON(meta)
    delete data.userData
    materials.set(m.uuid, { ...data, instanceAlpha: alpha, sectionCap, ...(hullCutouts ? { hullCutouts } : {}), ...(impostor ? { impostor } : {}),
      sectionPlanes: (m.clippingPlanes ?? []).map(p => [...p.normal.toArray(), p.constant]),
      clipIntersection: m.clipIntersection, clipShadows: m.clipShadows,
      colors: Object.fromEntries(COLOR_KEYS.filter(k => m[k]?.isColor).map(k => [k, m[k].toArray()])) })
    return m.uuid
  }
  function node(o, depth = 0) {
    if (!o.visible || o.isTransformControlsRoot) return null // Tools stay local; section caps remain part of the view.
    if (o.isSkinnedMesh || o.isBatchedMesh) fail(`Unsupported scene object ${o.type}`)
    const type = o instanceof THREE.ArrowHelper ? 'Object3D' : o.isLineSegments2 ? 'Mesh' : o.isInstancedMesh ? 'InstancedMesh' : o.isLineSegments ? 'LineSegments' : o.isLineLoop ? 'LineLoop' : o.type
    if (depth > 128 || !NODES.has(type)) fail(`Unsupported scene object ${o.type}`)
    if (o.isScene && (o.environment || o.fog || (o.background && !o.background.isColor))) fail('Environment/fog backgrounds are not yet supported')
    if (o.isLight && o.castShadow) fail('Shadow maps are not yet supported')
    if (o.isDirectionalLight && o.target.position.lengthSq()) fail('Custom light targets are not yet supported')
    if (o.matrixAutoUpdate) o.updateMatrix()
    const value = { type, uuid: o.uuid, name: o.name, matrix: o.matrix.toArray(), matrixAutoUpdate: false, layers: o.layers.mask,
      renderOrder: o.renderOrder, frustumCulled: o.frustumCulled, children: o.children.map(child => node(child, depth + 1)).filter(Boolean) }
    if (o.isLineSegments2) value.wideLine = true
    if (o.isSprite) value.center = o.center.toArray()
    if (o.geometry) value.geometry = geometry(o.geometry)
    if (o.material) value.material = Array.isArray(o.material) ? o.material.map(material) : material(o.material)
    if (o.isInstancedMesh) {
      value.count = o.count; value.instanceMatrix = attribute(o.instanceMatrix)
      if (o.instanceColor) value.instanceColor = attribute(o.instanceColor)
    }
    if (o.isLight) {
      value.color = o.color.getHex(); value.intensity = o.intensity
      if (o.groundColor) value.groundColor = o.groundColor.getHex()
      if (o.isPointLight) { value.distance = o.distance; value.decay = o.decay }
    }
    return value
  }
  const root = node(scene)
  const sectioned = [...materials.values()].some(m => m.sectionCap || m.sectionPlanes.length)
  const packageData = { format: 'nadoc-prepared-scene', version: [...materials.values()].some(m => m.hullCutouts?.length) ? 6 : view?.overlay ? 5 : [...materials.values()].some(m => m.impostor) ? 4 : [...materials.values()].some(m => m.wideLine) ? 3 : sectioned ? 2 : 1, threeRevision: THREE.REVISION, units: 'nm',
    title: String(title).slice(0, 200), sourceHash, view, capabilities: ['static-visible-scene', 'orbit'],
    camera, navigation, background: scene.background?.isColor ? `#${scene.background.getHexString()}` : background,
    render: { localClippingEnabled: !!renderer?.localClippingEnabled, toneMapping: renderer?.toneMapping ?? THREE.NoToneMapping, toneMappingExposure: renderer?.toneMappingExposure ?? 1, outputColorSpace: renderer?.outputColorSpace ?? THREE.SRGBColorSpace, clearColor: renderer?.getClearColor(new THREE.Color()).getHex() ?? 0, clearAlpha: renderer?.getClearAlpha() ?? 0 },
    root, geometries: [...geometries.values()], materials: [...materials.values()], textures: Object.values(meta.textures), images: Object.values(meta.images) }
  validateScene(packageData)
  return encodeContainer(packageData)
}

/** Validate before creating GPU resources or giving image URLs to Three.js. */
export function validateScene(data) {
  if (data?.format !== 'nadoc-prepared-scene' || ![1, 2, 3, 4, 5, 6].includes(data.version) || data.threeRevision !== THREE.REVISION || data.units !== 'nm') fail('Unsupported viewer package version')
  validateSharedOverlay(data)
  validateViewTools(data.view?.viewTools)
  validateSharedVisualization(data.view?.visualization)
  if (data.sourceHash !== null && !/^[a-f0-9]{64}$/.test(data.sourceHash)) fail('Invalid source identity')
  if (typeof data.title !== 'string' || data.title.length > 200) fail('Invalid package title')
  const pose = data.camera
  if (pose?.near != null && (!Number.isFinite(pose.near) || pose.near <= 0 || !Number.isFinite(pose.far) || pose.far <= pose.near)) fail('Invalid clipping range')
  if (!pose || !['position', 'target', 'up'].every(key => finiteVector(pose[key], 3)) || !Number.isFinite(pose.fov) || pose.fov <= 0 || pose.fov >= 180 || !['orbit', 'trackball', 'multiscale'].includes(pose.orbitMode)) fail('Invalid package camera')
  if (!(data.navigation instanceof Float64Array) || data.navigation.length % 6 || data.navigation.length > 6_000_000 || !data.navigation.every(Number.isFinite)) fail('Invalid package navigation')
  if (!Number.isInteger(data.render?.clearColor) || data.render.clearColor < 0 || data.render.clearColor > 0xffffff || !Number.isFinite(data.render.clearAlpha) || data.render.clearAlpha < 0 || data.render.clearAlpha > 1) fail('Invalid clear color')
  if (typeof data.background !== 'string' || !/^#[0-9a-f]{6}$/i.test(data.background)) fail('Invalid package background')
  if (!data.render || ![THREE.NoToneMapping, THREE.LinearToneMapping, THREE.ReinhardToneMapping, THREE.CineonToneMapping, THREE.ACESFilmicToneMapping, THREE.AgXToneMapping, THREE.NeutralToneMapping].includes(data.render.toneMapping) || !Number.isFinite(data.render.toneMappingExposure) || ![THREE.SRGBColorSpace, THREE.LinearSRGBColorSpace].includes(data.render.outputColorSpace)) fail('Invalid package rendering settings')
  if (data.render.localClippingEnabled != null && typeof data.render.localClippingEnabled !== 'boolean') fail('Invalid clipping setting')
  const table = (rows, limit) => {
    if (!Array.isArray(rows) || rows.length > limit) fail('Package resource limit exceeded')
    const map = new Map()
    for (const row of rows) {
      if (typeof row.uuid !== 'string' || !/^[a-zA-Z0-9-]{1,64}$/.test(row.uuid) || map.has(row.uuid)) fail('Invalid resource identity')
      map.set(row.uuid, row)
    }
    return map
  }
  const geometries = table(data.geometries, 100_000), materials = table(data.materials, 100_000)
  const textures = table(data.textures, 4096), images = table(data.images, 4096)
  let attributeBytes = 0
  const attr = a => {
    if (!a || !ArrayBuffer.isView(a.array) || !Number.isInteger(a.itemSize) || a.itemSize < 1 || a.itemSize > 16 || a.array.length % a.itemSize || !Number.isInteger(a.meshPerAttribute) || a.meshPerAttribute < 1 || !a.array.every(Number.isFinite)) fail('Invalid geometry attribute')
    attributeBytes += a.array.byteLength
    if (attributeBytes > 512 * 1024 * 1024) fail('Geometry allocation budget exceeded')
  }
  for (const g of geometries.values()) {
    if (!g.attributes || !g.attributes.position || Object.keys(g.attributes).length > 32) fail('Invalid geometry attributes')
    for (const [name, a] of Object.entries(g.attributes)) { if (!/^[A-Za-z0-9_]+$/.test(name)) fail('Invalid attribute name'); attr(a) }
    if (g.wideLine) {
      const start = g.attributes.instanceStart, end = g.attributes.instanceEnd
      if (!start?.instanced || !end?.instanced || start.itemSize !== 3 || end.itemSize !== 3 || start.array.length !== end.array.length || !Number.isInteger(g.instanceCount) || g.instanceCount < 0 || g.instanceCount > start.array.length / 3) fail('Invalid wide-line geometry')
    }
    if (g.attributes.position.itemSize !== 3) fail('Invalid vertex positions')
    const vertices = g.attributes.position.array.length / 3
    if (g.index) { attr(g.index); if (!(g.index.array instanceof Uint16Array || g.index.array instanceof Uint32Array) || g.index.itemSize !== 1 || g.index.array.some(i => i >= vertices)) fail('Invalid geometry indices') }
    const count = g.index?.array.length ?? vertices
    if (!g.drawRange || !Number.isInteger(g.drawRange.start) || g.drawRange.start < 0 || (g.drawRange.count !== null && (!Number.isInteger(g.drawRange.count) || g.drawRange.count < 0))) fail('Invalid geometry draw range')
    if (!Array.isArray(g.groups) || g.groups.length > 100_000 || g.groups.some(x => !Number.isInteger(x.start) || x.start < 0 || !Number.isInteger(x.count) || x.count < 0 || x.start + x.count > count || !Number.isInteger(x.materialIndex) || x.materialIndex < 0)) fail('Invalid geometry groups')
  }
  for (const m of materials.values()) {
    validateWideLineMaterial(m)
    if (m.colors && Object.entries(m.colors).some(([k, v]) => !COLOR_KEYS.includes(k) || !finiteVector(v, 3))) fail('Invalid material colors')
    if (!MATERIALS.has(m.type) || m.vertexShader || m.fragmentShader || m.uniforms || m.clippingPlanes) fail('Unsupported package material')
    if (m.hullCutouts != null) { validateHullCutouts(m.hullCutouts); if (m.hullCutouts.length && data.version < 6) fail('Unsupported hull cutout version'); if (m.impostor || m.instanceAlpha || m.sectionCap || !['MeshPhongMaterial', 'MeshBasicMaterial', 'LineBasicMaterial'].includes(m.type)) fail('Unsupported hull cutout material') }
    if (m.impostor != null && (data.version < 4 || m.type !== 'MeshPhongMaterial' || !Number.isFinite(m.impostor.radius) || m.impostor.radius <= 0 || typeof m.impostor.instanceAlpha !== 'boolean' || m.instanceAlpha || m.sectionCap || m.wideLine)) fail('Invalid sphere impostor')
    if (m.sectionCap != null && typeof m.sectionCap !== 'boolean') fail('Invalid section cap')
    if (m.sectionPlanes && (!Array.isArray(m.sectionPlanes) || m.sectionPlanes.length > 16 || m.sectionPlanes.some(p => !finiteVector(p, 4) || Math.abs(Math.hypot(...p.slice(0, 3)) - 1) > .001))) fail('Invalid section planes')
    for (const [key, value] of Object.entries(m)) if ((key === 'map' || key.endsWith('Map')) && value != null && !textures.has(value)) fail('Missing material texture')
  }
  for (const t of textures.values()) if (!images.has(t.image)) fail('Missing texture image')
  let imagePixels = 0
  for (const image of images.values()) {
    // Only embedded PNGs: no URLs, SVG, external images, or executable shader content.
    if (typeof image.url !== 'string' || !/^data:image\/png;base64,[A-Za-z0-9+/]+=*$/.test(image.url)) fail('This package requires embedded PNG textures')
    const header = atob(image.url.split(',')[1].slice(0, 44))
    if (header.length < 24 || header.slice(1, 4) !== 'PNG') fail('Invalid PNG texture')
    const bytes = Uint8Array.from(header, c => c.charCodeAt(0)), view = new DataView(bytes.buffer)
    const w = view.getUint32(16), h = view.getUint32(20)
    imagePixels += w * h
    if (imagePixels > 16_777_216) fail('Texture allocation budget exceeded')
    if (!w || !h || w > 4096 || h > 4096 || w * h > 4_194_304) fail('Texture dimensions exceed package limits')
  }
  let nodes = 0, instances = 0
  const nodeKeys = new Set(['type', 'uuid', 'name', 'matrix', 'matrixAutoUpdate', 'layers', 'renderOrder', 'frustumCulled', 'children', 'geometry', 'material', 'count', 'instanceMatrix', 'instanceColor', 'color', 'intensity', 'groundColor', 'distance', 'decay', 'center', 'wideLine'])
  function node(o, depth) {
    if (++nodes > 200_000 || depth > 128 || !NODES.has(o?.type) || !finiteVector(o.matrix, 16)) fail('Invalid scene node')
    if (Object.keys(o).some(k => !nodeKeys.has(k)) || !Number.isFinite(o.renderOrder) || !Number.isInteger(o.layers)) fail('Unsupported scene properties')
    if (o.type.endsWith('Light') && (!Number.isInteger(o.color) || o.color < 0 || o.color > 0xffffff || !Number.isFinite(o.intensity) || o.intensity < 0)) fail('Invalid light')
    if (o.geometry && !geometries.has(o.geometry)) fail('Missing scene geometry')
    if (o.material && (Array.isArray(o.material) ? o.material : [o.material]).some(m => !materials.has(m))) fail('Missing scene material')
    if (['Mesh', 'InstancedMesh', 'Line', 'LineSegments', 'LineLoop', 'Points'].includes(o.type) && (!o.geometry || !o.material)) fail('Incomplete render object')
    if (o.type === 'Sprite' && (!o.material || !finiteVector(o.center, 2))) fail('Invalid sprite')
    if (o.wideLine && (o.type !== 'Mesh' || !geometries.get(o.geometry)?.wideLine || !materials.get(o.material)?.wideLine)) fail('Invalid wide-line object')
    if (o.type === 'InstancedMesh') {
      attr(o.instanceMatrix)
      if (!(o.instanceMatrix.array instanceof Float32Array) || o.instanceMatrix.itemSize !== 16 || !Number.isInteger(o.count) || o.count < 0 || o.count > o.instanceMatrix.array.length / 16) fail('Invalid instance matrix')
      if (o.instanceColor) { attr(o.instanceColor); if (o.instanceColor.itemSize !== 3 || o.instanceColor.array.length / 3 < o.count) fail('Invalid instance colors') }
      instances += o.instanceMatrix.array.length / 16
      if (instances > 5_000_000) fail('Too many package instances')
    }
    if (!Array.isArray(o.children)) fail('Invalid scene children')
    for (const child of o.children) node(child, depth + 1)
  }
  if (data.root?.type !== 'Scene') fail('Package root must be a scene')
  node(data.root, 0)
  validateSharedAnnotations(data.view?.annotations, data.root)
  validateSharedSelection(data.view?.selection, data.root)
  return data
}

export function disposePreparedScene(scene) {
  const resources = new Set()
  scene.traverse(o => {
    if (o.geometry) resources.add(o.geometry)
    for (const m of o.material ? (Array.isArray(o.material) ? o.material : [o.material]) : []) {
      resources.add(m)
      for (const value of Object.values(m)) if (value?.isTexture) resources.add(value)
    }
    if (o.isInstancedMesh) o.dispose()
  })
  for (const resource of resources) resource.dispose()
  scene.clear()
}

export async function loadPreparedScene(buffer) {
  const data = validateScene(decodeContainer(buffer))
  const digest = globalThis.crypto?.subtle ? await crypto.subtle.digest('SHA-256', buffer) : null
  const packageHash = digest ? [...new Uint8Array(digest)].map(v => v.toString(16).padStart(2, '0')).join('') : null
  const loader = new THREE.ObjectLoader(), geometries = {}, materials = {}
  // ObjectLoader awaits images serially. Rendering a large previous scene can
  // delay every image callback; decode bounded batches while that scene stays usable.
  const images = {}
  for (let i = 0; i < data.images.length; i += 16) {
    const batch = await Promise.all(data.images.slice(i, i + 16).map(image => loader.parseImagesAsync([image])))
    for (const decoded of batch) Object.assign(images, decoded)
  }
  const textures = loader.parseTextures(data.textures, images)
  try {
    const materialLoader = new THREE.MaterialLoader().setTextures(textures)
    for (const m of data.materials) {
      materials[m.uuid] = m.wideLine ? loadWideLineMaterial(m) : materialLoader.parse(m)
      for (const [k, color] of Object.entries(m.colors ?? {})) {
        if (!materials[m.uuid][k]?.isColor) fail('Material color is not supported for this type')
        materials[m.uuid][k].fromArray(color)
      }
      if (m.impostor) {
        const material = makeImpostorPhongMaterial({ radius: m.impostor.radius })
        material.copy(materials[m.uuid])
        materials[m.uuid].dispose()
        materials[m.uuid] = material
        if (m.impostor.instanceAlpha) enableImpostorInstanceAlpha(material)
      }
      if (m.hullCutouts) applyHullCutouts(materials[m.uuid], m.hullCutouts)
      if (m.instanceAlpha) applyInstanceAlphaMaterial(materials[m.uuid])
      if (m.sectionCap) materials[m.uuid].onBeforeCompile = sectionCapShader
      materials[m.uuid].clippingPlanes = (m.sectionPlanes ?? []).map(p => new THREE.Plane(new THREE.Vector3(...p.slice(0, 3)), p[3]))
      materials[m.uuid].clipIntersection = !!m.clipIntersection
      materials[m.uuid].clipShadows = !!m.clipShadows
    }
    const attribute = a => {
      const result = a.instanced ? new THREE.InstancedBufferAttribute(a.array, a.itemSize, a.normalized, a.meshPerAttribute) : new THREE.BufferAttribute(a.array, a.itemSize, a.normalized)
      return result
    }
    for (const spec of data.geometries) {
      const geometry = spec.wideLine ? new LineSegmentsGeometry() : new THREE.BufferGeometry();
      if (spec.wideLine) geometry.instanceCount = spec.instanceCount; geometries[spec.uuid] = geometry
      for (const [name, a] of Object.entries(spec.attributes)) geometry.setAttribute(name, attribute(a))
      if (spec.index) geometry.setIndex(attribute(spec.index))
      for (const group of spec.groups) geometry.addGroup(group.start, group.count, group.materialIndex)
      geometry.setDrawRange(spec.drawRange.start, spec.drawRange.count ?? Infinity)
    }
    let scene = loader.parseObject(data.root, geometries, materials, textures, {})
    // ObjectLoader does not persist this flag in r172.
    const restore = (o, spec) => {
      if (spec.wideLine) o = restoreWideLine(o)
      o.frustumCulled = spec.frustumCulled

      if ((Array.isArray(o.material) ? o.material : [o.material]).some(m => m?.onBeforeCompile === sectionCapShader)) {
        o.onAfterRender = renderer => renderer.clearStencil()
        o.raycast = () => {} // The stencil plane is not a molecular surface to center on.
      }
      if (o.isInstancedMesh) {
        const impostor = preparedImpostorSpec(o.material)
        if (impostor) installSphereImpostorRaycast(o, impostor.radius)
        o.instanceMatrix = attribute(spec.instanceMatrix)
        if (spec.instanceColor) o.instanceColor = attribute(spec.instanceColor)
      }
      o.children = o.children.map((child, i) => { const next = restore(child, spec.children[i]); next.parent = o; return next })
      return o
    }
    loader.bindLightTargets(scene)
    scene = restore(scene, data.root)
    scene.traverse(o => { o.matrixAutoUpdate = false })
    scene.updateMatrixWorld(true)
    return { scene, data, packageHash, dispose: () => disposePreparedScene(scene) }
  } catch (error) {
    for (const resource of [...Object.values(geometries), ...Object.values(materials), ...Object.values(textures)]) resource.dispose()
    throw error
  }
}
