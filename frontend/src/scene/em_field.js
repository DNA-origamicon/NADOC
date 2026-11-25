/** Derived optical volume only; never changes molecular geometry or materials. */
import * as THREE from 'three'

export function fieldSamples(result, { mode = 'volume', slice = 0.5, minimum = 1, maximum = 100 } = {}) {
  const adaptive = result.sampling?.layout === 'octree'
  const [, ny, nz] = result.shape
  const positions = [], colors = []
  const color = new THREE.Color()
  const sliceAxis = { yz: 0, xz: 1, xy: 2 }[mode]
  const sliceIndex = sliceAxis === undefined ? null : Math.round(slice * (result.shape[sliceAxis] - 1))
  const plane = sliceAxis === undefined ? null : result.lower_nm[sliceAxis] + slice * (result.upper_nm[sliceAxis] - result.lower_nm[sliceAxis])
  const lowLog = -1, highLog = Math.log10(Math.max(1.01, maximum))
  for (let index = 0; index < result.intensity.length; index++) {
    const value = result.intensity[index]
    if (!result.outside[index] || !Number.isFinite(value) || (mode === 'volume' && value < minimum)) continue
    let local
    if (adaptive) {
      local = ArrayBuffer.isView(result.sample_positions_nm)
        ? result.sample_positions_nm.subarray(index*3,index*3+3) : result.sample_positions_nm[index]
      if (sliceAxis !== undefined) {
        const half = (ArrayBuffer.isView(result.cell_sizes_nm)
          ? result.cell_sizes_nm[index*3+sliceAxis] : result.cell_sizes_nm[index][sliceAxis]) / 2
        const lo = local[sliceAxis] - half, hi = local[sliceAxis] + half
        // Half-open intervals avoid showing both cells at a shared face.
        if (plane < lo || plane >= hi && !(slice === 1 && plane === hi)) continue
      }
    } else {
      const ijk = [Math.floor(index / (ny * nz)), Math.floor(index / nz) % ny, index % nz]
      if (sliceAxis !== undefined && ijk[sliceAxis] !== sliceIndex) continue
      local = ijk.map((n, a) => result.lower_nm[a] + n / (result.shape[a] - 1) * (result.upper_nm[a] - result.lower_nm[a]))
    }
    for (let a = 0; a < 3; a++) positions.push(result.origin_nm[a] + local.reduce((v, x, b) => v + x * result.basis[b][a], 0))
    const fraction = Math.max(0, Math.min(1, (Math.log10(Math.max(value, 1e-10)) - lowLog) / (highLog - lowLog)))
    color.setHSL((1 - fraction) * 0.67, 1, 0.5)
    colors.push(color.r, color.g, color.b)
  }
  return { positions: new Float32Array(positions), colors: new Float32Array(colors) }
}

const prepared = new WeakMap()
/** Prepare display arrays ahead of playback. Only one display variant per volume. */
export function prepareEMField(result, options) {
  const key = JSON.stringify([options.mode, options.slice, options.minimum, options.maximum])
  if (prepared.get(result)?.key !== key) prepared.set(result, {key, ...fieldSamples(result, options)})
  return prepared.get(result)
}

export function createEMFieldOverlay(scene) {
  const root = new THREE.Group()
  root.name = 'experimental-em-field'
  scene.add(root)
  let secondary = null, transition = null, baseOpacity = .24
  function weight(value) {
    for (const child of root.children) {
      if (child.name === 'experimental-em-field') continue
      child.traverse(object => {
        if (object.material) { object.material.transparent = true; object.material.opacity = value*(child.isPoints ? baseOpacity : 1) }
      })
    }
  }
  function clear() {
    secondary?.dispose(); secondary = null; transition = null; delete root.userData.interpolation
    root.traverse(object => { object.geometry?.dispose(); object.material?.dispose() })
    root.clear()
  }
  const api = {
    weight,
    showTransition(a,b,t,options) {
      if (t <= 0) { api.show(a,options); return }
      if (t >= 1) { api.show(b,options); return }
      const key = JSON.stringify(options)
      if (transition?.a !== a || transition?.b !== b || transition?.key !== key) {
        api.show(a,options)
        secondary ??= createEMFieldOverlay(root)
        secondary.show(b,options)
        transition = {a,b,key}
      }
      weight(1-t); secondary.weight(t)
      root.userData.interpolation = t
    },
    show(result, options) {
      transition = null; delete root.userData.interpolation
      secondary?.clear()

      const { positions, colors } = prepareEMField(result, options)
      let points = root.children.find(object => object.isPoints)
      if (!points) {
        points = new THREE.Points(new THREE.BufferGeometry(), new THREE.PointsMaterial({
          sizeAttenuation:false, vertexColors:true, transparent:true, depthWrite:false, toneMapped:false,
        }))
        points.raycast = () => {}; root.add(points)
      }
      const geometry = points.geometry
      for (const [name, values] of [['position',positions], ['color',colors]]) {
        const attribute = geometry.getAttribute(name)
        if (attribute?.array.length === values.length) { attribute.array.set(values); attribute.needsUpdate = true }
        else {
          // Release old GPU buffers before replacing differently sized attributes.
          geometry.dispose()
          geometry.setAttribute(name, new THREE.BufferAttribute(values.slice(),3))
        }
      }
      geometry.boundingSphere = null
      points.material.size = options.dotSize ?? (options.mode === 'volume' ? 3 : 5)
      baseOpacity = options.mode === 'volume' ? .24 : .85
      points.material.opacity = baseOpacity
      const origin = new THREE.Vector3(...result.origin_nm)
      const length = Math.max(...result.upper_nm.map((v, i) => v - result.lower_nm[i])) * .35
      const directions = [result.polarization_world, result.propagation_world]
      directions.forEach((direction, i) => {
        let arrow = root.children[i+1]
        if (!arrow) {
          arrow = new THREE.ArrowHelper(new THREE.Vector3(...direction), origin, length, [0xff75e6,0x66ffff][i])
          arrow.traverse(o => { o.raycast = () => {} }); root.add(arrow)
        }
        arrow.position.copy(origin); arrow.setDirection(new THREE.Vector3(...direction))
        arrow.setLength(length, length*.12, length*.06)
      })
      weight(1)
      root.userData.sampleCount = positions.length / 3
      root.visible = true
    },
    clear,
    dispose() { clear(); scene.remove(root) },
  }
  return api
}
