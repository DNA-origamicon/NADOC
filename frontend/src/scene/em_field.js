import {volumeGrid} from './em_volume_data.js'
import {createEMVolume,updateVolumeColors} from './em_volume.js'
/** Derived optical volume only; never changes molecular geometry or materials. */
import * as THREE from 'three'
import {emColorRGB} from './em_colors.js'

import { emLightAccumulator, emSamplePowers, setEMGlow, updateEMLights } from './em_lighting.js'

export function fieldSamples(result, { mode = 'volume', slice = 0.5, minimum = 1, maximum = 100, colorMinimum = .1, colormap = 'jet' } = {}) {
  const adaptive = result.sampling?.layout === 'octree'
  const [, ny, nz] = result.shape
  const positions = [], colors = [], weights = []
  const localCenter = result.upper_nm.map((v,i)=>(v+result.lower_nm[i])/2)
  const center = result.origin_nm.map((v,a)=>v+localCenter.reduce((sum,x,b)=>sum+x*result.basis[b][a],0))
  const lights = emLightAccumulator(center, Math.max(...result.upper_nm.map((v,i)=>v-result.lower_nm[i]))/2)
  const sliceAxis = { yz: 0, xz: 1, xy: 2 }[mode]
  const sliceIndex = sliceAxis === undefined ? null : Math.round(slice * (result.shape[sliceAxis] - 1))
  const plane = sliceAxis === undefined ? null : result.lower_nm[sliceAxis] + slice * (result.upper_nm[sliceAxis] - result.lower_nm[sliceAxis])
  for (let index = 0; index < result.intensity.length; index++) {
    const value = result.intensity[index]
    if (!result.outside[index] || !Number.isFinite(value) || ((mode === 'volume' || mode === 'smooth') && value < minimum)) continue
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
    const rgb=emColorRGB(value,{maximum,colorMinimum,colormap})
    colors.push(...rgb)
    const cell = adaptive ? (ArrayBuffer.isView(result.cell_sizes_nm)
      ? result.cell_sizes_nm.subarray(index*3,index*3+3) : result.cell_sizes_nm[index])
      : result.upper_nm.map((v,i)=>(v-result.lower_nm[i])/Math.max(1,result.shape[i]-1))
    weights.push(Math.max(0, Math.log10(Math.max(1,value)))*cell.reduce((v,n)=>v*n,1))
    lights.add(positions.slice(-3), rgb, value, cell.reduce((v,n)=>v*n,1))
  }
  return { positions: new Float32Array(positions), colors: new Float32Array(colors),
    powers:emSamplePowers(weights,colors,Math.max(...result.upper_nm.map((v,i)=>v-result.lower_nm[i]))/2), emitters:lights.finish() }
}

const prepared = new WeakMap()
/** Prepare display arrays ahead of playback. Only one display variant per volume. */
export function prepareEMField(result, options) {
  const key = JSON.stringify([options.mode, options.slice, options.minimum, options.maximum, options.colorMinimum, options.colormap])
  if (prepared.get(result)?.key !== key) prepared.set(result, {key, ...fieldSamples(result, options)})
  return prepared.get(result)
}

export function createEMFieldOverlay(scene) {
  const root = new THREE.Group()
  root.name = 'experimental-em-field'
  root.userData.emField = true
  scene.add(root)
  let displayed=null,layoutKey=null
  let secondary = null, transition = null, baseOpacity = .24
  function weight(value) {
    for (const child of root.children) {
      if (child.name === 'experimental-em-field') continue
      child.traverse(object => {
        if (object.userData.emLight) object.intensity = object.userData.emIntensity*value
        if (object.material) { object.material.transparent = true; object.material.opacity = value*(object.userData.emOpacity ?? (child.isPoints ? baseOpacity : 1)) }
      })
    }
  }
  const notify=()=>scene.dispatchEvent?.({type:'em-field-visibility'})
  function clear() {
    displayed=null;layoutKey=null
    secondary?.dispose(); secondary = null; transition = null; delete root.userData.interpolation
    root.traverse(object => { object.geometry?.dispose(); object.material?.dispose() })
    root.clear(); notify()
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

      const nextLayout=JSON.stringify([options.mode,options.minimum,options.lighting])
      if(options.mode==='smooth'&&displayed===result&&layoutKey===nextLayout){
        const {emitters}=prepareEMField(result,options)
        for(const mesh of root.children.filter(o=>o.userData.emSmooth)){
          updateVolumeColors(mesh,options)
        }
        updateEMLights(root,emitters,options.lighting==='illuminate');weight(1);notify();return
      }
      if (options.mode === 'smooth' || root.children.some(o=>o.userData.emSmooth)) clear()
      const { positions, colors, powers, emitters } = prepareEMField(result, options)
      if (options.mode === 'smooth') {
        for (const mesh of createEMVolume(result,volumeGrid(result),options)) root.add(mesh)
        updateEMLights(root,emitters,options.lighting === 'illuminate')
        displayed=result;layoutKey=nextLayout
        root.userData.sampleCount = positions.length / 3
        root.visible = true; notify()
        return
      }
      let points = root.children.find(object => object.isPoints)
      if (!points) {
        points = new THREE.Points(new THREE.BufferGeometry(), new THREE.PointsMaterial({
          sizeAttenuation:false, vertexColors:true, transparent:true, depthWrite:false, toneMapped:false,
        }))
        points.raycast = () => {}; root.add(points)
        points.userData.emSamples = true
      }
      const geometry = points.geometry
      for (const [name, values] of [['position',positions], ['color',colors], ['emPower',powers]]) {
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
      setEMGlow(points.material, (options.lighting ?? 'glow') !== 'off')
      baseOpacity = options.mode === 'volume' ? .24 : .85
      points.material.opacity = baseOpacity
      updateEMLights(root, emitters, options.lighting === 'illuminate')
      weight(1)
      root.userData.sampleCount = positions.length / 3
      root.visible = true; notify()
    },
    clear,
    dispose() { clear(); scene.remove(root) },
  }
  return api
}
