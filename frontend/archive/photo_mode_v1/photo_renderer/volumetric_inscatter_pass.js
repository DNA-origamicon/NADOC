/**
 * Volumetric inscatter post-process pass — Cycles/Unreal-style mist.
 *
 * For each pixel, marches the view ray from camera to scene-depth in N steps
 * and accumulates *additive* in-scattered radiance from point lights and a
 * merged ambient term. The scene colour is preserved (no transmittance loss),
 * so geometry stays sharp; only the air around lights brightens.
 *
 *   final.rgb = scene.rgb + sum_steps(L_in) * stepSize * density * scatter * fogColor
 *   L_in(p)   = ambient + sum_lights(color / max(|p - lightPos|², minR2))
 *
 * Architecture: the pass owns its own depth-only render target and renders the
 * scene through `MeshDepthMaterial` before sampling — same pattern as Three.js's
 * `SSAOPass`. This avoids any interaction with the composer's main render
 * target (which is fragile: attaching a DepthTexture there breaks the surface
 * MeshPhysicalMaterial transmission pre-pass on most drivers, AND HDR colour
 * reads through the swap buffers don't always survive the inscatter sampling).
 *
 * Caller is responsible for pushing the current light set + mist params via
 * setLights() / setMistParams() each frame.
 *
 * Insert AFTER RenderPass and before Bloom.
 */

import * as THREE from 'three'
import { Pass, FullScreenQuad } from 'three/addons/postprocessing/Pass.js'

const MAX_LIGHTS = 64
const STEPS      = 24

const VERT = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`

const FRAG = /* glsl */ `
  precision highp float;
  varying vec2 vUv;

  uniform sampler2D tDiffuse;
  uniform sampler2D tDepth;
  uniform mat4  uInvProjMat;
  uniform mat4  uInvViewMat;
  uniform vec3  uCameraPos;
  uniform float uMaxDist;

  uniform vec3  uPointPos[${MAX_LIGHTS}];
  uniform vec3  uPointColor[${MAX_LIGHTS}];   // colour × intensity
  uniform int   uNumPoints;

  uniform vec3  uAmbient;    // merged ambient + directional contribution per step
  uniform float uDensity;    // scattering coefficient (per scene unit)
  uniform vec3  uFogColor;   // tint applied to total inscatter
  uniform float uScatter;    // overall multiplier
  uniform float uMinR2;      // numerical floor on r² to avoid singularity at point lights

  // Non-uniform mist (3D world-space noise modulating per-step density).
  uniform float uNoiseContrast; // 0 = uniform; 1 = density swings 0..2× the base
  uniform float uNoiseScale;    // noise input frequency (units of 1/scene-unit)
  uniform float uNoiseSpeed;    // drift along z over time
  uniform float uTime;          // seconds since pass creation

  // Debug: 0 = passthrough (just tDiffuse), 1 = solid magenta, 2 = depth as greyscale,
  // 3 = ambient-only inscatter, anything else = full inscatter math
  uniform int   uDebugMode;

  vec3 worldFromDepth(vec2 uv, float depth) {
    vec4 ndc  = vec4(uv * 2.0 - 1.0, depth * 2.0 - 1.0, 1.0);
    vec4 view = uInvProjMat * ndc;
    view /= view.w;
    return (uInvViewMat * view).xyz;
  }

  float hash12(vec2 p) {
    return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453);
  }

  // Compact 3D hash (Hugo Elias / Dave Hoskins variant); cheap, not crypto-strong.
  float hash13(vec3 p) {
    p  = fract(p * vec3(0.1031, 0.1030, 0.0973));
    p += dot(p, p.zyx + 31.32);
    return fract((p.x + p.y) * p.z);
  }

  // Trilinearly-interpolated value noise on a unit lattice; returns ~[0,1].
  float vnoise3(vec3 p) {
    vec3 i = floor(p);
    vec3 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);                // smoothstep
    float n000 = hash13(i + vec3(0.0, 0.0, 0.0));
    float n100 = hash13(i + vec3(1.0, 0.0, 0.0));
    float n010 = hash13(i + vec3(0.0, 1.0, 0.0));
    float n110 = hash13(i + vec3(1.0, 1.0, 0.0));
    float n001 = hash13(i + vec3(0.0, 0.0, 1.0));
    float n101 = hash13(i + vec3(1.0, 0.0, 1.0));
    float n011 = hash13(i + vec3(0.0, 1.0, 1.0));
    float n111 = hash13(i + vec3(1.0, 1.0, 1.0));
    return mix(
      mix(mix(n000, n100, f.x), mix(n010, n110, f.x), f.y),
      mix(mix(n001, n101, f.x), mix(n011, n111, f.x), f.y),
      f.z
    );
  }

  // 2-octave fractional Brownian motion — gives wispier patterns than single-octave.
  float fbm2(vec3 p) {
    return (vnoise3(p) + 0.5 * vnoise3(p * 2.0 + vec3(13.0, 7.0, 19.0))) / 1.5;
  }

  void main() {
    vec4  col   = texture2D(tDiffuse, vUv);
    float depth = texture2D(tDepth,   vUv).r;

    if (uDebugMode == 1) { gl_FragColor = vec4(1.0, 0.0, 1.0, 1.0); return; }
    if (uDebugMode == 2) { gl_FragColor = vec4(vec3(depth), 1.0);   return; }
    if (uDebugMode == 0) { gl_FragColor = col;                      return; }

    vec3  endP;
    float rayLen;
    if (depth < 0.9999) {
      endP   = worldFromDepth(vUv, depth);
      rayLen = length(endP - uCameraPos);
    } else {
      vec3 dir = normalize(worldFromDepth(vUv, 0.9999) - uCameraPos);
      endP    = uCameraPos + dir * uMaxDist;
      rayLen  = uMaxDist;
    }
    rayLen = clamp(rayLen, 0.001, uMaxDist);
    vec3  rayDir   = normalize(endP - uCameraPos);
    float stepSize = rayLen / float(${STEPS});
    float jitter   = hash12(vUv);

    vec3 inscatter = vec3(0.0);
    for (int s = 0; s < ${STEPS}; s++) {
      float t = (float(s) + jitter) * stepSize;
      vec3  p = uCameraPos + rayDir * t;

      // Local density: 1.0 = uniform; varies in [0, 1+contrast] when noise is on.
      float densityMod = 1.0;
      if (uNoiseContrast > 0.0) {
        vec3 np = p * uNoiseScale + vec3(0.0, 0.0, uTime * uNoiseSpeed);
        float n = fbm2(np);                          // ~[0, 1], mean ~0.5
        densityMod = max(0.0, 1.0 + (n - 0.5) * 2.0 * uNoiseContrast);
      }

      vec3 contrib = uAmbient;
      if (uDebugMode != 3) {
        for (int i = 0; i < ${MAX_LIGHTS}; i++) {
          if (i >= uNumPoints) break;
          vec3  L  = uPointPos[i] - p;
          float r2 = dot(L, L);
          contrib += uPointColor[i] / max(r2, uMinR2);
        }
      }
      inscatter += contrib * densityMod;
    }
    inscatter *= stepSize * uDensity * uScatter * uFogColor;
    inscatter = max(inscatter, vec3(0.0));   // numerical safety

    gl_FragColor = vec4(col.rgb + inscatter, col.a);
  }
`

export const VOLUMETRIC_MAX_LIGHTS = MAX_LIGHTS

export class VolumetricInscatterPass extends Pass {
  /**
   * @param {THREE.Scene}  scene
   * @param {THREE.Camera} camera
   */
  constructor(scene, camera) {
    super()
    this.scene     = scene
    this.camera    = camera
    this.needsSwap = true

    // ── Depth pre-pass target (own GL state, no interaction with composer's main RT) ──
    const w0 = 1, h0 = 1   // resized in setSize()
    const depthTex = new THREE.DepthTexture(w0, h0)
    depthTex.format = THREE.DepthStencilFormat
    depthTex.type   = THREE.UnsignedInt248Type
    this._depthRT = new THREE.WebGLRenderTarget(w0, h0, {
      minFilter:    THREE.NearestFilter,
      magFilter:    THREE.NearestFilter,
      format:       THREE.RGBAFormat,
      depthBuffer:  true,
      stencilBuffer: true,
      depthTexture: depthTex,
    })
    this._depthMaterial = new THREE.MeshDepthMaterial()
    this._depthMaterial.depthPacking = THREE.BasicDepthPacking
    this._depthMaterial.blending     = THREE.NoBlending

    // Pre-allocate light-uniform arrays so per-frame updates don't churn allocations.
    const pointPos   = Array.from({ length: MAX_LIGHTS }, () => new THREE.Vector3())
    const pointColor = Array.from({ length: MAX_LIGHTS }, () => new THREE.Color(0, 0, 0))

    this.material = new THREE.ShaderMaterial({
      uniforms: {
        tDiffuse:       { value: null },
        tDepth:         { value: depthTex },
        uInvProjMat:    { value: new THREE.Matrix4() },
        uInvViewMat:    { value: new THREE.Matrix4() },
        uCameraPos:     { value: new THREE.Vector3() },
        uMaxDist:       { value: 200.0 },
        uPointPos:      { value: pointPos },
        uPointColor:    { value: pointColor },
        uNumPoints:     { value: 0 },
        uAmbient:       { value: new THREE.Color(0, 0, 0) },
        uDensity:       { value: 0.05 },
        uFogColor:      { value: new THREE.Color(0xcad3e0) },
        uScatter:       { value: 1.0 },
        uMinR2:         { value: 1.0 },     // ~1 nm² floor; prevents singularity inside the bead
        uNoiseContrast: { value: 0.0 },     // 0 = uniform mist (default — no noise cost)
        uNoiseScale:    { value: 0.05 },    // ~20 nm features at scale=0.05 in nm-units
        uNoiseSpeed:    { value: 0.0 },     // 0 = static
        uTime:          { value: 0.0 },     // updated each render()
        uDebugMode:     { value: 99 },      // 0=passthrough, 1=magenta, 2=depth, 3=ambient-only, else=full
      },
      vertexShader:   VERT,
      fragmentShader: FRAG,
    })
    this._fsq    = new FullScreenQuad(this.material)
    this._tStart = (typeof performance !== 'undefined' ? performance.now() : Date.now()) * 0.001
  }

  setSize(width, height) {
    this._depthRT.setSize(width, height)
  }

  /**
   * @param {object}        bundle
   * @param {Array<{position:THREE.Vector3, colorScaled:THREE.Color}>} bundle.points
   * @param {THREE.Color}   bundle.ambient
   */
  setLights({ points = [], ambient }) {
    const u = this.material.uniforms
    const n = Math.min(points.length, MAX_LIGHTS)
    if (points.length > MAX_LIGHTS) {
      console.warn(
        `[VolumetricInscatterPass] ${points.length} lights > MAX_LIGHTS=${MAX_LIGHTS}; truncating`,
      )
    }
    for (let i = 0; i < n; i++) {
      u.uPointPos.value[i].copy(points[i].position)
      u.uPointColor.value[i].copy(points[i].colorScaled)
    }
    u.uNumPoints.value = n
    if (ambient) u.uAmbient.value.copy(ambient)
  }

  setMistParams({ density, fogColor, scatter, maxDist, minR2 } = {}) {
    const u = this.material.uniforms
    if (density  !== undefined) u.uDensity.value  = density
    if (scatter  !== undefined) u.uScatter.value  = scatter
    if (maxDist  !== undefined) u.uMaxDist.value  = maxDist
    if (minR2    !== undefined) u.uMinR2.value    = minR2
    if (fogColor !== undefined) u.uFogColor.value.copy(fogColor)
  }

  setNoiseParams({ contrast, scale, speed } = {}) {
    const u = this.material.uniforms
    if (contrast !== undefined) u.uNoiseContrast.value = contrast
    if (scale    !== undefined) u.uNoiseScale.value    = scale
    if (speed    !== undefined) u.uNoiseSpeed.value    = speed
  }

  setDebugMode(mode) { this.material.uniforms.uDebugMode.value = mode }

  render(renderer, writeBuffer, readBuffer) {
    // ── Depth pre-pass: render the scene with MeshDepthMaterial into our own RT ──
    const oldOverride  = this.scene.overrideMaterial
    const oldClearColor = renderer.getClearColor(new THREE.Color())
    const oldClearAlpha = renderer.getClearAlpha()
    const oldAutoClear  = renderer.autoClear

    this.scene.overrideMaterial = this._depthMaterial
    renderer.setRenderTarget(this._depthRT)
    renderer.setClearColor(0x000000, 0)
    renderer.autoClear = true
    renderer.clear()
    renderer.render(this.scene, this.camera)

    this.scene.overrideMaterial = oldOverride
    renderer.setClearColor(oldClearColor, oldClearAlpha)
    renderer.autoClear = oldAutoClear

    // ── Inscatter shader: sample readBuffer (scene colour from RenderPass) + depth ──
    const u = this.material.uniforms
    u.tDiffuse.value = readBuffer.texture

    this.camera.updateMatrixWorld()
    u.uInvProjMat.value.copy(this.camera.projectionMatrixInverse)
    u.uInvViewMat.value.copy(this.camera.matrixWorld)
    u.uCameraPos.value.setFromMatrixPosition(this.camera.matrixWorld)

    const nowSec = (typeof performance !== 'undefined' ? performance.now() : Date.now()) * 0.001
    u.uTime.value = nowSec - this._tStart

    if (this.renderToScreen) {
      renderer.setRenderTarget(null)
    } else {
      renderer.setRenderTarget(writeBuffer)
      if (this.clear) renderer.clear()
    }
    this._fsq.render(renderer)
  }

  dispose() {
    this._depthRT.depthTexture?.dispose()
    this._depthRT.dispose()
    this._depthMaterial.dispose()
    this.material.dispose()
    this._fsq.dispose()
  }
}
