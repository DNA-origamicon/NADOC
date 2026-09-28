/** Exact positions with bounded GPU work: one point per nucleotide or line per axis
 * segment/joint. Scalar recoloring changes shader uniforms, never geometry. */
import * as THREE from 'three'
import { colormapRGB } from '../ui/colormaps.js'

export const LARGE_CANDO_THRESHOLD = 50000
export const MAX_CANDO_VIEW_BYTES = 256 * 1024 * 1024

export function decodeCandoView(buffer) {
  if (!buffer || buffer.byteLength < 12 || buffer.byteLength > MAX_CANDO_VIEW_BYTES) throw new Error('Invalid CanDo visualization size')
  const dv = new DataView(buffer)
  if (dv.getUint32(0, true) !== 0x5A495643 || dv.getUint32(4, true) !== 1) throw new Error('Unsupported CanDo visualization')
  const length = dv.getUint32(8, true)
  if (length > 1024 * 1024 || 12 + length > buffer.byteLength) throw new Error('Invalid CanDo visualization header')
  const meta = JSON.parse(new TextDecoder().decode(new Uint8Array(buffer, 12, length)))
  const offset = Math.ceil((12 + length) / 4) * 4
  const n = meta.count
  if (meta.kind === 'cando' && n % 2) throw new Error('Incomplete CanDo line endpoints')
  if (!Number.isSafeInteger(n) || n <= 0 || offset + n * (meta.identities ? 32 : 16) !== buffer.byteLength) throw new Error('Incomplete CanDo visualization')
  return { meta, positions: new Float32Array(buffer, offset, 3 * n),
    scalars: new Float32Array(buffer, offset + 12 * n, n),
    identities: meta.identities ? new Int32Array(buffer, offset + 16 * n, 4 * n) : null }
}

/** Progressive ordering spreads each draw prefix across the entire tile. Lines
 * are indivisible endpoint pairs, so changing detail cannot invent connectors. */
export function progressiveIndices(count, lines = false) {
  if (!Number.isInteger(count) || count < 0 || count > 65536 || (lines && count % 2)) throw new Error('Invalid visualization tile')
  const unit = lines ? 2 : 1, groups = Math.floor(count / unit)
  const bits = Math.ceil(Math.log2(Math.max(1, groups)))
  const out = new Uint16Array(count)
  let at = 0
  const put = i => { for (let j = 0; j < unit; j++) out[at++] = i * unit + j }
  if (groups) put(0)
  if (groups > 1) put(groups - 1)
  for (let i = 0; i < 2 ** bits; i++) {
    let x = i, reversed = 0
    for (let b = 0; b < bits; b++) { reversed = (reversed << 1) | (x & 1); x >>= 1 }
    if (reversed > 0 && reversed < groups - 1) put(reversed)
  }
  return out
}

export function projectedDrawCount(radiusPixels, count, lines = false) {
  const unit = lines ? 2 : 1
  return Math.min(count, unit * Math.max(32, Math.ceil(radiusPixels * radiusPixels * 2)))
}

export function initCandoLargeView(scene, name = 'cando-large-result') {
  let object = null, data = null, texture = null, material = null, boundsBox = null
  let bounds = null, cmap = 'jet'
  function clear() {
    if (object) { scene.remove(object); for (const tile of object.children) tile.geometry.dispose() }
    material?.dispose()
    texture?.dispose()
    object = null; data = null; texture = null; material = null; bounds = null; boundsBox = null
  }
  function recolor(lo, hi, colormap = cmap) {
    if (!object) return
    bounds = { lo, hi }; cmap = colormap
    const colors = texture.image.data
    for (let i = 0; i < 256; i++) {
      const rgb = colormapRGB(cmap, i / 255)
      for (let j = 0; j < 3; j++) colors[4 * i + j] = Math.round(rgb[j] * 255)
      colors[4 * i + 3] = 255
    }
    texture.needsUpdate = true
    material.uniforms.low.value = lo
    material.uniforms.span.value = Math.max(hi - lo, 1e-9)
  }
  function update(next, colormap = 'jet') {
    clear(); data = next
    texture = new THREE.DataTexture(new Uint8Array(256 * 4), 256, 1)
    texture.minFilter = texture.magFilter = THREE.LinearFilter
    const lines = data.meta.kind === 'cando'
    material = new THREE.ShaderMaterial({
      uniforms: { ramp: { value: texture }, low: { value: 0 }, span: { value: 1 },
        colored: { value: data.meta.kind !== 'deform' }, points: { value: !lines } },
      vertexShader: `attribute float scalar;
        varying float value;
        #include <common>
        #include <logdepthbuf_pars_vertex>
        void main() {
          value = scalar;
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
          gl_PointSize = 3.0;
          #include <logdepthbuf_vertex>
        }`,
      fragmentShader: `uniform sampler2D ramp;
        uniform float low, span;
        uniform bool colored, points;
        varying float value;
        #include <common>
        #include <logdepthbuf_pars_fragment>
        void main() {
          if (points && distance(gl_PointCoord, vec2(0.5)) > 0.5) discard;
          vec3 color = vec3(0.58, 0.68, 0.78);
          if (colored && value >= 0.0) color = texture2D(ramp, vec2(clamp((value-low)/span,0.0,1.0),0.5)).rgb;
          gl_FragColor = vec4(color,1.0);
          #include <logdepthbuf_fragment>
        }`,
    })
    object = new THREE.Group()
    object.name = name
    object.userData.count = data.meta.count
    boundsBox = new THREE.Box3()
    const center = new THREE.Vector3()
    for (let start = 0; start < data.meta.count; start += 4096) {
      const count = Math.min(4096, data.meta.count - start)
      const geometry = new THREE.BufferGeometry()
      geometry.setAttribute('position', new THREE.BufferAttribute(data.positions.subarray(3*start, 3*(start+count)), 3))
      geometry.setAttribute('scalar', new THREE.BufferAttribute(data.scalars.subarray(start, start+count), 1))
      geometry.setIndex(new THREE.BufferAttribute(progressiveIndices(count, lines), 1))
      geometry.computeBoundingBox(); geometry.computeBoundingSphere()
      boundsBox.union(geometry.boundingBox)
      const tile = lines ? new THREE.LineSegments(geometry, material) : new THREE.Points(geometry, material)
      tile.onBeforeRender = (renderer, _scene, camera) => {
        const sphere = geometry.boundingSphere
        center.copy(sphere.center).applyMatrix4(tile.matrixWorld)
        const radius = sphere.radius * tile.matrixWorld.getMaxScaleOnAxis()
        const height = renderer.domElement.height
        const pixels = camera.isPerspectiveCamera
          ? radius * height / (2 * Math.tan(camera.fov * Math.PI / 360) * Math.max(camera.near, camera.position.distanceTo(center) - radius))
          : radius * height * camera.zoom / Math.max(1e-9, camera.top - camera.bottom)
        geometry.setDrawRange(0, projectedDrawCount(pixels, count, lines))
      }
      object.add(tile)
    }
    recolor(data.meta.min, data.meta.max, colormap)
    scene.add(object)
  }
  function updatePositions(next) {
    if (!object || next.meta.count !== data.meta.count || next.meta.kind !== data.meta.kind) {
      update(next); return
    }
    data.positions.set(next.positions)
    boundsBox.makeEmpty()
    for (const tile of object.children) {
      tile.geometry.attributes.position.needsUpdate = true
      tile.geometry.computeBoundingBox(); tile.geometry.computeBoundingSphere()
      boundsBox.union(tile.geometry.boundingBox)
    }
  }
  function coloringInfo() {
    if (!data?.identities || !['flex', 'deviation'].includes(data.meta.kind)) return null
    const { meta, identities, scalars } = data
    const values = []
    for (let i = 0; i < scalars.length; i++) {
      if (scalars[i] < 0) continue
      values.push({ helix_id: meta.helix_ids[identities[4*i]], bp_index: identities[4*i+1],
        direction: identities[4*i+2] ? 'REVERSE' : 'FORWARD', copy: identities[4*i+3], value: scalars[i] })
    }
    const flex = meta.kind === 'flex'
    return { attribute: flex ? 'rmsf' : 'deviation', title: flex ? 'RMSF' : 'Deviation', unit: 'nm',
      colormap: cmap, ...bounds, values }
  }
  return { update, updatePositions, recolor, clear, coloringInfo, active: () => !!object,
    getBoundingBox: () => boundsBox }
}
