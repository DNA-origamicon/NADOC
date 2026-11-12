import { Material } from 'three'

/** Temporary shader multiplier; authored opacity and representation cross-fades remain untouched. */
export function createAuthoringDisplay({ getRoot, getRoots = () => [getRoot?.()], addFrameCallback, removeFrameCallback, opacity = 0.15 }) {
  const owners = new Set(), materials = new Map()
  function restore(material, { saved, uniform, compile, cacheKey, beforeCompile, beforeKey }) {
    uniform.value = 1
    if (material.onBeforeCompile === compile) material.onBeforeCompile = beforeCompile
    if (material.customProgramCacheKey === cacheKey) material.customProgramCacheKey = beforeKey
    for (const [key, state] of Object.entries(saved)) {
      if (state.descriptor) Object.defineProperty(material, key, { ...state.descriptor, value: state.value })
      else { delete material[key]; if (state.value !== state.original) material[key] = state.value }
    }
    material.needsUpdate = true
  }
  function refresh() {
    const current = new Set()
    for (const root of getRoots()) root?.traverse(object => {
      for (const material of (Array.isArray(object.material) ? object.material : [object.material])) {
        if (!material) continue
        current.add(material)
        if (materials.has(material)) continue
        const saved = {}, uniform = { value: opacity }
        const beforeCompile = material.onBeforeCompile, beforeKey = material.customProgramCacheKey
        const compile = function(shader, renderer) {
          beforeCompile.call(this, shader, renderer)
          shader.uniforms.nadocAuthoringOpacity = uniform
          if (!shader.fragmentShader.includes('uniform float nadocAuthoringOpacity;')) shader.fragmentShader = 'uniform float nadocAuthoringOpacity;\n' + shader.fragmentShader.replace(
            '#include <opaque_fragment>', 'diffuseColor.a *= nadocAuthoringOpacity;\n#include <opaque_fragment>')
        }
        const cacheKey = function() {
          const base = beforeKey
          const key = base === Material.prototype.customProgramCacheKey
            ? beforeCompile.toString() : base.call(this)
          return key + '|nadoc-authoring-opacity'
        }
        for (const key of ['transparent', 'depthWrite']) {
          const descriptor = Object.getOwnPropertyDescriptor(material, key)
          saved[key] = { descriptor, value: material[key], original: material[key] }
          Object.defineProperty(material, key, {
            configurable: true, enumerable: descriptor?.enumerable ?? false,
            get: () => key === 'transparent',
            set: value => { saved[key].value = value },
          })
        }
        material.onBeforeCompile = compile; material.customProgramCacheKey = cacheKey
        materials.set(material, { saved, uniform, compile, cacheKey, beforeCompile, beforeKey })
        material.needsUpdate = true
      }
    })
    for (const [material, saved] of materials) if (!current.has(material)) {
      restore(material, saved); materials.delete(material)
    }
  }
  return function begin() {
    const owner = {}; owners.add(owner)
    if (owners.size === 1) { refresh(); addFrameCallback(refresh) }
    return () => {
      if (!owners.delete(owner) || owners.size) return
      removeFrameCallback(refresh)
      for (const [material, saved] of materials) restore(material, saved)
      materials.clear()
    }
  }
}
