import * as THREE from 'three'

/** RGB display power, not optical radiance. The scale matches the existing
 * raster illumination convention; cell subdivision preserves total power. */
export function emSamplePowers(weights,colors,radius){
  const total=weights.reduce((sum,w)=>sum+w,0),power=new Float32Array(colors.length)
  if(total>0)for(let i=0;i<weights.length;i++)for(let k=0;k<3;k++)
    power[i*3+k]=.3*radius*radius*weights[i]/total*colors[i*3+k]
  return power
}

/** Illustrative lighting only. Integrate cell volumes so refinement adds no energy. */
export function emLightAccumulator(center, radius) {
  const buckets = Array.from({length:8}, () => ({weight:0, position:[0,0,0], color:[0,0,0]}))
  return {
    add(position, color, intensity, volume) {
      const weight = Math.max(0, Math.log10(Math.max(1,intensity))) * volume
      const key = position.reduce((n,v,i) => n | ((v >= center[i] ? 1 : 0) << i),0)
      const bucket = buckets[key]
      bucket.weight += weight
      for (let i=0;i<3;i++) {
        bucket.position[i] += position[i]*weight
        bucket.color[i] += color[i]*weight
      }
    },
    finish() {
      const total = buckets.reduce((sum,b) => sum+b.weight,0)
      return buckets.map(b => ({
        position:b.weight ? b.position.map(v=>v/b.weight) : center,
        color:b.weight ? b.color.map(v=>v/b.weight) : [0,0,0],
        intensity:total ? .3*radius*radius*b.weight/total : 0,
        distance:radius*2,
      }))
    },
  }
}

/** One draw call per cloud; each sample has a soft emissive halo, without a light per dot. */
export function setEMGlow(material, enabled) {
  if (material.userData.emGlow === enabled) return
  material.userData.emGlow = enabled
  material.onBeforeCompile = shader => {
    if (!enabled) return
    shader.fragmentShader = shader.fragmentShader.replace('#include <opaque_fragment>', `
      float radius = length(gl_PointCoord - vec2(0.5)) * 2.0;
      if (radius > 1.0) discard;
      diffuseColor.a *= exp(-4.0 * radius * radius) * (1.0 - smoothstep(0.8, 1.0, radius));
      #include <opaque_fragment>`)
  }
  material.customProgramCacheKey = () => `em-glow-${enabled}`
  // Alpha compositing preserves the intensity palette on white publication backgrounds.
  material.blending = THREE.NormalBlending
  material.needsUpdate = true
}

export function updateEMLights(root, emitters, enabled) {
  let group = root.children.find(o=>o.name==='em-illumination')
  if (!group) {
    group = new THREE.Group(); group.name = 'em-illumination'; root.add(group)
    for (let i=0;i<8;i++) {
      const light = new THREE.PointLight(0xffffff,0)
      light.userData.emLight = true; light.castShadow = false
      group.add(light)
    }
  }
  group.visible = enabled
  group.children.forEach((light,i) => {
    const source = emitters[i]
    light.position.fromArray(source.position); light.color.fromArray(source.color)
    light.distance = source.distance
    light.userData.emIntensity = enabled ? source.intensity : 0
    light.intensity = light.userData.emIntensity
  })
}
