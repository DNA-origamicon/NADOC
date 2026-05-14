/**
 * Photo mode — EffectComposer pipeline.
 *
 * Pipeline: RenderPass → SSAOPass → SMAAPass → [UnrealBloomPass] → OutputPass
 *
 * createComposer() returns a handle with:
 *   composer  — the EffectComposer instance
 *   ssaoPass  — SSAOPass (or null if disabled)
 *   bloomPass — UnrealBloomPass (or null if disabled)
 *   setSize(w, h)   — resize all passes
 *   dispose()       — clean up GPU resources
 */

import * as THREE from 'three'
import { EffectComposer }   from 'three/addons/postprocessing/EffectComposer.js'
import { RenderPass }       from 'three/addons/postprocessing/RenderPass.js'
import { SSAOPass }         from 'three/addons/postprocessing/SSAOPass.js'
import { SMAAPass }         from 'three/addons/postprocessing/SMAAPass.js'
import { UnrealBloomPass }  from 'three/addons/postprocessing/UnrealBloomPass.js'
import { OutputPass }       from 'three/addons/postprocessing/OutputPass.js'

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

  const composer = new EffectComposer(renderer)

  // ── Render pass ──────────────────────────────────────────────────────────────
  const renderPass = new RenderPass(scene, camera)
  composer.addPass(renderPass)

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
  }

  function dispose() {
    composer.dispose()
  }

  return { composer, ssaoPass, bloomPass, setSize, dispose }
}
