import * as THREE from 'three'
import { GPUComputationRenderer } from 'three/addons/misc/GPUComputationRenderer.js'
import { initialPegState, pivotStep, KB, ELEMENTARY_FORCE } from './peg_model.js'

export function pegComputeShader(segments) {
  return `
out vec4 pegOutput;
uniform uint sweep;
uniform uint seed;
uniform float fieldEnergy;
uniform float screening;
uniform bool wall;
uint state;
float randomValue() {
  state += 0x9e3779b9u;
  uint x = state;
  x = (x ^ (x >> 16u)) * 0x21f0aaadu;
  x = (x ^ (x >> 15u)) * 0x735a2d97u;
  x ^= x >> 15u;
  return float(x >> 8u) / 16777216.0;
}
vec3 readBead(int j) {
  return texelFetch(texturePosition, ivec2(j, int(gl_FragCoord.y)), 0).xyz;
}
float energy(float z) {
  return screening > 0.0 ? fieldEnergy * screening * exp(-z / screening) : -fieldEnergy * z;
}
vec3 rotateTail(vec3 pos, vec3 pivot, vec3 axis, float cosine, float sine) {
  vec3 v = pos - pivot;
  return pivot + v * cosine + cross(axis, v) * sine + axis * dot(axis, v) * (1.0 - cosine);
}
void main() {
  state = seed + sweep * 747796405u + uint(gl_FragCoord.y) * 2891336453u;
  int joint = int(floor(randomValue() * float(${segments})));
  float az = 2.0 * randomValue() - 1.0;
  float phi = 6.28318530718 * randomValue();
  float angle = (2.0 * randomValue() - 1.0) * 3.14159265359;
  float acceptance = randomValue();
  float radius = sqrt(1.0 - az * az);
  vec3 axis = vec3(radius * cos(phi), radius * sin(phi), az);
  float cosine = cos(angle), sine = sin(angle);
  vec3 pivot = readBead(joint);
  bool valid = true;
  if (wall) for (int j = 1; j <= ${segments}; j++) {
    if (j > joint && rotateTail(readBead(j), pivot, axis, cosine, sine).z < 0.0) valid = false;
  }
  vec3 end = readBead(${segments});
  vec3 nextEnd = rotateTail(end, pivot, axis, cosine, sine);
  bool accept = valid && log(max(acceptance, 1e-30)) < min(0.0, energy(end.z) - energy(nextEnd.z));
  int index = int(gl_FragCoord.x);
  vec3 position = readBead(index);
  if (accept && index > joint) position = rotateTail(position, pivot, axis, cosine, sine);
  pegOutput = vec4(position, 1.0);
}`
}

/** Actual GPU Metropolis updates in floating-point ping-pong render targets.
 * CPU fallback uses the same proposal and energy; GPU rendering alone is not
 * described as GPU simulation. Caller owns the WebGL renderer.
 */
export function createPegSampler(renderer, p, { forceCPU = false } = {}) {
  const data = initialPegState(p)
  let compute = null, variable = null, cpuTexture = null, sweeps = 0, fallbackReason = ''
  if (!forceCPU && renderer.extensions.has('EXT_color_buffer_float')) {
    try {
      compute = new GPUComputationRenderer(p.segments + 1, p.chains, renderer)
      const initial = compute.createTexture()
      initial.image.data.set(data)
      variable = compute.addVariable('texturePosition', pegComputeShader(p.segments), initial)
      variable.material.glslVersion = THREE.GLSL3
      compute.setVariableDependencies(variable, [variable])
      Object.assign(variable.material.uniforms, {
        sweep: { value: 0 }, seed: { value: p.seed >>> 0 },
        fieldEnergy: { value: p.charge * p.field * ELEMENTARY_FORCE / (KB * p.temperature) },
        screening: { value: p.screening }, wall: { value: p.wall },
      })
      const error = compute.init()
      if (error) throw new Error(error)
      // Force compilation and readback now so unsupported drivers fail visibly.
      variable.material.uniforms.sweep.value = 1
      compute.compute()
      renderer.readRenderTargetPixels(compute.getCurrentRenderTarget(variable), 0, 0, p.segments + 1, p.chains, data)
      if (data.some(x => !Number.isFinite(x)) || data[3] !== 1) throw new Error('Floating-point compute check failed')
      sweeps = 1
    } catch (error) {
      fallbackReason = error.message
      compute?.dispose()
      compute = null
      data.set(initialPegState(p))
    }
  } else fallbackReason = forceCPU ? 'CPU reference selected' : 'Float render targets unavailable'
  if (!compute) {
    cpuTexture = new THREE.DataTexture(data, p.segments + 1, p.chains, THREE.RGBAFormat, THREE.FloatType)
    cpuTexture.needsUpdate = true
  }
  return {
    backend: compute ? 'GPU Monte Carlo · WebGL2' : 'CPU Monte Carlo · WebGL rendering',
    fallbackReason,
    get sweeps() { return sweeps },
    get texture() { return compute ? compute.getCurrentRenderTarget(variable).texture : cpuTexture },
    step(count = 8) {
      for (let k = 0; k < count; k++) {
        sweeps++
        if (compute) { variable.material.uniforms.sweep.value = sweeps; compute.compute() }
        else pivotStep(data, p, sweeps)
      }
      if (cpuTexture) cpuTexture.needsUpdate = true
    },
    read() {
      if (compute) renderer.readRenderTargetPixels(compute.getCurrentRenderTarget(variable), 0, 0, p.segments + 1, p.chains, data)
      return data
    },
    dispose() { compute?.dispose(); cpuTexture?.dispose() },
  }
}
