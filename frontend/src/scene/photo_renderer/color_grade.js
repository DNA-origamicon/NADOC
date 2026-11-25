import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js'

export const GRADE_DEFAULTS = Object.freeze({ exposure: 1, contrast: 1, saturation: 1 })
export function normalizeGrade(input = {}) {
  const value = (key, min, max) => Number.isFinite(input[key])
    ? Math.max(min, Math.min(max, input[key])) : GRADE_DEFAULTS[key]
  return { exposure: value('exposure', .1, 4), contrast: value('contrast', .5, 1.5), saturation: value('saturation', 0, 2) }
}
/** Display-space grade after tone mapping. Pointwise: identical across tile boundaries.
 * Alpha and annotation colors remain untouched; neutral values are an identity.
 */
export function createColorGradePass() {
  const pass = new ShaderPass({
    uniforms: { tDiffuse: { value: null }, contrast: { value: 1 }, saturation: { value: 1 } },
    vertexShader: 'varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
    fragmentShader: `uniform sampler2D tDiffuse; uniform float contrast; uniform float saturation;
      varying vec2 vUv;
      void main() {
        vec4 pixel = texture2D(tDiffuse, vUv);
        float luminance = dot(pixel.rgb, vec3(0.2126, 0.7152, 0.0722));
        vec3 color = mix(vec3(luminance), pixel.rgb, saturation);
        gl_FragColor = vec4(clamp((color - 0.5) * contrast + 0.5, 0.0, 1.0), pixel.a);
      }`,
  })
  pass.setParams = settings => {
    const grade = normalizeGrade(settings)
    pass.uniforms.contrast.value = grade.contrast
    pass.uniforms.saturation.value = grade.saturation
    pass.enabled = grade.contrast !== 1 || grade.saturation !== 1
  }
  return pass
}

export function initColorGrade({ settings, renderer, isActive }) {
  const passes = new Set()
  return {
    set(input) {
      Object.assign(settings, normalizeGrade({ ...settings, ...input }))
      if (isActive()) renderer.toneMappingExposure = settings.exposure
      for (const pass of passes) pass.setParams(settings)
    },
    create() {
      const pass = createColorGradePass()
      pass.setParams(settings)
      passes.add(pass)
      const dispose = pass.dispose.bind(pass)
      pass.dispose = () => { passes.delete(pass); dispose() }
      return pass
    },
  }
}
