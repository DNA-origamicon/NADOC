/**
 * Photo mode — EffectComposer pipeline.
 *
 * Pipeline: RenderPass → [VolumetricInscatterPass] → SSAOPass → SMAAPass → [UnrealBloomPass] → OutputPass
 *
 * The VolumetricInscatterPass is always present in the chain but starts disabled;
 * orchestrator toggles `enabled` based on env-effect state and pushes per-frame
 * light uniforms via `inscatterPass.setLights(...)`.
 *
 * Default EffectComposer setup (no custom render target). The inscatter pass
 * owns its own depth pre-pass — see volumetric_inscatter_pass.js for why we
 * don't try to attach a DepthTexture to the main composer target.
 */

import * as THREE from 'three'
import { EffectComposer }   from 'three/addons/postprocessing/EffectComposer.js'
import { RenderPass }       from 'three/addons/postprocessing/RenderPass.js'
import { SSAOPass }         from 'three/addons/postprocessing/SSAOPass.js'
import { SMAAPass }         from 'three/addons/postprocessing/SMAAPass.js'
import { UnrealBloomPass }  from 'three/addons/postprocessing/UnrealBloomPass.js'
import { OutputPass }       from 'three/addons/postprocessing/OutputPass.js'
import { VolumetricInscatterPass } from './volumetric_inscatter_pass.js'

/**
 * @param {THREE.WebGLRenderer} renderer
 * @param {THREE.Scene}         scene
 * @param {THREE.Camera}        camera
 * @param {object}              opts
 * @param {boolean} [opts.ssao=true]
 * @param {boolean} [opts.bloom=false]
 * @param {number}  [opts.bloomStrength=0.5]
 * @param {number}  [opts.bloomRadius=0.4]
 * @param {number}  [opts.bloomThreshold=0.85]
 */
export function createComposer(renderer, scene, camera, opts = {}) {
  const {
    ssao          = true,
    bloom         = false,
    bloomStrength = 0.5,
    bloomRadius   = 0.4,
    bloomThreshold = 0.85,
  } = opts

  const w = renderer.domElement.width
  const h = renderer.domElement.height

  // Default composer setup — no custom render target. The inscatter pass below
  // owns its own depth pre-pass (SSAOPass-style), so we don't have to attach
  // a DepthTexture here. This avoids an interaction that broke the surface
  // MeshPhysicalMaterial's transmission pre-pass on most drivers (see
  // memory/project_photo_mode.md "depth-texture format gotcha").
  const composer = new EffectComposer(renderer)

  // ── Render pass ──────────────────────────────────────────────────────────────
  const renderPass = new RenderPass(scene, camera)
  composer.addPass(renderPass)

  // ── Volumetric inscatter (mist + light shafts) ───────────────────────────────
  const inscatterPass = new VolumetricInscatterPass(scene, camera)
  inscatterPass.enabled = false   // toggled on by env-effect controller
  inscatterPass.setSize(w, h)     // size the depth pre-pass target before first render
  composer.addPass(inscatterPass)

  // ── SSAO ─────────────────────────────────────────────────────────────────────
  let ssaoPass = null
  if (ssao) {
    ssaoPass = new SSAOPass(scene, camera, w, h)
    // Tuned for nm-scale DNA structures:
    // kernelRadius ≈ 0.3 nm — close-range occlusion between helices
    // minDistance  — avoid self-occlusion on flat surfaces
    // maxDistance  — don't darken wide open space
    ssaoPass.kernelRadius  = 0.3
    ssaoPass.minDistance   = 0.002
    ssaoPass.maxDistance   = 0.12
    ssaoPass.kernelSize    = 32
    ssaoPass.output        = SSAOPass.OUTPUT.Default  // SSAO blended with scene
    composer.addPass(ssaoPass)
  }

  // ── SMAA anti-aliasing ───────────────────────────────────────────────────────
  const smaaPass = new SMAAPass(w, h)
  composer.addPass(smaaPass)

  // ── Bloom (optional) ─────────────────────────────────────────────────────────
  let bloomPass = null
  if (bloom) {
    bloomPass = new UnrealBloomPass(new THREE.Vector2(w, h), bloomStrength, bloomRadius, bloomThreshold)
    composer.addPass(bloomPass)
  }

  // ── Output (tone-mapping + colour-space correction) ───────────────────────────
  const outputPass = new OutputPass()
  composer.addPass(outputPass)

  // ── Handle ───────────────────────────────────────────────────────────────────

  function setSize(width, height) {
    composer.setSize(width, height)
    ssaoPass?.setSize(width, height)
    inscatterPass.setSize(width, height)
  }

  function dispose() {
    inscatterPass.dispose()
    composer.dispose()
  }

  return { composer, ssaoPass, bloomPass, inscatterPass, setSize, dispose }
}
